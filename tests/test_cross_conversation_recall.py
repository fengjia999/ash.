import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import main
import database
import conversation_recall


class CrossConversationRecallTests(unittest.IsolatedAsyncioTestCase):
    async def test_local_switch_controls_recall(self):
        for enabled in (False, True):
            with patch.object(main, 'MEMORY_ENABLED', True), patch.object(main, 'CONTEXT_MANAGED', True), patch.object(
                main, 'get_conversation_model_settings', AsyncMock(return_value={
                    'cross_conversation_recall_enabled': enabled, 'nocturne_recall_enabled': True,
                })
            ), patch.object(main, '_build_past_conversation_recall_block', AsyncMock(return_value='history')) as local:
                result = await main.build_dynamic_turn_block('历史约定', 7)
                self.assertEqual(result, 'history' if enabled else '')
                self.assertEqual(local.called, enabled)

    async def test_legacy_settings_do_not_enable_history_via_vector_search(self):
        with patch.object(main, 'MEMORY_ENABLED', True), patch.object(
            main, 'get_conversation_model_settings', AsyncMock(return_value={'search_enabled': True})
        ), patch.object(conversation_recall, 'search', AsyncMock()) as search:
            self.assertEqual('', await main._build_past_conversation_recall_block('历史约定'))
        search.assert_not_awaited()

    async def test_fragment_recall_excludes_visible_ids(self):
        previous = main.fragments.pack([{'id': 5, 'content': '旧记忆'}], 500)
        with patch.object(main, 'MEMORY_ENABLED', True), patch.object(
            main, 'get_conversation_model_settings', AsyncMock(return_value={'cross_conversation_recall_enabled': True})
        ), patch.object(main, '_load_model_task_runtime', AsyncMock(return_value={'model':'','api_url':''})), \
           patch.object(conversation_recall, 'search', AsyncMock()) as original_search, \
           patch.object(main.fragments,'search', AsyncMock(return_value=[{'id':6,'content':'新的记忆'}])) as search:
            result = await main._build_past_conversation_recall_block('苹果', conv_id=7, messages=[
                {'role':'user','content':previous+'\n\n上一次对话'}])
        self.assertEqual({5}, search.await_args.kwargs['excluded'])
        self.assertEqual(7, search.await_args.kwargs['excluded_conversation_id'])
        self.assertIn('<fragment id="6">新的记忆</fragment>',result)
        original_search.assert_not_awaited()

    async def test_settings_update_is_independent_and_preserves_omitted_switch(self):
        for submitted, current, expected in [({'cross_conversation_recall_enabled': True}, False, True),
                                              ({'cross_conversation_recall_enabled': False}, True, False),
                                              ({}, True, True)]:
            with self.subTest(submitted=submitted):
                settings = {'cross_conversation_recall_enabled': current, 'nocturne_recall_enabled': False}
                request = MagicMock(json=AsyncMock(return_value=submitted))
                with patch.object(main, 'get_conversation_model_settings', AsyncMock(return_value=settings)), patch.object(
                    main, 'get_model_task_settings', AsyncMock(return_value={})
                ), patch.object(main, 'save_conversation_model_settings', AsyncMock(return_value=settings)) as save:
                    await main.api_update_conversation_model_settings(request)
                self.assertEqual(expected, save.await_args.kwargs['cross_conversation_recall_enabled'])
                self.assertNotIn('nocturne_recall_enabled', save.await_args.kwargs)
                self.assertFalse(save.await_args.kwargs['search_enabled'])

    async def test_switch_rejects_non_boolean_values(self):
        for value in [1, 'true', None, []]:
            with self.subTest(value=value):
                request = MagicMock(json=AsyncMock(return_value={'cross_conversation_recall_enabled': value}))
                response = await main.api_update_conversation_model_settings(request)
                self.assertEqual(400, response.status_code)

    async def test_database_migration_defaults_history_off_for_existing_rows(self):
        conn = MagicMock(execute=AsyncMock())
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        with patch.object(database, 'get_pool', AsyncMock(return_value=pool)):
            await database.init_conversation_model_settings_table()
        self.assertTrue(any('ADD COLUMN IF NOT EXISTS cross_conversation_recall_enabled BOOLEAN NOT NULL DEFAULT FALSE'
                            in call.args[0] for call in conn.execute.await_args_list))

    def test_public_settings_expose_independent_history_switch(self):
        self.assertFalse(main._public_conversation_model_settings({})['cross_conversation_recall_enabled'])
        data = main._public_conversation_model_settings({'cross_conversation_recall_enabled': True,
                                                         'nocturne_recall_enabled': False})
        self.assertTrue(data['cross_conversation_recall_enabled'])
        self.assertNotIn('nocturne_recall_enabled', data)
