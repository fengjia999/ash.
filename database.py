import asyncio
import os
import uuid
import re
import json
import math
import hashlib
from datetime import date, datetime, timedelta, timezone
from typing import Optional, List

import asyncpg
import httpx

# ---------- jieba 分词 ----------
import jieba
import logging
jieba.setLogLevel(logging.INFO)

DATABASE_URL = os.getenv("DATABASE_URL", "")
# Shared across workers and all explicit conversation-switch paths.
CONVERSATION_SWITCH_LOCK = 0x415348434F4E56
TIMEZONE_HOURS = int(os.getenv("TIMEZONE_HOURS", "8"))
FLOW_MEMORY_DEFAULT_MAX_ITEMS = max(
    1, min(100, int(os.getenv("FLOW_MEMORY_MAX_ITEMS", "8")))
)
# Count is the user-facing retention policy. This token ceiling remains only as
# an emergency guard against a handful of unusually large summaries.
FLOW_MEMORY_HARD_TOKENS = max(
    1, int(os.getenv("FLOW_MEMORY_HARD_TOKENS", "12000"))
)

# 搜索权重
WEIGHT_SEMANTIC = float(os.getenv("WEIGHT_SEMANTIC", "0.65"))
WEIGHT_KEYWORD = float(os.getenv("WEIGHT_KEYWORD", "0.20"))
WEIGHT_IMPORTANCE = float(os.getenv("WEIGHT_IMPORTANCE", "0.10"))
WEIGHT_RECENCY = float(os.getenv("WEIGHT_RECENCY", "0.05"))
MIN_SCORE_THRESHOLD = float(os.getenv("MIN_SCORE_THRESHOLD", "0.25"))
LONG_TERM_RECALL_MIN_SEMANTIC_SCORE = max(
    0.0,
    min(1.0, float(os.getenv("LONG_TERM_RECALL_MIN_SEMANTIC_SCORE", "0.35"))),
)
FRAGMENT_RECENCY_HALF_LIFE_DAYS = max(
    1.0, float(os.getenv('FRAGMENT_RECENCY_HALF_LIFE_DAYS', '30'))
)


def fragment_recall_scores(memory, query, semantic, related_ids=(), now=None):
    """All components are in [0, 1]; eligibility is checked before ranking."""
    metadata = _json_object(memory.get('metadata'))
    importance = metadata.get('importance', 0.5)
    try:
        importance = float(importance)
        if not math.isfinite(importance):
            importance = 0.5
    except (TypeError, ValueError):
        importance = 0.5
    recency = 0.0
    # Migration timestamps are not evidence of freshness.
    created = memory.get('created_at') if metadata.get('extraction_job_id') else None
    if isinstance(created, str):
        try:
            created = datetime.fromisoformat(created.replace('Z', '+00:00'))
        except ValueError:
            created = None
    if isinstance(created, datetime):
        created = created.replace(tzinfo=timezone.utc) if created.tzinfo is None else created
        age = max(0, ((now or datetime.now(timezone.utc)) - created).total_seconds() / 86400)
        recency = 2 ** (-age / FRAGMENT_RECENCY_HALF_LIFE_DAYS)
    entities = metadata.get('entities') or []
    entities = {entity.strip().casefold() for entity in entities
                if isinstance(entity, str) and entity.strip()} if isinstance(entities, list) else set()
    query = query.casefold()
    overlap = sum(entity in query for entity in entities) / len(entities) if entities else 0.0
    source_id = str(metadata.get('source_conversation_id') or '')
    affinity = float(bool(source_id) and source_id in {str(value) for value in related_ids})
    parts = dict(semantic_similarity=max(0.0, min(1.0, semantic)), recency_score=recency,
                 importance=max(0.0, min(1.0, importance)), entity_overlap=overlap,
                 thread_affinity=affinity)
    parts['total'] = (parts['semantic_similarity'] * 0.45 + recency * 0.20
                      + parts['importance'] * 0.15 + overlap * 0.10 + affinity * 0.10)
    return parts

# OpenAI-compatible Embeddings
EMBEDDING_ENABLED = os.getenv("EMBEDDING_ENABLED", "false").lower() == "true"
EMBEDDING_BASE_URL = os.getenv("EMBEDDING_BASE_URL", "").rstrip("/")
EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY", "")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
EMBEDDING_TIMEOUT = float(os.getenv("EMBEDDING_TIMEOUT", "60"))
LONG_TERM_RECALL_EMBEDDING_TIMEOUT = max(
    0.1,
    float(os.getenv("LONG_TERM_RECALL_EMBEDDING_TIMEOUT", "5")),
)
EMBEDDING_MAX_INPUT_CHARS = int(os.getenv("EMBEDDING_MAX_INPUT_CHARS", "8000"))
EMBEDDING_AUTOFILL_LIMIT = int(os.getenv("EMBEDDING_AUTOFILL_LIMIT", "10"))

# ============================================================
# 记忆分层：类型常量
# ============================================================

MEMORY_TYPES = {
    "factual",    # 长期事实：偏好、习惯、人物关系
    "episodic",   # 情景记忆：某天发生的具体事件
    "diary",      # 助手生成的日记/内心独白
    "quote",      # 对话原话存档
    "temp",       # 临时记忆：备忘、短期上下文
}

# 类型权重加成（用于搜索排序）
TYPE_WEIGHT_BOOST = {
    "quote": 0.10,      # 原话加分
    "factual": 0.05,    # 事实微加
    "episodic": 0.03,   # 情景中等
    "diary": 0.0,       # 日记不主动浮出（除非语义很匹配）
    "temp": -0.05,      # 临时记忆降权
}

# ============================================================
# 连接池管理
# ============================================================

_pool: Optional[asyncpg.Pool] = None
_long_term_embedding_refresh_task: asyncio.Task | None = None

async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        if not DATABASE_URL:
            raise RuntimeError("DATABASE_URL 未设置！")
        _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
        print("✅ 数据库连接池已创建")
    return _pool


def _json_list(value) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _json_object(value) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}

async def close_pool():
    global _pool, _long_term_embedding_refresh_task
    refresh_task = _long_term_embedding_refresh_task
    _long_term_embedding_refresh_task = None
    if refresh_task and not refresh_task.done():
        refresh_task.cancel()
        try:
            await refresh_task
        except asyncio.CancelledError:
            pass
    if _pool:
        await _pool.close()
        _pool = None
        print("✅ 数据库连接池已关闭")


# ============================================================
# 表结构初始化
# ============================================================

async def migrate_memory_layers():
    """给 memories 表加分层字段（幂等，跑多次不报错）"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        # 加字段
        await conn.execute("""
            ALTER TABLE memories ADD COLUMN IF NOT EXISTS type VARCHAR(20) DEFAULT 'factual'
        """)
        await conn.execute("""
            ALTER TABLE memories ADD COLUMN IF NOT EXISTS metadata JSONB
        """)
        await conn.execute("""
            ALTER TABLE memories ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ
        """)
        await conn.execute("""
            ALTER TABLE memories ADD COLUMN IF NOT EXISTS tags TEXT[]
        """)
        await conn.execute("""
            ALTER TABLE memories ADD COLUMN IF NOT EXISTS pinned BOOLEAN DEFAULT FALSE
        """)
        await conn.execute("""
            ALTER TABLE memories ADD COLUMN IF NOT EXISTS access_count INTEGER DEFAULT 0
        """)

        # 加索引
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(type)
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_expires
            ON memories(expires_at) WHERE expires_at IS NOT NULL
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_tags ON memories USING gin(tags)
        """)

    print("[db] ✅ memory layers migration done")


async def init_tables():
    pool = await get_pool()
    async with pool.acquire() as conn:
        # 记忆表
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id              SERIAL PRIMARY KEY,
                content         TEXT NOT NULL,
                importance      INTEGER DEFAULT 5,
                source_session  TEXT,
                created_at      TIMESTAMPTZ DEFAULT NOW(),
                last_accessed   TIMESTAMPTZ DEFAULT NOW(),
                access_count    INTEGER DEFAULT 0
            );
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_fts
            ON memories
            USING gin(to_tsvector('simple', content));
        """)
        # memory_embeddings 表
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS memory_embeddings (
                memory_id       INTEGER PRIMARY KEY REFERENCES memories(id) ON DELETE CASCADE,
                embedding       JSONB NOT NULL,
                model           TEXT NOT NULL,
                dim             INTEGER,
                updated_at      TIMESTAMPTZ DEFAULT NOW()
            );
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_memory_embeddings_model
            ON memory_embeddings (model);
        """)

        await init_context_tables()

        # Legacy dashboard archives duplicated context_messages and are no longer used.
        # Remove them after the canonical conversation tables are available.
        await conn.execute("DROP TABLE IF EXISTS session_archive_messages")
        await conn.execute("DROP TABLE IF EXISTS session_archives")

        await init_standing_memory_tables()
        await init_long_term_memory_tables()
        await init_flow_memory_settings_table()
        await enforce_flow_memory_window()

        await init_token_usage_tables()

        # memory_snapshots 表（手动记忆编辑回滚用）
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS memory_snapshots (
                id              SERIAL PRIMARY KEY,
                created_at      TIMESTAMPTZ DEFAULT NOW(),
                reason          TEXT,
                memory_count    INTEGER,
                snapshot        JSONB NOT NULL
            );
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_snapshots_created
            ON memory_snapshots (created_at DESC);
        """)

        # Rolling conversation summaries are retired. Existing legacy tables are
        # deliberately left untouched so upgrading does not destroy old data.

    # 执行分层字段迁移
    await migrate_memory_layers()

    print("✅ 数据库表结构已就绪")


async def init_standing_memory_tables():
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS standing_memory_blocks (
                id                      SERIAL PRIMARY KEY,
                title                   TEXT NOT NULL,
                content                 TEXT NOT NULL DEFAULT '',
                parent_id               INTEGER REFERENCES standing_memory_blocks(id) ON DELETE SET NULL,
                status                  TEXT NOT NULL DEFAULT 'active',
                source                  TEXT NOT NULL DEFAULT 'manual',
                layer                   TEXT NOT NULL DEFAULT 'core',
                inject_enabled          BOOLEAN NOT NULL DEFAULT TRUE,
                inject_every_n          INTEGER NOT NULL DEFAULT 1,
                inject_on_first_turn    BOOLEAN NOT NULL DEFAULT TRUE,
                sort_order              INTEGER NOT NULL DEFAULT 0,
                metadata                JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at              TIMESTAMPTZ DEFAULT NOW(),
                updated_at              TIMESTAMPTZ DEFAULT NOW(),
                -- Model-authored changes stay pending until approved by the user.
                CHECK (status IN ('active', 'pending', 'archived')),
                CHECK (source IN ('manual', 'model')),
                CHECK (inject_every_n >= 1)
            );
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_standing_memory_parent
            ON standing_memory_blocks(parent_id, sort_order, id);
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_standing_memory_status
            ON standing_memory_blocks(status);
        """)
        await conn.execute("""
            ALTER TABLE standing_memory_blocks
            ADD COLUMN IF NOT EXISTS layer TEXT NOT NULL DEFAULT 'core';
        """)
        await conn.execute("""
            ALTER TABLE standing_memory_blocks
            ALTER COLUMN status SET DEFAULT 'active';
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_standing_memory_layer
            ON standing_memory_blocks(layer);
        """)
        # Legacy proposal storage is retained only so old backups remain
        # round-trippable. No runtime code creates or applies these records.
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS memory_update_proposals (
                id                      SERIAL PRIMARY KEY,
                title                   TEXT NOT NULL DEFAULT '',
                target_layer            TEXT NOT NULL DEFAULT 'recent',
                target_block_id         INTEGER REFERENCES standing_memory_blocks(id) ON DELETE SET NULL,
                status                  TEXT NOT NULL DEFAULT 'pending',
                source                  TEXT NOT NULL DEFAULT 'model',
                source_ids              JSONB NOT NULL DEFAULT '[]'::jsonb,
                rationale               TEXT NOT NULL DEFAULT '',
                content                 TEXT NOT NULL DEFAULT '',
                score                   INTEGER NOT NULL DEFAULT 0,
                metadata                JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at              TIMESTAMPTZ DEFAULT NOW(),
                updated_at              TIMESTAMPTZ DEFAULT NOW(),
                CHECK (target_layer IN ('core', 'ring', 'recent')),
                CHECK (status IN ('pending', 'accepted', 'rejected', 'applied', 'archived')),
                CHECK (source IN ('manual', 'model'))
            );
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_memory_update_proposals_status
            ON memory_update_proposals(status, target_layer, created_at DESC);
        """)


async def init_long_term_memory_tables():
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS long_term_memories (
                id          SERIAL PRIMARY KEY,
                title       TEXT NOT NULL,
                keywords    JSONB NOT NULL DEFAULT '[]'::jsonb,
                summary     TEXT NOT NULL DEFAULT '',
                content     TEXT NOT NULL DEFAULT '',
                memory_date DATE DEFAULT CURRENT_DATE
            );
        """)
        await conn.execute("""
            ALTER TABLE long_term_memories
            ADD COLUMN IF NOT EXISTS memory_date DATE;
        """)
        await conn.execute("""
            ALTER TABLE long_term_memories
            ALTER COLUMN memory_date SET DEFAULT CURRENT_DATE;
        """)
        await conn.execute("""
            ALTER TABLE long_term_memories
            ADD COLUMN IF NOT EXISTS priority INTEGER NOT NULL DEFAULT 0;
        """)
        await conn.execute("""
            ALTER TABLE long_term_memories
            ADD COLUMN IF NOT EXISTS enabled BOOLEAN NOT NULL DEFAULT TRUE;
        """)
        await conn.execute("""
            ALTER TABLE long_term_memories
            ADD COLUMN IF NOT EXISTS summary TEXT NOT NULL DEFAULT '';
        """)
        await conn.execute("""
            ALTER TABLE long_term_memories
                ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();
        """)
        await conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_long_term_memory_source_flow
            ON long_term_memories ((metadata->>'source_flow_memory_id'))
            WHERE metadata ? 'source_flow_memory_id';
        """)
        # Flow overflow has always been diary material. Repair rows that were
        # temporarily misclassified while the fragment branch was introduced.
        await conn.execute("""
            UPDATE long_term_memories
            SET metadata = jsonb_set(
                    COALESCE(metadata, '{}'::jsonb),
                    '{entry_kind}',
                    '"diary"'::jsonb,
                    TRUE
                ),
                title = COALESCE(NULLIF(btrim(title), ''), '会话摘要'),
                memory_date = COALESCE(
                    memory_date,
                    NULLIF(metadata->>'flow_entered_on', '')::date,
                    created_at::date
                )
            WHERE metadata ? 'source_flow_memory_id'
               OR metadata->>'promoted_from' = 'standing_flow'
               OR metadata->>'source' = 'promoted_from_flow';
        """)
        await conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_fragment_source_diary_summary
            ON long_term_memories ((metadata->>'source_diary_summary_id'))
            WHERE metadata ? 'source_diary_summary_id';
        """)
        # A diary summary becomes a separate, text-only fragment. The source
        # diary remains intact; only its obsolete summary field is cleared.
        # source_diary_summary_id makes this split idempotent across restarts.
        await conn.execute("""
            INSERT INTO long_term_memories
                (title, keywords, summary, content, memory_date,
                 priority, enabled, metadata)
            SELECT
                '', '[]'::jsonb, '', btrim(diary.summary), NULL,
                diary.priority, diary.enabled,
                jsonb_build_object(
                    'entry_kind', 'fragment',
                    'source_diary_summary_id', diary.id,
                    'migrated_from', 'diary_summary'
                )
            FROM long_term_memories AS diary
            WHERE COALESCE(diary.metadata->>'entry_kind', 'diary') = 'diary'
              AND btrim(diary.summary) <> ''
            ON CONFLICT DO NOTHING;
        """)
        await conn.execute("""
            UPDATE long_term_memories
            SET summary = ''
            WHERE COALESCE(metadata->>'entry_kind', 'diary') = 'diary'
              AND btrim(summary) <> '';
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS long_term_memory_proposals (
                id                  SERIAL PRIMARY KEY,
                operation           TEXT NOT NULL,
                target_memory_id    INTEGER REFERENCES long_term_memories(id) ON DELETE CASCADE,
                title               TEXT NOT NULL DEFAULT '',
                keywords            JSONB NOT NULL DEFAULT '[]'::jsonb,
                summary             TEXT NOT NULL DEFAULT '',
                content             TEXT NOT NULL DEFAULT '',
                source              TEXT NOT NULL DEFAULT 'model',
                CHECK (operation IN ('create', 'edit', 'delete')),
                CHECK (source IN ('manual', 'model'))
            );
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_long_term_memory_proposals_target
            ON long_term_memory_proposals(target_memory_id, id);
        """)
        await conn.execute("""
            ALTER TABLE long_term_memory_proposals
            ADD COLUMN IF NOT EXISTS summary TEXT NOT NULL DEFAULT '';
        """)
        await conn.execute("""
            ALTER TABLE long_term_memory_proposals
                ADD COLUMN IF NOT EXISTS memory_date DATE,
                ADD COLUMN IF NOT EXISTS priority INTEGER NOT NULL DEFAULT 0,
                ADD COLUMN IF NOT EXISTS enabled BOOLEAN NOT NULL DEFAULT TRUE,
                ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW()
        """)
        await conn.execute("""
            UPDATE long_term_memory_proposals
            SET summary = COALESCE((
                SELECT string_agg(entry.value, '；')
                FROM jsonb_array_elements_text(COALESCE(keywords, '[]'::jsonb)) AS entry(value)
            ), '')
            WHERE btrim(summary) = '' AND keywords <> '[]'::jsonb;
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS long_term_memory_embeddings (
                memory_id       INTEGER PRIMARY KEY REFERENCES long_term_memories(id) ON DELETE CASCADE,
                content_hash    TEXT NOT NULL,
                embedding       JSONB,
                embedding_model TEXT NOT NULL,
                embedding_config_hash TEXT NOT NULL DEFAULT '',
                indexed_at      TIMESTAMPTZ DEFAULT NOW()
            );
        """)
        await conn.execute("""
            ALTER TABLE long_term_memory_embeddings
            ADD COLUMN IF NOT EXISTS embedding_config_hash TEXT NOT NULL DEFAULT ''
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_long_term_memory_embeddings_config
            ON long_term_memory_embeddings(embedding_model, embedding_config_hash);
        """)


async def init_token_usage_tables():
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS token_usage_logs (
                id                      SERIAL PRIMARY KEY,
                created_at              TIMESTAMPTZ DEFAULT NOW(),
                session_id              TEXT,
                provider                TEXT,
                model                   TEXT,
                route                   TEXT,
                stream                  BOOLEAN NOT NULL DEFAULT FALSE,
                success                 BOOLEAN NOT NULL DEFAULT TRUE,
                input_tokens            INTEGER NOT NULL DEFAULT 0,
                output_tokens           INTEGER NOT NULL DEFAULT 0,
                total_tokens            INTEGER NOT NULL DEFAULT 0,
                cache_read_tokens       INTEGER NOT NULL DEFAULT 0,
                cache_creation_tokens   INTEGER NOT NULL DEFAULT 0,
                reasoning_tokens        INTEGER NOT NULL DEFAULT 0,
                tool_rounds             INTEGER NOT NULL DEFAULT 0,
                latency_ms              INTEGER NOT NULL DEFAULT 0,
                metadata                JSONB NOT NULL DEFAULT '{}'::jsonb
            );
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_token_usage_created
            ON token_usage_logs (created_at DESC);
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_token_usage_model
            ON token_usage_logs (model, created_at DESC);
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_token_usage_provider
            ON token_usage_logs (provider, created_at DESC);
        """)


async def save_token_usage(
    session_id: str | int | None = None,
    provider: str = "",
    model: str = "",
    route: str = "",
    stream: bool = False,
    success: bool = True,
    input_tokens: int = 0,
    output_tokens: int = 0,
    total_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_creation_tokens: int = 0,
    reasoning_tokens: int = 0,
    tool_rounds: int = 0,
    latency_ms: int = 0,
    metadata: dict | None = None,
) -> int:
    pool = await get_pool()
    input_tokens = int(input_tokens or 0)
    output_tokens = int(output_tokens or 0)
    total_tokens = int(total_tokens or input_tokens + output_tokens)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO token_usage_logs
                (session_id, provider, model, route, stream, success,
                 input_tokens, output_tokens, total_tokens,
                 cache_read_tokens, cache_creation_tokens, reasoning_tokens,
                 tool_rounds, latency_ms, metadata)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15::jsonb)
            RETURNING id
            """,
            str(session_id) if session_id is not None else None,
            provider or "",
            model or "",
            route or "",
            bool(stream),
            bool(success),
            input_tokens,
            output_tokens,
            total_tokens,
            int(cache_read_tokens or 0),
            int(cache_creation_tokens or 0),
            int(reasoning_tokens or 0),
            int(tool_rounds or 0),
            int(latency_ms or 0),
            json.dumps(metadata or {}),
        )
        return row["id"]


