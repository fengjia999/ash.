import ast
import os
import time
import unittest
from pathlib import Path
from unittest.mock import patch


class DashboardStaticVersionTests(unittest.TestCase):
    def test_transfer_stylesheet_changes_refresh_cache_version(self):
        source = (Path(__file__).resolve().parents[1] / 'main.py').read_text()
        tree = ast.parse(source)
        function = next(node for node in tree.body
                        if isinstance(node, ast.FunctionDef)
                        and node.name == 'dashboard_static_version')
        namespace = {'os': os, 'time': time}
        exec(compile(ast.Module(body=[function], type_ignores=[]), 'main.py', 'exec'), namespace)
        transfer_mtime = 2000

        def modified_time(path):
            return transfer_mtime if path == 'static/css/transfer-paper.css' else 1000

        with patch.object(os.path, 'getmtime', side_effect=modified_time):
            self.assertEqual(namespace['dashboard_static_version'](), 2000)
            transfer_mtime = 3000
            self.assertEqual(namespace['dashboard_static_version'](), 3000)
