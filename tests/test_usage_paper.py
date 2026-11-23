import datetime
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import database
import main


class UsageSummaryTimezoneTests(unittest.IsolatedAsyncioTestCase):
    async def test_summary_endpoint_supplies_gateway_timezone_and_today(self):
        with patch.object(main, 'get_token_usage_summary', AsyncMock(return_value={'daily_usage': []})) as summary:
            result = await main.api_token_usage_summary(days=180)
        summary.assert_awaited_once_with(days=180, timezone_hours=main.TIMEZONE_HOURS)
        today = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=main.TIMEZONE_HOURS))).date().isoformat()
        self.assertEqual(result['today'], today)

    async def test_folded_note_can_read_latest_requests_without_a_date_filter(self):
        with patch.object(main, 'get_token_usage_logs', AsyncMock(return_value=[])) as logs:
            self.assertEqual(await main.api_token_usage_logs(limit=3, days=0), {'logs': []})
        logs.assert_awaited_once_with(limit=3, days=None)

    async def test_daily_buckets_bind_timezone_offset(self):
        class Connection:
            fetchrow = AsyncMock(return_value={key: 0 for key in ('total_tokens','input_tokens','output_tokens','cache_read_tokens','cache_creation_tokens','request_count')})
            fetch = AsyncMock(side_effect=[[], [], []])
        class Acquire:
            async def __aenter__(self): return connection
            async def __aexit__(self, *args): return False
        class Pool:
            def acquire(self): return Acquire()
        connection = Connection()
        with patch.object(database, 'get_pool', AsyncMock(return_value=Pool())):
            await database.get_token_usage_summary(days=180, timezone_hours=8)
        daily = connection.fetch.await_args_list[1]
        self.assertIn("created_at AT TIME ZONE 'UTC'", daily.args[0])
        self.assertIn("$2::int * INTERVAL '1 hour'", daily.args[0])
        self.assertEqual(daily.args[1:], (180, 8))


@unittest.skipUnless(shutil.which('node'), 'Node.js is required')
class UsageCalendarTests(unittest.TestCase):
    def test_ranking_uses_request_ratios_and_keeps_token_details(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / 'static/js/dashboard.js').read_text()
        renderer = 'function renderModelRanking(' + source.split('function renderModelRanking(',1)[1].split('function renderUsageLogs(',1)[0]
        result = subprocess.run(['node','-e', r"""
const assert = require('node:assert/strict');
const elements = {'usage-ranking-body':{innerHTML:''},'usage-ranking-count':{textContent:''}};
const byId = id => elements[id];
const usageNumber = value => Math.max(0, Number(value) || 0);
const fmtToken = value => String(value);
const escHtml = value => String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
""" + renderer + r"""
const rows = [{model:'small',request_count:25,total_tokens:900},{model:'<b>large</b>',request_count:100,total_tokens:100,input_tokens:70,output_tokens:30},{model:'zero',request_count:0}];
renderModelRanking({model_ranking:rows});
const html = elements['usage-ranking-body'].innerHTML;
assert.ok(html.indexOf('&lt;b&gt;large') < html.indexOf('small'));
assert.ok(html.includes('width:100%'));
assert.ok(html.includes('width:25%'));
assert.ok(html.includes('width:0%'));
assert.ok(html.includes('输入 70 · 输出 30 · 总计 100 tokens'));
assert.ok(!html.includes('<b>large</b>'));
assert.equal(rows[0].model,'small','sorting does not mutate source');
renderModelRanking({model_ranking:[]});
assert.ok(elements['usage-ranking-body'].innerHTML.includes('暂无用量记录'));
"""], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_calendar_has_180_days_monday_rows_and_real_token_levels(self):
        source = (Path(__file__).resolve().parents[1] / 'static/js/usage-paper.js').read_text()
        helpers = 'function usageNumber(' + source.split('function usageNumber(',1)[1].split('function openUsageNote(',1)[0]
        calendar = 'function usageCalendar(' + source.split('function usageCalendar(',1)[1].split('function renderUsageHeatmap(',1)[0]
        result = subprocess.run(['node','-e', helpers + calendar + r"""
const assert = require('node:assert/strict');
const data = {today:'2024-03-01',daily_usage:[
 {day:'2024-02-29',total_tokens:100,request_count:4},
 {day:'2024-03-01',total_tokens:400,request_count:9},
 {day:'2024-03-02',total_tokens:999999},
]};
const c = usageCalendar(data);
const actual = c.cells.filter(d=>!d.outside);
assert.equal(actual.length,180);
assert.equal(actual.at(-1).key,'2024-03-01');
assert.equal(actual.find(d=>d.key==='2024-02-29').level,1);
assert.equal(actual.at(-1).level,4);
assert.equal(actual.at(-1).requests,9);
assert.equal(c.cells.length,c.weeks*7);
assert.equal(new Date(c.cells[0].key+'T00:00:00Z').getUTCDay(),1);
const empty = usageCalendar({today:'2026-01-01',daily_usage:[]});
assert.equal(empty.cells.filter(d=>!d.outside).length,180);
assert.ok(empty.cells.every(d=>d.level===0));
assert.equal(usageNumber(-4),0);
assert.equal(usageNumber('bad'),0);
"""], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