async def get_token_usage_summary(days: int = 7) -> dict:
    days = max(1, int(days or 7))
    pool = await get_pool()
    async with pool.acquire() as conn:
        totals = await conn.fetchrow(
            """
            SELECT
                COALESCE(SUM(total_tokens), 0)::bigint AS total_tokens,
                COALESCE(SUM(input_tokens), 0)::bigint AS input_tokens,
                COALESCE(SUM(output_tokens), 0)::bigint AS output_tokens,
                COALESCE(SUM(cache_read_tokens), 0)::bigint AS cache_read_tokens,
                COALESCE(SUM(cache_creation_tokens), 0)::bigint AS cache_creation_tokens,
                COUNT(*)::bigint AS request_count
            FROM token_usage_logs
            WHERE created_at >= NOW() - ($1::int * INTERVAL '1 day')
            """,
            days,
        )
        model_rows = await conn.fetch(
            """
            SELECT
                model,
                provider,
                COUNT(*)::bigint AS request_count,
                COALESCE(SUM(input_tokens), 0)::bigint AS input_tokens,
                COALESCE(SUM(output_tokens), 0)::bigint AS output_tokens,
                COALESCE(SUM(total_tokens), 0)::bigint AS total_tokens
            FROM token_usage_logs
            WHERE created_at >= NOW() - ($1::int * INTERVAL '1 day')
            GROUP BY model, provider
            ORDER BY total_tokens DESC
            LIMIT 20
            """,
            days,
        )
        daily_rows = await conn.fetch(
            """
            SELECT
                created_at::date AS day,
                COUNT(*)::bigint AS request_count,
                COALESCE(SUM(input_tokens), 0)::bigint AS input_tokens,
                COALESCE(SUM(output_tokens), 0)::bigint AS output_tokens,
                COALESCE(SUM(total_tokens), 0)::bigint AS total_tokens,
                COALESCE(SUM(cache_read_tokens), 0)::bigint AS cache_read_tokens,
                COALESCE(SUM(cache_creation_tokens), 0)::bigint AS cache_creation_tokens
            FROM token_usage_logs
            WHERE created_at >= NOW() - ($1::int * INTERVAL '1 day')
            GROUP BY day
            ORDER BY day ASC
            """,
            days,
        )
        provider_rows = await conn.fetch(
            """
            SELECT
                provider,
                COUNT(*)::bigint AS request_count,
                COALESCE(SUM(input_tokens), 0)::bigint AS input_tokens,
                COALESCE(SUM(output_tokens), 0)::bigint AS output_tokens,
                COALESCE(SUM(total_tokens), 0)::bigint AS total_tokens
            FROM token_usage_logs
            WHERE created_at >= NOW() - ($1::int * INTERVAL '1 day')
            GROUP BY provider
            ORDER BY total_tokens DESC
            """,
            days,
        )
    return {
        "days": days,
        "total_tokens": int(totals["total_tokens"]),
        "input_tokens": int(totals["input_tokens"]),
        "output_tokens": int(totals["output_tokens"]),
        "cache_read_tokens": int(totals["cache_read_tokens"]),
        "cache_creation_tokens": int(totals["cache_creation_tokens"]),
        "request_count": int(totals["request_count"]),
        "model_ranking": [dict(r) for r in model_rows],
        "daily_usage": [{**dict(r), "day": r["day"].isoformat()} for r in daily_rows],
        "provider_usage": [dict(r) for r in provider_rows],
    }


async def get_token_usage_logs(limit: int = 100, days: int | None = None) -> list[dict]:
    limit = min(max(1, int(limit or 100)), 500)
    pool = await get_pool()
    async with pool.acquire() as conn:
        if days is None:
            rows = await conn.fetch(
                """
                SELECT *
                FROM token_usage_logs
                ORDER BY created_at DESC
                LIMIT $1
                """,
                limit,
            )
        else:
            days = max(1, int(days or 7))
            rows = await conn.fetch(
                """
                SELECT *
                FROM token_usage_logs
                WHERE created_at >= NOW() - ($1::int * INTERVAL '1 day')
                ORDER BY created_at DESC
                LIMIT $2
                """,
                days,
                limit,
            )
    return [dict(r) for r in rows]


async def init_heartbeat_activity_tables():
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS heartbeat_activity_logs (
                id                  SERIAL PRIMARY KEY,
                created_at          TIMESTAMPTZ DEFAULT NOW(),
                conversation_id     INTEGER,
                provider            TEXT,
                model               TEXT,
                elapsed_minutes     INTEGER NOT NULL DEFAULT 0,
                status              TEXT NOT NULL DEFAULT 'completed',
                final_text          TEXT NOT NULL DEFAULT '',
                tool_events         JSONB NOT NULL DEFAULT '[]'::jsonb,
                context_recorded    BOOLEAN NOT NULL DEFAULT FALSE
            );
        """)
        await conn.execute("""
            ALTER TABLE heartbeat_activity_logs
            ADD COLUMN IF NOT EXISTS context_recorded BOOLEAN NOT NULL DEFAULT FALSE;
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_heartbeat_activity_created
            ON heartbeat_activity_logs (created_at DESC);
        """)


async def init_heartbeat_settings_table():
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS heartbeat_settings (
                id              SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
                enabled         BOOLEAN NOT NULL DEFAULT FALSE,
                interval_minutes INTEGER NOT NULL DEFAULT 30,
                provider        TEXT NOT NULL DEFAULT 'openai',
                model           TEXT NOT NULL DEFAULT '',
                updated_at      TIMESTAMPTZ DEFAULT NOW()
            );
        """)


async def init_route_settings_table():
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS route_settings (
                id          SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
                provider    TEXT NOT NULL DEFAULT 'auto',
                updated_at  TIMESTAMPTZ DEFAULT NOW()
            );
        """)


async def init_flow_memory_settings_table():
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS flow_memory_settings (
                id          SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
                max_items   INTEGER NOT NULL DEFAULT 8
                            CHECK (max_items BETWEEN 1 AND 100),
                updated_at  TIMESTAMPTZ DEFAULT NOW()
            );
        """)


async def get_flow_memory_settings() -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT max_items, updated_at FROM flow_memory_settings WHERE id = 1"
        )
    if row:
        return dict(row)
    return {
        "max_items": FLOW_MEMORY_DEFAULT_MAX_ITEMS,
        "updated_at": None,
    }


async def save_flow_memory_settings(max_items: int) -> dict:
    max_items = int(max_items)
    if not 1 <= max_items <= 100:
        raise ValueError("max_items must be between 1 and 100")
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow("""
                INSERT INTO flow_memory_settings (id, max_items, updated_at)
                VALUES (1, $1, NOW())
                ON CONFLICT (id) DO UPDATE SET
                    max_items = EXCLUDED.max_items,
                    updated_at = NOW()
                RETURNING max_items, updated_at
            """, max_items)
            promoted_ids = await _promote_flow_memory_overflow(
                conn, max_items=max_items
            )
    return {
        **dict(row),
        "promoted_count": len(promoted_ids),
    }


async def init_anthropic_credentials_table():
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS anthropic_credentials (
                id          SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
                api_key     TEXT NOT NULL,
                updated_at  TIMESTAMPTZ DEFAULT NOW()
            );
        """)


async def get_anthropic_credentials() -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT api_key, updated_at FROM anthropic_credentials WHERE id = 1"
        )
    return dict(row) if row else {"api_key": "", "updated_at": None}


async def save_anthropic_api_key(api_key: str) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO anthropic_credentials (id, api_key, updated_at)
            VALUES (1, $1, NOW())
            ON CONFLICT (id) DO UPDATE
            SET api_key = EXCLUDED.api_key, updated_at = NOW()
            RETURNING api_key, updated_at
        """, api_key)
    return dict(row)


async def delete_anthropic_api_key() -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM anthropic_credentials WHERE id = 1"
        )
    return result != "DELETE 0"


async def init_ocr_settings_table():
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS ocr_settings (
                id          SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
                enabled     BOOLEAN NOT NULL DEFAULT FALSE,
                api_url     TEXT NOT NULL DEFAULT '',
                model       TEXT NOT NULL DEFAULT '',
                api_key     TEXT NOT NULL DEFAULT '',
                updated_at  TIMESTAMPTZ DEFAULT NOW()
            );
        """)


async def init_conversation_model_settings_table():
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS conversation_model_settings (
                id                  SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
                search_enabled      BOOLEAN NOT NULL DEFAULT FALSE,
                embedding_api_url   TEXT NOT NULL DEFAULT '',
                embedding_model     TEXT NOT NULL DEFAULT '',
                embedding_api_key   TEXT NOT NULL DEFAULT '',
                long_term_recall_limit BIGINT NOT NULL DEFAULT 5,
                long_term_recall_token_budget BIGINT,
                title_enabled       BOOLEAN NOT NULL DEFAULT FALSE,
                title_provider_id   INTEGER REFERENCES openai_provider_profiles(id) ON DELETE SET NULL,
                title_api_url       TEXT NOT NULL DEFAULT '',
                title_model         TEXT NOT NULL DEFAULT '',
                title_api_key       TEXT NOT NULL DEFAULT '',
                handoff_provider_id INTEGER REFERENCES openai_provider_profiles(id) ON DELETE SET NULL,
                handoff_model       TEXT NOT NULL DEFAULT '',
                long_term_summary_provider_id INTEGER REFERENCES openai_provider_profiles(id) ON DELETE SET NULL,
                long_term_summary_model TEXT NOT NULL DEFAULT '',
                long_term_summary_configured BOOLEAN NOT NULL DEFAULT FALSE,
                updated_at          TIMESTAMPTZ DEFAULT NOW()
            );
        """)
        await conn.execute("""
            ALTER TABLE conversation_model_settings
            ADD COLUMN IF NOT EXISTS title_provider_id INTEGER
            REFERENCES openai_provider_profiles(id) ON DELETE SET NULL
        """)
        await conn.execute("""
            ALTER TABLE conversation_model_settings
            ADD COLUMN IF NOT EXISTS long_term_recall_limit BIGINT NOT NULL DEFAULT 5
        """)
        await conn.execute("""
            ALTER TABLE conversation_model_settings
            ADD COLUMN IF NOT EXISTS long_term_recall_token_budget BIGINT
        """)
        await conn.execute("""
            ALTER TABLE conversation_model_settings
            ADD COLUMN IF NOT EXISTS handoff_provider_id INTEGER
            REFERENCES openai_provider_profiles(id) ON DELETE SET NULL
        """)
        await conn.execute("""
            ALTER TABLE conversation_model_settings
            ADD COLUMN IF NOT EXISTS handoff_model TEXT NOT NULL DEFAULT ''
        """)
        await conn.execute("""
            ALTER TABLE conversation_model_settings
            ADD COLUMN IF NOT EXISTS long_term_summary_provider_id INTEGER
            REFERENCES openai_provider_profiles(id) ON DELETE SET NULL
        """)
        await conn.execute("""
            ALTER TABLE conversation_model_settings
            ADD COLUMN IF NOT EXISTS long_term_summary_model TEXT NOT NULL DEFAULT ''
        """)
        await conn.execute("""
            ALTER TABLE conversation_model_settings
            ADD COLUMN IF NOT EXISTS long_term_summary_configured BOOLEAN NOT NULL DEFAULT FALSE
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS conversation_search_chunks (
                id                  BIGSERIAL PRIMARY KEY,
                conversation_id     INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                first_message_id    INTEGER NOT NULL,
                last_message_id     INTEGER NOT NULL,
                content             TEXT NOT NULL,
                messages            JSONB NOT NULL DEFAULT '[]'::jsonb,
                content_hash        TEXT NOT NULL,
                embedding           JSONB,
                embedding_model     TEXT NOT NULL,
                indexed_at          TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE (conversation_id, content_hash, embedding_model)
            );
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_conversation_search_chunks_conversation
            ON conversation_search_chunks (conversation_id, first_message_id);
        """)


async def init_openai_provider_profiles_table():
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS openai_provider_profiles (
                id          SERIAL PRIMARY KEY,
                name        TEXT NOT NULL,
                api_url     TEXT NOT NULL,
                api_key     TEXT NOT NULL,
                is_active   BOOLEAN NOT NULL DEFAULT FALSE,
                created_at  TIMESTAMPTZ DEFAULT NOW(),
                updated_at  TIMESTAMPTZ DEFAULT NOW()
            );
        """)
        await conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_openai_provider_profiles_active
            ON openai_provider_profiles (is_active)
            WHERE is_active = TRUE;
        """)


async def get_openai_provider_profiles() -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, name, api_url, api_key, is_active, created_at, updated_at
            FROM openai_provider_profiles
            ORDER BY is_active DESC, updated_at DESC, id DESC
        """)
    return [dict(row) for row in rows]


async def get_active_openai_provider_profile() -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT id, name, api_url, api_key, is_active, created_at, updated_at
            FROM openai_provider_profiles
            WHERE is_active = TRUE
            LIMIT 1
        """)
    return dict(row) if row else None


async def get_openai_provider_profile(profile_id: int) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT id, name, api_url, api_key, is_active, created_at, updated_at
            FROM openai_provider_profiles
            WHERE id = $1
        """, int(profile_id))
    return dict(row) if row else None


async def save_openai_provider_profile(
    name: str,
    api_url: str,
    api_key: str,
    is_active: bool = False,
) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            if is_active:
                await conn.execute("""
                    UPDATE openai_provider_profiles
                    SET is_active = FALSE, updated_at = NOW()
                    WHERE is_active = TRUE
                """)
            row = await conn.fetchrow(
                """
                INSERT INTO openai_provider_profiles
                    (name, api_url, api_key, is_active, created_at, updated_at)
                VALUES ($1, $2, $3, $4, NOW(), NOW())
                RETURNING *
                """,
                name,
                api_url,
                api_key,
                bool(is_active),
            )
    return dict(row)


async def update_openai_provider_profile(
    profile_id: int,
    name: str,
    api_url: str,
    api_key: str | None = None,
    is_active: bool = False,
) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            if is_active:
                await conn.execute("""
                    UPDATE openai_provider_profiles
                    SET is_active = FALSE, updated_at = NOW()
                    WHERE is_active = TRUE AND id <> $1
                """, int(profile_id))
            row = await conn.fetchrow(
                """
                UPDATE openai_provider_profiles
                SET name = $2,
                    api_url = $3,
                    api_key = COALESCE($4, api_key),
                    is_active = $5,
                    updated_at = NOW()
                WHERE id = $1
                RETURNING *
                """,
                int(profile_id),
                name,
                api_url,
                api_key,
                bool(is_active),
            )
    return dict(row) if row else None


async def activate_openai_provider_profile(profile_id: int) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            target = await conn.fetchrow(
                "SELECT id FROM openai_provider_profiles WHERE id = $1 FOR UPDATE",
                int(profile_id),
            )
            if not target:
                return None
            await conn.execute("""
                UPDATE openai_provider_profiles
                SET is_active = FALSE, updated_at = NOW()
                WHERE is_active = TRUE
            """)
            row = await conn.fetchrow(
                """
                UPDATE openai_provider_profiles
                SET is_active = TRUE, updated_at = NOW()
                WHERE id = $1
                RETURNING *
                """,
                int(profile_id),
            )
    return dict(row) if row else None


async def delete_openai_provider_profile(profile_id: int) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM openai_provider_profiles WHERE id = $1",
            int(profile_id),
        )
    return result != "DELETE 0"


async def get_route_settings(default_provider: str = "auto") -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM route_settings WHERE id = 1")
    if row:
        return dict(row)
    return {
        "provider": default_provider or "auto",
        "updated_at": None,
    }


async def save_route_settings(provider: str) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO route_settings (id, provider, updated_at)
            VALUES (1, $1, NOW())
            ON CONFLICT (id) DO UPDATE SET
                provider = EXCLUDED.provider,
                updated_at = NOW()
            RETURNING *
            """,
            provider or "auto",
        )
    return dict(row)


async def get_ocr_settings() -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM ocr_settings WHERE id = 1")
    if row:
        return dict(row)
    return {
        "enabled": False,
        "api_url": "",
        "model": "",
        "api_key": "",
        "updated_at": None,
    }


async def get_conversation_model_settings() -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM conversation_model_settings WHERE id = 1"
        )
    if row:
        return dict(row)
    return {
        "search_enabled": False,
        "embedding_api_url": "",
        "embedding_model": "",
        "embedding_api_key": "",
        "long_term_recall_limit": 5,
        "long_term_recall_token_budget": None,
        "title_enabled": False,
        "title_provider_id": None,
        "title_api_url": "",
        "title_model": "",
        "title_api_key": "",
        "handoff_provider_id": None,
        "handoff_model": "",
        "long_term_summary_provider_id": None,
        "long_term_summary_model": "",
        "long_term_summary_configured": False,
        "updated_at": None,
    }


async def save_conversation_model_settings(
    search_enabled: bool,
    embedding_api_url: str,
    embedding_model: str,
    embedding_api_key: str | None,
    long_term_recall_limit: int,
    long_term_recall_token_budget: int,
    title_enabled: bool,
    title_provider_id: int | None,
    title_model: str,
    handoff_provider_id: int | None,
    handoff_model: str,
    long_term_summary_provider_id: int | None = None,
    long_term_summary_model: str = "",
    long_term_summary_configured: bool = False,
) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO conversation_model_settings
                (id, search_enabled, embedding_api_url, embedding_model,
                 embedding_api_key, long_term_recall_limit,
                 long_term_recall_token_budget,
                 title_enabled, title_provider_id, title_model,
                 handoff_provider_id, handoff_model,
                 long_term_summary_provider_id, long_term_summary_model,
                 long_term_summary_configured,
                 updated_at)
            VALUES
                (1, $1, $2, $3, COALESCE($4, ''), $5, $6, $7, $8, $9, $10,
                 $11, $12, $13, $14, NOW())
            ON CONFLICT (id) DO UPDATE SET
                search_enabled = EXCLUDED.search_enabled,
                embedding_api_url = EXCLUDED.embedding_api_url,
                embedding_model = EXCLUDED.embedding_model,
                embedding_api_key = COALESCE($4, conversation_model_settings.embedding_api_key),
                long_term_recall_limit = EXCLUDED.long_term_recall_limit,
                long_term_recall_token_budget = EXCLUDED.long_term_recall_token_budget,
                title_enabled = EXCLUDED.title_enabled,
                title_provider_id = EXCLUDED.title_provider_id,
                title_model = EXCLUDED.title_model,
                handoff_provider_id = EXCLUDED.handoff_provider_id,
                handoff_model = EXCLUDED.handoff_model,
                long_term_summary_provider_id = EXCLUDED.long_term_summary_provider_id,
                long_term_summary_model = EXCLUDED.long_term_summary_model,
                long_term_summary_configured = EXCLUDED.long_term_summary_configured,
                title_api_url = CASE
                    WHEN EXCLUDED.title_provider_id IS NOT NULL THEN ''
                    ELSE conversation_model_settings.title_api_url
                END,
                title_api_key = CASE
                    WHEN EXCLUDED.title_provider_id IS NOT NULL THEN ''
                    ELSE conversation_model_settings.title_api_key
                END,
                updated_at = NOW()
            RETURNING *
            """,
            bool(search_enabled),
            embedding_api_url or "",
            embedding_model or "",
            embedding_api_key,
            int(long_term_recall_limit),
            int(long_term_recall_token_budget),
            bool(title_enabled),
            int(title_provider_id) if title_provider_id is not None else None,
            title_model or "",
            int(handoff_provider_id) if handoff_provider_id is not None else None,
            handoff_model or "",
            (
                int(long_term_summary_provider_id)
                if long_term_summary_provider_id is not None else None
            ),
            long_term_summary_model or "",
            bool(long_term_summary_configured),
        )
    return dict(row)


async def save_ocr_settings(enabled: bool, api_url: str, model: str,
                            api_key: str | None = None) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO ocr_settings
                (id, enabled, api_url, model, api_key, updated_at)
            VALUES (1, $1, $2, $3, COALESCE($4, ''), NOW())
            ON CONFLICT (id) DO UPDATE SET
                enabled = EXCLUDED.enabled,
                api_url = EXCLUDED.api_url,
                model = EXCLUDED.model,
                api_key = COALESCE($4, ocr_settings.api_key),
                updated_at = NOW()
            RETURNING *
            """,
            bool(enabled),
            api_url or "",
            model or "",
            api_key,
        )
    return dict(row)


