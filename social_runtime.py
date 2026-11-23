import os
import time
from photon_runtime import PhotonRuntime, ROOT

class SocialRuntime(PhotonRuntime):
    def entrypoint(self):
        return ROOT / 'integrations/social/index.mjs'

    async def load_config(self):
        from bot_connections import load
        return await load(provider=self.provider)

    def should_run(self, config):
        return bool(config and (config.get('enabled') or config.get('setup_until', 0) > time.time()))

    def payload(self, config):
        return {'provider': self.provider, 'enabled': bool(config.get('enabled')),
                'setupEnabled': config.get('setup_until',0)>time.time(),
                'feishuDomain': config.get('feishu_domain', 'feishu'),
                'appId': config.get('app_id', ''), 'appSecret': config.get('app_secret', ''),
                'botToken': config.get('bot_token', ''), 'botId': config.get('bot_id', ''),
                'baseUrl': config.get('base_url', 'https://ilinkai.weixin.qq.com'),
                'allowedUsers': config.get('allowed_users', []),
                'gatewayUrl': 'http://127.0.0.1:' + str(int(config.get('gateway_port') or os.getenv('PORT', '8080'))),
                'gatewaySecret': config['gateway_token'], 'timeEnabled': config.get('time_enabled', True),
                'debounceSeconds': config.get('debounce_seconds', 30),
                'stateFile': str(self.directory / 'channel-state.json')}

runtimes = {provider: SocialRuntime(provider) for provider in ('feishu', 'weixin')}
