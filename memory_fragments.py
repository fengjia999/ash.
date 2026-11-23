"""First-person memories shared by the chat gateway and external clients."""
import asyncio
import json
import logging
import re
from datetime import timezone, timedelta
from html import escape

import database as db

CATEGORIES = ('情绪', '里程碑', '日常', '计划')
RECALL_DESCRIPTION = '对话涉及过去的事，或现有记忆缺少细节、时间线不完整时调用。用人物、事件或主题关键词查询，可按类别筛选，返回相关记忆片段。'
INTRO = '这是过去的记忆片段，可能与对话相关，也可能毫无关联'
HINTS = (('心情', '开心', '难过', '感受', '情绪'), ('第一次', '终于', '突破', '进展', '里程碑'),
         ('平时', '日常', '昨天', '习惯'), ('打算', '准备', '安排', '计划', '接下来'))
FRAGMENT = "metadata->>'kind'='ash_fragment'"
log = logging.getLogger(__name__)
TIME_PREFIX = re.compile(r'^【(\d{4}-\d{2}-\d{2} \d{2}:\d{2})】\s*')


def conversation_time(content):
    match = TIME_PREFIX.match(content)
    return match[1] if match else None


def dated_content(content, stamp):
    text = TIME_PREFIX.sub('', content, count=1).strip()
    if not text:
        raise ValueError('请在时间后填写片段正文')
    return f'【{stamp}】{text}' if stamp else text


def categories(value):
    if not isinstance(value, list) or not value or any(x not in CATEGORIES for x in value):
        raise ValueError('请选择情绪、里程碑、日常或计划')
    return list(dict.fromkeys(value))


def validate(item, *, original_time=None):
    body = item.get('content')
    if isinstance(body, str):
        body = body.strip()
        if original_time:
            body = dated_content(body, conversation_time(body) or original_time)
    if not isinstance(body, str) or not 1 <= len(body) <= 800:
        raise ValueError('片段正文需要 1 至 800 个字')
    score = item.get('importance', 5)
    if type(score) is not int or not 1 <= score <= 10:
        raise ValueError('重要度需要 1 至 10 的整数')
    return body, categories(item.get('categories')), score


async def insert(conn, item, metadata, source=''):
    body, tags, score = validate(item)
    return await conn.fetchval("""
        INSERT INTO memories(content,tags,importance,type,metadata,source_session)
        VALUES($1,$2,$3,'episodic',$4::jsonb,$5) RETURNING id
    """, body, tags, score, json.dumps({**metadata, 'kind': 'ash_fragment'}), source)


async def search(query='', selected=None, excluded=(), limit=3, before=None, chronology=False,
                 max_importance=None, excluded_conversation_id=None):
    selected = categories(selected) if selected else [
        category for category, hints in zip(CATEGORIES, HINTS) if any(h in query for h in hints)]
    # Broad prompts such as “最近有什么计划” can be answered by the category
    # alone. Specific topics still require a word from the fragment itself.
    residual = query
    if selected:
        for group in HINTS:
            for hint in group:
                residual = residual.replace(hint, '')
        residual = re.sub(r'最近|现在|我们|我的|你的|之前|有什么|有哪些|怎么样|说说|回忆|一下|[了呢吗的呀啊？?，。！!\s]', '', residual)
    category_only = bool(selected and not residual)
    keywords = db.extract_search_keywords(query)
    if query.strip():
        keywords.append(query.strip())
    pool = await db.get_pool()
    rows = await pool.fetch(f"""
        SELECT id,content,tags,importance,created_at,metadata,COALESCE(pinned,false) AS pinned FROM memories m
        CROSS JOIN LATERAL (SELECT count(*) hits FROM unnest($1::text[]) term
            WHERE strpos(lower(m.content),lower(term))>0) rank
        WHERE {FRAGMENT} AND NOT metadata ? 'merged_into'
        AND (cardinality($2::text[])=0 OR tags && $2)
        AND NOT id=ANY($3::int[])
        AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements_text(metadata->'members') elem
                       WHERE elem::int=ANY($3))
        AND ($4::int IS NULL OR id<$4)
        AND ($5='' OR hits>0 OR $8::boolean)
        AND ($9::int IS NULL OR importance<=$9)
        AND ($10::int IS NULL OR (
            source_session IS DISTINCT FROM $10::text
            AND NOT EXISTS(
                SELECT 1
                FROM jsonb_array_elements_text(
                    CASE WHEN jsonb_typeof(m.metadata->'sources')='array'
                         THEN m.metadata->'sources' ELSE '[]'::jsonb END
                ) source(message_id)
                JOIN context_messages cm ON cm.id=(
                    CASE WHEN source.message_id ~ '^[0-9]+$'
                         THEN source.message_id::int END
                )
                WHERE cm.conversation_id=$10
            )
        ))
        ORDER BY CASE WHEN NOT $7::boolean THEN hits END DESC,
                 CASE WHEN NOT $7 AND $5<>'' THEN importance END DESC,id DESC LIMIT $6
    """, keywords, selected, list(excluded), before, query.strip(), limit, chronology,
    category_only, max_importance, excluded_conversation_id)
    return [{**dict(r), 'conversation_time': conversation_time(r['content'])} for r in rows]