async def get_heartbeat_settings(defaults: dict | None = None) -> dict:
    defaults = defaults or {}
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM heartbeat_settings WHERE id = 1")
    if row:
        return dict(row)
    return {
        "enabled": bool(defaults.get("enabled", False)),
        "interval_minutes": int(defaults.get("interval_minutes", 30)),
        "provider": str(defaults.get("provider") or "openai"),
        "model": str(defaults.get("model") or ""),
        "updated_at": None,
    }


async def save_heartbeat_settings(enabled: bool, interval_minutes: int,
                                  provider: str, model: str) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO heartbeat_settings
                (id, enabled, interval_minutes, provider, model, updated_at)
            VALUES (1, $1, $2, $3, $4, NOW())
            ON CONFLICT (id) DO UPDATE SET
                enabled = EXCLUDED.enabled,
                interval_minutes = EXCLUDED.interval_minutes,
                provider = EXCLUDED.provider,
                model = EXCLUDED.model,
                updated_at = NOW()
            RETURNING *
            """,
            bool(enabled),
            max(1, int(interval_minutes or 30)),
            provider or "openai",
            model or "",
        )
    return dict(row)


async def save_heartbeat_activity(
    conversation_id: int | None,
    provider: str,
    model: str,
    elapsed_minutes: int,
    status: str,
    final_text: str = "",
    tool_events: list[dict] | None = None,
) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO heartbeat_activity_logs
                (conversation_id, provider, model, elapsed_minutes, status,
                 final_text, tool_events)
            VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
            RETURNING id
            """,
            conversation_id,
            provider or "",
            model or "",
            max(0, int(elapsed_minutes or 0)),
            status or "completed",
            final_text or "",
            json.dumps(tool_events or [], ensure_ascii=False, default=str),
        )
        return row["id"]


async def get_heartbeat_activities(limit: int = 100) -> list[dict]:
    limit = min(max(1, int(limit or 100)), 500)
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, created_at, conversation_id, provider, model,
                   elapsed_minutes, status, final_text, tool_events,
                   context_recorded
            FROM heartbeat_activity_logs
            ORDER BY created_at DESC
            LIMIT $1
            """,
            limit,
        )
    activities = []
    for row in rows:
        activity = dict(row)
        activity["tool_events"] = _json_list(activity.get("tool_events"))
        activities.append(activity)
    return activities


def _heartbeat_activity_context_text(row: dict) -> str:
    events = _json_list(row.get("tool_events"))
    lines = [
        "<heartbeat_activity>",
        f"苏醒活动 #{row.get('id')}（用户离开约 {int(row.get('elapsed_minutes') or 0)} 分钟时）",
    ]
    for event in events:
        name = str(event.get("name") or "tool")
        input_text = json.dumps(event.get("input") or {}, ensure_ascii=False, default=str)
        result_text = str(event.get("result") or "")
        status_text = "成功" if event.get("ok") else "失败"
        lines.append(f"- 调用 {name}（{status_text}）")
        lines.append(f"  输入：{input_text}")
        lines.append(f"  结果：{result_text}")
    final_text = str(row.get("final_text") or "").strip()
    if final_text:
        lines.append(f"结束时的判断：{final_text}")
    lines.append("</heartbeat_activity>")
    return "\n".join(lines)


async def _materialize_heartbeat_activities_with_conn(conn, conversation_id: int) -> int:
    rows = await conn.fetch(
        """
        SELECT id, elapsed_minutes, final_text, tool_events
        FROM heartbeat_activity_logs
        WHERE conversation_id = $1
          AND context_recorded = FALSE
          AND jsonb_array_length(tool_events) > 0
        ORDER BY id ASC
        FOR UPDATE
        """,
        conversation_id,
    )
    for row in rows:
        content = _heartbeat_activity_context_text(dict(row))
        await conn.execute(
            """
            INSERT INTO context_messages
                (conversation_id, role, content, kind, hidden, affects_activity)
            VALUES ($1, 'assistant', $2, 'heartbeat_activity', TRUE, FALSE)
            """,
            conversation_id,
            content,
        )
        await conn.execute(
            """
            UPDATE heartbeat_activity_logs
            SET context_recorded = TRUE
            WHERE id = $1
            """,
            row["id"],
        )
    return len(rows)


async def materialize_pending_heartbeat_activities(conversation_id: int) -> int:
    """Insert unseen, state-changing heartbeat activity as assistant history."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            count = await _materialize_heartbeat_activities_with_conn(conn, conversation_id)
            if count:
                await conn.execute(
                    "UPDATE conversations SET updated_at = NOW() WHERE id = $1",
                    conversation_id,
                )
            return count


# ============================================================
# 中文分词工具
# ============================================================

EN_WORD_PATTERN = re.compile(r'[a-zA-Z][a-zA-Z0-9]*')
NUM_PATTERN = re.compile(r'\d{2,}')

_STOP_WORDS = frozenset({
    "的", "了", "在", "是", "我", "你", "他", "她", "它", "们",
    "这", "那", "有", "和", "与", "也", "都", "又", "就", "但",
    "而", "或", "到", "被", "把", "让", "从", "对", "为", "以",
    "及", "等", "个", "不", "没", "很", "太", "吗", "呢", "吧",
    "啊", "嗯", "哦", "哈", "呀", "嘛", "么", "啦", "哇", "喔",
    "会", "能", "要", "想", "去", "来", "说", "做", "看", "给",
    "上", "下", "里", "中", "大", "小", "多", "少", "好", "可以",
    "什么", "怎么", "如何", "哪里", "哪个", "为什么", "还是",
    "然后", "因为", "所以", "虽然", "但是", "可以", "已经",
    "一个", "一些", "一下", "一点", "一起", "一样",
    "比较", "应该", "可能", "如果", "这个", "那个",
    "自己", "知道", "觉得", "感觉", "时候", "现在",
})

def extract_search_keywords(query: str) -> List[str]:
    keywords = set()
    for match in EN_WORD_PATTERN.finditer(query):
        word = match.group()
        if len(word) >= 2:
            keywords.add(word)
    for match in NUM_PATTERN.finditer(query):
        keywords.add(match.group())
    words = jieba.cut(query, cut_all=False)
    for word in words:
        word = word.strip()
        if not word:
            continue
        if EN_WORD_PATTERN.fullmatch(word) or NUM_PATTERN.fullmatch(word):
            continue
        if len(word) < 2 or word in _STOP_WORDS:
            continue
        keywords.add(word)
    return list(keywords)

# ============================================================
# OpenAI-compatible Embedding 工具
# ============================================================

def _embedding_config_ok() -> bool:
    return bool(EMBEDDING_ENABLED and EMBEDDING_BASE_URL and EMBEDDING_API_KEY and EMBEDDING_MODEL)


def _embedding_url() -> str:
    return EMBEDDING_BASE_URL.rstrip("/") + "/embeddings"


async def embed_text(text: str) -> list[float] | None:
    if not _embedding_config_ok():
        return None

    text = (text or "").strip()
    if not text:
        return None

    if len(text) > EMBEDDING_MAX_INPUT_CHARS:
        text = text[:EMBEDDING_MAX_INPUT_CHARS]

    headers = {
        "Authorization": f"Bearer {EMBEDDING_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": EMBEDDING_MODEL,
        "input": text,
    }

    try:
        async with httpx.AsyncClient(timeout=EMBEDDING_TIMEOUT) as client:
            resp = await client.post(_embedding_url(), headers=headers, json=payload)

        if resp.status_code != 200:
            print(f"⚠️ embedding failed: HTTP {resp.status_code}: {resp.text[:300]}")
            return None

        data = resp.json()
        emb = data.get("data", [{}])[0].get("embedding")

        if not isinstance(emb, list) or not emb:
            print(f"⚠️ embedding failed: empty embedding response: {str(data)[:300]}")
            return None

        return [float(x) for x in emb]

    except Exception as e:
        print(f"⚠️ embedding request error: {e}")
        return None


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0

    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0

    for x, y in zip(a, b):
        dot += x * y
        norm_a += x * x
        norm_b += y * y

    if norm_a <= 0 or norm_b <= 0:
        return 0.0

    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


def _safe_load_embedding(raw) -> list[float] | None:
    if raw is None:
        return None

    try:
        if isinstance(raw, str):
            data = json.loads(raw)
        else:
            data = raw

        if not isinstance(data, list):
            return None

        return [float(x) for x in data]
    except Exception:
        return None


def keyword_match_score(query: str, content: str, keywords: list[str] = None) -> tuple[float, int]:
    if not query or not content:
        return 0.0, 0

    if keywords is None:
        keywords = extract_search_keywords(query)

    if not keywords:
        return 0.0, 0

    content_lower = content.lower()
    hit_count = 0

    for kw in keywords:
        kw = kw.strip()
        if not kw:
            continue

        if kw.lower() in content_lower:
            hit_count += 1

    return hit_count / max(len(keywords), 1), hit_count


def recency_score_from_created_at(created_at) -> float:
    if not created_at:
        return 0.0

    try:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)

        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)

        age_days = max((now - created_at).total_seconds() / 86400.0, 0.0)
        return 1.0 / (1.0 + age_days)
    except Exception:
        return 0.0


async def upsert_memory_embedding(memory_id: int, content: str) -> bool:
    if not _embedding_config_ok():
        return False

    emb = await embed_text(content)
    if not emb:
        return False

    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO memory_embeddings (memory_id, embedding, model, dim, updated_at)
            VALUES ($1, $2::jsonb, $3, $4, NOW())
            ON CONFLICT (memory_id)
            DO UPDATE SET
                embedding = EXCLUDED.embedding,
                model = EXCLUDED.model,
                dim = EXCLUDED.dim,
                updated_at = NOW()
            """,
            memory_id,
            json.dumps(emb),
            EMBEDDING_MODEL,
            len(emb),
        )

    return True


async def rebuild_memory_embeddings(limit: int = 500) -> dict:
    if not _embedding_config_ok():
        return {
            "status": "skipped",
            "reason": "embedding not configured",
        }

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT m.id, m.content
            FROM memories m
            LEFT JOIN memory_embeddings e ON e.memory_id = m.id
            WHERE e.memory_id IS NULL OR e.model <> $1
            ORDER BY m.id ASC
            LIMIT $2
            """,
            EMBEDDING_MODEL,
            limit,
        )

    ok = 0
    failed = 0

    for r in rows:
        success = await upsert_memory_embedding(r["id"], r["content"])
        if success:
            ok += 1
        else:
            failed += 1

    return {
        "status": "ok",
        "model": EMBEDDING_MODEL,
        "processed": len(rows),
        "success": ok,
        "failed": failed,
    }


async def _autofill_missing_embeddings(rows: list[dict]) -> int:
    if not _embedding_config_ok() or EMBEDDING_AUTOFILL_LIMIT <= 0:
        return 0

    filled = 0

    for r in rows:
        if filled >= EMBEDDING_AUTOFILL_LIMIT:
            break

        if r.get("embedding") is not None and r.get("embedding_model") == EMBEDDING_MODEL:
            continue

        success = await upsert_memory_embedding(r["id"], r["content"])
        if success:
            filled += 1

    return filled

# ============================================================
# 记忆搜索（核心）
# ============================================================

async def search_memories_keyword_only(query: str, limit: int = 10, update_access: bool = True):
    keywords = extract_search_keywords(query)
    if not keywords:
        return []

    pool = await get_pool()
    async with pool.acquire() as conn:
        case_parts = []
        params = []

        for i, kw in enumerate(keywords):
            case_parts.append(f"CASE WHEN content ILIKE '%' || ${i+1} || '%' THEN 1 ELSE 0 END")
            params.append(kw)

        hit_count_expr = " + ".join(case_parts)
        max_hits = len(keywords)

        where_parts = [f"content ILIKE '%' || ${i+1} || '%'" for i in range(len(keywords))]
        where_clause = " OR ".join(where_parts)

        sql = f"""
            SELECT
                id, content, importance, source_session, type, metadata, expires_at,
                tags, created_at, last_accessed, COALESCE(access_count, 0) AS access_count,
                ({hit_count_expr}) AS hit_count,
                (
                    {WEIGHT_KEYWORD} * ({hit_count_expr})::float / {max_hits}::float +
                    {WEIGHT_IMPORTANCE} * importance::float / 10.0 +
                    {WEIGHT_RECENCY} * (1.0 / (1.0 + EXTRACT(EPOCH FROM (NOW() - created_at)) / 86400.0))
                ) AS score
            FROM memories
            WHERE {where_clause}
            ORDER BY score DESC, importance DESC, created_at DESC
            LIMIT {max(limit * 10, 100)}
        """

        results = await conn.fetch(sql, *params)

        rows = [dict(r) for r in results]

        rows.sort(
            key=lambda x: (
                x["score"],
                x.get("hit_count") or 0,
                x.get("importance") or 0,
                x.get("created_at") or datetime.min.replace(tzinfo=timezone.utc),
            ),
            reverse=True,
        )
        rows = rows[:limit]

        if MIN_SCORE_THRESHOLD > 0:
            before_count = len(rows)
            rows = [r for r in rows if float(r.get("score") or 0) >= MIN_SCORE_THRESHOLD]
            filtered = before_count - len(rows)
        else:
            filtered = 0

        if rows:
            print(
                f"🔍 关键词搜索 '{query}' → 关键词 {keywords[:8]}{'...' if len(keywords)>8 else ''} "
                f"→ 命中 {len(rows)} 条" + (f"（过滤 {filtered} 条低分）" if filtered else "")
            )
            for r in rows[:3]:
                print(
                    f"   📌 [score={float(r['score']):.3f}] "
                    f"(hits={r['hit_count']}, imp={r['importance']}, type={r.get('type', 'factual')}) {r['content'][:60]}..."
                )

            if update_access:
                ids = [r["id"] for r in rows]
                await conn.execute(
                    """
                    UPDATE memories
                    SET last_accessed = NOW(),
                        access_count = COALESCE(access_count, 0) + 1
                    WHERE id = ANY($1::int[])
                    """,
                    ids,
                )
        else:
            print(
                f"🔍 关键词搜索 '{query}' → 关键词 {keywords[:8]} → 无结果"
                + (f"（{filtered} 条被分数阈值过滤）" if filtered else "")
            )

        return rows


async def search_memories(query: str, limit: int = 10, update_access: bool = True):
    query = (query or "").strip()
    if not query:
        return []

    keywords = extract_search_keywords(query)

    if not _embedding_config_ok():
        return await search_memories_keyword_only(query, limit=limit, update_access=update_access)

    query_emb = await embed_text(query)

    if not query_emb:
        print("⚠️ query embedding failed, fallback to keyword search")
        return await search_memories_keyword_only(query, limit=limit, update_access=update_access)

    pool = await get_pool()

    async with pool.acquire() as conn:
        raw_rows = await conn.fetch(
            """
            SELECT
                m.id,
                m.content,
                m.importance,
                m.source_session,
                m.type,
                m.metadata,
                m.expires_at,
                m.tags,
                m.created_at,
                m.last_accessed,
                COALESCE(m.access_count, 0) AS access_count,
                e.embedding,
                e.model AS embedding_model,
                e.dim AS embedding_dim
            FROM memories m
            LEFT JOIN memory_embeddings e ON e.memory_id = m.id
            ORDER BY m.id ASC
            """
        )

    rows = [dict(r) for r in raw_rows]

    if not rows:
        return []

    filled = await _autofill_missing_embeddings(rows)
    if filled:
        print(f"🧩 自动补 memory embeddings：{filled} 条")

        async with pool.acquire() as conn:
            raw_rows = await conn.fetch(
                """
                SELECT
                    m.id,
                    m.content,
                    m.importance,
                    m.source_session,
                    m.type,
                    m.metadata,
                    m.expires_at,
                    m.tags,
                    m.created_at,
                    m.last_accessed,
                    COALESCE(m.access_count, 0) AS access_count,
                    e.embedding,
                    e.model AS embedding_model,
                    e.dim AS embedding_dim
                FROM memories m
                LEFT JOIN memory_embeddings e ON e.memory_id = m.id
                ORDER BY m.id ASC
                """
            )
        rows = [dict(r) for r in raw_rows]

    scored = []

    for r in rows:
        content = r.get("content") or ""
        mem_type = r.get("type", "factual")

        # 过期的 temp 直接跳过
        if mem_type == "temp" and r.get("expires_at"):
            from datetime import datetime, timezone as tz
            expires_at = r["expires_at"]
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=tz.utc)
            if expires_at < datetime.now(tz.utc):
                continue

        emb = None
        if r.get("embedding_model") == EMBEDDING_MODEL:
            emb = _safe_load_embedding(r.get("embedding"))

        semantic_score = cosine_similarity(query_emb, emb) if emb else 0.0
        keyword_score, hit_count = keyword_match_score(query, content, keywords)
        importance_score = min(max(float(r.get("importance") or 0) / 10.0, 0.0), 1.0)
        recency_score = recency_score_from_created_at(r.get("created_at"))

        final_score = (
            WEIGHT_SEMANTIC * semantic_score +
            WEIGHT_KEYWORD * keyword_score +
            WEIGHT_IMPORTANCE * importance_score +
            WEIGHT_RECENCY * recency_score
        )

        # 类型加权
        type_boost = TYPE_WEIGHT_BOOST.get(mem_type, 0.0)
        base_score = final_score + type_boost
        final_score = base_score

        if final_score < MIN_SCORE_THRESHOLD and hit_count <= 0:
            continue

        item = {
            "id": r["id"],
            "content": content,
            "importance": r.get("importance"),
            "source_session": r.get("source_session"),
            "type": mem_type,
            "metadata": r.get("metadata"),
            "tags": r.get("tags"),
            "created_at": r.get("created_at"),
            "last_accessed": r.get("last_accessed"),
            "access_count": r.get("access_count"),
            "score": final_score,
            "base_score": base_score,
            "semantic_score": semantic_score,
            "keyword_score": keyword_score,
            "hit_count": hit_count,
            "importance_score": importance_score,
            "recency_score": recency_score,
        }

        scored.append(item)

    scored.sort(
        key=lambda x: (
            x["score"],
            x["semantic_score"],
            x["keyword_score"],
            x["importance"] or 0,
        ),
        reverse=True,
    )

    results = scored[:limit]

    if results:
        if update_access:
            ids = [r["id"] for r in results]
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE memories
                    SET last_accessed = NOW(),
                        access_count = COALESCE(access_count, 0) + 1
                    WHERE id = ANY($1::int[])
                    """,
                    ids,
                )

        print(
            f"🔎 语义搜索 '{query[:80]}' "
            f"→ 返回 {len(results)} 条 / 候选 {len(scored)} 条 / keywords={keywords[:8]}"
        )
        for r in results[:3]:
            print(
                f"   🧠 [score={r['score']:.3f}, sem={r['semantic_score']:.3f}, "
                f"kw={r['keyword_score']:.3f}, hits={r['hit_count']}, imp={r['importance']}, type={r['type']}] "
                f"{r['content'][:70]}..."
            )
    else:
        print(f"🔎 语义搜索 '{query[:80]}' → 无结果，尝试关键词 fallback")
        return await search_memories_keyword_only(query, limit=limit, update_access=update_access)

    return results

# ============================================================
# 记忆 CRUD
# ============================================================
async def save_memory(
    content: str,
    importance: int = 5,
    source_session: str = "",
    memory_type: str = "factual",
    metadata: dict = None,
    expires_at = None,
    tags: list = None,
    pinned: bool = False,
) -> int:
    """
    保存一条记忆。
    - memory_type: factual/episodic/diary/quote/temp
    - metadata: 扩展信息（quote 的 speaker/context 等）
    - expires_at: 仅 temp 类型用，过期后降权或清理
    - tags: 标签数组
    - pinned: 是否钉住（整理时不会删除）
    """
    if memory_type not in MEMORY_TYPES:
        memory_type = "factual"

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO memories (content, importance, source_session, type, metadata, expires_at, tags, pinned)
            VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, $8)
            RETURNING id
            """,
            content,
            importance,
            source_session,
            memory_type,
            json.dumps(metadata) if metadata else None,
            expires_at,
            tags or [],
            pinned,
        )

    memory_id = row["id"]

    try:
        await upsert_memory_embedding(memory_id, content)
    except Exception as e:
        print(f"⚠️ save_memory embedding failed for id={memory_id}: {e}")

    return memory_id

