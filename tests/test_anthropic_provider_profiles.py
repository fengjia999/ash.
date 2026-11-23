import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import database
import main


class Request:
    def __init__(self, payload):
        self.payload = payload

    async def json(self):
        return self.payload


class AnthropicProviderTests(unittest.IsolatedAsyncioTestCase):
    profile = {
        'id': 9, 'name': 'A relay', 'api_url': 'https://relay.example/v1',
        'api_key': 'secret-profile-key', 'is_active': True,
    }

    async def test_profile_resolves_url_and_key_together(self):
        with patch.object(main, 'get_active_anthropic_provider_profile', AsyncMock(return_value=self.profile)), patch.object(main, '_load_anthropic_api_key', AsyncMock()) as legacy:
            provider = await main._load_active_anthropic_provider()
        self.assertEqual('https://relay.example/v1/messages', provider['api_url'])
        self.assertEqual(self.profile['api_key'], provider['api_key'])
        legacy.assert_not_awaited()

    async def test_no_active_profile_keeps_legacy_configuration(self):
        with patch.object(main, 'get_active_anthropic_provider_profile', AsyncMock(return_value=None)), patch.object(main, '_load_anthropic_api_key', AsyncMock(return_value='old-key')), patch.object(main, 'ANTHROPIC_API_URL', 'https://old.example/messages'):
            provider = await main._load_active_anthropic_provider()
        self.assertEqual('old-key', provider['api_key'])
        self.assertEqual('https://old.example/messages', provider['api_url'])

    async def test_list_supports_multiple_profiles_without_revealing_keys(self):
        profiles = [self.profile, {**self.profile, 'id': 10, 'is_active': False}]
        with patch.object(main, 'get_anthropic_provider_profiles', AsyncMock(return_value=profiles)):
            result = await main.api_list_anthropic_providers()
        self.assertEqual(2, len(result['profiles']))
        self.assertEqual(9, result['effective']['id'])
        self.assertNotIn(self.profile['api_key'], repr(result))

    async def test_create_and_edit_with_blank_key(self):
        with patch.object(main, 'save_anthropic_provider_profile', AsyncMock(return_value=self.profile)) as save:
            result = await main.api_create_anthropic_provider(Request(self.profile))
        save.assert_awaited_once_with('A relay', self.profile['api_url'], self.profile['api_key'], True)
        self.assertNotIn(self.profile['api_key'], repr(result))
        with patch.object(main, 'update_anthropic_provider_profile', AsyncMock(return_value=self.profile)) as update:
            await main.api_update_anthropic_provider(9, Request({**self.profile, 'api_key': ''}))
        self.assertIsNone(update.await_args.args[3])

    async def test_create_rejects_missing_key_and_bad_url(self):
        for fields in ({'api_key': ''}, {'api_url': 'file:///tmp/key'}):
            response = await main.api_create_anthropic_provider(Request({**self.profile, **fields}))
            self.assertEqual(400, response.status_code)

    async def test_missing_activation_and_deletion_return_404(self):
        with patch.object(main, 'activate_anthropic_provider_profile', AsyncMock(return_value=None)):
            self.assertEqual(404, (await main.api_activate_anthropic_provider(99)).status_code)
        with patch.object(main, 'delete_anthropic_provider_profile', AsyncMock(return_value=False)):
            self.assertEqual(404, (await main.api_delete_anthropic_provider(99)).status_code)

    async def test_models_use_active_profile_url_and_auth(self):
        client = MagicMock()
        client.get = AsyncMock(return_value=MagicMock(status_code=200, json=lambda: {'data': [{'id': 'claude-test'}]}))
        with patch.object(main, 'get_active_anthropic_provider_profile', AsyncMock(return_value=self.profile)), patch.object(main, 'get_http_client', AsyncMock(return_value=client)):
            result = await main._load_anthropic_provider_models()
        self.assertEqual('claude-test', result['data'][0]['id'])
        self.assertEqual('https://relay.example/v1/models', client.get.await_args.args[0])
        self.assertEqual(self.profile['api_key'], client.get.await_args.kwargs['headers']['x-api-key'])

    def test_endpoint_controls_auth_and_openrouter_body(self):
        messages = [{'role': 'user', 'content': 'hello'}]
        for url, is_openrouter in [('https://openrouter.ai/api/v1/messages', True), ('https://relay.example/v1/messages', False)]:
            with patch.object(main, 'ANTHROPIC_API_URL', 'https://different.example/v1/messages'):
                headers = main._anthropic_headers('profile-key', url)
                body = main._anthropic_body_for_request({'model': 'claude-opus-4-6'}, messages, stream=False, api_url=url)
            self.assertEqual(is_openrouter, 'Authorization' in headers)
            self.assertEqual(is_openrouter, 'provider' in body)

    async def test_nonstream_uses_selected_endpoint(self):
        client = MagicMock()
        client.post = AsyncMock(return_value=MagicMock(status_code=400, json=lambda: {'error': 'test rejection'}))
        url = 'https://relay.example/v1/messages'
        with patch.object(main, 'get_http_client', AsyncMock(return_value=client)), patch.object(main, '_record_token_usage', AsyncMock()):
            await main.handle_tool_loop(main._anthropic_headers('key', url), {'model': 'claude-test', 'messages': []}, api_url=url)
        self.assertEqual(url, client.post.await_args.args[0])

    async def test_stream_uses_selected_endpoint(self):
        response = MagicMock(status_code=400)
        response.aread = AsyncMock(return_value=b'{"error":"test rejection"}')
        client = MagicMock()
        client.stream.return_value.__aenter__ = AsyncMock(return_value=response)
        factory = MagicMock()
        factory.return_value.__aenter__ = AsyncMock(return_value=client)
        url = 'https://relay.example/v1/messages'
        with patch.object(main.httpx, 'AsyncClient', factory), patch.object(main, '_record_token_usage', AsyncMock()):
            chunks = [chunk async for chunk in main.stream_with_tool_loop(main._anthropic_headers('key', url), {'model': 'claude-test', 'messages': []}, 1, '', 'claude-test', api_url=url)]
        self.assertTrue(chunks)
        self.assertEqual(url, client.stream.call_args.args[1])

    def test_backups_exclude_provider_secrets(self):
        self.assertNotIn('anthropic_provider_profiles', {spec['table'] for spec in database.GATEWAY_BACKUP_TABLES.values()})
