"""Paged original-text vector search, shared by tools and hybrid recall."""
import asyncio
import math

import database as db
from conversation_recall import config_hash, dialogue_turns, sentence_spans, source_hash, source_text

VECTOR_PAGE_SIZE = 256
SEARCH_TIMEOUT = 30


def embedding_configured(settings):
    return all(str(settings.get(key) or '').strip()
               for key in ('embedding_api_url', 'embedding_model', 'embedding_api_key'))


async def search(query, settings, current_conversation_id=None, limit=5, *, recency_weight=.1):
    query = str(query or '').strip()[:1000]
    if not query:
        return []
    if not embedding_configured(settings):
        # The tool remains usable without embedding credentials. The hybrid
        # module calls this vector arm only when credentials are configured.
        from memory_retrieval import retrieve
        turns, _ = await retrieve(query, settings, current_conversation_id=current_conversation_id,
                                  override={'keyword': 1., 'semantic': 0.}, limit=limit)
        return turns
    async with asyncio.timeout(SEARCH_TIMEOUT):
        vectors = await asyncio.wait_for(
            db._embed_conversation_chunks([query], settings, task='retrieval.query'),
            timeout=db.LONG_TERM_RECALL_EMBEDDING_TIMEOUT)
        vector = vectors[0] if vectors else None
        if not vector or not all(math.isfinite(v) for v in vector):
            raise RuntimeError('query embedding unavailable')
        return await _search_index(vector, settings, current_conversation_id, max(1, min(limit, 8)), query, recency_weight)


async def _search_index(vector, settings, current_conversation_id, limit, query, recency_weight=.1):
    # Page vectors, retain only the best sentence per shortlisted message, then
    # fetch those originals and their user context. No whole-archive text load.
    pool = await db.get_pool()
    cfg = config_hash(settings)
    last_key = (-1, -1, -1)
    candidates = {}
    capacity = limit * 10
    while True:
        async with pool.acquire() as conn:
            page = await conn.fetch('''
                SELECT i.message_id, i.start_offset, i.end_offset, i.source_hash, i.embedding,
                       m.created_at
                FROM conversation_recall_index i
                JOIN context_messages m ON m.id = i.message_id
                WHERE i.config_hash = $1 AND i.embedding IS NOT NULL
                  AND (i.message_id, i.start_offset, i.end_offset) > ($2, $3, $4)
                  AND m.hidden = FALSE AND m.kind = 'chat' AND m.role IN ('user', 'assistant')
                ORDER BY i.message_id, i.start_offset, i.end_offset LIMIT $5
            ''', cfg, *last_key, VECTOR_PAGE_SIZE)
        if not page:
            break
        for entry in page:
            embedding = db._safe_load_embedding(entry['embedding'])
            similarity = db.cosine_similarity(vector, embedding)
            if not math.isfinite(similarity) or similarity <= 0 or similarity < db.LONG_TERM_RECALL_MIN_SEMANTIC_SCORE:
                continue
            score = (1 - recency_weight) * similarity + recency_weight * db.recency_score_from_created_at(entry['created_at'])
            message_id = entry['message_id']
            previous = candidates.get(message_id)
            if previous and previous['score'] >= score:
                continue
            candidates[message_id] = {key: entry[key] for key in
                                      ('message_id', 'start_offset', 'end_offset', 'source_hash')}
            candidates[message_id].update(score=score, similarity=similarity)
            if len(candidates) > capacity:
                lowest = min(candidates, key=lambda mid: (candidates[mid]['score'], mid))
                del candidates[lowest]
        final = page[-1]
        last_key = (final['message_id'], final['start_offset'], final['end_offset'])
        if len(page) < VECTOR_PAGE_SIZE:
            break
        await asyncio.sleep(0)
    if not candidates:
        return []
    async with pool.acquire() as conn:
        rows = await conn.fetch('''
            WITH candidates AS (
                SELECT id, conversation_id, role FROM context_messages WHERE id = ANY($1::integer[])
            ), ids AS (
                SELECT id FROM candidates
                UNION
                SELECT parent.id FROM candidates c
                CROSS JOIN LATERAL (
                    SELECT m.id FROM context_messages m
                    WHERE m.conversation_id = c.conversation_id AND m.id < c.id AND m.role = 'user'
                    ORDER BY m.id DESC LIMIT 1
                ) parent WHERE c.role = 'assistant'
            )
            SELECT m.id, m.conversation_id, m.role, m.content, m.content_json,
                   m.created_at, m.kind, m.hidden
            FROM context_messages m JOIN ids ON ids.id = m.id ORDER BY m.conversation_id, m.id
        ''', list(candidates))
    results = []
    for turn in dialogue_turns([dict(row) for row in rows]):
        if turn['conversation_id'] == current_conversation_id and any(
            row['role'] == 'user' and source_text(row).strip() == query for row in turn['messages']
        ):
            continue
        if not any(row['role'] == 'user' for row in turn['messages']):
            continue
        matches = []
        for row in turn['messages']:
            entry = candidates.get(row['id'])
            if not entry or source_hash(row) != entry['source_hash']:
                continue
            text = source_text(row)
            span = (entry['start_offset'], entry['end_offset'])
            if span not in set(sentence_spans(text)):
                continue
            matches.append({'message_id': row['id'], 'role': row['role'],
                            'start': span[0], 'end': span[1], 'text': text[slice(*span)],
                            'score': entry['score']})
        if not matches:
            continue
        score = max(match['score'] for match in matches)
        if not any(match['role'] == 'user' for match in matches):
            row = turn['messages'][0]
            text = source_text(row)
            matches.append({'message_id': row['id'], 'role': 'user', 'start': 0,
                            'end': len(text), 'text': text, 'score': score})
        results.append({**turn, 'matches': matches, 'score': score})
    results.sort(key=lambda turn: (turn['score'], turn['turn_id']), reverse=True)
    return results[:limit]