async def save_quote(
    content: str,
    speaker: str = "both",
    context_note: str = "",
    emotion: str = "",
    original_date: str = "",
    tags: list = None,
    importance: int = 7,
) -> int:
    """
    保存对话原话。由用户手动触发或通过 API 存入。
    importance 默认 7（比普通记忆高，原话是灵魂）
    """
    metadata = {
        "speaker": speaker,  # user/assistant/both
    }
    if context_note:
        metadata["context"] = context_note
    if emotion:
        metadata["emotion"] = emotion
    if original_date:
        metadata["original_date"] = original_date

    return await save_memory(
        content=content,
        importance=importance,
        source_session="quote-manual",
        memory_type="quote",
        metadata=metadata,
        tags=tags or ["原话"],
    )


async def get_recent_memories(limit: int = 20):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT id, content, importance, type, metadata, tags, created_at FROM memories ORDER BY created_at DESC LIMIT $1",
            limit,
        )

async def get_all_memories_count():
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT COUNT(*) as cnt FROM memories")
        return row["cnt"]

async def get_all_memories():
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT content, importance, type, metadata, tags, source_session, created_at FROM memories ORDER BY id"
        )
        return [dict(r) for r in rows]

async def get_all_memories_detail():
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, content, importance, type, metadata, tags, pinned, source_session, created_at FROM memories ORDER BY id"
        )
        return [dict(r) for r in rows]


GATEWAY_BACKUP_TABLES = {
    "prompt_sections": {
        "table": "prompt_sections",
        "columns": (
            "section_key", "mode", "priority", "content", "updated_at",
            "updated_by",
        ),
        "order_by": "priority DESC, section_key ASC",
        "sequence": False,
    },
    "memories": {
        "table": "memories",
        "columns": (
            "id", "content", "importance", "source_session", "created_at",
            "last_accessed", "access_count", "type", "metadata", "expires_at",
            "tags", "pinned",
        ),
        "json": {"metadata"},
    },
    "standing_memory_blocks": {
        "table": "standing_memory_blocks",
        "columns": (
            "id", "title", "content", "parent_id", "status", "source", "layer",
            "inject_enabled", "inject_every_n", "inject_on_first_turn",
            "sort_order", "metadata", "created_at", "updated_at",
        ),
        "json": {"metadata"},
        "deferred": {"parent_id"},
    },
    "long_term_memories": {
        "table": "long_term_memories",
        "columns": (
            "id", "title", "keywords", "summary", "content", "memory_date",
            "priority", "enabled", "metadata", "created_at",
        ),
        "json": {"keywords", "metadata"},
        "defaults": {
            "summary": "",
            "priority": 0,
            "enabled": True,
            "metadata": {},
        },
    },
    "long_term_memory_proposals": {
        "table": "long_term_memory_proposals",
        "columns": (
            "id", "operation", "target_memory_id", "title", "keywords",
            "summary", "content", "source", "memory_date", "priority", "enabled",
            "metadata", "created_at",
        ),
        "json": {"keywords", "metadata"},
        "defaults": {
            "priority": 0,
            "enabled": True,
            "metadata": {},
            "summary": "",
        },
    },
    "memory_update_proposals": {
        "table": "memory_update_proposals",
        "columns": (
            "id", "title", "target_layer", "target_block_id", "status", "source",
            "source_ids", "rationale", "content", "score", "metadata",
            "created_at", "updated_at",
        ),
        "json": {"source_ids", "metadata"},
    },
    "conversations": {
        "table": "conversations",
        "columns": (
            "id", "name", "external_session_id", "max_messages", "is_active",
            "created_at", "updated_at", "cache_anchor_fingerprint",
            "handoff_draft", "handoff_summary", "handoff_source_id",
            "handoff_message_ids", "handoff_summary_through_message_id",
            "handoff_summary_version", "handoff_summary_ready_for_flow",
            "last_anthropic_tools", "last_frontend_tool_names", "heartbeat_count",
            "heartbeat_last_user_message_id", "heartbeat_claim_token",
            "heartbeat_claimed_at", "heartbeat_last_sent_at",
            "heartbeat_last_checked_at",
        ),
        "json": {
            "handoff_message_ids", "last_anthropic_tools",
            "last_frontend_tool_names",
        },
        "defaults": {
            "handoff_message_ids": [],
            "handoff_summary_version": 0,
            "handoff_summary_ready_for_flow": False,
        },
        "deferred": {"handoff_source_id"},
    },
    "context_messages": {
        "table": "context_messages",
        "columns": (
            "id", "conversation_id", "role", "content", "created_at",
            "content_json", "kind", "hidden", "affects_activity",
        ),
        "json": {"content_json"},
    },
    "memory_extraction_jobs": {
        "table": "memory_extraction_jobs",
        "columns": (
            "id", "source_conversation_id", "target_conversation_id",
            "snapshot", "status", "attempts", "available_at", "lease_token",
            "last_error", "created_at", "completed_at", "legacy_snapshot",
        ),
        "json": {"snapshot", "legacy_snapshot"},
    },
    "fragment_forgetting_pending": {
        "table": "fragment_forgetting_pending",
        "columns": ("memory_id", "content_snapshot", "created_at"),
        "order_by": "memory_id ASC",
        "sequence": False,
    },
}

GATEWAY_BACKUP_DELETE_ORDER = (
    "fragment_forgetting_pending",
    "memory_extraction_jobs",
    "context_messages",
    "conversations",
    "memory_update_proposals",
    "long_term_memory_proposals",
    "long_term_memories",
    "standing_memory_blocks",
    "memories",
    "prompt_sections",
)

GATEWAY_BACKUP_INSERT_ORDER = (
    "prompt_sections",
    "memories",
    "standing_memory_blocks",
    "long_term_memories",
    "long_term_memory_proposals",
    "memory_update_proposals",
    "conversations",
    "context_messages",
    "memory_extraction_jobs",
    "fragment_forgetting_pending",
)


async def export_gateway_backup_data() -> dict:
    pool = await get_pool()
    result = {}
    async with pool.acquire() as conn:
        async with conn.transaction(isolation="repeatable_read", readonly=True):
            for section, spec in GATEWAY_BACKUP_TABLES.items():
                columns = ", ".join(spec["columns"])
                order_by = spec.get("order_by", "id ASC")
                rows = await conn.fetch(
                    f"SELECT {columns} FROM {spec['table']} ORDER BY {order_by}"
                )
                result[section] = [dict(row) for row in rows]
    return result


def _backup_value(column: str, value, json_columns: set[str]):
    if value is None:
        return None
    if column in json_columns:
        if isinstance(value, str):
            try:
                json.loads(value)
                return value
            except (TypeError, ValueError):
                pass
        return json.dumps(value, ensure_ascii=False, default=str)
    if column.endswith("_date") and isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    if (column.endswith("_at") or column == "last_accessed") and isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return value


async def _restore_backup_section(conn, section: str, rows: list[dict]) -> int:
    spec = GATEWAY_BACKUP_TABLES[section]
    columns = spec["columns"]
    json_columns = spec.get("json", set())
    defaults = spec.get("defaults", {})
    deferred = spec.get("deferred", set())
    insert_columns = tuple(column for column in columns if column not in deferred)
    placeholders = [
        f"${index}::jsonb" if column in json_columns else f"${index}"
        for index, column in enumerate(insert_columns, start=1)
    ]
    query = (
        f"INSERT INTO {spec['table']} ({', '.join(insert_columns)}) "
        f"VALUES ({', '.join(placeholders)})"
    )
    restored = 0
    for raw_row in rows:
        if not isinstance(raw_row, dict):
            raise ValueError(f"invalid row in {section}")
        values = [
            _backup_value(
                column,
                raw_row[column] if column in raw_row else defaults.get(column),
                json_columns,
            )
            for column in insert_columns
        ]
        await conn.execute(query, *values)
        restored += 1

    for deferred_column in deferred:
        for raw_row in rows:
            value = raw_row.get(deferred_column)
            if value is None:
                continue
            await conn.execute(
                f"UPDATE {spec['table']} SET {deferred_column} = $1 WHERE id = $2",
                value,
                raw_row.get("id"),
            )
    return restored


async def _reset_backup_sequence(conn, table: str) -> None:
    await conn.execute(
        f"""
        SELECT setval(
            pg_get_serial_sequence('{table}', 'id'),
            COALESCE((SELECT MAX(id) FROM {table}), 1),
            EXISTS(SELECT 1 FROM {table})
        )
        """
    )


async def restore_gateway_backup_data(data: dict) -> dict:
    if not isinstance(data, dict):
        raise ValueError("invalid backup payload")
    for section in GATEWAY_BACKUP_TABLES:
        if section not in data or not isinstance(data[section], list):
            raise ValueError(f"backup section missing: {section}")

    pool = await get_pool()
    restored = {}
    async with pool.acquire() as conn:
        async with conn.transaction():
            for section in GATEWAY_BACKUP_DELETE_ORDER:
                await conn.execute(f"DELETE FROM {GATEWAY_BACKUP_TABLES[section]['table']}")
            for section in GATEWAY_BACKUP_INSERT_ORDER:
                restored[section] = await _restore_backup_section(
                    conn, section, data[section]
                )
            # A process that was working when the backup was taken no longer
            # owns its lease after restore. Requeue it so a fresh worker can
            # safely resume from the persisted snapshots.
            await conn.execute("""
                UPDATE memory_extraction_jobs
                SET status = 'pending', lease_token = NULL, available_at = NOW()
                WHERE status = 'running'
            """)
            for spec in GATEWAY_BACKUP_TABLES.values():
                if spec.get("sequence", True):
                    await _reset_backup_sequence(conn, spec["table"])
            await _promote_flow_memory_overflow(conn)
    return restored


async def update_memory(
    memory_id: int,
    content: str = None,
    importance: int = None,
    memory_type: str = None,
    pinned: bool = None,
):
    pool = await get_pool()

    async with pool.acquire() as conn:
        updates = []
        params = []
        idx = 1

        if content is not None:
            updates.append(f"content = ${idx}")
            params.append(content)
            idx += 1

        if importance is not None:
            updates.append(f"importance = ${idx}")
            params.append(importance)
            idx += 1

        if memory_type is not None:
            updates.append(f"type = ${idx}")
            params.append(memory_type)
            idx += 1

        if pinned is not None:  # ← 新增
            updates.append(f"pinned = ${idx}")
            params.append(pinned)
            idx += 1

        if updates:
            params.append(memory_id)
            sql = f"UPDATE memories SET {', '.join(updates)} WHERE id = ${idx}"
            await conn.execute(sql, *params)

    # embedding 更新逻辑保持不变
    if content is not None:
        try:
            await upsert_memory_embedding(memory_id, content)
        except Exception as e:
            print(f"⚠️ update_memory embedding failed for id={memory_id}: {e}")


async def delete_memory(memory_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM memories WHERE id = $1", memory_id)

async def delete_memories_batch(memory_ids: list):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM memories WHERE id = ANY($1::int[])", memory_ids
        )

# ============================================================
# 记忆分层：按类型/标签查询
# ============================================================

async def get_memories_by_type(
    memory_type: str,
    limit: int = 50,
    offset: int = 0,
) -> list:
    """按类型拉记忆"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, content, importance, type, metadata, tags, created_at
            FROM memories
            WHERE type = $1
            ORDER BY created_at DESC
            LIMIT $2 OFFSET $3
            """,
            memory_type, limit, offset,
        )
        return [dict(r) for r in rows]


async def get_memories_by_tag(tag: str, limit: int = 30) -> list:
    """按标签搜"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, content, importance, type, metadata, tags, created_at
            FROM memories
            WHERE $1 = ANY(tags)
            ORDER BY created_at DESC
            LIMIT $2
            """,
            tag, limit,
        )
        return [dict(r) for r in rows]


