import asyncio
import json
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import conversation_recall as recall
import conversation_search as search
import database
import main

SETTINGS = {'search_enabled': True, 'embedding_api_url': 'https://embedding.test/v1',
            'embedding_model': 'test', 'embedding_api_key': 'test-key'}


def message(mid, content='过去的原话。', role='user', conv=2, **kwargs):
    return {'id': mid, 'conversation_id': conv, 'content': content, 'role': role,
            'created_at': datetime.now(timezone.utc), 'hidden': False, 'kind': 'chat', **kwargs}


def entry(row, vector=(1., 0.)):
    return {'message_id': row['id'], 'start_offset': 0, 'end_offset': len(row['content']),
            'source_hash': recall.source_hash(row), 'embedding': json.dumps(vector),
            'created_at': row['created_at']}


def pool_for(entries, sources):
    conn = MagicMock()

    async def fetch(sql, *args):
        if 'FROM conversation_recall_index' in sql:
            _, last_id, start, end, size = args
            return [e for e in entries if (e['message_id'], e['start_offset'], e['end_offset']) > (last_id, start, end)][:size]
        ids = set(args[0])
        for row in sources:
            if row['id'] in ids and row['role'] == 'assistant':
                preceding = [r for r in sources if r['conversation_id'] == row['conversation_id'] and r['id'] < row['id'] and r['role'] == 'user']
                if preceding:
                    ids.add(max(preceding, key=lambda r: r['id'])['id'])
        return [r for r in sources if r['id'] in ids]

    conn.fetch = AsyncMock(side_effect=fetch)
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool, conn


