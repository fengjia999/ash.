import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import unittest
import conversation_recall as recall


SETTINGS = {"embedding_model": "test", "embedding_api_url": "https://example.test"}


def row(id, text, role="user", conv=1, **kwargs):
    return dict(id=id, content=text, role=role, conversation_id=conv,
                created_at=datetime.now(timezone.utc), **kwargs)


def indexed(message, vector=(1., 0.), digest=None):
    return [dict(message_id=message["id"], start_offset=start, end_offset=end,
                 source_hash=digest or recall.source_hash(message),
                 profile=json.dumps(recall.profile(message)), embedding=json.dumps(vector))
            for start, end in recall.sentence_spans(recall.source_text(message))]


def mock_pool(entries):
    conn = MagicMock()

    async def fetch(sql, *args):
        # refresh_index only needs to know whether an embedding exists; mirror
        # the production query without materialising the vector body.
        if "AS has_embedding" in sql:
            return [dict(
                message_id=e["message_id"], start_offset=e["start_offset"],
                end_offset=e["end_offset"], source_hash=e["source_hash"],
                has_embedding=e.get("embedding") is not None,
            ) for e in entries]
        return entries

    conn.fetch = AsyncMock(side_effect=fetch)
    conn.execute = AsyncMock()
    conn.executemany = AsyncMock()
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool, conn


async def run_search(rows, entries=(), query="昨天约定", **kwargs):
    embed = AsyncMock(side_effect=AssertionError("history must not embed"))
    with patch.object(recall, "candidate_rows", AsyncMock(return_value=rows)), patch.object(
        recall.db, "get_pool", AsyncMock(side_effect=AssertionError("must not read vectors"))
    ), patch.object(recall.db, "_embed_conversation_chunks", embed):
        result = await recall.search(query, SETTINGS, **kwargs)
    embed.assert_not_awaited()
    return result