async def cleanup_expired_memories() -> int:
    """清理过期的 temp 记忆"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute("""
            DELETE FROM memories
            WHERE type = 'temp' AND expires_at IS NOT NULL AND expires_at < NOW()
        """)
        try:
            count = int(result.split()[-1])
        except Exception:
            count = 0
        if count:
            print(f"[memory] 🧹 清理 {count} 条过期临时记忆")
        return count


# ============================================================
# Standing Memory / 常驻记忆
# ============================================================

STANDING_MEMORY_STATUSES = {"active", "pending", "archived"}
STANDING_MEMORY_SOURCES = {"manual", "model"}
STANDING_MEMORY_LAYERS = {"core", "ring", "recent"}


def _normalize_standing_status(status: str | None) -> str:
    status = status or "active"
    return status if status in STANDING_MEMORY_STATUSES else "active"


def _normalize_standing_source(source: str | None) -> str:
    source = source or "manual"
    return source if source in STANDING_MEMORY_SOURCES else "manual"


def _normalize_standing_layer(layer: str | None) -> str:
    layer = layer or "core"
    return layer if layer in STANDING_MEMORY_LAYERS else "core"


def _normalize_optional_int(value) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _flow_memory_token_estimate(block: dict) -> int:
    """Conservatively estimate the rendered input cost of one flow event."""
    payload = "\n".join([
        str(block.get("title") or ""),
        str(block.get("content") or ""),
        str(block.get("created_at") or ""),
    ])
    ascii_chars = sum(1 for char in payload if ord(char) < 128)
    non_ascii_chars = len(payload) - ascii_chars
    return max(1, (ascii_chars + 3) // 4 + non_ascii_chars + 24)


def get_flow_memory_window_status(
    blocks: list[dict],
    max_items: int = FLOW_MEMORY_DEFAULT_MAX_ITEMS,
) -> dict:
    """Return dashboard-safe flow-window pressure without mutating anything."""
    flow = [
        block for block in blocks
        if block.get("status") == "active" and block.get("layer") == "recent"
    ]
    token_estimate = sum(_flow_memory_token_estimate(block) for block in flow)
    max_items = max(1, int(max_items))
    if token_estimate > FLOW_MEMORY_HARD_TOKENS or len(flow) > max_items:
        state = "hard"
    elif len(flow) == max_items:
        state = "full"
    else:
        state = "stable"
    return {
        "item_count": len(flow),
        "max_items": max_items,
        "token_estimate": token_estimate,
        "hard_tokens": FLOW_MEMORY_HARD_TOKENS,
        "state": state,
    }


def _select_flow_memory_window(
    blocks: list[dict],
    max_items: int = FLOW_MEMORY_DEFAULT_MAX_ITEMS,
    hard_tokens: int = FLOW_MEMORY_HARD_TOKENS,
) -> tuple[list[dict], list[dict]]:
    """Keep the newest configured number of flow summaries.

    The count cap is the primary policy. A hard token ceiling is retained only
    as an emergency guard for unusually large individual summaries.
    """
    ordered = sorted(
        (dict(block) for block in blocks),
        key=lambda block: (
            str(block.get("created_at") or ""),
            int(block.get("id") or 0),
        ),
        reverse=True,
    )
    if not ordered:
        return [], []

    max_items = max(1, int(max_items))
    hard_tokens = max(1, int(hard_tokens))
    costs = [_flow_memory_token_estimate(block) for block in ordered]
    kept_count = len(ordered)
    used_tokens = sum(costs)

    # Remove only the minimum oldest suffix needed to respect the saved count
    # or the emergency token ceiling. Always retain the newest summary.
    while kept_count > 1 and (
        kept_count > max_items or used_tokens > hard_tokens
    ):
        kept_count -= 1
        used_tokens -= costs[kept_count]

    return ordered[:kept_count], ordered[kept_count:]


def _flow_memory_date(value) -> date:
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(
            timezone(timedelta(hours=TIMEZONE_HOURS))
        ).date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value or "").strip()[:10])
    except ValueError:
        return datetime.now(
            timezone(timedelta(hours=TIMEZONE_HOURS))
        ).date()


def _long_term_memory_date_from_title(title: str) -> date | None:
    """Use only an explicit ISO date prefix as an intentional diary date."""
    match = re.match(r"^\s*(\d{4}-\d{2}-\d{2})(?=\s|[·|｜:：—-]|$)", str(title or ""))
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


async def _promote_flow_memory_overflow(
    conn,
    *,
    max_items: int | None = None,
) -> list[int]:
    """Move overflow flow events directly into long-term memory, atomically."""
    if max_items is None:
        saved_max_items = await conn.fetchval(
            "SELECT max_items FROM flow_memory_settings WHERE id = 1"
        )
        max_items = int(saved_max_items or FLOW_MEMORY_DEFAULT_MAX_ITEMS)
    rows = await conn.fetch("""
        SELECT id, title, content, metadata, created_at
        FROM standing_memory_blocks
        WHERE status = 'active'
          AND layer = 'recent'
        ORDER BY created_at DESC, id DESC
        FOR UPDATE
    """)
    _kept, overflow = _select_flow_memory_window(
        [dict(row) for row in rows], max_items=max_items
    )
    promoted_ids = []
    for block in reversed(overflow):
        flow_id = int(block["id"])
        entered_on = _flow_memory_date(block.get("created_at"))
        title = str(block.get("title") or "会话摘要").strip() or "会话摘要"
        title_date = _long_term_memory_date_from_title(title)
        memory_date = title_date or entered_on
        metadata = {
            **_json_object(block.get("metadata")),
            "entry_kind": "diary",
            "source_flow_memory_id": flow_id,
            "promoted_from": "standing_flow",
            "flow_entered_on": entered_on.isoformat(),
            "promotion_memory_date_source": (
                "title" if title_date else "flow_entered_on"
            ),
        }
        promoted = await conn.fetchrow("""
            INSERT INTO long_term_memories
                (title, keywords, summary, content, memory_date,
                 priority, enabled, metadata)
            VALUES ($1, '[]'::jsonb, '', $2, $3, 0, TRUE, $4::jsonb)
            ON CONFLICT DO NOTHING
            RETURNING id
        """,
            title,
            str(block.get("content") or "").strip(),
            memory_date,
            json.dumps(metadata, ensure_ascii=False),
        )
        long_term_id = (
            int(promoted["id"])
            if promoted else await conn.fetchval("""
                SELECT id
                FROM long_term_memories
                WHERE metadata->>'source_flow_memory_id' = $1
                ORDER BY id DESC
                LIMIT 1
            """, str(flow_id))
        )
        if long_term_id is None:
            raise RuntimeError(
                f"failed to promote flow memory #{flow_id} to long-term memory"
            )
        await conn.execute(
            "DELETE FROM standing_memory_blocks WHERE id = $1",
            flow_id,
        )
        promoted_ids.append(int(long_term_id))
    return promoted_ids


async def enforce_flow_memory_window() -> list[int]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await _promote_flow_memory_overflow(conn)


async def create_standing_memory_block(
    title: str,
    content: str = "",
    parent_id: int | None = None,
    status: str = "active",
    source: str = "manual",
    layer: str = "core",
    inject_enabled: bool = True,
    inject_every_n: int = 1,
    inject_on_first_turn: bool = True,
    sort_order: int | None = None,
    metadata: dict | None = None,
) -> dict:
    pool = await get_pool()
    title = (title or "").strip()
    if not title:
        title = "Untitled"
    inject_every_n = max(1, int(inject_every_n or 1))
    async with pool.acquire() as conn:
        if sort_order is None:
            sort_order = await conn.fetchval(
                """
                SELECT COALESCE(MAX(sort_order) + 10, 10)
                FROM standing_memory_blocks
                WHERE status = $1
                  AND parent_id IS NOT DISTINCT FROM $2
                """,
                _normalize_standing_status(status),
                parent_id,
            )
        row = await conn.fetchrow(
            """
            INSERT INTO standing_memory_blocks
                (title, content, parent_id, status, source, layer, inject_enabled,
                 inject_every_n, inject_on_first_turn, sort_order, metadata)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb)
            RETURNING *
            """,
            title,
            content or "",
            parent_id,
            _normalize_standing_status(status),
            _normalize_standing_source(source),
            _normalize_standing_layer(layer),
            bool(inject_enabled),
            inject_every_n,
            bool(inject_on_first_turn),
            int(sort_order),
            json.dumps(metadata or {}),
        )
        return dict(row)


async def upsert_pending_standing_memory_operation(
    operation: str,
    target_block_id: int | None = None,
    content: str = "",
    metadata: dict | None = None,
) -> tuple[dict, bool]:
    """Create or replace a model-authored pending operation for standing memory."""
    operation = str(operation or "").strip().lower()
    if operation not in {"create", "edit", "delete"}:
        raise ValueError("invalid operation")
    target_id = int(target_block_id) if target_block_id else None
    content = str(content or "").strip()
    if operation in {"create", "edit"} and not content:
        raise ValueError("content is required")
    if operation in {"edit", "delete"} and not target_id:
        raise ValueError("target_block_id is required")

    target = None
    pool = await get_pool()
    async with pool.acquire() as conn:
        if operation == "create":
            duplicate = await conn.fetchrow(
                """
                SELECT * FROM standing_memory_blocks
                WHERE lower(btrim(content)) = lower(btrim($1))
                  AND (
                    status = 'active'
                    OR (
                        status = 'pending'
                        AND COALESCE(metadata->>'pending_operation', 'create') = 'create'
                    )
                  )
                ORDER BY CASE WHEN status = 'active' THEN 0 ELSE 1 END, id ASC
                LIMIT 1
                """,
                content,
            )
            if duplicate:
                return dict(duplicate), False
        else:
            target = await conn.fetchrow(
                """
                SELECT * FROM standing_memory_blocks
                WHERE id = $1 AND status = 'active'
                """,
                target_id,
            )
            if not target:
                raise ValueError("target memory not found")
            existing = await conn.fetchrow(
                """
                SELECT * FROM standing_memory_blocks
                WHERE status = 'pending'
                  AND metadata->>'target_block_id' = $1
                ORDER BY id DESC LIMIT 1
                """,
                str(target_id),
            )
            if existing:
                next_content = target.get("content") if operation == "delete" else content
                next_metadata = {
                    **_json_object(existing.get("metadata")),
                    **(metadata or {}),
                    "pending_operation": operation,
                    "target_block_id": target_id,
                }
                row = await conn.fetchrow(
                    """
                    UPDATE standing_memory_blocks
                    SET title = $2,
                        content = $3,
                        layer = $4,
                        metadata = $5::jsonb,
                        updated_at = NOW()
                    WHERE id = $1
                    RETURNING *
                    """,
                    int(existing["id"]),
                    f"{'Delete' if operation == 'delete' else 'Edit'} memory #{target_id}",
                    str(next_content or ""),
                    target.get("layer") or "core",
                    json.dumps(next_metadata, ensure_ascii=False),
                )
                return dict(row), False

    if operation == "create":
        title = next(
            (line.strip() for line in content.splitlines() if line.strip()),
            "Memory",
        )[:80]
        layer = "core"
        next_content = content
    else:
        target = dict(target)
        title = f"{'Delete' if operation == 'delete' else 'Edit'} memory #{target_id}"
        layer = target.get("layer") or "core"
        next_content = target.get("content") if operation == "delete" else content
    block = await create_standing_memory_block(
        title=title,
        content=next_content,
        status="pending",
        source="model",
        layer=layer,
        inject_enabled=False,
        metadata={
            **(metadata or {}),
            "pending_operation": operation,
            **({"target_block_id": target_id} if target_id else {}),
        },
    )
    return block, True


async def get_standing_memory_blocks(
    status: str | None = None,
    include_archived: bool = True,
) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        if status:
            status = _normalize_standing_status(status)
            rows = await conn.fetch(
                """
                SELECT *
                FROM standing_memory_blocks
                WHERE status = $1
                ORDER BY parent_id NULLS FIRST, sort_order ASC, id ASC
                """,
                status,
            )
        elif include_archived:
            rows = await conn.fetch(
                """
                SELECT *
                FROM standing_memory_blocks
                WHERE status IN ('active', 'pending', 'archived')
                ORDER BY parent_id NULLS FIRST, sort_order ASC, id ASC
                """
            )
        else:
            rows = await conn.fetch(
                """
                SELECT *
                FROM standing_memory_blocks
                WHERE status = 'active'
                ORDER BY parent_id NULLS FIRST, sort_order ASC, id ASC
                """
            )
        return [dict(r) for r in rows]


async def get_standing_memory_block(block_id: int) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM standing_memory_blocks WHERE id = $1",
            block_id,
        )
        return dict(row) if row else None


async def update_standing_memory_block(block_id: int, **fields) -> dict | None:
    allowed = {
        "title", "content", "parent_id", "status", "source", "inject_enabled",
        "layer", "inject_every_n", "inject_on_first_turn", "sort_order", "metadata",
    }
    updates = []
    params = []
    idx = 1

    for key, value in fields.items():
        if key not in allowed:
            continue
        if key == "status":
            value = _normalize_standing_status(value)
        elif key == "source":
            value = _normalize_standing_source(value)
        elif key == "layer":
            value = _normalize_standing_layer(value)
        elif key == "inject_every_n":
            value = max(1, int(value or 1))
        elif key == "sort_order":
            value = int(value or 0)
        elif key == "metadata":
            value = json.dumps(value or {})
            updates.append(f"{key} = ${idx}::jsonb")
            params.append(value)
            idx += 1
            continue
        updates.append(f"{key} = ${idx}")
        params.append(value)
        idx += 1

    if not updates:
        return await get_standing_memory_block(block_id)

    updates.append("updated_at = NOW()")
    params.append(block_id)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"""
            UPDATE standing_memory_blocks
            SET {', '.join(updates)}
            WHERE id = ${idx}
            RETURNING *
            """,
            *params,
        )
        return dict(row) if row else None


async def delete_standing_memory_block(block_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM standing_memory_blocks WHERE id = $1",
            block_id,
        )


async def apply_pending_standing_memory_operation(block_id: int) -> dict | None:
    """Apply one approved standing-memory proposal atomically."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            pending = await conn.fetchrow(
                """
                SELECT * FROM standing_memory_blocks
                WHERE id = $1 AND status = 'pending'
                FOR UPDATE
                """,
                int(block_id),
            )
            if not pending:
                return None

            metadata = _json_object(pending.get("metadata"))
            operation = str(metadata.get("pending_operation") or "create")
            target_id = _normalize_optional_int(metadata.get("target_block_id"))

            if operation == "create":
                row = await conn.fetchrow(
                    """
                    UPDATE standing_memory_blocks AS pending
                    SET status = 'active',
                        inject_enabled = TRUE,
                        sort_order = COALESCE((
                            SELECT MAX(active.sort_order) + 10
                            FROM standing_memory_blocks AS active
                            WHERE active.status = 'active'
                              AND active.id != pending.id
                              AND active.parent_id IS NOT DISTINCT FROM pending.parent_id
                        ), 10),
                        metadata = (COALESCE(pending.metadata, '{}'::jsonb)
                            - 'pending_operation' - 'target_block_id')
                            || jsonb_build_object('approved_at', NOW()),
                        updated_at = NOW()
                    WHERE id = $1
                    RETURNING *
                    """,
                    int(block_id),
                )
                return {"operation": operation, "block": dict(row)}

            if operation not in {"edit", "delete"} or not target_id:
                return {"error": "invalid pending memory operation"}

            target = await conn.fetchrow(
                """
                SELECT * FROM standing_memory_blocks
                WHERE id = $1 AND status = 'active'
                FOR UPDATE
                """,
                target_id,
            )
            if not target:
                return {"error": "target memory not found"}

            if operation == "edit":
                row = await conn.fetchrow(
                    """
                    UPDATE standing_memory_blocks
                    SET content = $2,
                        metadata = COALESCE(metadata, '{}'::jsonb)
                            || jsonb_build_object('last_model_edit_at', NOW()),
                        updated_at = NOW()
                    WHERE id = $1
                    RETURNING *
                    """,
                    target_id,
                    pending.get("content") or "",
                )
            else:
                row = await conn.fetchrow(
                    """
                    DELETE FROM standing_memory_blocks
                    WHERE id = $1
                    RETURNING *
                    """,
                    target_id,
                )

            await conn.execute(
                "DELETE FROM standing_memory_blocks WHERE id = $1",
                int(block_id),
            )
            return {"operation": operation, "block": dict(row)}


def _normalize_long_term_keywords(keywords) -> list[str]:
    if isinstance(keywords, str):
        keywords = re.split(r"[,，、\n]+", keywords)
    if not isinstance(keywords, list):
        return []
    normalized = []
    seen = set()
    for keyword in keywords:
        value = str(keyword or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized


def long_term_memory_summary(memory: dict) -> str:
    """Return the real summary, falling back only for pre-migration records."""
    explicit = str(memory.get("summary") or "").strip()
    if explicit:
        return explicit
    return "；".join(_normalize_long_term_keywords(memory.get("keywords")))


def long_term_memory_kind(memory: dict) -> str:
    """Split archived handoff fragments from authored diary entries."""
    metadata = _json_object(memory.get("metadata"))
    explicit = str(metadata.get("entry_kind") or "").strip().lower()
    if explicit in {"fragment", "diary"}:
        return explicit
    # Flow overflow is a diary source. Fragments exist only as explicit rows
    # created from old diary summaries or by the memory extractor.
    return "diary"


def _normalize_long_term_memory_date(value) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError as exc:
        raise ValueError("memory_date must be YYYY-MM-DD") from exc


async def create_long_term_memory(
    title: str,
    keywords,
    content: str,
    memory_date: str | date | None = None,
    priority: int = 0,
    enabled: bool = True,
    summary: str | None = None,
    metadata: dict | None = None,
) -> dict:
    metadata = metadata or {}
    is_fragment = long_term_memory_kind({"metadata": metadata}) == "fragment"
    title = str(title or "").strip()
    content = str(content or "").strip()
    if not title and not is_fragment:
        raise ValueError("title is required")
    if not content:
        raise ValueError("content is required")
    if is_fragment:
        title = ""
        memory_date = None
    else:
        memory_date = _normalize_long_term_memory_date(memory_date)
    normalized_keywords = _normalize_long_term_keywords(keywords)
    summary_text = (
        "" if is_fragment
        else str(summary or "").strip() if summary is not None
        else ""
    )
    source_flow_memory_id = metadata.get("source_flow_memory_id")
    pool = await get_pool()
    async with pool.acquire() as conn:
        insert_sql = """
            INSERT INTO long_term_memories
                (title, keywords, summary, content, memory_date, priority, enabled,
                 metadata)
            VALUES ($1, $2::jsonb, $3, $4,
                    CASE WHEN $9::boolean THEN NULL
                         ELSE COALESCE($5::date, CURRENT_DATE) END,
                    $6, $7, $8::jsonb)
        """
        if source_flow_memory_id is not None:
            # Manual promotion can be retried or arrive concurrently. The unique
            # source-flow index makes the insert idempotent at the database edge.
            insert_sql += """
                ON CONFLICT ((metadata->>'source_flow_memory_id'))
                WHERE metadata ? 'source_flow_memory_id'
                DO NOTHING
                RETURNING *
            """
        else:
            insert_sql += " RETURNING *"

        row = await conn.fetchrow(
            insert_sql,
            title,
            json.dumps(normalized_keywords, ensure_ascii=False),
            summary_text,
            content,
            memory_date,
            int(priority or 0),
            bool(enabled),
            json.dumps(metadata, ensure_ascii=False),
            is_fragment,
        )
        if row is None and source_flow_memory_id is not None:
            row = await conn.fetchrow(
                """
                SELECT * FROM long_term_memories
                WHERE metadata->>'source_flow_memory_id' = $1
                ORDER BY id DESC
                LIMIT 1
                """,
                str(source_flow_memory_id),
            )
        if row is None:
            raise RuntimeError("failed to create long-term memory")
        result = dict(row)
        result["keywords"] = _json_list(result.get("keywords"))
        result["metadata"] = _json_object(result.get("metadata"))
        result["summary"] = long_term_memory_summary(result)
        return result


def _long_term_memory_sort_key(memory: dict) -> tuple[date, int]:
    value = memory.get("memory_date")
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, str):
        try:
            value = date.fromisoformat(value[:10])
        except ValueError:
            value = None
    if not isinstance(value, date):
        match = re.search(
            r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)",
            str(memory.get("title") or ""),
        )
        if match:
            try:
                value = date.fromisoformat(match.group(1))
            except ValueError:
                value = None
    return value or date.max, int(memory.get("id") or 0)


async def get_long_term_memories() -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, title, keywords, summary, content, memory_date,
                      priority, enabled, metadata, created_at
               FROM long_term_memories"""
        )
        result = []
        for row in rows:
            item = dict(row)
            item["keywords"] = _json_list(item.get("keywords"))
            item["metadata"] = _json_object(item.get("metadata"))
            item["summary"] = long_term_memory_summary(item)
            item["entry_kind"] = long_term_memory_kind(item)
            result.append(item)
        result.sort(key=_long_term_memory_sort_key)
        return result


async def get_long_term_memory_catalog() -> list[dict]:
    """Return only model-facing directory metadata, never long-term content."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, title, keywords, summary
            FROM long_term_memories
            ORDER BY memory_date ASC NULLS LAST, id ASC
        """)
    result = []
    for row in rows:
        item = dict(row)
        item["keywords"] = _json_list(item.get("keywords"))
        item["summary"] = long_term_memory_summary(item)
        result.append(item)
    return result


async def get_recent_long_term_memory_catalog(limit: int) -> list[dict]:
    """Return a recent title/summary directory without an application-level cap."""
    limit = int(limit)
    if limit <= 0:
        return []
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, title, keywords, summary, memory_date
            FROM long_term_memories
            ORDER BY memory_date DESC NULLS LAST, id DESC
            LIMIT $1
        """, limit)
    result = []
    for row in rows:
        item = dict(row)
        item["keywords"] = _json_list(item.get("keywords"))
        item["summary"] = long_term_memory_summary(item)
        result.append(item)
    return result


async def get_long_term_memory_counts() -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT metadata FROM long_term_memories")
        pending_count = await conn.fetchval(
            "SELECT COUNT(*) FROM long_term_memory_proposals"
        )
    fragment_count = sum(
        long_term_memory_kind(dict(row)) == "fragment" for row in rows
    )
    return {
        "memory_count": len(rows),
        "fragment_count": fragment_count,
        "diary_count": len(rows) - fragment_count,
        "pending_count": int(pending_count or 0),
    }


async def get_long_term_memory(memory_id: int) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, title, keywords, summary, content, memory_date, priority, enabled
                   , metadata, created_at
            FROM long_term_memories
            WHERE id = $1
            """,
            int(memory_id),
        )
        if not row:
            return None
        result = dict(row)
        result["keywords"] = _json_list(result.get("keywords"))
        result["metadata"] = _json_object(result.get("metadata"))
        result["summary"] = long_term_memory_summary(result)
        result["entry_kind"] = long_term_memory_kind(result)
        return result


async def update_long_term_memory(
    memory_id: int,
    title: str,
    keywords,
    content: str,
    memory_date: str | date | None = None,
    priority: int = 0,
    enabled: bool = True,
    summary: str | None = None,
) -> dict | None:
    title = str(title or "").strip()
    content = str(content or "").strip()
    if not title:
        raise ValueError("title is required")
    if not content:
        raise ValueError("content is required")
    memory_date = _normalize_long_term_memory_date(memory_date)
    normalized_keywords = (
        _normalize_long_term_keywords(keywords)
        if keywords is not None else None
    )
    if summary is not None:
        summary_text = str(summary or "").strip()
    else:
        summary_text = None
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE long_term_memories
            SET title = $2,
                keywords = COALESCE($3::jsonb, keywords),
                summary = COALESCE($4, summary),
                content = $5,
                memory_date = COALESCE($6::date, memory_date),
                priority = $7,
                enabled = $8
            WHERE id = $1
            RETURNING *
            """,
            int(memory_id),
            title,
            (
                json.dumps(normalized_keywords, ensure_ascii=False)
                if normalized_keywords is not None else None
            ),
            summary_text,
            content,
            memory_date,
            int(priority or 0),
            bool(enabled),
        )
        if not row:
            return None
        result = dict(row)
        result["keywords"] = _json_list(result.get("keywords"))
        result["metadata"] = _json_object(result.get("metadata"))
        result["summary"] = long_term_memory_summary(result)
        return result


async def delete_long_term_memory(memory_id: int) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM long_term_memories WHERE id = $1",
            int(memory_id),
        )
        return result != "DELETE 0"