def visible_ids(messages):
    ids = set()
    for msg in messages:
        if msg.get('role') != 'user':
            continue
        content = msg.get('content', '')
        for block in content if isinstance(content, list) else [content]:
            text = block.get('text', '') if isinstance(block, dict) else block
            if isinstance(text, str) and text.startswith('<memories>'):
                ids.update(map(int, re.findall(r'<fragment id="(\d+)">', text.partition('</memories>')[0])))
    return ids


def pack(rows, budget):
    lines = []
    for r in rows[:3]:
        line = f'<fragment id="{int(r["id"])}">{escape(r["content"])}</fragment>'
        if len('\n'.join(['<memories>', INTRO, *lines, line, '</memories>'])) <= budget:
            lines.append(line)
    return '\n'.join(['<memories>', INTRO, *lines, '</memories>']) if lines else ''


async def process(conn, interval, complete):
    # Lock one conversation batch across instances. Writes and acknowledgement
    # share the transaction, so an interrupted model request is safe to retry.
    conv = await conn.fetchval("""
        SELECT m.conversation_id FROM context_messages m JOIN conversations c ON c.id=m.conversation_id
        WHERE m.fragment_pending GROUP BY m.conversation_id,c.is_active,c.external_session_id
        HAVING count(*) >= $1 OR (NOT c.is_active AND c.external_session_id IS NULL) ORDER BY min(m.id) LIMIT 1
    """, interval)
    if conv is None:
        pending = await conn.fetchrow(f"""SELECT id,content,tags,metadata FROM memories WHERE {FRAGMENT} AND pinned IS NOT TRUE
            AND metadata ? 'review_pending' AND NOT metadata ? 'merged_into' ORDER BY id LIMIT 1 FOR UPDATE""")
        if not pending:
            return False
        await consolidate(conn, [], complete, 'mcp', pending=dict(pending))
        await conn.execute("UPDATE memories SET metadata=metadata-'review_pending' WHERE id=$1 AND pinned IS NOT TRUE", pending['id'])
        return True
    ends = await conn.fetch("""SELECT id FROM context_messages WHERE conversation_id=$1
        AND fragment_pending ORDER BY id LIMIT $2 FOR UPDATE""", conv, interval)
    ids = [r['id'] for r in ends]
    rows = await conn.fetch("""
        SELECT a.id,u.id AS user_id,COALESCE(u.created_at,a.created_at) AS recorded_at,u.content AS user_text,a.content AS assistant_text FROM context_messages a
        JOIN LATERAL (SELECT id,content,created_at,hidden,kind FROM context_messages WHERE conversation_id=$1
            AND role='user' AND id<a.id ORDER BY id DESC LIMIT 1) u ON TRUE
        WHERE a.id=ANY($2::int[]) AND NOT a.hidden AND NOT u.hidden AND u.kind='chat' ORDER BY a.id
    """, conv, ids)
    if rows:
        await consolidate(conn, [dict(r) for r in rows], complete, str(conv))
    await conn.execute('UPDATE context_messages SET fragment_pending=false WHERE id=ANY($1::int[])', ids)
    return True


