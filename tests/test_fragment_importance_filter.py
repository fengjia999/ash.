import unittest
from unittest.mock import AsyncMock, patch

import main
import memory_fragments as fragments


class FragmentImportanceFilterTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_applies_importance_upper_bound(self):
        pool = AsyncMock()
        pool.fetch.return_value = []

        with patch.object(fragments.db, "get_pool", AsyncMock(return_value=pool)):
            await fragments.search(max_importance=4, excluded_conversation_id=7)

        query = pool.fetch.await_args.args[0]
        self.assertIn("importance<=$9", query)
        self.assertIn("source_session IS DISTINCT FROM $10::text", query)
        self.assertIn("JOIN context_messages", query)
        self.assertEqual((4, 7), pool.fetch.await_args.args[-2:])

    async def test_directory_validates_and_forwards_importance_upper_bound(self):
        search = AsyncMock(return_value=[])
        with patch.object(main, "MEMORY_ENABLED", True), patch.object(
            main.fragments, "search", search
        ):
            result = await main.fragment_directory(max_importance=4)
            invalid = await main.fragment_directory(max_importance=0)

        self.assertEqual([], result)
        search.assert_awaited_once_with(
            "", None, limit=40, before=None, chronology=True, max_importance=4
        )
        self.assertEqual(400, invalid.status_code)

