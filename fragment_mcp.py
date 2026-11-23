"""Stateless Streamable HTTP tools for clients sharing the Ash memory store."""
import json
import logging
import re
from typing import Literal

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

import database as db
import memory_fragments as fragments

Category = Literal['情绪', '里程碑', '日常', '计划']


class MCPAccessLogFilter(logging.Filter):
    def filter(self, record):
        # Uvicorn's access log contains the request URL, including its password.
        if isinstance(record.args, tuple) and len(record.args) == 5:
            args = list(record.args)
            args[2] = re.sub(r'(/mcp/)[^?\s]+', r'\1[redacted]', str(args[2]))
            record.args = tuple(args)
        return True


def install_access_log_filter():
    logger = logging.getLogger('uvicorn.access')
    if not any(isinstance(item, MCPAccessLogFilter) for item in logger.filters):
        logger.addFilter(MCPAccessLogFilter())


class Arguments(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class DiaryQuery(Arguments):
    query: str = Field(default='', max_length=1000, description='搜索主题或关键词，留空返回最近的日记目录')
    id: int | None = Field(default=None, gt=0, description='日记编号，提供后直接读取该篇全文，优先于 query')


class DiaryWrite(Arguments):
    title: str = Field(min_length=1, max_length=200, description='概括这段对话的日记标题')
    content: str = Field(min_length=1, max_length=32000, description='日记正文，记录对话经过、感受和后续值得关注的事')
    diary_date: str | None = Field(default=None, description='日记日期，格式为 YYYY-MM-DD')


class FragmentQuery(Arguments):
    query: str = Field(min_length=1, max_length=1200, description='要查找的人物、事件或主题关键词')
    categories: list[Category] = Field(default_factory=list, description='可选类别筛选，可多选，留空时根据查询内容判断类别')


class FragmentWrite(Arguments):
    content: str = Field(min_length=1, max_length=800, description='可独立理解的记忆正文，每条记录一个主题，最多 800 字')
    categories: list[Category] = Field(min_length=1, max_length=4, description='按内容选择至少一个类别，可多选')
    importance: int = Field(default=5, ge=1, le=10, description='重要度，1 至 10，越高越重要，默认 5')


TOOLS = {
    'core_memory': (Arguments, '在对话开始时调用，读取完整核心记忆，了解身份、关系和已有背景。无需参数。'),
    'query_diary': (DiaryQuery, '需要了解过去一段对话的整体经过或核对当时的记录时调用。用 query 搜索日记目录，留空查看最近日记，再用返回的 id 读取全文。'),
    'write_diary': (DiaryWrite, '在一段对话接近结束时主动调用，保存这段对话的整体记录。提供标题和正文，以{assistant_name}的第一人称记录经过、感受和后续值得关注的事。涉及{user_name}的经历时，用{user_name}的名字或第三人称描述。'),
    'recall_fragments': (FragmentQuery, fragments.RECALL_DESCRIPTION),
    'write_fragment': (FragmentWrite, '出现值得以后记住的事实、偏好、情绪变化、重要经历或计划时主动调用。每条记录一个主题，选择对应类别并设置重要度。正文用{assistant_name}自己的第一人称书写，涉及{user_name}的经历时，用{user_name}的名字或第三人称描述。'),
}


def diary_heading(row):
    return ' · '.join(str(value) for value in
                      (f"ID {row['id']}", row.get('memory_date'), row.get('title')) if value)


async def call(name, args, current_conversation_id=None):
    if name == 'core_memory':
        blocks = await db.get_standing_memory_blocks(status='active')
        # Match the main chat's eligibility rules, preserving complete bodies.
        records = [row for row in blocks if row.get('status') == 'active'
                   and row.get('inject_enabled') is True
                   and str(row.get('content') or '').strip()]
        return {
            'fixed': [{'id': row['id'], 'content': row['content']}
                      for row in records if row.get('layer') != 'recent'],
            'flow': [{'id': row['id'], 'title': row.get('title') or '',
                      'content': row['content'], 'created_at': row.get('created_at')}
                     for row in sorted(
                         (row for row in records if row.get('layer') == 'recent'),
                         key=lambda row: (str(row.get('created_at') or ''), row['id']))],
        }
    if name == 'write_fragment':
        pool = await db.get_pool()
        async with pool.acquire() as conn:
            return {'id': await fragments.insert(conn, args.model_dump(), {'review_pending':True}, 'mcp')}
    if name == 'recall_fragments':
        search_options = (
            {'excluded_conversation_id': current_conversation_id}
            if current_conversation_id is not None else {}
        )
        return [{k:r[k] for k in ('id','content','tags','conversation_time','created_at')}
                for r in await fragments.search(args.query, args.categories, **search_options)]
    if name == 'write_diary':
        row = await db.create_long_term_memory(args.title, [], args.content, args.diary_date,
            metadata={'entry_kind':'diary','author_role':'assistant'})
        return {'id':row['id']}
    if args.id:
        row = await db.get_long_term_memory(args.id)
        if (not row or db.long_term_memory_kind(row) != 'diary' or
                row.get('metadata', {}).get('source') == 'raw_user_quotes'):
            raise ValueError('没有这篇日记')
        return f"{diary_heading(row)}\n\n{row['content']}"
    if args.query:
        rows = await db.search_long_term_memory_summaries(args.query,await db.get_conversation_model_settings(),10)
    else:
        rows = (await db.get_diary_list())[-10:][::-1]
    entries = []
    for row in rows:
        entry = diary_heading(row)
        if row.get('keywords'):
            entry += '\n关键词：' + '、'.join(map(str, row['keywords']))
        entries.append(entry)
    return '\n\n'.join(entries) or ('没有找到匹配的日记。' if args.query else '还没有日记。')


async def endpoint(request: Request, enabled: bool, read_identity):
    origin = request.headers.get('origin')
    if origin and origin != str(request.base_url).rstrip('/'):
        return Response(status_code=403)
    try:
        body = await request.json()
    except ValueError:
        body = None
    rid = body.get('id') if isinstance(body,dict) else None
    def error(code, message):
        return JSONResponse({'jsonrpc':'2.0','id':rid,'error':{'code':code,'message':message}})
    if not isinstance(body,dict) or body.get('jsonrpc') != '2.0':
        return error(-32600,'Invalid Request')
    method = body.get('method')
    if rid is None:
        return Response(status_code=202)
    params = body.get('params',{})
    if not isinstance(params,dict):
        return error(-32602,'Invalid params')
    if method == 'initialize':
        result = {'protocolVersion':'2025-06-18','capabilities':{'tools':{}},
                  'serverInfo':{'name':'ash-memory','version':'1.0'}}
    elif method == 'ping':
        result = {}
    elif method == 'tools/list':
        identity = await read_identity()
        names = {'assistant_name': identity.get('assistant_name') or '助手',
                 'user_name': identity.get('user_name') or '用户'}
        result = {'tools':[{'name':name,'description':description.format_map(names),'inputSchema':schema.model_json_schema(),
                           'annotations': {'readOnlyHint': name not in {'write_diary', 'write_fragment'},
                                           'destructiveHint': False, 'openWorldHint': False}}
                           for name,(schema,description) in TOOLS.items()]}
    elif method == 'tools/call':
        name = params.get('name')
        if not isinstance(name,str) or name not in TOOLS:
            return error(-32602,'Unknown tool')
        try:
            if not enabled:
                raise ValueError('记忆系统尚未开启')
            args = TOOLS[name][0].model_validate(params.get('arguments',{}))
            value = await call(name,args)
            text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
            result = {'content':[{'type':'text','text':text}]}
        except (ValidationError,ValueError) as exc:
            result = {'isError':True,'content':[{'type':'text','text':str(exc)}]}
    else:
        return error(-32601,'Method not found')
    return {'jsonrpc':'2.0','id':rid,'result':result}