class ExplicitVectorSearchTests(unittest.IsolatedAsyncioTestCase):
    async def test_manual_search_uses_embeddings_not_local_keywords(self):
        row = message(1, '阳光下的海岸。')
        pool, conn = pool_for([entry(row)], [row])
        embed = AsyncMock(return_value=[[1., 0.]])
        with patch.object(database, 'get_pool', AsyncMock(return_value=pool)), patch.object(
            database, '_embed_conversation_chunks', embed
        ), patch.object(recall, 'search', AsyncMock(side_effect=AssertionError('wrong path'))):
            results = await database.search_conversation_history('想去度假', 1, SETTINGS)
        embed.assert_awaited_once_with(['想去度假'], SETTINGS, task='retrieval.query')
        self.assertEqual('阳光下的海岸。', results[0]['matches'][0]['messages'][0]['content'])
        sql = conn.fetch.await_args_list[0].args[0]
        self.assertNotIn('m.conversation_id <>', sql)
        self.assertIn("m.hidden = FALSE AND m.kind = 'chat'", sql)
        self.assertEqual(recall.config_hash(SETTINGS), conn.fetch.await_args_list[0].args[1])

    async def test_vector_pages_and_original_shortlist_are_bounded(self):
        rows = [message(i, conv=i + 1) for i in range(1, 601)]
        pool, conn = pool_for([entry(row) for row in rows], rows)
        with patch.object(database, 'get_pool', AsyncMock(return_value=pool)), patch.object(
            database, '_embed_conversation_chunks', AsyncMock(return_value=[[1., 0.]])
        ):
            result = await search.search('没有关键词重叠', SETTINGS, 1, limit=5)
        self.assertEqual(5, len(result))
        self.assertEqual(3, len([c for c in conn.fetch.await_args_list if 'LIMIT $5' in c.args[0]]))
        self.assertLessEqual(len(conn.fetch.await_args.args[1]), 50)
        self.assertNotIn('content', conn.fetch.await_args_list[0].args[0])

    async def test_stale_hidden_and_dimension_mismatch_are_rejected(self):
        for change in ['edited', 'hidden', 'dimension']:
            row = message(1)
            old = entry(row, (1., 0., 0.) if change == 'dimension' else (1., 0.))
            if change == 'edited':
                row['content'] = '修改后的内容。'
            if change == 'hidden':
                row['hidden'] = True
            pool, _ = pool_for([old], [row])
            with patch.object(database, 'get_pool', AsyncMock(return_value=pool)), patch.object(
                database, '_embed_conversation_chunks', AsyncMock(return_value=[[1., 0.]])
            ):
                self.assertEqual([], await search.search('查询', SETTINGS, 1))

    async def test_assistant_match_preserves_original_user(self):
        rows = [message(1, '我还没有决定。'), message(2, '可以去海边。', role='assistant')]
        pool, _ = pool_for([entry(rows[1])], rows)
        with patch.object(database, 'get_pool', AsyncMock(return_value=pool)), patch.object(
            database, '_embed_conversation_chunks', AsyncMock(return_value=[[1., 0.]])
        ):
            result = await database.search_conversation_history('度假', 1, SETTINGS)
        self.assertEqual(['user', 'assistant'], [m['role'] for m in result[0]['matches'][0]['messages']])

    async def test_old_current_turn_is_searchable_but_query_itself_is_skipped(self):
        rows = [message(1, '以前讨论的海边度假。', conv=1), message(2, '度假', conv=1)]
        pool, _ = pool_for([entry(row) for row in rows], rows)
        with patch.object(database, 'get_pool', AsyncMock(return_value=pool)), patch.object(
            database, '_embed_conversation_chunks', AsyncMock(return_value=[[1., 0.]])
        ):
            result = await search.search('度假', SETTINGS, 1)
        self.assertEqual([1], [turn['turn_id'] for turn in result])

    async def test_missing_configuration_does_not_call_embedding(self):
        source=message(1,'过去的原话。',conv=2)
        candidate={'conversation_id':2,'turn_id':1,'messages':[source],'score':1.,
                   'matches':[{'message_id':1,'role':'user','start':0,'end':len(source['content']),'text':source['content']}]}
        with patch.object(database, '_embed_conversation_chunks', AsyncMock()) as embed, patch(
            'memory_retrieval.lexical_search', AsyncMock(return_value=[candidate])
        ):
            results=await search.search('查询', {}, 1)
            self.assertEqual(1,results[0]['turn_id'])
        embed.assert_not_awaited()

    async def test_fragment_storage_failure_is_tool_error(self):
        with patch.object(main,'MEMORY_ENABLED',True), patch.object(main.fragments,'search',AsyncMock(side_effect=TimeoutError)):
            result = await main.dispatch_tool_call('recall_fragments', {'query':'查询'})
        self.assertIn('暂时不可用', result)

    async def test_fragment_recall_works_without_raw_message_embeddings(self):
        embed = AsyncMock(side_effect=AssertionError('unexpected raw history search'))
        with patch.object(main,'MEMORY_ENABLED',True), patch.object(main,'get_conversation_model_settings',
            AsyncMock(return_value={'cross_conversation_recall_enabled':True})), patch.object(
            main.fragments,'search',AsyncMock(return_value=[{'id':1,'content':'我记得海边。'}])
        ), patch.object(database,'_embed_conversation_chunks',embed):
            result = await main._build_past_conversation_recall_block('海边',conv_id=1)
        self.assertIn('我记得海边。',result)
        embed.assert_not_awaited()

    async def test_worker_does_not_index_without_embedding_configuration(self):
        with patch.dict('os.environ', {'HISTORY_RECALL_INDEX_ENABLED': 'true'}), patch.object(
            database, 'get_conversation_model_settings', AsyncMock(return_value={'search_enabled': True})
        ), patch.object(recall, 'refresh_index', AsyncMock()) as refresh, patch.object(
            recall.asyncio, 'sleep', AsyncMock(side_effect=[None, asyncio.CancelledError()])
        ):
            with self.assertRaises(asyncio.CancelledError):
                await recall.index_worker()
        refresh.assert_not_awaited()
