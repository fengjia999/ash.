import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import recall_audit as audit


class RecallAuditTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        audit.active.set(None)
        self.conn = MagicMock(execute=AsyncMock(), fetchrow=AsyncMock())
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=self.conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        self.enterContext(patch.object(audit.db, 'get_pool', AsyncMock(return_value=pool)))

    async def asyncTearDown(self):
        audit.active.set(None)

    async def test_snapshot_and_reply_link_use_exact_request_not_nearest_user(self):
        await audit.capture(7, 12, '问题', '<system_info>本次原文</system_info>')
        await audit.link(7, 19)
        self.assertEqual((19, 12), self.conn.execute.await_args.args[1:])
        calls = self.conn.execute.await_count
        await audit.link(8, 20)
        self.assertEqual(calls, self.conn.execute.await_count)

    async def test_read_returns_original_snapshot_without_retrieval(self):
        snapshot = '<system_info><past_conversations><past_turn conversation_id="2" turn_id="3"><message role="user" date="2020-01-01">原话 &lt;script&gt;</message></past_turn></past_conversations></system_info>'
        self.conn.fetchrow.return_value = {'query': '过去的问题', 'injection': snapshot}
        data = await audit.read(19)
        self.assertEqual(snapshot, data['injection'])
        self.assertEqual('原话 <script>', data['results'][0]['messages'][0]['text'])
        self.assertEqual(3, data['results'][0]['turn_id'])

    async def test_missing_record_is_distinct_from_recorded_empty_recall(self):
        self.conn.fetchrow.return_value = None
        self.assertFalse((await audit.read(19))['recorded'])
        self.conn.fetchrow.return_value = {'query': '问题', 'injection': ''}
        data = await audit.read(20)
        self.assertTrue(data['recorded'])
        self.assertEqual([], data['results'])