async def delete_long_term_memories_batch(memory_ids: list[int]) -> list[int]:
    normalized_ids = sorted({int(memory_id) for memory_id in memory_ids})
    if not normalized_ids:
        return []
    if any(memory_id <= 0 for memory_id in normalized_ids):
        raise ValueError("memory ids must be positive integers")
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            DELETE FROM long_term_memories
            WHERE id = ANY($1::int[])
            RETURNING id
            """,
            normalized_ids,
        )
    return sorted(int(row["id"]) for row in rows)


async def create_pending_long_term_memory_operation(
    operation: str,
    target_memory_id: int | None = None,
    title: str = "",
    keywords=None,
    content: str = "",
    memory_date: str | date | None = None,
    priority: int = 0,
    enabled: bool = True,
    metadata: dict | None = None,
    summary: str | None = None,
) -> dict:
    operation = str(operation or "").strip().lower()
    if operation not in {"create", "edit", "delete"}:
        raise ValueError("invalid operation")
    target_memory_id = int(target_memory_id) if target_memory_id else None
    title = str(title or "").strip()
    content = str(content or "").strip()
    memory_date = _normalize_long_term_memory_date(memory_date)
    if operation == "create" and (not title or not content):
        raise ValueError("title and content are required")
    if operation in {"edit", "delete"} and not target_memory_id:
        raise ValueError("target_memory_id is required")

    pool = await get_pool()
    async with pool.acquire() as conn:
        if target_memory_id:
            target = await conn.fetchrow(
                """
                SELECT id, title, keywords, summary, content, memory_date, priority, enabled
                FROM long_term_memories WHERE id = $1
                """,
                target_memory_id,
            )
            if not target:
                raise ValueError("target long-term memory not found")
            if operation == "edit":
                title = title or str(target.get("title") or "").strip()
                content = content or str(target.get("content") or "").strip()
                if keywords is None:
                    keywords = _json_list(target.get("keywords"))
                if summary is None:
                    summary = long_term_memory_summary({
                        **dict(target),
                        "keywords": _json_list(target.get("keywords")),
                    })
                memory_date = memory_date or target.get("memory_date")
                priority = int(target.get("priority") or 0)
                enabled = bool(target.get("enabled", True))
            elif operation == "delete":
                title = str(target.get("title") or "").strip()
                content = str(target.get("content") or "").strip()
                keywords = _json_list(target.get("keywords"))
                summary = long_term_memory_summary({
                    **dict(target),
                    "keywords": keywords,
                })
                memory_date = target.get("memory_date")
                priority = int(target.get("priority") or 0)
                enabled = bool(target.get("enabled", True))

        normalized_keywords = _normalize_long_term_keywords(keywords)
        summary_text = (
            str(summary or "").strip()
            if summary is not None
            else "；".join(normalized_keywords)
        )
        row = await conn.fetchrow(
            """
            INSERT INTO long_term_memory_proposals
                (operation, target_memory_id, title, keywords, summary, content,
                 source, memory_date, priority, enabled, metadata)
            VALUES ($1, $2, $3, $4::jsonb, $5, $6, 'model', $7, $8, $9, $10::jsonb)
            RETURNING *
            """,
            operation,
            target_memory_id,
            title,
            json.dumps(normalized_keywords, ensure_ascii=False),
            summary_text,
            content,
            memory_date,
            int(priority or 0),
            bool(enabled),
            json.dumps(metadata or {}, ensure_ascii=False),
        )
        result = dict(row)
        result["keywords"] = _json_list(result.get("keywords"))
        result["summary"] = long_term_memory_summary(result)
        result["metadata"] = _json_object(result.get("metadata"))
        return result


async def upsert_pending_long_term_memory_operation(
    operation: str,
    target_memory_id: int | None = None,
    title: str = "",
    keywords=None,
    content: str = "",
    memory_date: str | date | None = None,
    metadata: dict | None = None,
    summary: str | None = None,
) -> tuple[dict, bool]:
    """Create a pending intent or update the existing intent for one active target."""
    operation = str(operation or "").strip().lower()
    if operation not in {"create", "edit", "delete"}:
        raise ValueError("invalid operation")
    target_id = int(target_memory_id) if target_memory_id else None
    if operation in {"edit", "delete"} and not target_id:
        raise ValueError("target_memory_id is required")
    pool = await get_pool()
    async with pool.acquire() as conn:
        if operation == "create":
            duplicate = await conn.fetchrow(
                """
                SELECT * FROM long_term_memory_proposals
                WHERE operation = 'create'
                  AND lower(btrim(title)) = lower(btrim($1))
                  AND lower(btrim(content)) = lower(btrim($2))
                ORDER BY id ASC LIMIT 1
                """,
                str(title or "").strip(),
                str(content or "").strip(),
            )
            if duplicate:
                item = dict(duplicate)
                item["keywords"] = _json_list(item.get("keywords"))
                item["summary"] = long_term_memory_summary(item)
                item["metadata"] = _json_object(item.get("metadata"))
                return item, False
        elif target_id:
            existing = await conn.fetchrow(
                """
                SELECT * FROM long_term_memory_proposals
                WHERE target_memory_id = $1
                ORDER BY id DESC LIMIT 1
                """,
                target_id,
            )
            if existing:
                target = await conn.fetchrow(
                    """
                    SELECT id, title, keywords, summary, content, memory_date, priority, enabled
                    FROM long_term_memories WHERE id = $1
                    """,
                    target_id,
                )
                if not target:
                    raise ValueError("target long-term memory not found")
                if operation == "delete":
                    next_title = str(target.get("title") or "").strip()
                    next_content = str(target.get("content") or "").strip()
                    next_keywords = _json_list(target.get("keywords"))
                    next_summary = long_term_memory_summary({
                        **dict(target),
                        "keywords": next_keywords,
                    })
                else:
                    next_title = str(title or "").strip() or str(target.get("title") or "").strip()
                    next_content = str(content or "").strip() or str(target.get("content") or "").strip()
                    next_keywords = (
                        _normalize_long_term_keywords(keywords)
                        if keywords is not None else _json_list(target.get("keywords"))
                    )
                    next_summary = (
                        str(summary or "").strip()
                        if summary is not None
                        else long_term_memory_summary({
                            **dict(target),
                            "keywords": _json_list(target.get("keywords")),
                        })
                    )
                merged_metadata = {
                    **_json_object(existing.get("metadata")),
                    **(metadata or {}),
                }
                row = await conn.fetchrow(
                    """
                    UPDATE long_term_memory_proposals
                    SET operation = $2,
                        title = $3,
                        keywords = $4::jsonb,
                        summary = $5,
                        content = $6,
                        memory_date = $7,
                        priority = $8,
                        enabled = $9,
                        metadata = $10::jsonb
                    WHERE id = $1
                    RETURNING *
                    """,
                    int(existing["id"]),
                    operation,
                    next_title,
                    json.dumps(next_keywords, ensure_ascii=False),
                    next_summary,
                    next_content,
                    _normalize_long_term_memory_date(memory_date) or target.get("memory_date"),
                    int(target.get("priority") or 0),
                    bool(target.get("enabled", True)),
                    json.dumps(merged_metadata, ensure_ascii=False),
                )
                item = dict(row)
                item["keywords"] = _json_list(item.get("keywords"))
                item["summary"] = long_term_memory_summary(item)
                item["metadata"] = _json_object(item.get("metadata"))
                return item, False

    created = await create_pending_long_term_memory_operation(
        operation,
        target_memory_id=target_id,
        title=title,
        keywords=keywords,
        summary=summary,
        content=content,
        memory_date=memory_date,
        metadata=metadata,
    )
    return created, True


async def get_pending_long_term_memory_operations() -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, operation, target_memory_id, title, keywords, summary, content, source,
                   memory_date, priority, enabled, metadata, created_at
            FROM long_term_memory_proposals
            ORDER BY id ASC
            """
        )
        result = []
        for row in rows:
            item = dict(row)
            item["keywords"] = _json_list(item.get("keywords"))
            item["summary"] = long_term_memory_summary(item)
            item["metadata"] = _json_object(item.get("metadata"))
            result.append(item)
        return result


async def reject_pending_long_term_memory_operation(proposal_id: int) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM long_term_memory_proposals WHERE id = $1",
            int(proposal_id),
        )
        return result != "DELETE 0"


async def apply_pending_long_term_memory_operation(proposal_id: int) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            proposal = await conn.fetchrow(
                """
                SELECT *
                FROM long_term_memory_proposals
                WHERE id = $1
                FOR UPDATE
                """,
                int(proposal_id),
            )
            if not proposal:
                return None

            operation = str(proposal.get("operation") or "")
            target_id = proposal.get("target_memory_id")
            if operation == "create":
                memory = await conn.fetchrow(
                    """
                    INSERT INTO long_term_memories
                        (title, keywords, summary, content, memory_date, priority, enabled)
                    VALUES ($1, $2::jsonb, $3, $4, COALESCE($5, CURRENT_DATE), $6, $7)
                    RETURNING *
                    """,
                    proposal.get("title") or "",
                    json.dumps(
                        _json_list(proposal.get("keywords")),
                        ensure_ascii=False,
                    ),
                    long_term_memory_summary({
                        **dict(proposal),
                        "keywords": _json_list(proposal.get("keywords")),
                    }),
                    proposal.get("content") or "",
                    proposal.get("memory_date"),
                    int(proposal.get("priority") or 0),
                    bool(proposal.get("enabled", True)),
                )
            elif operation in {"edit", "delete"} and target_id:
                target = await conn.fetchrow(
                    "SELECT * FROM long_term_memories WHERE id = $1 FOR UPDATE",
                    int(target_id),
                )
                if not target:
                    return {"error": "target long-term memory not found"}
                if operation == "edit":
                    memory = await conn.fetchrow(
                        """
                        UPDATE long_term_memories
                        SET title = $2, keywords = $3::jsonb, summary = $4,
                            content = $5, memory_date = COALESCE($6, memory_date)
                        WHERE id = $1
                        RETURNING *
                        """,
                        int(target_id),
                        proposal.get("title") or "",
                        json.dumps(
                            _json_list(proposal.get("keywords")),
                            ensure_ascii=False,
                        ),
                        long_term_memory_summary({
                            **dict(proposal),
                            "keywords": _json_list(proposal.get("keywords")),
                        }),
                        proposal.get("content") or "",
                        proposal.get("memory_date"),
                    )
                else:
                    memory = await conn.fetchrow(
                        "DELETE FROM long_term_memories WHERE id = $1 RETURNING *",
                        int(target_id),
                    )
            else:
                return {"error": "invalid pending long-term memory operation"}

            await conn.execute(
                "DELETE FROM long_term_memory_proposals WHERE id = $1",
                int(proposal_id),
            )
            result = dict(memory)
            result["keywords"] = _json_list(result.get("keywords"))
            result["summary"] = long_term_memory_summary(result)
            return {"operation": operation, "memory": result}


async def get_injectable_standing_memory_blocks(turn_number: int) -> list[dict]:
    turn_number = max(1, int(turn_number or 1))
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT *
            FROM standing_memory_blocks
            WHERE status = 'active'
              AND inject_enabled = TRUE
              AND (
                    (inject_on_first_turn = TRUE AND $1 = 1)
                    OR (($1 % inject_every_n) = 0)
                  )
            ORDER BY parent_id NULLS FIRST, sort_order ASC, id ASC
            """,
            turn_number,
        )
        return [dict(r) for r in rows]


# ============================================================
# 上下文管理 — 会话 + 消息
# ============================================================

async def init_context_tables():
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id           SERIAL PRIMARY KEY,
                name         TEXT NOT NULL,
                external_session_id TEXT UNIQUE,
                max_messages INT DEFAULT 50,
                is_active    BOOLEAN DEFAULT FALSE,
                created_at   TIMESTAMPTZ DEFAULT NOW(),
                updated_at   TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("""
            ALTER TABLE conversations ADD COLUMN IF NOT EXISTS external_session_id TEXT UNIQUE
        """)
        await conn.execute("""
            ALTER TABLE conversations
                ADD COLUMN IF NOT EXISTS cache_anchor_fingerprint TEXT,
                ADD COLUMN IF NOT EXISTS handoff_draft TEXT,
                ADD COLUMN IF NOT EXISTS handoff_summary TEXT,
                ADD COLUMN IF NOT EXISTS handoff_source_id INT REFERENCES conversations(id) ON DELETE SET NULL,
                ADD COLUMN IF NOT EXISTS handoff_message_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
                ADD COLUMN IF NOT EXISTS handoff_summary_through_message_id BIGINT,
                ADD COLUMN IF NOT EXISTS handoff_summary_version INT NOT NULL DEFAULT 0,
                ADD COLUMN IF NOT EXISTS handoff_summary_ready_for_flow BOOLEAN NOT NULL DEFAULT FALSE,
                ADD COLUMN IF NOT EXISTS last_anthropic_tools JSONB,
                ADD COLUMN IF NOT EXISTS last_frontend_tool_names JSONB,
                ADD COLUMN IF NOT EXISTS heartbeat_count INT NOT NULL DEFAULT 0,
                ADD COLUMN IF NOT EXISTS heartbeat_last_user_message_id BIGINT,
                ADD COLUMN IF NOT EXISTS heartbeat_claim_token TEXT,
                ADD COLUMN IF NOT EXISTS heartbeat_claimed_at TIMESTAMPTZ,
                ADD COLUMN IF NOT EXISTS heartbeat_last_sent_at TIMESTAMPTZ,
                ADD COLUMN IF NOT EXISTS heartbeat_last_checked_at TIMESTAMPTZ
        """)
        await conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_conversations_external_session
            ON conversations(external_session_id)
            WHERE external_session_id IS NOT NULL
        """)
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock($1)", CONVERSATION_SWITCH_LOCK)
            # Repair legacy duplicate active flags before enforcing the invariant.
            # Message activity changes updated_at, so use the stable conversation
            # creation order to retain the newest handoff, not the last writer.
            await conn.execute("""
                UPDATE conversations SET is_active = FALSE
                WHERE is_active = TRUE AND id <> (
                    SELECT id FROM conversations WHERE is_active = TRUE
                    ORDER BY id DESC LIMIT 1
                )
            """)
            await conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_conversations_single_active
                ON conversations (is_active) WHERE is_active = TRUE
            """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS context_messages (
                id              SERIAL PRIMARY KEY,
                conversation_id INT REFERENCES conversations(id) ON DELETE CASCADE,
                role            TEXT NOT NULL,
                content         TEXT NOT NULL,
                created_at      TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        # 新增：结构化内容字段（存 tool_use / tool_result 的原始结构）
        await conn.execute("""
            ALTER TABLE context_messages ADD COLUMN IF NOT EXISTS content_json JSONB
        """)
        await conn.execute("""
            ALTER TABLE context_messages
                ADD COLUMN IF NOT EXISTS kind TEXT NOT NULL DEFAULT 'chat',
                ADD COLUMN IF NOT EXISTS hidden BOOLEAN NOT NULL DEFAULT FALSE,
                ADD COLUMN IF NOT EXISTS affects_activity BOOLEAN NOT NULL DEFAULT TRUE
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_ctx_conv_id
            ON context_messages(conversation_id, id ASC)
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_ctx_visible_conversation_created
            ON context_messages(conversation_id, created_at)
            WHERE hidden = FALSE
              AND role IN ('user', 'assistant')
              AND (role = 'user' OR content_json IS NULL)
        """)

        count = await conn.fetchval("SELECT COUNT(*) FROM conversations")
        if count == 0:
            await conn.execute("""
                INSERT INTO conversations (name, max_messages, is_active)
                VALUES ('默认', 50, TRUE)
            """)
            print("[context] 已创建默认会话")

    await init_heartbeat_activity_tables()
    await init_heartbeat_settings_table()
    await init_route_settings_table()
    await init_anthropic_credentials_table()
    await init_ocr_settings_table()
    await init_openai_provider_profiles_table()
    await init_conversation_model_settings_table()


async def create_conversation(name: str, max_messages: int = 50, external_session_id: str | None = None) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO conversations (name, max_messages, external_session_id)
            VALUES ($1, $2, NULLIF($3, ''))
            RETURNING id, name, external_session_id, max_messages, is_active, created_at, updated_at
        """, name, max_messages, external_session_id or "")
        return dict(row)


async def get_or_create_conversation_for_session(
    external_session_id: str,
    name: str | None = None,
    max_messages: int = 50,
) -> dict:
    session_key = str(external_session_id or "").strip()
    if not session_key:
        raise ValueError("external_session_id required")
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO conversations (name, max_messages, external_session_id)
            VALUES ($1, $2, $3)
            ON CONFLICT (external_session_id)
            DO UPDATE SET updated_at = NOW()
            RETURNING id, name, external_session_id, max_messages, is_active, created_at, updated_at
        """, name or f"外部会话 {session_key[:32]}", max_messages, session_key)
        return dict(row)


async def get_all_conversations(include_message_stats: bool = True) -> list:
    pool = await get_pool()
    async with pool.acquire() as conn:
        if not include_message_stats:
            rows = await conn.fetch("""
                SELECT c.id, c.name, c.external_session_id, c.max_messages,
                       c.is_active, c.created_at, c.updated_at,
                       CASE WHEN c.is_active THEN (
                           SELECT COUNT(*)
                           FROM context_messages m
                           WHERE m.conversation_id = c.id
                             AND m.hidden = FALSE
                             AND m.role IN ('user', 'assistant')
                             AND (m.role = 'user' OR m.content_json IS NULL)
                       ) ELSE NULL::BIGINT END AS message_count,
                       c.created_at AS started_at,
                       c.updated_at AS last_message_at
                FROM conversations c
                ORDER BY c.updated_at DESC
            """)
            return [dict(r) for r in rows]
        rows = await conn.fetch("""
            SELECT c.id, c.name, c.external_session_id, c.max_messages, c.is_active,
                   c.created_at, c.updated_at,
                   COALESCE(m.msg_count, 0) AS message_count,
                   m.started_at, m.last_message_at
            FROM conversations c
            LEFT JOIN (
                SELECT conversation_id, COUNT(*) AS msg_count,
                       MIN(created_at) AS started_at,
                       MAX(created_at) AS last_message_at
                FROM context_messages
                WHERE hidden = FALSE
                  AND role IN ('user', 'assistant')
                  AND (role = 'user' OR content_json IS NULL)
                GROUP BY conversation_id
            ) m ON m.conversation_id = c.id
            ORDER BY c.updated_at DESC
        """)
        return [dict(r) for r in rows]


async def get_conversation_context_metadata(
    conversation_id: int,
    include_message_stats: bool = True,
) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        if not include_message_stats:
            row = await conn.fetchrow("""
                SELECT c.id, c.name, c.external_session_id, c.max_messages,
                       c.is_active, c.handoff_summary, c.handoff_draft,
                       c.created_at, c.updated_at,
                       NULL::BIGINT AS message_count,
                       NULL::TIMESTAMPTZ AS started_at,
                       NULL::TIMESTAMPTZ AS last_message_at
                FROM conversations c
                WHERE c.id = $1
            """, int(conversation_id))
            return dict(row) if row else None
        row = await conn.fetchrow("""
            SELECT c.id, c.name, c.external_session_id, c.max_messages,
                   c.is_active, c.handoff_summary, c.handoff_draft,
                   c.created_at, c.updated_at,
                   COALESCE(m.message_count, 0) AS message_count,
                   COALESCE(m.started_at, c.created_at) AS started_at,
                   COALESCE(m.last_message_at, c.created_at) AS last_message_at
            FROM conversations c
            LEFT JOIN LATERAL (
                SELECT COUNT(*) AS message_count,
                       MIN(created_at) AS started_at,
                       MAX(created_at) AS last_message_at
                FROM context_messages
                WHERE conversation_id = c.id
                  AND hidden = FALSE
                  AND role IN ('user', 'assistant')
                  AND (role = 'user' OR content_json IS NULL)
            ) m ON TRUE
            WHERE c.id = $1
        """, int(conversation_id))
    return dict(row) if row else None


def _conversation_embedding_url(api_url: str) -> str:
    value = str(api_url or "").rstrip("/")
    if value.endswith("/embeddings"):
        return value
    return value + "/embeddings"


def _conversation_chunks(messages: list[dict], max_chars: int = 3200) -> list[dict]:
    chunks = []
    current = []

    def rendered(items: list[dict]) -> str:
        return "\n\n".join(
            f"{('用户' if item['role'] == 'user' else '助手')}：{item['content']}"
            for item in items
        )

    def flush():
        if not current:
            return
        content = rendered(current)
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        chunks.append({
            "first_message_id": int(current[0]["id"]),
            "last_message_id": int(current[-1]["id"]),
            "content": content,
            "messages": [dict(item) for item in current],
            "content_hash": digest,
        })

    for message in messages:
        candidate = [*current, message]
        if current and len(rendered(candidate)) > max_chars:
            overlap = current[-1:]
            flush()
            current = [*overlap, message]
            if len(rendered(current)) > max_chars and len(current) > 1:
                current = [message]
        else:
            current = candidate
    flush()
    return chunks


async def _embed_conversation_chunks(texts: list[str], settings: dict) -> list[list[float] | None]:
    if not texts:
        return []
    try:
        async with httpx.AsyncClient(timeout=EMBEDDING_TIMEOUT) as client:
            response = await client.post(
                _conversation_embedding_url(settings.get("embedding_api_url")),
                headers={
                    "Authorization": f"Bearer {settings.get('embedding_api_key') or ''}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.get("embedding_model") or "",
                    "input": texts,
                },
            )
        if response.status_code != 200:
            print(f"[history] embedding failed: HTTP {response.status_code}")
            return [None] * len(texts)
        by_index = {
            int(item.get("index", index)): item.get("embedding")
            for index, item in enumerate(response.json().get("data") or [])
            if isinstance(item, dict)
        }
        return [
            [float(value) for value in by_index[index]]
            if isinstance(by_index.get(index), list) and by_index[index]
            else None
            for index in range(len(texts))
        ]
    except Exception as exc:
        print(f"[history] embedding error: {exc}")
        return [None] * len(texts)


def _long_term_embedding_text(memory: dict) -> str:
    summary = long_term_memory_summary(memory)
    searchable_body = str(memory.get("content") or "").strip()[
        :EMBEDDING_MAX_INPUT_CHARS
    ]
    if long_term_memory_kind(memory) == "fragment":
        return searchable_body
    return "\n".join(filter(None, [
        str(memory.get("title") or "").strip(),
        summary,
        searchable_body,
    ]))


def _long_term_embedding_config_hash(settings: dict) -> str:
    """Identify the vector space without tying it to a rotatable API key."""
    payload = {
        "api_url": _conversation_embedding_url(
            str(settings.get("embedding_api_url") or "")
        ),
        "model": str(settings.get("embedding_model") or "").strip(),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


async def refresh_long_term_memory_embeddings(settings: dict) -> dict:
    """Incrementally index fragment text and searchable diary fields."""
    model = str(settings.get("embedding_model") or "").strip()
    if not model:
        return {"indexed": 0, "embedded": 0}
    config_hash = _long_term_embedding_config_hash(settings)
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, title, keywords, summary, content, metadata
            FROM long_term_memories
            ORDER BY id ASC
        """)
        existing_rows = await conn.fetch("""
            SELECT memory_id, content_hash, embedding
            FROM long_term_memory_embeddings
            WHERE embedding_model = $1 AND embedding_config_hash = $2
        """, model, config_hash)

    memories = []
    for row in rows:
        memory = dict(row)
        memory["keywords"] = _json_list(memory.get("keywords"))
        text = _long_term_embedding_text(memory)
        memory["embedding_text"] = text
        memory["content_hash"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
        memories.append(memory)
    existing = {
        (int(row["memory_id"]), str(row["content_hash"])): row["embedding"]
        for row in existing_rows
    }
    missing = [
        memory for memory in memories
        if not existing.get((int(memory["id"]), memory["content_hash"]))
    ]
    embeddings = []
    for start in range(0, len(missing), 20):
        batch = missing[start:start + 20]
        embeddings.extend(await _embed_conversation_chunks(
            [memory["embedding_text"] for memory in batch], settings
        ))

    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """DELETE FROM long_term_memory_embeddings
                   WHERE embedding_model <> $1 OR embedding_config_hash <> $2""",
                model,
                config_hash,
            )
            valid_ids = [int(memory["id"]) for memory in memories]
            if valid_ids:
                await conn.execute("""
                    DELETE FROM long_term_memory_embeddings
                    WHERE NOT (memory_id = ANY($1::int[]))
                """, valid_ids)
            else:
                await conn.execute("DELETE FROM long_term_memory_embeddings")
            for memory, embedding in zip(missing, embeddings):
                await conn.execute("""
                    INSERT INTO long_term_memory_embeddings
                        (memory_id, content_hash, embedding, embedding_model,
                         embedding_config_hash, indexed_at)
                    VALUES ($1, $2, $3::jsonb, $4, $5, NOW())
                    ON CONFLICT (memory_id) DO UPDATE SET
                        content_hash = EXCLUDED.content_hash,
                        embedding = EXCLUDED.embedding,
                        embedding_model = EXCLUDED.embedding_model,
                        embedding_config_hash = EXCLUDED.embedding_config_hash,
                        indexed_at = NOW()
                """,
                    int(memory["id"]),
                    memory["content_hash"],
                    json.dumps(embedding) if embedding else None,
                    model,
                    config_hash,
                )
    return {
        "indexed": len(memories),
        "embedded": sum(1 for value in embeddings if value),
    }


