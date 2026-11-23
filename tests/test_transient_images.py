import copy
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import database
import main
from transient_images import without_images
from tests import test_gateway_backup as backup_tests


class TransientImageTests(unittest.IsolatedAsyncioTestCase):
    def test_nested_images_are_removed_without_mutating_live_tool_round(self):
        live = [{'type': 'text', 'text': '看看这个'},
                {'type': 'image', 'source': {'type': 'base64', 'data': 'SECRET'}},
                {'type': 'tool_result', 'tool_use_id': 't1', 'content': [
                    {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,SECRET'}},
                    {'type': 'text', 'text': '工具文字'}]},
                {'type': 'input_image', 'image_url': 'https://example.com/image.png'}]
        before = copy.deepcopy(live)
        stored = without_images(live)
        self.assertEqual(live, before)
        self.assertNotIn('SECRET', json.dumps(stored))
        self.assertNotIn('https://', json.dumps(stored))
        self.assertEqual(stored[2]['tool_use_id'], 't1')
        self.assertEqual(stored[2]['content'][1]['text'], '工具文字')
        self.assertEqual(json.loads(without_images(json.dumps(live))), stored)

    async def test_message_save_strips_images_at_database_boundary(self):
        conn = MagicMock(fetchval=AsyncMock(return_value=7), execute=AsyncMock(),
                         fetchrow=AsyncMock(return_value={'id': 1}))
        live = [{'type': 'image', 'source': {'data': 'SECRET'}}]
        with patch.object(database, 'get_pool', AsyncMock(return_value=backup_tests.GatewayBackupTests._pool_with_connection(conn))):
            await database.save_context_message(7, 'user', '[图片]', content_json=live)
        self.assertNotIn('SECRET', conn.fetchrow.call_args.args[4])
        self.assertEqual(live[0]['source']['data'], 'SECRET')

    async def test_old_backup_images_are_not_reimported(self):
        conn = MagicMock(executemany=AsyncMock())
        await database._restore_backup_section(conn, 'context_messages', [{
            'id': 1, 'role': 'user', 'content': '文字',
            'content_json': [{'type': 'image_url', 'image_url': {'url': 'SECRET'}}]}])
        self.assertNotIn('SECRET', str(conn.executemany.call_args))

    async def test_export_filters_legacy_images_without_changing_database_row(self):
        old_row = {'id': 1, 'content_json': json.dumps([
            {'type': 'text', 'text': '旧文字'},
            {'type': 'image', 'source': {'data': 'SECRET'}}])}
        async def cursor(query, **kwargs):
            if ' FROM context_messages ' in query:
                yield old_row
        conn = MagicMock(cursor=MagicMock(side_effect=cursor), fetchval=AsyncMock(return_value=0))
        with patch.object(database, 'get_pool', AsyncMock(return_value=backup_tests.GatewayBackupTests._pool_with_connection(conn))):
            rows = [item async for item in database.iter_gateway_backup_data()]
        exported = next(row for section, row in rows if section == 'context_messages' and row)
        self.assertNotIn('SECRET', str(exported))
        self.assertIn('旧文字', str(exported))
        self.assertIn('SECRET', old_row['content_json'])

    def test_old_history_does_not_replay_images(self):
        result = main._rebuild_messages_from_rows([{
            'role': 'user', 'content': '文字', 'content_json': json.dumps([
                {'type': 'text', 'text': '文字'},
                {'type': 'image', 'source': {'data': 'SECRET'}}])}])
        self.assertNotIn('SECRET', str(result))
        self.assertIn('文字', str(result))
