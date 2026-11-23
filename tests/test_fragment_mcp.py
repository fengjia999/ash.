import json
import logging
import unittest
from datetime import date
from unittest.mock import AsyncMock, patch

import httpx
import main
import fragment_mcp


class ExternalFragmentTools(unittest.IsolatedAsyncioTestCase):
    async def test_query_diary_returns_readable_text_through_mcp(self):
        row = {'id': 37, 'title': '雨天', 'memory_date': date(2026, 11, 19),
               'content': '我记得她说：“听。”\n\n雨还在下。', 'keywords': ['雨', '窗边']}
        heading = 'ID 37 · 2026-11-19 · 雨天'
        listing = heading + '\n关键词：雨、窗边'
        with patch.object(main, 'MCP_SECRET', 'test-key'), patch.object(main, 'MEMORY_ENABLED', True), \
             patch.object(fragment_mcp.db, 'get_long_term_memory', AsyncMock(side_effect=[
                 row, None, dict(row, metadata={'entry_kind': 'fragment'}),
                 dict(row, metadata={'source': 'raw_user_quotes'})])), \
             patch.object(fragment_mcp.db, 'get_diary_list', AsyncMock(side_effect=[[row], []])), \
             patch.object(fragment_mcp.db, 'get_conversation_model_settings', AsyncMock(return_value={})), \
             patch.object(fragment_mcp.db, 'search_long_term_memory_summaries', AsyncMock(side_effect=[[row], []])):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),
                                         base_url='https://ash.test') as client:
                async def query(**arguments):
                    response = await client.post('/mcp/test-key', json={
                        'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                        'params': {'name': 'query_diary', 'arguments': arguments}})
                    response.raise_for_status()
                    return response.json()['result']

                for arguments, expected in [
                    ({'query': '雨'}, listing), ({}, listing),
                    ({'id': 37}, heading + '\n\n' + row['content']),
                    ({'query': '雪'}, '没有找到匹配的日记。'), ({}, '还没有日记。')
                ]:
                    self.assertEqual(await query(**arguments), {'content': [{'type': 'text', 'text': expected}]})
                for entry_id in [38, 39, 40]:
                    self.assertEqual(await query(id=entry_id), {
                        'isError': True, 'content': [{'type': 'text', 'text': '没有这篇日记'}]})

    async def test_write_description_follows_current_identity_presets(self):
        rpc = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}
        identities = [{'assistant_name': '阿九', 'user_name': '晚晴'},
                      {'assistant_name': '云', 'user_name': '小满'}, {}]
        with patch.object(main, 'MCP_SECRET', 'test-key'), \
             patch.object(main, 'get_identity_presets', AsyncMock(side_effect=identities)):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),
                                        base_url='https://ash.test') as client:
                for author, user in [('阿九', '晚晴'), ('云', '小满'), ('助手', '用户')]:
                    result = await client.post('/mcp/test-key', json=rpc)
                    tools = result.json()['result']['tools']
                    description = next(t['description'] for t in tools if t['name'] == 'write_fragment')
                    self.assertEqual(
                        '出现值得以后记住的事实、偏好、情绪变化、重要经历或计划时主动调用。'
                        '每条记录一个主题，选择对应类别并设置重要度。'
                        f'正文用{author}自己的第一人称书写，涉及{user}的经历时，用{user}的名字或第三人称描述。', description)
                    diary = next(t['description'] for t in tools if t['name'] == 'write_diary')
                    self.assertIn(f'以{author}的第一人称', diary)
                    self.assertIn(f'用{user}的名字或第三人称描述', diary)

    async def test_url_password_is_separate_and_oauth_is_removed(self):
        rpc = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}
        with patch.object(main, 'MCP_SECRET', 'separate-memory-key'), \
             patch.object(main, 'GATEWAY_SECRET', 'gateway-key'), \
             patch.object(main, 'DASHBOARD_PASSWORD', 'dashboard-password'):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),
                                        base_url='https://ash.test') as client:
                for path in ['/mcp/separate-memory-key', '/mcp/separate-memory-key/']:
                    result = await client.post(path, json=rpc)
                    self.assertEqual(200, result.status_code)
                    names = {tool['name'] for tool in result.json()['result']['tools']}
                    self.assertEqual(set(fragment_mcp.TOOLS), names)
                    self.assertNotIn('securitySchemes', result.json()['result']['tools'][0])
                for path in ['/mcp/wrong', '/mcp/gateway-key', '/mcp/dashboard-password']:
                    self.assertEqual(401, (await client.post(path, json=rpc)).status_code)
                self.assertEqual(401, (await client.post('/mcp', json=rpc)).status_code)
                legacy = await client.post('/mcp', json=rpc,
                                           headers={'Authorization': 'Bearer gateway-key'})
                self.assertEqual(200, legacy.status_code)
                for path in ['/v1/models', '/api/standing-memory']:
                    result = await client.get(path, headers={'Authorization': 'Bearer separate-memory-key'})
                    self.assertEqual(401, result.status_code)
                self.assertEqual(401, (await client.post('/mcp/refresh-tools')).status_code)
                for path in ['/mcp', '/mcp/']:
                    result = await client.post(path, json=rpc,
                        headers={'Authorization': 'Bearer ash_mcp_access_old-oauth-token'})
                    self.assertEqual(401, result.status_code)
                    self.assertNotIn('www-authenticate', result.headers)
        paths = {getattr(route, 'path', '') for route in main.app.routes}
        self.assertNotIn('/oauth/authorize', paths)
        self.assertNotIn('/oauth/token', paths)
        self.assertNotIn('/.well-known/oauth-authorization-server', paths)

    async def test_url_password_disabled_when_unconfigured(self):
        with patch.object(main, 'MCP_SECRET', ''):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),
                                        base_url='https://ash.test') as client:
                self.assertEqual(401, (await client.post('/mcp/anything')).status_code)

    def test_access_log_masks_url_password(self):
        record = logging.LogRecord('uvicorn.access', logging.INFO, '', 0,
            '%s - "%s %s HTTP/%s" %d',
            ('127.0.0.1', 'POST', '/mcp/private-password', '1.1', 200), None)
        fragment_mcp.MCPAccessLogFilter().filter(record)
        self.assertNotIn('private-password', record.getMessage())
        self.assertIn('/mcp/[redacted]', record.getMessage())

    async def test_remote_client_discovers_tools_and_submits_classified_fragment(self):
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport,base_url='http://ash.test') as client:
            async def rpc(method, **params):
                return await client.post('/mcp',json={'jsonrpc':'2.0','id':1,'method':method,'params':params})
            with patch.object(main,'GATEWAY_SECRET','test'), patch.object(main,'MEMORY_ENABLED',True):
                self.assertEqual(401,(await rpc('tools/list')).status_code)
                client.headers.update({'Authorization':'Bearer test'})
                self.assertIn('tools',(await rpc('initialize')).json()['result']['capabilities'])
                tools = (await rpc('tools/list')).json()['result']['tools']
                self.assertEqual({'core_memory','query_diary','write_diary','recall_fragments','write_fragment'}, {t['name'] for t in tools})
                bad = await rpc('tools/call',name='write_fragment',arguments={'content':'我的记忆'})
                self.assertTrue(bad.json()['result']['isError'])
                with patch.object(fragment_mcp,'call',AsyncMock(return_value={'id':8})) as write:
                    good = await rpc('tools/call',name='write_fragment',arguments={'content':'我的记忆','categories':['情绪']})
                self.assertIn('8',good.json()['result']['content'][0]['text'])
                self.assertEqual(['情绪'],write.await_args.args[1].categories)

    async def test_core_memory_returns_complete_enabled_records_only(self):
        complete = '完整记忆，不应截断。' * 2000
        base = {'status': 'active', 'inject_enabled': True, 'layer': 'core'}
        rows = [dict(base, id=1, content=complete),
                dict(base, id=2, content='待确认', status='pending'),
                dict(base, id=3, content='关闭注入', inject_enabled=False),
                dict(base, id=4, content='归档', status='archived'),
                dict(base, id=5, content='   '),
                dict(base, id=6, content='最近的经历', layer='recent',
                     title='会话摘要', created_at='2026-11-18')]
        transport = httpx.ASGITransport(app=main.app)
        with patch.object(main, 'GATEWAY_SECRET', 'test'), \
             patch.object(main, 'MEMORY_ENABLED', True), \
             patch.object(fragment_mcp.db, 'get_standing_memory_blocks',
                          AsyncMock(return_value=rows)) as read:
            async with httpx.AsyncClient(transport=transport, base_url='http://ash.test',
                                        headers={'Authorization': 'Bearer test'}) as client:
                response = await client.post('/mcp', json={
                    'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                    'params': {'name': 'core_memory', 'arguments': {}}})
        result = json.loads(response.json()['result']['content'][0]['text'])
        self.assertEqual([{'id': 1, 'content': complete}], result['fixed'])
        self.assertEqual([6], [row['id'] for row in result['flow']])
        self.assertEqual('最近的经历', result['flow'][0]['content'])
        read.assert_awaited_once_with(status='active')

    def test_internal_tools_keep_diary_and_fragment_reads(self):
        with patch.object(main, 'MEMORY_ENABLED', True):
            names = {tool['name'] for tool in main._collect_all_tools()}
        self.assertNotIn('core_memory', names)
        self.assertTrue({'search_diary', 'read_diary', 'recall_fragments'} <= names)
        self.assertEqual('在对话开始时调用，读取完整核心记忆，了解身份、关系和已有背景。无需参数。',
                         fragment_mcp.TOOLS['core_memory'][1])