class ConversationRecallTests(unittest.IsolatedAsyncioTestCase):
    def test_sentence_spans_preserve_exact_original(self):
        text = '我说：“不要忘记！”\n第二句，别改。末尾没有句号'
        spans = list(recall.sentence_spans(text))
        assert [text[a:b] for a, b in spans] == ['我说：“不要忘记！”', '第二句，别改。', '末尾没有句号']
        assert all(text[a:b].strip() for a, b in spans)


    def test_sources_exclude_hidden_handoff_tools_and_thinking(self):
        assert not recall.source_text(row(1, "秘密", hidden=True))
        assert not recall.source_text(row(1, "摘要", kind="handoff"))
        assert not recall.source_text(row(1, "[tool_calls]", role="assistant"))
        assert recall.source_text(row(1, "用户原话", content_json=[{"type": "text", "text": "注入内容"}])) == "用户原话"
        assert recall.source_text(row(2, "fallback", role="assistant", content_json=[
            {"type": "thinking", "thinking": "不能召回"},
            {"type": "tool_use", "input": {"text": "不能召回"}},
            {"type": "text", "text": "真正回复"}])) == "真正回复"


    def test_turns_keep_conversation_and_speaker_boundaries(self):
        turns = recall.dialogue_turns([row(1, "问题"), row(2, "回答", "assistant"),
                                      row(3, "下个问题"), row(4, "另一个会话", "assistant", conv=2)])
        assert [[m["id"] for m in t["messages"]] for t in turns] == [[1, 2], [3], [4]]
        assert recall.profile(row(1, "我喜欢安静"))["importance"] == .7
        assert recall.profile(row(2, "我喜欢安静", "assistant"))["importance"] == .5
        assert recall.profile(row(2, "我很难过", "assistant"))["emotion"] is None


    async def test_search_current_old_turns_gate_stale_hidden_and_visible(self):
        rows = [row(1, "昨天的约定。"), row(2, "正在聊的内容。"),
                row(3, "不相关。"), row(4, "被修改的消息。"),
                row(5, "隐藏消息。", hidden=True)]
        entries = indexed(rows[0]) + indexed(rows[1]) + indexed(rows[2], (0, 1)) + indexed(rows[3], digest="old") + indexed(rows[4])
        results = await run_search(rows, entries, current_conversation_id=1,
                                   visible_messages=[{"role": "user", "content": rows[1]["content"]}])
        assert [t["turn_id"] for t in results] == [1]
        assert results[0]["matches"][0]["text"] == "昨天的约定。"


    async def test_assistant_match_carries_original_user_context(self):
        rows = [row(1, "我还没决定。"), row(2, "可以试试这个办法。", "assistant")]
        results = await run_search(rows, indexed(rows[1]), query="这个办法", current_conversation_id=2)
        assert {m["role"] for m in results[0]["matches"]} == {"user", "assistant"}
        block, selected, _ = recall.pack(results, 2000)
        assert "我还没决定。" in block and "可以试试这个办法。" in block
        assert 'role="user"' in block and 'role="assistant"' in block
        assert '<past_conversations source="memory_gateway">' in block
        assert selected[0]["message_ids"] == [1, 2]


    async def test_budget_skips_oversized_quote_and_keeps_later_complete_sentence(self):
        rows = [row(1, "长句" * 1000 + "。"), row(2, "短句<&>。", conv=2)]
        results = await run_search(rows, indexed(rows[0]) + indexed(rows[1]), query="长句 短句")
        block, selected, skipped = recall.pack(results, 500)
        assert len(block) <= 500
        assert "长" not in block and "短句&lt;&amp;&gt;。" in block
        assert 1 in skipped and selected[0]["message_ids"] == [2]
        assert recall.pack(results, 0)[0] == ""


    async def test_oversized_user_context_prevents_orphan_assistant(self):
        rows = [row(1, "长" * 2000), row(2, "建议。", "assistant")]
        results = await run_search(rows, indexed(rows[1]), query="建议")
        assert recall.pack(results, 500)[0] == ""


    async def test_index_persists_offsets_not_originals_and_caps_embedding_batch(self):
        rows = [row(1, "第一句。第二句。第三句。")]
        pool, conn = mock_pool([])
        embed = AsyncMock(return_value=[[1., 0.]])
        recall._cursors.clear()
        with patch.object(recall, "source_rows", AsyncMock(return_value=rows)), patch.object(
            recall.db, "get_pool", AsyncMock(return_value=pool)
        ), patch.object(recall.db, "_embed_conversation_chunks", embed):
            status = await recall.refresh_index(SETTINGS, batch_size=1)
        assert status == dict(messages=1, sentences=3, indexed=1, pending=2)
        assert len(embed.await_args.args[0]) == 1
        assert embed.await_args.kwargs["task"] == "retrieval.passage"
        sql, values = conn.executemany.await_args.args
        assert len(values) == 1 and len(values[0]) == 6
        assert "context_messages" not in sql
        assert values[0][1:3] in [(0, 4), (4, 8), (8, 12)]
        assert "第一句。第二句。第三句。" not in str(values)
        assert "source_hash = $5" in conn.execute.await_args.args[0]


    async def test_valid_index_is_reused_without_embedding(self):
        rows = [row(1, "原话。")]
        pool, conn = mock_pool(indexed(rows[0]))
        embed = AsyncMock()
        with patch.object(recall, "source_rows", AsyncMock(return_value=rows)), patch.object(
            recall.db, "get_pool", AsyncMock(return_value=pool)
        ), patch.object(recall.db, "_embed_conversation_chunks", embed):
            status = await recall.refresh_index(SETTINGS)
        assert status["pending"] == 0
        embed.assert_not_awaited()
        conn.executemany.assert_not_awaited()


    async def test_failed_vectors_retry_other_sentences_next_pass(self):
        rows = [row(1, "一。二。三。")]
        pool, _ = mock_pool([])
        embed = AsyncMock(return_value=[None])
        recall._cursors.clear()
        with patch.object(recall, "source_rows", AsyncMock(return_value=rows)), patch.object(
            recall.db, "get_pool", AsyncMock(return_value=pool)
        ), patch.object(recall.db, "_embed_conversation_chunks", embed):
            await recall.refresh_index(SETTINGS, batch_size=1)
            await recall.refresh_index(SETTINGS, batch_size=1)
        assert embed.await_args_list[0].args[0] != embed.await_args_list[1].args[0]


    async def test_search_never_reads_original_archive_or_vector_pages(self):
        rows = [row(i, f"消息{i}。", conv=i) for i in range(1, 121)]
        pool = AsyncMock(side_effect=AssertionError("vector reads forbidden"))
        source = AsyncMock(side_effect=AssertionError("full archive reads forbidden"))
        embed = AsyncMock(side_effect=AssertionError("embedding forbidden"))
        with patch.object(recall, "candidate_rows", AsyncMock(return_value=rows)), patch.object(
            recall, "source_rows", source
        ), patch.object(recall.db, "get_pool", pool), patch.object(recall.db, "_embed_conversation_chunks", embed):
            results = await recall.search("消息", SETTINGS, limit=5)
        assert len(results) == 5
        source.assert_not_awaited()
        pool.assert_not_awaited()
        embed.assert_not_awaited()

    async def test_refresh_index_does_not_fetch_embedding_bodies(self):
        rows = [row(1, "原话。")]
        pool, conn = mock_pool(indexed(rows[0]))
        with patch.object(recall, "source_rows", AsyncMock(return_value=rows)), patch.object(
            recall.db, "get_pool", AsyncMock(return_value=pool)
        ), patch.object(recall.db, "_embed_conversation_chunks", AsyncMock()) as embed:
            status = await recall.refresh_index(SETTINGS)
        assert status["pending"] == 0
        first_sql = conn.fetch.await_args_list[0].args[0]
        assert "AS has_embedding" in first_sql
        assert "source_hash, embedding" not in first_sql
        embed.assert_not_awaited()

    def test_config_and_source_changes_invalidate_index(self):
        assert recall.config_hash(SETTINGS) != recall.config_hash({**SETTINGS, "embedding_model": "other"})
        assert recall.source_hash(row(1, "原话")) != recall.source_hash(row(1, "编辑后"))
        assert recall.source_hash(row(1, "原话")) != recall.source_hash(row(1, "原话", "assistant"))


    def test_recency_uses_original_date_and_local_text_score(self):
        old = row(1, "以前", created_at_override=None)
        old["created_at"] = "2000-01-01T00:00:00Z"
        scores = recall.sentence_scores(old, recall.profile(old), "以前", .8, 2)
        assert scores["recency_score"] < .001
        assert scores["text_similarity"] == .8
        assert scores["total"] < scores["base_total"] * .36

    def test_hidden_turn_does_not_merge_following_reply_into_prior_user(self):
        turns = recall.dialogue_turns([row(1, "旧问题"), row(2, "隐藏问题", hidden=True),
                                      row(3, "后一个回答", "assistant")])
        assert [[m["id"] for m in t["messages"]] for t in turns] == [[1], [3]]

    async def test_index_failure_does_not_break_automatic_chat_context(self):
        import main
        with patch.object(main, "MEMORY_ENABLED", True), patch.object(
            main, "get_conversation_model_settings", AsyncMock(return_value={
                "search_enabled": True, "long_term_recall_char_budget": 2000})
        ), patch.object(recall, "search", AsyncMock(side_effect=RuntimeError("index unavailable"))):
            assert await main._build_past_conversation_recall_block("原话", conv_id=1) == ""

    async def test_zero_budget_does_not_request_embeddings(self):
        import main
        search = AsyncMock()
        with patch.object(main, "MEMORY_ENABLED", True), patch.object(
            main, "get_conversation_model_settings", AsyncMock(return_value={
                "search_enabled": True, "long_term_recall_char_budget": 0})
        ), patch.object(recall, "search", search):
            assert await main._build_past_conversation_recall_block("原话", conv_id=1) == ""
        search.assert_not_awaited()

    async def test_index_reads_only_one_source_page_and_its_vector_presence(self):
        rows = [row(i, "原话。") for i in range(100, 60, -1)]
        pool, conn = mock_pool([])
        source = AsyncMock(return_value=rows)
        recall._page_cursors.clear()
        with patch.object(recall, "source_rows", source), patch.object(
            recall.db, "get_pool", AsyncMock(return_value=pool)
        ), patch.object(recall.db, "_embed_conversation_chunks", AsyncMock(return_value=[])):
            await recall.refresh_index(SETTINGS)
            await recall.refresh_index(SETTINGS)
        assert source.await_args_list[0].kwargs == {"before_id": None, "limit": 40}
        assert source.await_args_list[1].kwargs == {"before_id": 61, "limit": 40}
        query = conn.fetch.await_args.args
        assert "AS has_embedding" in query[0]
        assert "message_id = ANY($2::integer[])" in query[0]
        assert query[2] == list(range(100, 60, -1))

    async def test_worker_backs_off_database_failure_and_resets_after_recovery(self):
        import asyncio
        settings = AsyncMock(side_effect=[ConnectionRefusedError(), ConnectionRefusedError(),
                                          {**SETTINGS, "embedding_api_key": "test", "search_enabled": True}])
        sleep = AsyncMock(side_effect=[None, None, None, asyncio.CancelledError()])
        refresh = AsyncMock()
        with patch.dict("os.environ", {"HISTORY_RECALL_INDEX_ENABLED": "true"}), patch.object(
            recall.db, "get_conversation_model_settings", settings
        ), patch.object(recall, "refresh_index", refresh), patch.object(recall.asyncio, "sleep", sleep):
            with self.assertRaises(asyncio.CancelledError):
                await recall.index_worker()
        assert [call.args[0] for call in sleep.await_args_list] == [10, 30, 60, 10]
        refresh.assert_awaited_once()

    async def test_worker_can_be_paused_without_touching_database(self):
        settings = AsyncMock()
        with patch.dict("os.environ", {"HISTORY_RECALL_INDEX_ENABLED": "false"}), patch.object(
            recall.db, "get_conversation_model_settings", settings
        ):
            await recall.index_worker()
        settings.assert_not_awaited()


class LocalRecallTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_embedding_even_with_provider_configured_and_edited_source(self):
        rows = [row(1, '我喜欢苹果。')]
        result = await run_search(rows, indexed(rows[0], digest='stale'), query='苹果')
        assert result[0]['matches'][0]['text'] == '我喜欢苹果。'

    async def test_recent_important_match_beats_three_month_old_exact_match(self):
        from datetime import timedelta
        recent = row(2, '请记住我喜欢周末一起爬山。')
        recent['created_at'] -= timedelta(days=3)
        old = row(1, '周末爬山计划')
        old['created_at'] -= timedelta(days=90)
        results = await run_search([old, recent], query='周末爬山计划')
        assert results[0]['turn_id'] == 2
        assert results[0]['score_components']['recency_score'] > .8

    async def test_unrelated_recent_important_message_is_not_recalled(self):
        assert await run_search([row(1, '请记住我对花生过敏。')], query='星际旅行') == []

    async def test_minimum_score_and_weights_are_used(self):
        rows = [row(1, '苹果')]
        with patch.object(recall, 'candidate_rows', AsyncMock(return_value=rows)):
            assert await recall.search('苹果', {'history_recall_settings': {'min_score': 1}}) == []
            result = await recall.search('苹果', {'history_recall_settings': {
                'keyword': 1, 'text': 0, 'importance': 0, 'recency': 0, 'min_score': .9}})
        assert result[0]['score'] == 1

    async def test_candidate_sql_is_bounded_and_never_reads_index(self):
        pool, conn = mock_pool([])
        with patch.object(recall.db, 'get_pool', AsyncMock(return_value=pool)):
            await recall.candidate_rows('苹果')
        sql, window, query, keywords, count = conn.fetch.await_args.args
        assert window == 2000 and count == 120
        assert 'MATERIALIZED' in sql and 'LIMIT $1' in sql and 'LIMIT $4' in sql
        assert 'embedding' not in sql and 'conversation_recall_index' not in sql
        assert 'parent.id' in sql

    async def test_diary_reads_only_existing_metadata_and_escapes_budgeted_output(self):
        diary = dict(id=3, memory_date='2026-09-29', title='<苹果>', keywords='["苹果"]')
        pool, conn = mock_pool([diary])
        with patch.object(recall.db, 'get_pool', AsyncMock(return_value=pool)), patch.object(
            recall.db, 'get_identity_presets', AsyncMock(return_value={'assistant_name': 'Ash'})
        ):
            diaries = await recall.diary_metadata('苹果')
        sql = conn.fetch.await_args.args[0]
        assert 'SELECT id, memory_date, title, keywords' in sql
        assert 'summary' not in sql and 'content' not in sql and 'embedding' not in sql
        assert 'LIMIT 256' in sql and 'LIMIT 8' in sql
        block, _, _ = recall.pack([], 2000, diaries)
        assert '&lt;苹果&gt;' in block and '2026-09-29' in block and 'diary_metadata' in block
        assert diaries[0]['author_role'] == 'assistant'
        assert diaries[0]['author_name'] == 'Ash'
        assert 'author_role' in block and 'Ash' in block
        assert recall.pack([], 10, diaries)[0] == ''

    async def test_query_failure_and_timeout_skip_recall(self):
        import asyncio
        async def slow(_):
            await asyncio.sleep(1)
        for candidate in [AsyncMock(side_effect=RuntimeError('private connection')), slow]:
            with patch.object(recall, 'candidate_rows', candidate), patch.object(recall, 'RECALL_TIMEOUT', .01), patch('builtins.print') as log:
                assert await recall.search('苹果', {}) == []
                assert log.called
                assert 'private connection' not in str(log.call_args_list)

    async def test_settings_failure_does_not_break_chat_context(self):
        import main
        with patch.object(main, 'MEMORY_ENABLED', True), patch.object(
            main, 'get_conversation_model_settings', AsyncMock(side_effect=RuntimeError())
        ), patch.object(recall, 'search', AsyncMock(return_value=[])), patch.object(
            recall, 'diary_metadata', AsyncMock()
        ):
            assert await main._build_past_conversation_recall_block('苹果') == ''

    async def test_cross_conversation_recall_does_not_query_legacy_diaries(self):
        import main
        turns = [{'id':1,'content':'我喜欢苹果。'}]
        with patch.object(main, 'MEMORY_ENABLED', True), patch.object(
            main, 'get_conversation_model_settings', AsyncMock(return_value={
                'cross_conversation_recall_enabled': True,
                'search_enabled': False,
                'long_term_recall_char_budget': 2000,
            })
        ), patch.object(main.fragments, 'search', AsyncMock(return_value=turns)), patch.object(
            recall, 'diary_metadata', AsyncMock(side_effect=RuntimeError('diary unavailable'))
        ) as diary_lookup, patch('builtins.print') as log:
            block = await main._build_past_conversation_recall_block('苹果')

        assert '我喜欢苹果。' in block
        diary_lookup.assert_not_awaited()

    async def test_visible_turn_and_orphan_assistant_are_skipped(self):
        assert await run_search([row(1, '苹果'), row(2, '苹果很好', 'assistant')], query='苹果',
                                current_conversation_id=1, visible_messages=[{'role': 'user', 'content': '苹果'}]) == []
        assert await run_search([row(2, '苹果很好', 'assistant')], query='苹果') == []
