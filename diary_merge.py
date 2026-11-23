"""Reviewable same-day diary merges with preserved source text."""
import json
import re
from datetime import date
from diary_author import diary_author_role

from database import _json_object, _json_list, long_term_memory_kind, long_term_memory_summary


def snapshot(memory):
    result = {key: memory.get(key) for key in (
        'id', 'title', 'content', 'summary', 'memory_date', 'priority', 'enabled',
    )}
    result['memory_date'] = str(result['memory_date']) if result['memory_date'] else None
    result['keywords'] = _json_list(memory.get('keywords'))
    # Approval reads raw JSONB strings, while preview reads decoded keywords.
    # Derive the fallback summary from the same normalized values in both paths.
    result['summary'] = long_term_memory_summary(result)
    result['metadata'] = _json_object(memory.get('metadata'))
    return result


def diary_day(memory):
    value = str(memory.get('memory_date') or '')[:10]
    if not value:
        match = re.search(r'(?:^|\D)(\d{4}-\d{2}-\d{2})(?:\D|$)', memory.get('title') or '')
        value = match[1] if match else ''
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise ValueError('日记缺少有效日期，请先补充日期') from None


def validate_sources(memories):
    if not 2 <= len(memories) <= 30 or len({m['id'] for m in memories}) != len(memories):
        raise ValueError('每次请选择同一天的2至30篇日记')
    if any(long_term_memory_kind(m) != 'diary' for m in memories):
        raise ValueError('只能合并日记')
    if len({diary_author_role(m) for m in memories}) != 1:
        raise ValueError('只能合并同一作者的日记')
    days = {diary_day(m) for m in memories}
    if len(days) != 1:
        raise ValueError('只能合并同一天的日记')
    return days.pop()


async def apply_merge(conn, proposal, sources):
    """Called inside the proposal approval transaction; verify before any writes."""
    try:
        day = validate_sources(sources)
    except (ValueError, KeyError, TypeError):
        return {'error': '合并来源无效，请重新生成'}
    rows = await conn.fetch(
        'SELECT * FROM long_term_memories WHERE id = ANY($1::int[]) ORDER BY id FOR UPDATE',
        sorted(source['id'] for source in sources),
    )
    expected = sorted(sources, key=lambda source: source['id'])
    if [snapshot(dict(row)) for row in rows] != expected:
        return {'error': '原日记已修改或删除，请拒绝此稿并重新生成合并稿'}
    if str(proposal.get('memory_date')) != day:
        return {'error': '合并稿日期与原日记不一致'}
    memory = await conn.fetchrow(
        '''INSERT INTO long_term_memories
           (title, content, keywords, summary, memory_date, priority, enabled, metadata)
           VALUES ($1, $2, $3::jsonb, '', $4, $5, $6, $7::jsonb) RETURNING *''',
        proposal['title'], proposal['content'],
        json.dumps(_json_list(proposal.get('keywords')), ensure_ascii=False),
        proposal['memory_date'],
        max(int(row.get('priority') or 0) for row in rows),
        any(row.get('enabled', True) for row in rows),
        json.dumps({'entry_kind': 'diary', 'author_role': diary_author_role(sources[0]),
                    'merge_sources': sources}, ensure_ascii=False),
    )
    await conn.execute('DELETE FROM long_term_memories WHERE id = ANY($1::int[])',
                       [source['id'] for source in sources])
    await conn.execute('DELETE FROM long_term_memory_proposals WHERE id = $1', proposal['id'])
    result = dict(memory)
    result['keywords'] = _json_list(result.get('keywords'))
    result['metadata'] = _json_object(result.get('metadata'))
    return {'operation': 'merge', 'memory': result}