def _long_term_embedding_refresh_finished(task: asyncio.Task) -> None:
    global _long_term_embedding_refresh_task
    if _long_term_embedding_refresh_task is task:
        _long_term_embedding_refresh_task = None
    try:
        task.result()
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        print(f"[long-term-memory] background embedding refresh failed: {exc}")


def schedule_long_term_memory_embedding_refresh(settings: dict) -> bool:
    """Start one best-effort refresh without delaying the active chat request."""
    global _long_term_embedding_refresh_task
    if (
        _long_term_embedding_refresh_task
        and not _long_term_embedding_refresh_task.done()
    ):
        return False
    settings_snapshot = dict(settings)
    task = asyncio.create_task(
        refresh_long_term_memory_embeddings(settings_snapshot)
    )
    _long_term_embedding_refresh_task = task
    task.add_done_callback(_long_term_embedding_refresh_finished)
    return True


async def search_long_term_memory_summaries(
    query: str,
    settings: dict,
    limit: int,
    entry_kind: str | None = None,
) -> list[dict]:
    query = str(query or "").strip()
    limit = int(limit)
    if not query or limit <= 0:
        return []
    schedule_long_term_memory_embedding_refresh(settings)
    try:
        query_vectors = await asyncio.wait_for(
            _embed_conversation_chunks([query], settings),
            timeout=LONG_TERM_RECALL_EMBEDDING_TIMEOUT,
        )
    except asyncio.TimeoutError:
        print('[long-term-memory] query embedding timed out; ' +
              ('fragment recall skipped' if entry_kind == 'fragment' else 'using keyword recall'))
        query_vectors = [None]
    query_embedding = query_vectors[0] if query_vectors else None
    if entry_kind == 'fragment' and not query_embedding:
        return []
    keywords = extract_search_keywords(query)
    model = str(settings.get("embedding_model") or "").strip()
    config_hash = _long_term_embedding_config_hash(settings)
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT m.id, m.title, m.keywords, m.summary, m.content,
                   m.memory_date, m.metadata, m.created_at, m.enabled, e.embedding
            FROM long_term_memories m
            LEFT JOIN long_term_memory_embeddings e
              ON e.memory_id = m.id
             AND e.embedding_model = $1
             AND e.embedding_config_hash = $2
        """, model, config_hash)
        related_ids = []
        if entry_kind == 'fragment':
            current_id = settings.get('_recall_conversation_id')
            if current_id is None:
                current_id = await conn.fetchval('SELECT id FROM conversations WHERE is_active = TRUE LIMIT 1')
            if type(current_id) is int:
                related = await conn.fetch('''
                    WITH RECURSIVE ancestors(id, parent) AS (
                        SELECT id, handoff_source_id FROM conversations WHERE id = $1
                        UNION
                        SELECT c.id, c.handoff_source_id FROM conversations c
                        JOIN ancestors a ON c.id = a.parent
                    ), family(id) AS (
                        SELECT id FROM ancestors
                        UNION
                        SELECT c.id FROM conversations c JOIN family f ON c.handoff_source_id = f.id
                    ) SELECT id FROM family
                ''', current_id)
                related_ids = [row['id'] for row in related]

    scored = []
    for record in rows:
        memory = dict(record)
        memory["metadata"] = _json_object(memory.get("metadata"))
        memory["entry_kind"] = long_term_memory_kind(memory)
        if entry_kind and memory["entry_kind"] != entry_kind:
            continue
        if memory.get('enabled') is False:
            continue
        if memory['metadata'].get('forgetting_pending'):
            continue
        memory["keywords"] = _json_list(memory.get("keywords"))
        memory["summary"] = long_term_memory_summary(memory)
        embedding = _safe_load_embedding(memory.get("embedding"))
        semantic = cosine_similarity(query_embedding, embedding) if query_embedding else 0.0
        keyword_score, hits = keyword_match_score(
            query,
            _long_term_embedding_text(memory),
            keywords,
        )
        semantic_match = (
            semantic > 0
            and semantic >= LONG_TERM_RECALL_MIN_SEMANTIC_SCORE
        )
        if memory['entry_kind'] == 'fragment':
            if not semantic_match or not math.isfinite(semantic):
                continue
            memory['score_components'] = fragment_recall_scores(memory, query, semantic, related_ids)
            memory['score'] = memory['score_components']['total']
        else:
            if not semantic_match and hits <= 0:
                continue
            memory['score'] = semantic * 0.8 + keyword_score * 0.2
        memory.pop("embedding", None)
        if memory["entry_kind"] != "fragment":
            memory.pop("content", None)
        scored.append(memory)
    scored.sort(key=lambda item: (item["score"], int(item["id"])), reverse=True)
    return scored[:limit]


async def refresh_conversation_search_index(settings: dict) -> dict:
    """Incrementally index visible chat messages without changing message rows."""
    model = str(settings.get("embedding_model") or "").strip()
    if not model:
        return {"indexed": 0, "embedded": 0}
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT c.id AS conversation_id, m.id, m.role, m.content
            FROM conversations c
            LEFT JOIN context_messages m
              ON m.conversation_id = c.id
             AND m.hidden = FALSE
             AND m.role IN ('user', 'assistant')
             AND (m.role = 'user' OR m.content_json IS NULL)
             AND m.kind <> 'handoff_copy'
             AND m.content NOT IN ('', '[tool_calls]', '[tool_result]')
            ORDER BY c.id ASC, m.id ASC
        """)
        existing_rows = await conn.fetch("""
            SELECT conversation_id, content_hash, embedding
            FROM conversation_search_chunks
            WHERE embedding_model = $1
        """, model)

    existing = {
        (int(row["conversation_id"]), str(row["content_hash"])): row["embedding"]
        for row in existing_rows
    }
    grouped: dict[int, list[dict]] = {}
    for row in rows:
        conv_id = int(row["conversation_id"])
        grouped.setdefault(conv_id, [])
        if row["id"] is not None:
            grouped[conv_id].append({
                "id": int(row["id"]),
                "role": str(row["role"]),
                "content": str(row["content"] or ""),
            })

    all_chunks = []
    for conv_id, messages in grouped.items():
        for chunk in _conversation_chunks(messages):
            chunk["conversation_id"] = conv_id
            all_chunks.append(chunk)

    missing = [
        chunk for chunk in all_chunks
        if not existing.get((chunk["conversation_id"], chunk["content_hash"]))
    ]
    embeddings = []
    for start in range(0, len(missing), 20):
        batch = missing[start:start + 20]
        embeddings.extend(await _embed_conversation_chunks(
            [chunk["content"] for chunk in batch], settings
        ))

    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "DELETE FROM conversation_search_chunks WHERE embedding_model <> $1",
                model,
            )
            valid_by_conversation = {
                conv_id: [chunk["content_hash"] for chunk in all_chunks
                          if chunk["conversation_id"] == conv_id]
                for conv_id in grouped
            }
            for conv_id, hashes in valid_by_conversation.items():
                if hashes:
                    await conn.execute("""
                        DELETE FROM conversation_search_chunks
                        WHERE conversation_id = $1 AND embedding_model = $2
                          AND NOT (content_hash = ANY($3::text[]))
                    """, conv_id, model, hashes)
                else:
                    await conn.execute("""
                        DELETE FROM conversation_search_chunks
                        WHERE conversation_id = $1 AND embedding_model = $2
                    """, conv_id, model)

            for chunk, embedding in zip(missing, embeddings):
                await conn.execute("""
                    INSERT INTO conversation_search_chunks
                        (conversation_id, first_message_id, last_message_id,
                         content, messages, content_hash, embedding,
                         embedding_model, indexed_at)
                    VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7::jsonb, $8, NOW())
                    ON CONFLICT (conversation_id, content_hash, embedding_model)
                    DO UPDATE SET
                        first_message_id = EXCLUDED.first_message_id,
                        last_message_id = EXCLUDED.last_message_id,
                        content = EXCLUDED.content,
                        messages = EXCLUDED.messages,
                        embedding = COALESCE(EXCLUDED.embedding, conversation_search_chunks.embedding),
                        indexed_at = NOW()
                """,
                    chunk["conversation_id"],
                    chunk["first_message_id"],
                    chunk["last_message_id"],
                    chunk["content"],
                    json.dumps(chunk["messages"], ensure_ascii=False),
                    chunk["content_hash"],
                    json.dumps(embedding) if embedding else None,
                    model,
                )
    return {
        "indexed": len(all_chunks),
        "embedded": sum(1 for value in embeddings if value),
    }


def _history_excerpt_messages(messages, keywords: list[str], max_chars: int = 1200) -> list[dict]:
    messages = _json_list(messages)
    if not messages:
        return []
    best_index = 0
    best_hits = -1
    for index, message in enumerate(messages):
        content = str(message.get("content") or "").lower()
        hits = sum(1 for keyword in keywords if keyword.lower() in content)
        if hits > best_hits:
            best_index, best_hits = index, hits

    selected = []
    used = 0
    for index in range(max(0, best_index - 1), min(len(messages), best_index + 2)):
        message = messages[index]
        size = len(str(message.get("content") or ""))
        if used + size > max_chars:
            continue
        selected.append(message)
        used += size
    return selected


async def search_conversation_history(
    query: str,
    current_conversation_id: int,
    settings: dict,
    limit: int = 5,
) -> list[dict]:
    query = str(query or "").strip()
    if not query:
        return []
    await refresh_conversation_search_index(settings)
    query_vectors = await _embed_conversation_chunks([query], settings)
    query_embedding = query_vectors[0] if query_vectors else None
    keywords = extract_search_keywords(query)
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT sc.*, c.name,
                   COALESCE(MIN(m.created_at) FILTER (
                       WHERE m.hidden = FALSE AND m.role IN ('user', 'assistant')
                         AND (m.role = 'user' OR m.content_json IS NULL)
                   ), c.created_at) AS started_at,
                   COALESCE(MAX(m.created_at) FILTER (
                       WHERE m.hidden = FALSE AND m.role IN ('user', 'assistant')
                         AND (m.role = 'user' OR m.content_json IS NULL)
                   ), c.created_at) AS last_message_at
            FROM conversation_search_chunks sc
            JOIN conversations c ON c.id = sc.conversation_id
            LEFT JOIN context_messages m ON m.conversation_id = c.id
            WHERE sc.embedding_model = $1 AND sc.conversation_id <> $2
            GROUP BY sc.id, c.id
        """, settings.get("embedding_model") or "", int(current_conversation_id))

    scored = []
    for record in rows:
        row = dict(record)
        embedding = _safe_load_embedding(row.get("embedding"))
        semantic = cosine_similarity(query_embedding, embedding) if query_embedding else 0.0
        keyword, hits = keyword_match_score(query, row.get("content") or "", keywords)
        if semantic <= 0 and hits <= 0:
            continue
        row["score"] = semantic * 0.75 + keyword * 0.25
        row["excerpt_messages"] = _history_excerpt_messages(
            row.get("messages"), keywords
        )
        scored.append(row)
    scored.sort(key=lambda item: item["score"], reverse=True)

    grouped_results = []
    by_conversation = {}
    for row in scored:
        conv_id = int(row["conversation_id"])
        if conv_id not in by_conversation:
            result = {
                "conversation_id": conv_id,
                "title": row.get("name") or f"会话 #{conv_id}",
                "started_at": row.get("started_at"),
                "last_message_at": row.get("last_message_at"),
                "matches": [],
            }
            by_conversation[conv_id] = result
            grouped_results.append(result)
        result = by_conversation[conv_id]
        if not result["matches"]:
            result["matches"].append({
                "first_message_id": int(row["first_message_id"]),
                "last_message_id": int(row["last_message_id"]),
                "messages": row["excerpt_messages"],
            })
        if len(grouped_results) >= limit:
            break
    return grouped_results[:limit]


async def get_active_conversation() -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT id, name, max_messages, is_active, cache_anchor_fingerprint,
                   handoff_draft, handoff_summary, handoff_source_id,
                   handoff_message_ids, handoff_summary_through_message_id,
                   handoff_summary_version, handoff_summary_ready_for_flow,
                   last_anthropic_tools, last_frontend_tool_names,
                   heartbeat_count, heartbeat_last_user_message_id,
                   heartbeat_claim_token, heartbeat_claimed_at,
                   heartbeat_last_sent_at, heartbeat_last_checked_at,
                   created_at, updated_at
            FROM conversations
            WHERE is_active = TRUE
            LIMIT 1
        """)
        if not row:
            return None
        conversation = dict(row)
        if conversation.get("last_anthropic_tools") is not None:
            conversation["last_anthropic_tools"] = _json_list(conversation["last_anthropic_tools"])
        if conversation.get("last_frontend_tool_names") is not None:
            conversation["last_frontend_tool_names"] = _json_list(
                conversation["last_frontend_tool_names"]
            )
        conversation["handoff_message_ids"] = [
            int(value) for value in _json_list(conversation.get("handoff_message_ids"))
            if str(value).isdigit()
        ]
        return conversation


