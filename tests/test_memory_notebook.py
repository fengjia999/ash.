import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("node"), "Node.js is required")
class MemoryNotebookTests(unittest.TestCase):
    def run_script(self, scenario):
        source = (ROOT / "static/js/dashboard.js").read_text()
        source += "\n" + (ROOT / "static/js/memory-notebook.js").read_text()
        harness = r"""
const assert = require('node:assert/strict');
const elements = {'diary-calendar-flipper': {appendChild(){},addEventListener(){}}};
const document = {
    createElement: () => ({setAttribute(){}}),
    addEventListener: () => {},
    getElementById: id => elements[id] || null,
    querySelector: () => null,
};
const window = {addEventListener: () => {}, location: {assign: () => {}}};
"""
        result = subprocess.run(
            ["node", "-"], input=harness + source + "\n(async () => {\n" + scenario
            + "\n})().catch(error => {console.error(error); process.exitCode = 1;});",
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_same_day_order_and_undated_diaries_remain_accessible(self):
        self.run_script(r"""
longTermMemories = [
    {id: 8, diary_date: '2024-02-29'}, {id: 3, diary_date: '2024-02-29'},
    {id: 4, diary_date: '2024-02-30'}, {id: 6, title: '2024-03-01 的日记'},
    {id: 5, diary_date: ''}
];
assert.deepEqual(diaryNotebookEntries('2024-02-29').map(d => d.id), [3, 8]);
assert.deepEqual(diaryNotebookEntries('').map(d => d.id), [4, 5]);
assert.deepEqual(diaryNotebookEntries('2024-03-01').map(d => d.id), [6]);
renderDiaryNotebook = () => {};
diaryNotebookMonth = '2024-01';
selectDiaryNotebookMonth('2024-02');
assert.equal(diaryNotebookDay, '2024-02-29');
diaryNotebookMonth = '2026-12';
selectDiaryNotebookMonth('2027-01');
assert.equal(diaryNotebookMonth, '2027-01');
assert.equal(diaryNotebookDay, '2027-01-01');
for (const value of ['', '2027-13', '0000-01', '2027-1']) selectDiaryNotebookMonth(value);
assert.equal(diaryNotebookMonth, '2027-01');
""")

    def test_late_full_text_response_cannot_replace_the_selected_page(self):
        self.run_script(r"""
document.createElement = () => ({textContent:'', append(){}});
const makeCard = () => {
    const body = {replaceChildren(content){this.content=content;}, prepend(){}};
    return {open:true,isConnected:true,dataset:{},querySelector:()=>body,body};
};
const oldCard=makeCard(), selectedCard=makeCard();
let finishOld;
fetch = async url => {
    if (url.endsWith('/1')) return new Promise(resolve => { finishOld = resolve; });
    return new Response(JSON.stringify({content:'Selected full text'}));
};
const olderRead = readNotebookDiary(oldCard,1);
++diaryNotebookRequest;
await readNotebookDiary(selectedCard,2);
finishOld(new Response(JSON.stringify({content:'Old full text'})));
await olderRead;
assert.equal(selectedCard.body.content.textContent,'Selected full text');
assert.equal(selectedCard.dataset.loaded,'true');
assert.equal(oldCard.body.content.textContent,'加载中…');
assert.equal(oldCard.dataset.loaded,undefined);
let calls=0;
fetch=async()=>{calls++;throw new Error('must not fetch folded or cached cards');};
await readNotebookDiary({open:false},3);
await readNotebookDiary(selectedCard,2);
assert.equal(calls,0);
""")

    def test_fixed_directory_shows_three_then_expands(self):
        self.run_script(r"""
const rows = Array.from({length: 7}, (_, i) => ({id: i+1, content: 'memory-' + i}));
const folded = renderMemoryShelf(rows);
assert.ok(folded.includes('7 条固定记忆') && folded.includes('展开其余 4 条'));
assert.ok(folded.includes('memory-2') && !folded.includes('memory-3'));
fixedMemoryStackExpanded = true;
assert.ok(renderMemoryShelf(rows).includes('memory-6'));
""")
