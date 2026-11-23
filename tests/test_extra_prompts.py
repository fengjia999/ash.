import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import database
import main


class ExtraPromptTests(unittest.IsolatedAsyncioTestCase):
    def test_system_prompts_are_captured_as_complete_distinct_values(self):
        messages = [
            {"role": "system", "content": "world one"},
            {"role": "user", "content": "hello"},
            {"role": "system", "content": "world two"},
            {"role": "system", "content": "world one"},
        ]
        self.assertEqual(
            ["world one", "world two", "world one"],
            main._frontend_system_prompt_contents(messages),
        )

    def test_before_prompt_is_put_before_the_real_user_message(self):
        prompt = main._render_extra_prompts([{
            "id": 3, "title": "world", "content": "Keep the moon blue.",
        }])
        messages = main._prepend_extra_prompts_to_latest_user(
            [{"role": "user", "content": "hello"}], prompt,
        )
        blocks = messages[0]["content"]
        self.assertIn('<extra_prompt id="3" name="world">', blocks[0]["text"])
        self.assertIn(main._CURRENT_MESSAGE_MARKER, blocks[0]["text"])
        self.assertEqual("hello", blocks[1]["text"])

    def test_stored_user_text_stays_raw_while_runtime_context_gets_prompt(self):
        row = {
            "id": 42,
            "role": "user",
            "content": "hello",
            "content_json": None,
            "prompt_injections": [{
                "kind": "prompt", "reference_id": 3, "title": "world",
                "content": "Keep the moon blue.", "position": "before",
            }],
        }

        messages = main._rebuild_messages_from_rows([row])

        self.assertEqual("hello", row["content"])
        self.assertIn("Keep the moon blue.", messages[0]["content"][0]["text"])
        self.assertEqual("hello", messages[0]["content"][1]["text"])

    def test_after_prompt_is_annotated_but_not_rebuilt_into_history(self):
        row = {
            "id": 42,
            "role": "user",
            "content": "hello",
            "content_json": None,
            "prompt_injections": [{
                "kind": "prompt", "reference_id": 3, "title": "world",
                "content": "request only", "position": "after",
            }],
        }

        messages = main._rebuild_messages_from_rows([row])

        self.assertEqual("hello", messages[0]["content"])

    def test_after_prompt_is_request_only_and_internal_key_is_removed(self):
        source_messages = [{"role": "user", "content": "hello"}]
        body = {
            "model": "claude-test",
            "messages": source_messages,
            "system": "core",
            "_extra_prompt_suffix": "<extra_prompt>once</extra_prompt>",
        }
        with patch.object(main, "PROMPT_CACHE_ENABLED", False):
            request = main._anthropic_body_for_request(
                body, source_messages, stream=False,
            )

        self.assertNotIn("_extra_prompt_suffix", request)
        self.assertEqual("hello", source_messages[0]["content"])
        self.assertIn("once", str(request["messages"][0]["content"]))

    def test_after_prompt_sits_after_the_message_cache_breakpoint(self):
        messages = [{"role": "user", "content": "hello"}]
        body = {
            "model": "claude-test", "messages": messages, "system": [],
            "_extra_prompt_suffix": "<extra_prompt>once</extra_prompt>",
        }
        with patch.object(main, "PROMPT_CACHE_ENABLED", True), patch.object(
            main, "PROMPT_CACHE_MESSAGE_MODELS", {"claude-test"}
        ):
            request = main._anthropic_body_for_request(
                body, messages, stream=False, cache_scope_id=7,
            )

        blocks = request["messages"][0]["content"]
        self.assertIsNotNone(blocks[0].get("cache_control"))
        self.assertIn("once", blocks[-1]["text"])
        self.assertNotIn("cache_control", blocks[-1])

    async def test_capture_uses_conversation_scoped_hash_deduplication(self):
        conn = MagicMock()
        conn.fetchrow = AsyncMock(side_effect=[
            {"id": 1, "conversation_id": 7, "content": "same",
             "configured": False, "initial_injected": False},
            {"id": 2, "conversation_id": 7, "content": "different",
             "configured": False, "initial_injected": False},
        ])
        acquire = MagicMock()
        acquire.__aenter__ = AsyncMock(return_value=conn)
        acquire.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire.return_value = acquire

        with patch.object(database, "get_pool", AsyncMock(return_value=pool)):
            captured = await database.capture_conversation_system_prompts(
                7, ["same", "same", "different"],
            )

        self.assertEqual(["same", "different"], [row["content"] for row in captured])
        self.assertTrue(all(row["newly_captured"] for row in captured))
        self.assertEqual(2, conn.fetchrow.await_count)
        self.assertTrue(all(call.args[1] == 7 for call in conn.fetchrow.await_args_list))

    async def test_existing_capture_is_not_treated_as_new_again(self):
        conn = MagicMock()
        conn.fetchrow = AsyncMock(side_effect=[
            None,
            {"id": 4, "conversation_id": 7, "content": "system text",
             "configured": False, "initial_injected": False},
        ])
        acquire = MagicMock()
        acquire.__aenter__ = AsyncMock(return_value=conn)
        acquire.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire.return_value = acquire

        with patch.object(database, "get_pool", AsyncMock(return_value=pool)):
            captured = await database.capture_conversation_system_prompts(
                7, ["system text"],
            )

        self.assertEqual(4, captured[0]["id"])
        self.assertFalse(captured[0]["initial_injected"])
        self.assertFalse(captured[0]["newly_captured"])

    def test_new_frontend_prompt_is_injected_raw_once(self):
        sources = [
            {"content": "raw system prompt", "newly_captured": True,
             "configured": False,
             "initial_injected": False},
            {"content": "already used", "newly_captured": False,
             "configured": False,
             "initial_injected": True},
            {"content": "already sorted", "newly_captured": True,
             "configured": True,
             "initial_injected": False},
        ]

        self.assertEqual(
            "raw system prompt", main._initial_frontend_prompt_text(sources),
        )
        messages = main._prepend_extra_prompts_to_latest_user(
            [{"role": "user", "content": "hello"}],
            main._initial_frontend_prompt_text(sources),
        )
        self.assertEqual(
            "raw system prompt\n\n" + main._CURRENT_MESSAGE_MARKER,
            messages[0]["content"][0]["text"],
        )
        self.assertNotIn("<extra_prompt", messages[0]["content"][0]["text"])
        self.assertEqual(
            "", main._initial_frontend_prompt_text(sources, auto_inject=False),
        )

    async def test_injection_record_advances_only_each_blocks_own_counter(self):
        conn = MagicMock()
        conn.execute = AsyncMock()
        transaction = MagicMock()
        transaction.__aenter__ = AsyncMock(return_value=None)
        transaction.__aexit__ = AsyncMock(return_value=False)
        conn.transaction.return_value = transaction
        acquire = MagicMock()
        acquire.__aenter__ = AsyncMock(return_value=conn)
        acquire.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire.return_value = acquire
        injected = {"id": 1, "position": "before", "frequency": "repeat"}
        waiting = {"id": 2, "position": "after", "frequency": "repeat"}
        completed = {
            "id": 3, "position": "after", "frequency": "once",
            "injection_count": 1,
        }

        with patch.object(database, "get_pool", AsyncMock(return_value=pool)):
            await database.record_conversation_extra_prompt_injections(
                7, [injected, waiting, completed], [injected], 42,
            )

        self.assertEqual(3, conn.execute.await_count)
        sql = "\n".join(call.args[0] for call in conn.execute.await_args_list)
        self.assertIn("INSERT INTO conversation_extra_prompt_injections", sql)
        self.assertEqual((2, 7), conn.execute.await_args_list[-1].args[1:])
        self.assertFalse(any(3 in call.args[1:] for call in conn.execute.await_args_list))

    def test_prompt_payload_uses_lock_as_disabled_state(self):
        self.assertEqual(
            ("book", "content", "after", False, "repeat", 4),
            main._extra_prompt_payload({
                "title": "book", "content": "content",
                "position": "AFTER", "locked": False,
                "frequency": "repeat", "interval_turns": 4,
            }),
        )

    def test_repeat_prompt_uses_its_own_turn_interval(self):
        prompt = {
            "id": 1, "frequency": "repeat", "interval_turns": 3,
            "injection_count": 1, "turns_since_injection": 1,
        }
        self.assertEqual([], main._select_extra_prompts_for_turn([prompt]))
        prompt["turns_since_injection"] = 2
        self.assertEqual([prompt], main._select_extra_prompts_for_turn([prompt]))

    def test_new_repeat_prompt_is_injected_on_its_first_turn(self):
        prompt = {
            "id": 1, "frequency": "repeat", "interval_turns": 20,
            "injection_count": 0, "turns_since_injection": 0,
        }
        self.assertEqual([prompt], main._select_extra_prompts_for_turn([prompt]))

    def test_once_prompt_stops_after_first_injection(self):
        prompt = {"id": 1, "frequency": "once", "injection_count": 0}
        self.assertEqual([prompt], main._select_extra_prompts_for_turn([prompt]))
        prompt["injection_count"] = 1
        self.assertEqual([], main._select_extra_prompts_for_turn([prompt]))


if __name__ == "__main__":
    unittest.main()
