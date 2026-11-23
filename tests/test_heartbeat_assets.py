import unittest
from pathlib import Path
from unittest.mock import patch

import main


class HeartbeatAssetTests(unittest.TestCase):
    def test_save_bean_card_and_printed_recipe_remain_on_cup(self):
        html = (Path(__file__).resolve().parents[1] / "templates/dashboard.html").read_text()
        coffee = html.split('id="heartbeat-coffee"', 1)[1].split('<div class="coffee-controls"', 1)[0]
        self.assertIn('class="coffee-bean-save" id="heartbeat-save"', coffee)
        self.assertIn('aria-label="保存心跳间隔"', coffee)
        self.assertEqual(html.count('id="heartbeat-save"'), 1)
        self.assertIn('<label class="coffee-interval"', coffee)
        self.assertNotIn('coffee-recipe-surface', coffee)
        self.assertNotIn('coffee-recipe-shade', coffee)
        self.assertNotIn('coffee-recipe-tape', coffee)
        self.assertIn('/static/images/heartbeat-cup.svg?v={{ static_version }}', coffee)
        self.assertIn('<svg viewBox="0 0 80 54" fill="none"', coffee)
        for field in ('heartbeatInterval', 'heartbeatRoute', 'heartbeatProviderName', 'heartbeatModelName'):
            self.assertEqual(coffee.count('id="' + field + '"'), 1)

    def test_coffee_stylesheet_updates_dashboard_cache_version(self):
        for asset in ("static/css/heartbeat-coffee.css", "static/images/heartbeat-cup.svg"):
            with self.subTest(asset=asset), patch.object(main.os.path, "getmtime", side_effect=lambda path:
                              9000 if path == asset else 1):
                self.assertEqual(main.dashboard_static_version(), 9000)
