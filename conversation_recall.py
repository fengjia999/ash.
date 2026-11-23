"""Legacy local retrieval and shared original-sentence vector index maintenance."""
import asyncio
import hashlib
import json
import math
import os
import re
from itertools import islice
from datetime import datetime, timezone
from html import escape

import database as db
from emotion_recall import detect_emotion
from diary_author import diary_author_fields

INDEX_VERSION = 'original-sentences-v1'
_index_lock = asyncio.Lock()
_status = {'messages': 0, 'sentences': 0, 'indexed': 0, 'pending': 0}
_cursors = {}
_page_cursors = {}


def source_text(row):
    if row.get('hidden') or row.get('kind', 'chat') != 'chat' or row.get('role') not in ('user', 'assistant'):
        return ''
    content = row.get('content') or ''
    blocks = row.get('content_json') if row['role'] == 'assistant' else None
    if isinstance(blocks, str):
        try:
            blocks = json.loads(blocks)
        except ValueError:
            blocks = None
    if isinstance(blocks, list):
        content = '\n'.join(b.get('text', '') for b in blocks
                            if isinstance(b, dict) and b.get('type') == 'text')
    return content if isinstance(content, str) and content.strip() and content not in ('[tool_calls]', '[tool_result]') else ''


def source_hash(row):
    return hashlib.sha256((row['role'] + '\0' + source_text(row)).encode()).hexdigest()


def config_hash(settings):
    return hashlib.sha256((INDEX_VERSION + db._long_term_embedding_config_hash(settings)).encode()).hexdigest()


def sentence_spans(text):
    start = 0
    for match in re.finditer(r'[。！？!?]+[”’"\']*|\n+|\.(?=\s|$)', text):
        end = match.end()
        if text[start:end].strip():
            yield start, end
        start = end
    if text[start:].strip():
        yield start, len(text)


def profile(row, include_keywords=True):
    text = source_text(row)
    # A modest, inspectable heuristic, not a model-assigned importance judgment.
    important = row['role'] == 'user' and bool(re.search(
        r'我(?:不喜欢|喜欢|不能|需要|决定|计划|希望|习惯)|请记住|不要忘记|过敏|约定', text))
    return {'importance': .7 if important else .5,
            'importance_method': 'explicit_words',
            'emotion': detect_emotion(text) if row['role'] == 'user' else None,
            'keywords': db.extract_search_keywords(text)[:20] if include_keywords else []}


def dialogue_turns(rows):
    """A user message and following assistant messages form one turn."""
    turns, current = [], None
    for row in rows:
        text = source_text(row)
        if not text:
            # Omitted turns must not attach their assistant replies to an older user.
            current = None
            continue
        if row['role'] == 'user' or current is None or current['conversation_id'] != row['conversation_id']:
            current = {'conversation_id': row['conversation_id'], 'turn_id': row['id'], 'messages': []}
            turns.append(current)
        current['messages'].append(row)
    return turns