async def set_conversation_anthropic_tools(conversation_id: int, tools: list[dict]) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE conversations
            SET last_anthropic_tools = $2::jsonb
            WHERE id = $1
        """, conversation_id, json.dumps(tools or [], ensure_ascii=False, default=str))


async def freeze_conversation_tool_snapshot(
    conversation_id: int,
    tools: list[dict],
    frontend_tool_names: list[str],
) -> tuple[list[dict], list[str]]:
    """Persist the first tool snapshot for a conversation and return the winner."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            UPDATE conversations
            SET last_anthropic_tools = COALESCE(last_anthropic_tools, $2::jsonb),
                last_frontend_tool_names = COALESCE(last_frontend_tool_names, $3::jsonb)
            WHERE id = $1
            RETURNING last_anthropic_tools, last_frontend_tool_names
        """,
            conversation_id,
            json.dumps(tools or [], ensure_ascii=False, default=str),
            json.dumps(frontend_tool_names or [], ensure_ascii=False, default=str),
        )
    if not row:
        return tools or [], frontend_tool_names or []
    return (
        _json_list(row["last_anthropic_tools"]),
        _json_list(row["last_frontend_tool_names"]),
    )


async def _store_conversation_summary_in_flow(conn, source) -> int | None:
    """Consume a newly generated active-conversation summary into the timeline."""
    if (
        not source
        or source.get("is_active") is not True
        or source.get("handoff_summary_ready_for_flow") is not True
    ):
        return None
    summary = str(source.get("handoff_draft") or "").strip()
    if not summary:
        return None
    source_conv_id = int(source["id"])
    version = int(source.get("handoff_summary_version") or 0)
    existing_id = await conn.fetchval(
        """
        SELECT id
        FROM standing_memory_blocks
        WHERE metadata->>'kind' = 'conversation_summary'
          AND metadata->>'source_conversation_id' = $1
          AND metadata->>'handoff_summary_version' = $2
        ORDER BY id DESC
        LIMIT 1
        """,
        str(source_conv_id),
        str(version),
    )
    if existing_id is not None:
        await conn.execute(
            """
            UPDATE conversations
            SET handoff_summary_ready_for_flow = FALSE
            WHERE id = $1 AND handoff_summary_version = $2
            """,
            source_conv_id,
            version,
        )
        return int(existing_id)
    flow = await conn.fetchrow(
        """
        INSERT INTO standing_memory_blocks
            (title, content, parent_id, status, source, layer,
             inject_enabled, inject_every_n, inject_on_first_turn,
             sort_order, metadata)
        VALUES (
            $1, $2, NULL, 'active', 'model', 'recent',
            TRUE, 1, TRUE,
            COALESCE((
                SELECT MAX(sort_order) + 10
                FROM standing_memory_blocks
                WHERE status = 'active' AND layer = 'recent'
            ), 10),
            $3::jsonb
        )
        RETURNING id
        """,
        str(source.get("name") or "未命名会话"),
        summary,
        json.dumps({
            "kind": "conversation_summary",
            "source_conversation_id": source_conv_id,
            "handoff_summary_version": version,
            "through_message_id": source.get("handoff_summary_through_message_id"),
        }, ensure_ascii=False),
    )
    await _promote_flow_memory_overflow(conn)
    await conn.execute(
        """
        UPDATE conversations
        SET handoff_summary_ready_for_flow = FALSE
        WHERE id = $1 AND handoff_summary_version = $2
        """,
        source_conv_id,
        version,
    )
    return int(flow["id"])


async def set_active_conversation(
    conv_id: int,
    store_summary_in_flow: bool = True,
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock($1)", CONVERSATION_SWITCH_LOCK)
            exists = await conn.fetchval("SELECT EXISTS(SELECT 1 FROM conversations WHERE id = $1)", conv_id)
            if not exists:
                raise ValueError("conversation not found")
            source = await conn.fetchrow("""
                SELECT id, name, is_active, handoff_draft, handoff_summary_version,
                       handoff_summary_through_message_id,
                       handoff_summary_ready_for_flow
                FROM conversations
                WHERE is_active = TRUE
                FOR UPDATE
            """)
            if (
                store_summary_in_flow
                and source
                and int(source["id"]) != int(conv_id)
                and source.get("handoff_summary_ready_for_flow") is True
            ):
                await _store_conversation_summary_in_flow(conn, source)
            await conn.execute("UPDATE conversations SET is_active = FALSE")
            await conn.execute("""
                UPDATE conversations SET is_active = TRUE, updated_at = NOW()
                WHERE id = $1
            """, conv_id)


async def update_conversation(conv_id: int, name: str = None, max_messages: int = None):
    pool = await get_pool()
    async with pool.acquire() as conn:
        if name is not None:
            await conn.execute("""
                UPDATE conversations SET name = $1, updated_at = NOW()
                WHERE id = $2
            """, name, conv_id)
        if max_messages is not None:
            await conn.execute("""
                UPDATE conversations SET max_messages = $1, updated_at = NOW()
                WHERE id = $2
            """, max_messages, conv_id)


async def set_conversation_handoff_draft(conv_id: int, summary: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute("""
            UPDATE conversations
            SET handoff_draft = NULLIF($2, ''),
                handoff_summary_through_message_id = NULL,
                handoff_summary_version = handoff_summary_version + 1,
                handoff_summary_ready_for_flow = COALESCE(is_active, FALSE),
                updated_at = NOW()
            WHERE id = $1
        """, conv_id, summary.strip())
        if result == "UPDATE 0":
            raise ValueError("conversation not found")


async def save_conversation_handoff_command_summary(
    conv_id: int,
    summary: str,
    through_message_id: int,
) -> int:
    """Persist one slash-command summary snapshot and return its version."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        version = await conn.fetchval("""
            UPDATE conversations
            SET handoff_draft = NULLIF($2, ''),
                handoff_summary_through_message_id = $3,
                handoff_summary_version = handoff_summary_version + 1,
                handoff_summary_ready_for_flow = COALESCE(is_active, FALSE),
                updated_at = NOW()
            WHERE id = $1
            RETURNING handoff_summary_version
        """, conv_id, summary.strip(), int(through_message_id))
        if version is None:
            raise ValueError("conversation not found")
        return int(version)


async def set_conversation_handoff_message_ids(
    conv_id: int,
    message_ids: list[int],
) -> list[int]:
    """Freeze the exact messages selected by a gateway slash command."""
    unique_ids = list(dict.fromkeys(int(mid) for mid in message_ids))
    pool = await get_pool()
    async with pool.acquire() as conn:
        value = await conn.fetchval("""
            UPDATE conversations
            SET handoff_message_ids = $2::jsonb, updated_at = NOW()
            WHERE id = $1
            RETURNING handoff_message_ids
        """, conv_id, json.dumps(unique_ids))
        if value is None:
            raise ValueError("conversation not found")
        return [int(mid) for mid in _json_list(value)]


async def get_conversation_handoff_summary(conv_id: int) -> str:
    pool = await get_pool()
    async with pool.acquire() as conn:
        value = await conn.fetchval(
            "SELECT handoff_summary FROM conversations WHERE id = $1",
            conv_id,
        )
        return str(value or "")


async def create_conversation_from_messages(
    source_conv_id: int,
    name: str,
    message_ids: list[int],
    store_summary_in_flow: bool = True,
    require_active_source: bool = False,
    extract_memories: bool = False,
) -> dict:
    """Create and activate a handoff conversation, optionally copying messages."""
    unique_ids = list(dict.fromkeys(int(mid) for mid in message_ids))

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock($1)", CONVERSATION_SWITCH_LOCK)
            source = await conn.fetchrow("""
                SELECT id, name, max_messages, is_active, handoff_draft,
                       handoff_summary_version,
                       handoff_summary_through_message_id,
                       handoff_summary_ready_for_flow
                FROM conversations WHERE id = $1 FOR SHARE
            """, source_conv_id)
            if not source:
                raise ValueError("conversation not found")
            if require_active_source and source.get("is_active") is not True:
                raise ValueError("当前活动会话已变化，请重试")

            messages = []
            if unique_ids:
                messages = await conn.fetch("""
                    SELECT id, role, content, content_json
                    FROM context_messages
                    WHERE conversation_id = $1 AND id = ANY($2::int[]) AND hidden = FALSE
                    ORDER BY id ASC
                """, source_conv_id, unique_ids)
                if len(messages) != len(unique_ids):
                    raise ValueError("one or more messages not found")

            flow_memory_id = (
                await _store_conversation_summary_in_flow(conn, source)
                if (
                    store_summary_in_flow
                    and source.get("is_active") is True
                    and source.get("handoff_summary_ready_for_flow") is True
                ) else None
            )

            target = await conn.fetchrow("""
                INSERT INTO conversations
                    (name, max_messages, handoff_source_id)
                VALUES ($1, $2, $3)
                RETURNING id, name, max_messages, handoff_summary,
                          handoff_source_id, created_at, updated_at
            """, name, source["max_messages"], source_conv_id)

            for message in messages:
                content_json = message["content_json"]
                if content_json is not None and not isinstance(content_json, str):
                    content_json = json.dumps(content_json, ensure_ascii=False)
                await conn.execute("""
                    INSERT INTO context_messages
                        (conversation_id, role, content, content_json, kind, hidden, affects_activity)
                    VALUES ($1, $2, $3, $4::jsonb, 'handoff_copy', FALSE, FALSE)
                """, target["id"], message["role"], message["content"], content_json)

            await conn.execute("UPDATE conversations SET is_active = FALSE")
            await conn.execute("""
                UPDATE conversations SET is_active = TRUE, updated_at = NOW()
                WHERE id = $1
            """, target["id"])
            if extract_memories:
                from memory_extraction import enqueue_extraction
                await enqueue_extraction(conn, source_conv_id, int(target['id']))
            result = dict(target)
            result["flow_memory_id"] = flow_memory_id
            return result


async def delete_conversation(conv_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM conversations WHERE id = $1", conv_id)

        # Deleting the active conversation deliberately leaves no active
        # conversation. Only an explicit activate request may choose another one.


async def save_context_message(
    conversation_id: int,
    role: str,
    content: str,
    content_json: list = None,  # 新增：结构化内容
    kind: str = "chat",
    hidden: bool = False,
    affects_activity: bool = True,
) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.fetchval(
                "SELECT id FROM conversations WHERE id = $1 FOR UPDATE",
                conversation_id,
            )
            row = await conn.fetchrow("""
                INSERT INTO context_messages
                    (conversation_id, role, content, content_json, kind, hidden, affects_activity)
                VALUES ($1, $2, $3, $4::jsonb, $5, $6, $7)
                RETURNING id, role, content, content_json, kind, hidden,
                          affects_activity, created_at
            """, conversation_id, role, content,
                 json.dumps(content_json) if content_json else None,
                 kind, hidden, affects_activity)
            if role == "user" and affects_activity:
                await conn.execute("""
                    UPDATE conversations
                    SET updated_at = NOW(), heartbeat_count = 0,
                        heartbeat_last_user_message_id = $2
                    WHERE id = $1
                """, conversation_id, row["id"])
            else:
                await conn.execute("""
                    UPDATE conversations SET updated_at = NOW()
                    WHERE id = $1
                """, conversation_id)
            return dict(row)


async def save_context_messages_batch(
    conversation_id: int,
    messages: list[dict],
) -> list[dict]:
    """Persist one completed tool transcript without splitting its pairs."""
    if not messages:
        return []

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.fetchval(
                "SELECT id FROM conversations WHERE id = $1 FOR UPDATE",
                conversation_id,
            )
            saved = []
            for message in messages:
                content_json = message.get("content_json")
                row = await conn.fetchrow("""
                    INSERT INTO context_messages
                        (conversation_id, role, content, content_json, kind, hidden, affects_activity)
                    VALUES ($1, $2, $3, $4::jsonb, $5, $6, $7)
                    RETURNING id, role, content, content_json, kind, hidden,
                              affects_activity, created_at
                """, conversation_id, message["role"], message.get("content", ""),
                     json.dumps(content_json) if content_json is not None else None,
                     message.get("kind", "tool_event"),
                     bool(message.get("hidden", False)),
                     bool(message.get("affects_activity", False)))
                saved.append(dict(row))

            await conn.execute("""
                UPDATE conversations SET updated_at = NOW()
                WHERE id = $1
            """, conversation_id)
            return saved


async def get_context_messages(conversation_id: int, limit: int = None) -> list:
    pool = await get_pool()
    async with pool.acquire() as conn:
        if limit:
            rows = await conn.fetch("""
                SELECT * FROM (
                    SELECT id, conversation_id, role, content, content_json,
                           kind, hidden, affects_activity, created_at
                    FROM context_messages
                    WHERE conversation_id = $1
                    ORDER BY id DESC
                    LIMIT $2
                ) sub
                ORDER BY id ASC
            """, conversation_id, limit)
        else:
            rows = await conn.fetch("""
                SELECT id, conversation_id, role, content, content_json,
                       kind, hidden, affects_activity, created_at
                FROM context_messages
                WHERE conversation_id = $1
                ORDER BY id ASC
            """, conversation_id)
        return [dict(r) for r in rows]


async def get_context_message_page(
    conversation_id: int,
    limit: int,
    before_id: int | None = None,
) -> list:
    """Fetch a small management-page slice without returning large JSONB payloads."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        if before_id is None:
            rows = await conn.fetch("""
                SELECT * FROM (
                    SELECT id, conversation_id, role, content,
                           NULL::JSONB AS content_json,
                           (content_json IS NOT NULL) AS has_content_json,
                           kind, hidden, affects_activity, created_at
                    FROM context_messages
                    WHERE conversation_id = $1
                      AND hidden = FALSE
                      AND role IN ('user', 'assistant')
                      AND (role = 'user' OR content_json IS NULL)
                    ORDER BY id DESC
                    LIMIT $2
                ) page
                ORDER BY id ASC
            """, int(conversation_id), int(limit))
        else:
            rows = await conn.fetch("""
                SELECT * FROM (
                    SELECT id, conversation_id, role, content,
                           NULL::JSONB AS content_json,
                           (content_json IS NOT NULL) AS has_content_json,
                           kind, hidden, affects_activity, created_at
                    FROM context_messages
                    WHERE conversation_id = $1 AND id < $2
                      AND hidden = FALSE
                      AND role IN ('user', 'assistant')
                      AND (role = 'user' OR content_json IS NULL)
                    ORDER BY id DESC
                    LIMIT $3
                ) page
                ORDER BY id ASC
            """, int(conversation_id), int(before_id), int(limit))
        return [dict(row) for row in rows]


async def set_conversation_cache_anchor(conversation_id: int, fingerprint: str | None):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE conversations SET cache_anchor_fingerprint = $2
            WHERE id = $1
        """, conversation_id, fingerprint or None)


async def try_claim_heartbeat(
    conversation_id: int,
    expected_last_user_id: int,
    expected_last_message_id: int,
    stale_seconds: int = 600,
) -> str | None:
    token = uuid.uuid4().hex
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            UPDATE conversations c
            SET heartbeat_claim_token = $4, heartbeat_claimed_at = NOW()
            WHERE c.id = $1
              AND c.is_active = TRUE
              AND (
                    c.heartbeat_claim_token IS NULL
                    OR c.heartbeat_claimed_at < NOW() - ($5::double precision * INTERVAL '1 second')
                  )
              AND COALESCE((
                    SELECT MAX(m.id) FROM context_messages m
                    WHERE m.conversation_id = c.id
                      AND m.role = 'user' AND m.affects_activity = TRUE
                  ), 0) = $2
              AND COALESCE((
                    SELECT MAX(m.id) FROM context_messages m
                    WHERE m.conversation_id = c.id
                  ), 0) = $3
            RETURNING c.id
        """, conversation_id, expected_last_user_id, expected_last_message_id,
             token, stale_seconds)
        return token if row else None


async def validate_heartbeat_claim(
    conversation_id: int,
    claim_token: str,
    expected_last_user_id: int,
    expected_last_message_id: int,
) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return bool(await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM conversations c
                WHERE c.id = $1 AND c.is_active = TRUE
                  AND c.heartbeat_claim_token = $2
                  AND COALESCE((
                        SELECT MAX(m.id) FROM context_messages m
                        WHERE m.conversation_id = c.id
                          AND m.role = 'user' AND m.affects_activity = TRUE
                      ), 0) = $3
                  AND COALESCE((
                        SELECT MAX(m.id) FROM context_messages m
                        WHERE m.conversation_id = c.id
                      ), 0) = $4
            )
        """, conversation_id, claim_token,
             expected_last_user_id, expected_last_message_id))


async def finish_heartbeat(
    conversation_id: int,
    claim_token: str,
    expected_last_user_id: int,
    expected_last_message_id: int,
    trigger_text: str,
    assistant_text: str,
) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.fetchval(
                "SELECT id FROM conversations WHERE id = $1 FOR UPDATE",
                conversation_id,
            )
            valid = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT 1 FROM conversations c
                    WHERE c.id = $1 AND c.is_active = TRUE
                      AND c.heartbeat_claim_token = $2
                      AND COALESCE((
                            SELECT MAX(m.id) FROM context_messages m
                            WHERE m.conversation_id = c.id
                              AND m.role = 'user' AND m.affects_activity = TRUE
                          ), 0) = $3
                      AND COALESCE((
                            SELECT MAX(m.id) FROM context_messages m
                            WHERE m.conversation_id = c.id
                          ), 0) = $4
                )
            """, conversation_id, claim_token,
                 expected_last_user_id, expected_last_message_id)
            if not valid:
                return False
            await conn.execute("""
                INSERT INTO context_messages
                    (conversation_id, role, content, kind, hidden, affects_activity)
                VALUES
                    ($1, 'user', $2, 'heartbeat_trigger', TRUE, FALSE),
                    ($1, 'assistant', $3, 'proactive', FALSE, FALSE)
            """, conversation_id, trigger_text, assistant_text)
            await conn.execute("""
                UPDATE conversations
                SET heartbeat_count = heartbeat_count + 1,
                    heartbeat_last_sent_at = NOW(), heartbeat_last_checked_at = NOW(),
                    updated_at = NOW(),
                    heartbeat_claim_token = NULL, heartbeat_claimed_at = NULL
                WHERE id = $1 AND heartbeat_claim_token = $2
            """, conversation_id, claim_token)
            return True


async def finish_heartbeat_silently(
    conversation_id: int,
    claim_token: str,
    expected_last_user_id: int,
    expected_last_message_id: int,
    materialize_activities: bool = False,
) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            valid = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT 1 FROM conversations c
                    WHERE c.id = $1 AND c.is_active = TRUE
                      AND c.heartbeat_claim_token = $2
                      AND COALESCE((
                            SELECT MAX(m.id) FROM context_messages m
                            WHERE m.conversation_id = c.id
                              AND m.role = 'user' AND m.affects_activity = TRUE
                          ), 0) = $3
                      AND COALESCE((
                            SELECT MAX(m.id) FROM context_messages m
                            WHERE m.conversation_id = c.id
                          ), 0) = $4
                )
            """, conversation_id, claim_token,
                 expected_last_user_id, expected_last_message_id)
            if not valid:
                return False
            if materialize_activities:
                await _materialize_heartbeat_activities_with_conn(conn, conversation_id)
            await conn.execute("""
                UPDATE conversations
                SET heartbeat_last_checked_at = NOW(), updated_at = NOW(),
                    heartbeat_claim_token = NULL, heartbeat_claimed_at = NULL
                WHERE id = $1 AND heartbeat_claim_token = $2
            """, conversation_id, claim_token)
            return True


async def release_heartbeat_claim(conversation_id: int, claim_token: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE conversations
            SET heartbeat_claim_token = NULL, heartbeat_claimed_at = NULL
            WHERE id = $1 AND heartbeat_claim_token = $2
        """, conversation_id, claim_token)


async def clear_context(conversation_id: int) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute("""
            DELETE FROM context_messages WHERE conversation_id = $1
        """, conversation_id)
        await conn.execute("""
            UPDATE conversations
            SET cache_anchor_fingerprint = NULL, heartbeat_count = 0,
                heartbeat_last_user_message_id = NULL,
                heartbeat_claim_token = NULL, heartbeat_claimed_at = NULL,
                heartbeat_last_sent_at = NULL, heartbeat_last_checked_at = NULL
            WHERE id = $1
        """, conversation_id)
        try:
            return int(result.split()[-1])
        except Exception:
            return 0


async def delete_context_message(msg_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        conversation_id = await conn.fetchval(
            "DELETE FROM context_messages WHERE id = $1 RETURNING conversation_id", msg_id
        )
        if conversation_id:
            await conn.execute("""
                UPDATE conversations SET cache_anchor_fingerprint = NULL
                WHERE id = $1
            """, conversation_id)

async def update_context_message(msg_id: int, content: str):
    """编辑单条消息内容"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        conversation_id = await conn.fetchval("""
            UPDATE context_messages SET content = $1
            WHERE id = $2
            RETURNING conversation_id
        """, content, msg_id)
        if conversation_id:
            await conn.execute("""
                UPDATE conversations SET cache_anchor_fingerprint = NULL
                WHERE id = $1
            """, conversation_id)

async def get_context_stats(conversation_id: int) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT
                COUNT(*)                                    AS total_messages,
                COUNT(*) FILTER (WHERE role = 'user')       AS user_messages,
                COUNT(*) FILTER (WHERE role = 'assistant')  AS assistant_messages,
                MIN(created_at)                             AS first_message_at,
                MAX(created_at)                             AS last_message_at
            FROM context_messages
            WHERE conversation_id = $1
              AND hidden = FALSE
              AND role IN ('user', 'assistant')
              AND (role = 'user' OR content_json IS NULL)
        """, conversation_id)
        return dict(row)

# ============================================================
# 记忆快照（回滚用）
# ============================================================

async def save_snapshot(reason: str = "") -> int:
    """保存当前记忆库完整快照，返回 snapshot_id"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, content, importance, source_session, type,
                   tags, metadata, pinned, created_at
            FROM memories ORDER BY id
        """)
        snapshot = []
        for r in rows:
            item = dict(r)
            if item.get("created_at"):
                item["created_at"] = item["created_at"].isoformat()
            if item.get("metadata") and not isinstance(item["metadata"], str):
                item["metadata"] = json.dumps(item["metadata"], ensure_ascii=False)
            snapshot.append(item)

        snap_id = await conn.fetchval("""
            INSERT INTO memory_snapshots (reason, memory_count, snapshot)
            VALUES ($1, $2, $3::jsonb)
            RETURNING id
        """, reason, len(snapshot), json.dumps(snapshot, ensure_ascii=False))

    print(f"[snapshot] 💾 已保存快照 id={snap_id}，共 {len(snapshot)} 条记忆")
    return snap_id

async def restore_snapshot(snapshot_id: int) -> int:
    """从快照恢复记忆库（危险操作，会清空当前记忆）"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT snapshot FROM memory_snapshots WHERE id = $1", snapshot_id
        )
        if not row:
            raise ValueError(f"snapshot {snapshot_id} not found")

        snapshot = json.loads(row["snapshot"]) if isinstance(row["snapshot"], str) else row["snapshot"]

        # 清空
        await conn.execute("DELETE FROM memory_embeddings")
        await conn.execute("DELETE FROM memories")

        # 恢复
        restored = 0
        for m in snapshot:
            await conn.execute("""
                INSERT INTO memories (id, content, importance, source_session,
                    type, tags, metadata, pinned, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9)
            """,
                m["id"], m["content"], m.get("importance", 5),
                m.get("source_session", ""),
                m.get("type", "factual"),
                m.get("tags") or [],
                m.get("metadata"),
                m.get("pinned", False),
                m.get("created_at"),
            )
            restored += 1

        # 重置序列
        await conn.execute("""
            SELECT setval('memories_id_seq', COALESCE((SELECT MAX(id) FROM memories), 0))
        """)

    print(f"[snapshot] ♻️ 已从快照 {snapshot_id} 恢复 {restored} 条记忆")
    return restored

async def get_all_snapshots(limit: int = 20) -> list:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, created_at, reason, memory_count
            FROM memory_snapshots
            ORDER BY created_at DESC
            LIMIT $1
        """, limit)
        return [dict(r) for r in rows]

async def get_pinned_memories() -> list:
    """获取所有 pinned 记忆"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, content, importance, type, tags, created_at
            FROM memories
            WHERE pinned = TRUE
            ORDER BY importance DESC, id ASC
        """)
        return [dict(r) for r in rows]

async def update_memory_pin(memory_id: int, pinned: bool):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE memories SET pinned = $1 WHERE id = $2",
            pinned, memory_id,
        )
# ============================================================
# Prompt 段落表
# ============================================================

async def init_prompt_table():
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS prompt_sections (
                section_key TEXT PRIMARY KEY,
                mode TEXT NOT NULL DEFAULT 'locked',
                priority INTEGER DEFAULT 50,
                content TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT NOW(),
                updated_by TEXT DEFAULT 'seed'
            )
        """)
    print("[db] prompt_sections table ready")