async def consolidate(conn, turns, complete, source, pending=None):
    local_zone = timezone(timedelta(hours=db.TIMEZONE_HOURS))
    turns = [{**t, 'recorded_at': t['recorded_at'].astimezone(local_zone).strftime('%Y-%m-%d %H:%M')
              if t['recorded_at'] else None} for t in turns]
    by_turn = {t['id']: t for t in turns}
    topic = pending['content'] if pending else ' '.join(t['user_text'] for t in turns)
    terms = db.extract_search_keywords(topic)[:80]
    recent = await conn.fetch(f"""
        WITH active AS (
            SELECT id,content FROM memories WHERE {FRAGMENT} AND pinned IS NOT TRUE AND NOT metadata ? 'merged_into'
        ), related AS (
            SELECT id FROM active CROSS JOIN LATERAL
                (SELECT count(*) hits FROM unnest($1::text[]) word
                 WHERE strpos(lower(content),lower(word))>0) rank
            WHERE hits>0 ORDER BY hits DESC,id DESC LIMIT 12
        ), latest AS (SELECT id FROM active ORDER BY id DESC LIMIT 12)
        SELECT id,content,tags,metadata FROM memories WHERE id IN
            (SELECT id FROM related UNION SELECT id FROM latest)
        AND pinned IS NOT TRUE AND NOT metadata ? 'merged_into'
        ORDER BY id DESC FOR UPDATE
    """, terms)
    known = {r['id']: r for r in recent}
    if pending:
        known.setdefault(pending['id'], pending)
    candidates = [{k:r[k] for k in ('id','content','tags')} for r in known.values()]
    for candidate in candidates:
        candidate['review'] = bool(pending and candidate['id'] == pending['id'])
    items = await complete(turns, candidates)
    if not isinstance(items, list):
        raise ValueError('片段提取结果应为数组')
    used = set()
    for item in items:
        body, tags, score = validate(item)
        parents = item.get('merge_ids', [])
        if not isinstance(parents, list) or any(type(i) is not int or i not in known or i in used for i in parents):
            raise ValueError('片段合并来源无效')
        if pending and pending['id'] not in parents:
            raise ValueError('重排结果应绑定待整理的片段')
        parents = list(dict.fromkeys(parents))
        used.update(parents)
        turn_ids = item.get('turn_ids', [])
        if (not isinstance(turn_ids, list) or (not parents and not turn_ids)
                or any(type(i) is not int or i not in by_turn for i in turn_ids)):
            raise ValueError('片段需要标明本批对话中对应的轮次')
        cited = [by_turn[i] for i in turn_ids]
        sources = [i for t in cited for i in (t['id'], t['user_id'])]
        stamps = [t['recorded_at'] for t in cited if t['recorded_at']]
        members = set(parents)
        for i in parents:
            stamp = conversation_time(known[i]['content'])
            if stamp:
                stamps.append(stamp)
            meta = db._json_object(known[i]['metadata'])
            sources.extend(meta.get('sources', []))
            members.update(meta.get('members', []))
        metadata = {'kind':'ash_fragment','sources':sorted(set(sources)), 'members':sorted(members)}
        item = {**item, 'content': dated_content(body, min(stamps, default=None))}
        if parents:
            body, tags, score = validate(item)
            await conn.execute('UPDATE memories SET content=$2,tags=$3,importance=$4,metadata=$5::jsonb WHERE id=$1 AND pinned IS NOT TRUE',
                               parents[0], body, tags, score, json.dumps(metadata))
            await conn.execute("""UPDATE memories SET metadata=metadata || jsonb_build_object('merged_into',$2::int)
                WHERE id=ANY($1::int[]) AND pinned IS NOT TRUE""", parents[1:], parents[0])
        else:
            await insert(conn, item, metadata, source)


async def worker(runtime_for, complete):
    while True:
        delay = 15
        try:
            runtime = await runtime_for('fragment_extract')
            if runtime['model'] and runtime['api_url']:
                settings = await db.get_conversation_model_settings()
                interval = db._json_object(settings.get('history_recall_settings')).get('fragment_interval', 3)
                pool = await db.get_pool()
                async with pool.acquire() as conn, conn.transaction():
                    if await conn.fetchval('SELECT pg_try_advisory_xact_lock(73051246)'):
                        if await process(conn, interval, lambda t,r: complete(runtime,t,r)):
                            delay = 1
        except Exception:
            log.exception('记忆片段提取失败')
            delay = 60
        await asyncio.sleep(delay)
