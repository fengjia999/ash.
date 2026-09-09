"""Deterministic forgetting proposals. No model calls and no automatic deletion."""
import asyncio
import json
import math
import os
from datetime import datetime, timezone

from database import get_pool, _json_object

THRESHOLD = max(.01, min(.9, float(os.getenv('FRAGMENT_FORGET_THRESHOLD', '.2'))))


def retention(memory, now=None):
    metadata = _json_object(memory.get('metadata'))
    if metadata.get('entry_kind') != 'fragment' or metadata.get('keep_forever'):
        return None
    importance = metadata.get('importance')
    if type(importance) not in (int, float) or not math.isfinite(importance) or not 0 <= importance <= 1:
        return None  # Unscored legacy memories wait for scoring.
    start = metadata.get('retention_reset_at') or metadata.get('importance_scored_at')
    if not start and metadata.get('extraction_job_id'):
        start = memory.get('created_at')
    if isinstance(start, str):
        try:
            start = datetime.fromisoformat(start.replace('Z', '+00:00'))
        except ValueError:
            return None
    if not isinstance(start, datetime):
        return None
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    age = max(0, ((now or datetime.now(timezone.utc)) - start).total_seconds() / 86400)
    # Half-life ranges from 30 to 180 days with importance. Rejection resets
    # this clock, so the item cannot immediately re-enter the pending queue.
    return 2 ** (-age / (30 + 150 * importance))


async def init_decay_tables():
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS fragment_forgetting_pending (
                memory_id INTEGER PRIMARY KEY REFERENCES long_term_memories(id) ON DELETE CASCADE,
                content_snapshot TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        ''')


async def sweep():
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            rows = await conn.fetch('''
                SELECT id, content, metadata, created_at FROM long_term_memories
                WHERE metadata->>'entry_kind' = 'fragment' FOR UPDATE SKIP LOCKED
            ''')
            for row in rows:
                score = retention(dict(row))
                if score is not None and score < THRESHOLD:
                    await conn.execute('''
                        INSERT INTO fragment_forgetting_pending(memory_id, content_snapshot)
                        VALUES ($1, $2) ON CONFLICT DO NOTHING
                    ''', row['id'], row['content'])
                    await conn.execute('''
                        UPDATE long_term_memories
                        SET metadata = metadata || '{"forgetting_pending":true}'::jsonb WHERE id = $1
                    ''', row['id'])


async def list_pending():
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch('''
            SELECT m.id, m.content, m.metadata FROM fragment_forgetting_pending p
            JOIN long_term_memories m ON m.id = p.memory_id ORDER BY p.created_at, m.id
        ''')
    return [{'id': row['id'], 'content': row['content'],
             'anchors': _json_object(row['metadata']).get('anchors', [])} for row in rows]


async def resolve(memory_id, forget):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Same lock order as sweep, and compare reviewed contents before deletion.
            memory = await conn.fetchrow('SELECT * FROM long_term_memories WHERE id = $1 FOR UPDATE', memory_id)
            if not memory:
                return False
            pending = await conn.fetchrow('SELECT * FROM fragment_forgetting_pending WHERE memory_id = $1 FOR UPDATE', memory_id)
            if not pending:
                return False
            if forget:
                if memory['content'] != pending['content_snapshot']:
                    raise ValueError('碎片内容已变化，请先保留并重新核对')
                await conn.execute('DELETE FROM long_term_memories WHERE id = $1', memory_id)
            else:
                await conn.execute('''
                    UPDATE long_term_memories SET metadata =
                        (metadata - 'forgetting_pending') || $2::jsonb WHERE id = $1
                ''', memory_id, json.dumps({'retention_reset_at': datetime.now(timezone.utc).isoformat()}))
                await conn.execute('DELETE FROM fragment_forgetting_pending WHERE memory_id = $1', memory_id)
    return True


async def decay_worker():
    while True:
        try:
            await sweep()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            print(f'[fragment-decay] {type(error).__name__}')
        await asyncio.sleep(3600)