async def init_tables():
    pool = await db.get_pool()
    async with pool.acquire() as conn:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS conversation_recall_index (
                message_id INTEGER NOT NULL REFERENCES context_messages(id) ON DELETE CASCADE,
                start_offset INTEGER NOT NULL,
                end_offset INTEGER NOT NULL,
                config_hash TEXT NOT NULL,
                source_hash TEXT NOT NULL,
                profile JSONB NOT NULL,
                embedding JSONB,
                PRIMARY KEY(message_id, start_offset, end_offset, config_hash)
            )
        ''')


async def source_rows(before_id=None, limit=None):
    pool = await db.get_pool()
    async with pool.acquire() as conn:
        if limit is not None:
            rows = await conn.fetch("""
                SELECT id, conversation_id, role, content, content_json, created_at, kind, hidden
                FROM context_messages
                WHERE role IN ('user', 'assistant') AND ($1::integer IS NULL OR id < $1)
                ORDER BY id DESC LIMIT $2
            """, before_id, limit)
        else:
            rows = await conn.fetch("""
                SELECT id, conversation_id, role, content, content_json, created_at, kind, hidden
                FROM context_messages WHERE role IN ('user', 'assistant')
                ORDER BY conversation_id, id
            """)
    return [dict(row) for row in rows]


async def refresh_index(settings, batch_size=40):
    """Page through originals without loading the entire archive or its vectors."""
    if _index_lock.locked():
        return dict(_status)
    async with _index_lock:
        cfg = config_hash(settings)
        page = await source_rows(before_id=_page_cursors.get(cfg), limit=40)
        rows = [row for row in page if source_text(row)]
        pool = await db.get_pool()
        async with pool.acquire() as conn:
            existing_rows = await conn.fetch('''
                SELECT message_id, start_offset, end_offset, source_hash,
                       (embedding IS NOT NULL AND embedding != '[]'::jsonb) AS has_embedding
                FROM conversation_recall_index WHERE config_hash = $1
                    AND message_id = ANY($2::integer[])
            ''', cfg, [row['id'] for row in rows])
        existing = {(r['message_id'], r['start_offset'], r['end_offset']): dict(r) for r in existing_rows}
        pending = []
        for row in rows:
            await asyncio.sleep(0)  # let health checks/chat run between messages
            digest, info, text = source_hash(row), profile(row), source_text(row)
            for start, end in sentence_spans(text):
                old = existing.get((row['id'], start, end))
                if old and old['source_hash'] == digest and old.get('has_embedding', bool(db._safe_load_embedding(old.get('embedding')))):
                    continue
                item = (row['id'], start, end, cfg, digest, json.dumps(info, ensure_ascii=False))
                pending.append((item, text[start:end]))
        embedded = 0
        # Recent originals get indexed first; older messages are processed next.
        ordered = sorted(pending, key=lambda value: value[0][0], reverse=True)
        cursor = _cursors.get(cfg, 0) % max(1, len(ordered))
        batch = (ordered[cursor:] + ordered[:cursor])[:batch_size]
        _cursors[cfg] = cursor + len(batch)
        # Preserve the remote fix: only persist the selected legacy index batch.
        if batch:
            async with pool.acquire() as conn:
                await conn.executemany('''
                    INSERT INTO conversation_recall_index
                        (message_id, start_offset, end_offset, config_hash, source_hash, profile)
                    VALUES ($1, $2, $3, $4, $5, $6::jsonb)
                    ON CONFLICT (message_id, start_offset, end_offset, config_hash)
                    DO UPDATE SET source_hash = EXCLUDED.source_hash, profile = EXCLUDED.profile,
                        embedding = CASE WHEN conversation_recall_index.source_hash = EXCLUDED.source_hash
                                         THEN conversation_recall_index.embedding ELSE NULL END
                ''', [item for item, _ in batch])
        if batch and settings.get('embedding_model') and settings.get('embedding_api_url'):
            for offset in range(0, len(batch), 20):
                subset = batch[offset:offset + 20]
                vectors = await db._embed_conversation_chunks(
                    [text[:db.EMBEDDING_MAX_INPUT_CHARS] for _, text in subset], settings,
                    task='retrieval.passage')
                async with pool.acquire() as conn:
                    for (item, _), vector in zip(subset, vectors):
                        if not vector or not all(math.isfinite(v) for v in vector):
                            continue
                        await conn.execute('''
                            UPDATE conversation_recall_index SET embedding = $6::jsonb
                            WHERE message_id = $1 AND start_offset = $2 AND end_offset = $3
                              AND config_hash = $4 AND source_hash = $5
                        ''', *item[:5], json.dumps(vector))
                        embedded += 1
        total = sum(1 for row in rows for _ in sentence_spans(source_text(row)))
        _status.update(messages=len(rows), sentences=total,
                       indexed=total - len(pending) + embedded, pending=len(pending) - embedded)
        _page_cursors[cfg] = min(row['id'] for row in page) if len(page) == 40 else None
        if pending:
            print('[history-recall] index ' + json.dumps({
                **_status, 'scope': 'page', 'next_before_id': _page_cursors[cfg]}), flush=True)
        return dict(_status)


async def index_worker():
    # Permit a deployment to pause indexing without disabling existing recall/chat.
    if os.getenv('HISTORY_RECALL_INDEX_ENABLED', 'true').lower() == 'false':
        print('[history-recall] index paused by HISTORY_RECALL_INDEX_ENABLED', flush=True)
        return
    await asyncio.sleep(10)  # allow the web server to finish becoming ready first
    failures = 0
    while True:
        phase = 'settings'
        delay = 10
        try:
            settings = await db.get_conversation_model_settings()
            from conversation_search import embedding_configured
            if embedding_configured(settings):
                phase = 'index_page'
                await refresh_index(settings)
            failures = 0
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            failures += 1
            delay = min(300, 30 * 2 ** min(failures - 1, 4))
            # Avoid logging the exception text, which can contain database credentials.
            print('[history-recall] index error ' + json.dumps({
                'error_type': type(exc).__name__, 'phase': phase,
                'errno': getattr(exc, 'errno', None), 'consecutive_failures': failures,
                'retry_in_seconds': delay,
            }), flush=True)
        await asyncio.sleep(delay)


# Hard bounds keep recall independent of archive size. Older rows remain stored.
CANDIDATE_WINDOW = 2000
CANDIDATE_LIMIT = 120
RECALL_TIMEOUT = 1.5
DEFAULT_SEARCH = {'keyword': .35, 'text': .35, 'importance': .15, 'recency': .15,
                  'min_score': .25}


def search_options(settings):
    saved = db._json_object(settings.get('history_recall_settings'))
    result = dict(DEFAULT_SEARCH)
    for key in result:
        value = saved.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and 0 <= value <= 1:
            result[key] = float(value)
    return result


def text_similarity(query, text):
    # Character bigram Dice overlap works for Chinese and Latin text locally.
    def grams(value):
        value = ''.join(c for c in value.casefold() if c.isalnum())
        return {value[i:i + 2] for i in range(max(0, len(value) - 1))}
    a, b = grams(query), grams(text)
    return 2 * len(a & b) / (len(a) + len(b)) if a and b else 0.0


async def candidate_rows(query):
    keywords = sorted(db.extract_search_keywords(query))[:16]
    # A small bigram route also admits local text matches without exact tokens.
    compact = ''.join(c for c in query.casefold() if c.isalnum())
    keywords += list(dict.fromkeys(compact[i:i + 2] for i in range(len(compact) - 1)))[:16]
    pool = await db.get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            WITH recent_messages AS MATERIALIZED (
                SELECT id, conversation_id, role, content, content_json, created_at, kind, hidden
                FROM context_messages ORDER BY id DESC LIMIT $1
            ), candidates AS (
                SELECT * FROM recent_messages
                WHERE hidden = FALSE AND kind = 'chat' AND role IN ('user', 'assistant')
                  AND length(content) <= 16000
                  AND (strpos(lower(content), lower($2)) > 0 OR EXISTS (
                      SELECT 1 FROM unnest($3::text[]) k WHERE strpos(lower(content), lower(k)) > 0))
                ORDER BY id DESC LIMIT $4
            ), ids AS (
                SELECT id FROM candidates
                UNION
                SELECT parent.id FROM candidates c
                CROSS JOIN LATERAL (
                    SELECT w.id FROM recent_messages w
                    WHERE w.conversation_id = c.conversation_id AND w.id < c.id AND w.role = 'user'
                    ORDER BY w.id DESC LIMIT 1
                ) parent WHERE c.role = 'assistant'
            )
            SELECT w.* FROM recent_messages w JOIN ids USING (id) ORDER BY conversation_id, id
        """, CANDIDATE_WINDOW, query, keywords, CANDIDATE_LIMIT)
    return [dict(r) for r in rows]


def sentence_scores(row, info, query, similarity, current_conversation_id, query_hint=None, settings=None, keyword_score=None):
    created = row.get('created_at')
    if isinstance(created, str):
        try:
            created = datetime.fromisoformat(created.replace('Z', '+00:00'))
        except ValueError:
            created = None
    recency = 0.0
    if isinstance(created, datetime):
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age = max(0, (datetime.now(timezone.utc) - created).total_seconds() / 86400)
        recency = 2 ** (-age / 14)
    keyword = keyword_score
    if keyword is None:
        keyword, _ = db.keyword_match_score(query, info.get('text', source_text(row)))
    weights = search_options(settings or {})
    importance = info.get('importance', .5)
    base = (weights['keyword'] * keyword + weights['text'] * similarity
            + weights['importance'] * importance + weights['recency'] * recency)
    # Additive recency alone cannot overcome an old exact match. Age also
    # attenuates the combined score, while keeping old relevant evidence usable.
    age_penalty = .65 * min(1, weights['recency'] / .15)
    total = base * (1 - age_penalty + age_penalty * recency)
    return {'text_similarity': similarity, 'keyword_score': keyword,
            'recency_score': recency, 'importance': importance,
            'importance_method': 'explicit_words', 'base_total': base, 'total': total}


async def search(query, settings, current_conversation_id=None, visible_messages=(), limit=50, context_query=None):
    try:
        async with asyncio.timeout(RECALL_TIMEOUT):
            return await _search(query, settings, current_conversation_id, visible_messages, limit, context_query)
    except Exception as exc:
        print(f'[history-recall] recall error: {type(exc).__name__}', flush=True)
        return []


async def _search(query, settings, current_conversation_id, visible_messages, limit, context_query):
    query = str(query or '').strip()[-1200:]
    if not query:
        return []
    queries = [query]
    if context_query and context_query != query:
        queries.append(str(context_query)[-1200:])
    keywords_by_query = {q: db.extract_search_keywords(q) for q in queries}
    minimum = search_options(settings)['min_score']
    rows = await candidate_rows(' '.join(queries))
    visible = {(m['role'], m['content']) for m in visible_messages if m.get('role') and isinstance(m.get('content'), str)}
    visible.add(('user', query))
    results = []
    for turn in dialogue_turns(rows):
        await asyncio.sleep(0)  # allow deadlines and concurrent chat requests to run
        if turn['conversation_id'] == current_conversation_id and any(
            m['role'] == 'user' and (m['role'], source_text(m)) in visible for m in turn['messages']
        ):
            continue
        # A bounded candidate window may omit the original user: skip orphan replies.
        if not any(m['role'] == 'user' for m in turn['messages']):
            continue
        matches = []
        for row in turn['messages']:
            text = source_text(row)
            if len(text) > 16000:
                continue
            info = profile(row, include_keywords=False)
            for start, end in islice(sentence_spans(text), 128):
                excerpt = text[start:end]
                scored = []
                for q in queries:
                    similarity = text_similarity(q, excerpt)
                    keyword, _ = db.keyword_match_score(q, excerpt, keywords_by_query[q])
                    if keyword <= 0 and similarity < .12:
                        continue
                    scored.append(sentence_scores(row, {**info, 'text': excerpt}, q, similarity,
                                                  current_conversation_id, settings=settings, keyword_score=keyword))
                if not scored:
                    continue
                parts = max(scored, key=lambda x: x['total'])
                if parts['total'] < minimum:
                    continue
                matches.append({'message_id': row['id'], 'role': row['role'], 'start': start, 'end': end,
                                'text': excerpt, 'created_at': str(row.get('created_at') or ''),
                                'score_components': parts})
        if matches:
            parts = max(matches, key=lambda m: m['score_components']['total'])['score_components']
            if not any(m['role'] == 'user' for m in matches):
                row = turn['messages'][0]
                text = source_text(row)
                matches.append({'message_id': row['id'], 'role': 'user', 'start': 0, 'end': len(text),
                                'text': text, 'context': True, 'created_at': str(row.get('created_at') or ''),
                                'score_components': dict(parts)})
            results.append({**turn, 'matches': matches, 'score': parts['total'], 'score_components': dict(parts)})
    results.sort(key=lambda t: (t['score'], t['turn_id']), reverse=True)
    return results[:max(0, min(limit, 50))]


async def diary_metadata(query):
    """Read only existing diary metadata, never content or summary."""
    pool = await db.get_pool()
    keywords = sorted(db.extract_search_keywords(str(query)[-1200:]))[:16]
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            WITH recent AS MATERIALIZED (
                SELECT id, memory_date, title, keywords,
                       metadata->>'author_role' AS author_role FROM long_term_memories
                WHERE enabled = TRUE AND metadata->>'entry_kind' IS DISTINCT FROM 'fragment'
                  AND metadata->>'source' IS DISTINCT FROM 'raw_user_quotes'
                  AND COALESCE(metadata->>'forgetting_pending', 'false') <> 'true'
                ORDER BY id DESC LIMIT 256
            )
            SELECT id, memory_date, title, keywords, author_role FROM recent
            WHERE EXISTS (SELECT 1 FROM unnest($1::text[]) k
                WHERE strpos(lower(title || ' ' || keywords::text), lower(k)) > 0)
            ORDER BY memory_date DESC, id DESC LIMIT 8
        """, keywords)
    identity = await db.get_identity_presets() if rows else {}
    return [{**dict(row), **diary_author_fields(dict(row), identity)} for row in rows]


def render_turn(turn, matches):
    lines = [f'<past_turn conversation_id="{int(turn["conversation_id"])}" turn_id="{int(turn["turn_id"])}">']
    for match in sorted(matches, key=lambda m: (m['message_id'], m['start'])):
        lines.append(f'<message id="{int(match["message_id"])}" role="{match["role"]}" date="{escape(match["created_at"], quote=True)}" excerpt="true">{escape(match["text"])}</message>')
    return '\n'.join([*lines, '</past_turn>'])


def pack(turns, budget, diaries=()):
    opening = '<past_conversations source="memory_gateway">\n'
    closing = '\n</past_conversations>'
    blocks, selected, skipped = [], [], []
    used_sources = set()
    for turn in turns:
        chosen = []
        # User evidence has first claim on the budget. Each sentence is intact.
        for match in sorted(turn['matches'], key=lambda m: (m['role'] == 'user', m['score_components']['total']), reverse=True):
            if match['role'] == 'assistant' and any(m['role'] == 'user' for m in turn['messages']) and not any(m['role'] == 'user' for m in chosen):
                continue
            key = (match['message_id'], match['start'], match['end'])
            if key in used_sources:
                continue
            trial = render_turn(turn, chosen + [match])
            if len(opening + '\n'.join(blocks + [trial]) + closing) <= budget:
                chosen.append(match)
        if not chosen:
            skipped.append(turn['turn_id'])
            continue
        blocks.append(render_turn(turn, chosen))
        used_sources.update((m['message_id'], m['start'], m['end']) for m in chosen)
        selected.append({'conversation_id': turn['conversation_id'], 'turn_id': turn['turn_id'],
                         'message_ids': sorted({m['message_id'] for m in chosen}),
                         'sentence_count': len(chosen), 'score_components': turn['score_components'],
                         'sentences': [{'message_id': m['message_id'], 'start': m['start'],
                                        'end': m['end'], 'context': bool(m.get('context')),
                                        'score_components': m['score_components']} for m in chosen]})
    for diary in diaries:
        metadata = {**diary_author_fields(diary),
                    **{key: str(diary.get(key) or '') for key in ('id', 'memory_date', 'title')}}
        if diary.get('author_name'):
            metadata['author_name'] = diary['author_name']
        metadata['keywords'] = db._json_list(diary.get('keywords'))
        entry = '<diary_metadata>' + escape(json.dumps(metadata, ensure_ascii=False)) + '</diary_metadata>'
        if len(opening + '\n'.join(blocks + [entry]) + closing) <= budget:
            blocks.append(entry)
    block = opening + '\n'.join(blocks) + closing if blocks else ''
    return block, selected, skipped
