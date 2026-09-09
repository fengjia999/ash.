import asyncio
import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import database


class ConversationActivationTests(unittest.IsolatedAsyncioTestCase):
    async def test_delayed_shortcut_cannot_override_a_completed_switch(self):
        lock = asyncio.Lock()
        first_locked = asyncio.Event()
        release_first = asyncio.Event()
        second_waiting = asyncio.Event()
        state = {"active": 7, "connections": 0, "inserted": False}

        class Connection:
            def __init__(self, number):
                self.number = number
                self.locked = False

            @asynccontextmanager
            async def transaction(self):
                try:
                    yield
                finally:
                    if self.locked:
                        lock.release()

            async def execute(self, query, *args):
                if "pg_advisory_xact_lock" in query:
                    if self.number == 2:
                        second_waiting.set()
                    await lock.acquire()
                    self.locked = True
                    if self.number == 1:
                        first_locked.set()
                        await release_first.wait()
                elif "SET is_active = FALSE" in query:
                    state["active"] = None
                elif "SET is_active = TRUE" in query:
                    state["active"] = args[0]

            async def fetchval(self, query, *args):
                return True

            async def fetchrow(self, query, *args):
                if "INSERT INTO conversations" in query:
                    state["inserted"] = True
                    raise AssertionError("stale command created a conversation")
                if "WHERE id = $1" in query:
                    return {"id": args[0], "is_active": state["active"] == args[0]}
                return {"id": state["active"], "is_active": True}

        class Pool:
            @asynccontextmanager
            async def acquire(self):
                state["connections"] += 1
                yield Connection(state["connections"])

        with patch.object(database, "get_pool", AsyncMock(return_value=Pool())):
            first = asyncio.create_task(database.set_active_conversation(8, False))
            second = None
            try:
                await asyncio.wait_for(first_locked.wait(), 1)
                second = asyncio.create_task(database.create_conversation_from_messages(
                    7, "delayed shortcut", [], False, require_active_source=True
                ))
                await asyncio.wait_for(second_waiting.wait(), 1)
                self.assertFalse(second.done())
                release_first.set()
                await asyncio.wait_for(first, 1)
                with self.assertRaisesRegex(ValueError, "当前活动会话已变化"):
                    await asyncio.wait_for(second, 1)
            finally:
                release_first.set()
                for task in (first, second):
                    if task is not None and not task.done():
                        task.cancel()
                await asyncio.gather(*(t for t in (first, second) if t), return_exceptions=True)

        self.assertEqual(state["active"], 8)
        self.assertFalse(state["inserted"])
