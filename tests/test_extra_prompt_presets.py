import json
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import database
import main


PRESET = dict(id=11, title="常用格式", content="使用简洁的中文。", position="after",
              frequency="repeat", interval_turns=3, locked=False)


def pool_for(conn):
    conn.transaction = MagicMock()
    conn.transaction.return_value.__aenter__ = AsyncMock()
    conn.transaction.return_value.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool


class PresetApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_save_retains_configuration_but_not_conversation_state(self):
        request = MagicMock(json=AsyncMock(return_value={
            **PRESET, "source_id": 99, "injection_count": 20, "conversation_id": 7,
        }))
        save = AsyncMock(return_value=PRESET)
        with patch.object(main, "save_extra_prompt_preset", save):
            result = await main.api_create_extra_prompt_preset(request)
        self.assertEqual(PRESET, result["preset"])
        save.assert_awaited_once_with("常用格式", "使用简洁的中文。", "after", False, "repeat", 3)

    async def test_invalid_presets_are_rejected_without_saving(self):
        for payload in ([], {}, {**PRESET, "title": " "}, {**PRESET, "position": "system"},
                        {**PRESET, "locked": "false"}, {**PRESET, "interval_turns": -1}):
            with self.subTest(payload=payload), patch.object(main, "save_extra_prompt_preset", AsyncMock()) as save:
                response = await main.api_create_extra_prompt_preset(MagicMock(json=AsyncMock(return_value=payload)))
                self.assertEqual(400, response.status_code)
                save.assert_not_awaited()

    async def test_update_missing_delete_missing_and_apply_missing_are_404(self):
        with patch.object(main, "save_extra_prompt_preset", AsyncMock(return_value=None)):
            result = await main.api_update_extra_prompt_preset(11, MagicMock(json=AsyncMock(return_value=PRESET)))
            self.assertEqual(404, result.status_code)
        with patch.object(main, "delete_extra_prompt_preset", AsyncMock(return_value=False)):
            self.assertEqual(404, (await main.api_delete_extra_prompt_preset(11)).status_code)
        with patch.object(main, "apply_extra_prompt_preset", AsyncMock(side_effect=ValueError("会话不存在"))):
            self.assertEqual(404, (await main.api_apply_extra_prompt_preset(7, 11)).status_code)

    async def test_old_backup_has_empty_preset_library(self):
        payload = {"kind": "memory_gateway_backup", "schema_version": 18,
                   **{key: [] for key in database.GATEWAY_BACKUP_TABLES if key != "extra_prompt_presets"}}
        restore = AsyncMock(return_value={})
        with patch.object(main, "MEMORY_ENABLED", True), patch.object(main, "restore_gateway_backup_data", restore):
            result = await main.import_memories(MagicMock(json=AsyncMock(return_value=payload)), include_messages=True)
        self.assertEqual("done", result["status"])
        self.assertEqual([], restore.await_args.args[0]["extra_prompt_presets"])

    async def test_preset_survives_backup_without_history(self):
        payload = {"kind": "memory_gateway_backup", "schema_version": 19,
                   **{key: [] for key in database.GATEWAY_BACKUP_TABLES}}
        payload["extra_prompt_presets"] = [PRESET]
        filtered = database.gateway_backup_without_messages(payload)
        self.assertEqual([PRESET], filtered["extra_prompt_presets"])
        spec = database.GATEWAY_BACKUP_TABLES["extra_prompt_presets"]
        self.assertIn("extra_prompt_presets", database.GATEWAY_BACKUP_INSERT_ORDER)
        self.assertIn("extra_prompt_presets", database.GATEWAY_BACKUP_DELETE_ORDER)
        self.assertNotIn("source_id", spec["columns"])


class PresetStorageTests(unittest.IsolatedAsyncioTestCase):
    async def test_application_copies_configuration_and_resets_injection_state(self):
        copied = {**PRESET, "id": 31, "conversation_id": 7, "source_id": None,
                  "injection_count": 0, "turns_since_injection": 0}
        conn = MagicMock(fetchval=AsyncMock(return_value=7),
                         fetchrow=AsyncMock(side_effect=[PRESET, None, copied]))
        with patch.object(database, "get_pool", AsyncMock(return_value=pool_for(conn))):
            result = await database.apply_extra_prompt_preset(7, 11)
        self.assertTrue(result["created"])
        self.assertEqual(0, result["prompt"]["injection_count"])
        insert = conn.fetchrow.await_args_list[-1]
        self.assertEqual((7, "常用格式", "使用简洁的中文。", "after", False, "repeat", 3), insert.args[1:])
        self.assertNotIn("preset_id", insert.args[0])
        self.assertNotIn("injection_count", insert.args[0])
        self.assertIn("FOR UPDATE", conn.fetchval.await_args.args[0])

    async def test_repeated_application_reuses_existing_copy(self):
        existing = {**PRESET, "id": 31, "conversation_id": 7, "injection_count": 4}
        conn = MagicMock(fetchval=AsyncMock(return_value=7),
                         fetchrow=AsyncMock(side_effect=[PRESET, existing]))
        with patch.object(database, "get_pool", AsyncMock(return_value=pool_for(conn))):
            result = await database.apply_extra_prompt_preset(7, 11)
        self.assertFalse(result["created"])
        self.assertEqual(4, result["prompt"]["injection_count"])
        self.assertEqual(2, conn.fetchrow.await_count)

    async def test_delete_only_removes_library_entry(self):
        conn = MagicMock(execute=AsyncMock(return_value="DELETE 1"))
        with patch.object(database, "get_pool", AsyncMock(return_value=pool_for(conn))):
            self.assertTrue(await database.delete_extra_prompt_preset(11))
        conn.execute.assert_awaited_once_with("DELETE FROM extra_prompt_presets WHERE id=$1", 11)


@unittest.skipUnless(shutil.which("node"), "Node.js required")
class PresetUiTests(unittest.TestCase):
    def test_editor_application_duplicates_and_conversation_switch(self):
        html = (Path(__file__).resolve().parents[1] / "static/js/conversation-prompts.js").read_text().replace('promptConversationId', 'currentConvId')
        functions = html.split("async function loadExtraPromptPresets() {", 1)[1].split("function loadExtraPrompts() {", 1)[0]
        functions = "async function loadExtraPromptPresets() {" + functions
        harness = r"""
const assert = require('node:assert/strict');
const nodes = new Proxy({}, {get:(map,id) => map[id] ||= {value:'',checked:false,textContent:'',innerHTML:''}});
const document = {getElementById:id=>nodes[id],querySelectorAll:()=>[]};
let currentConvId=7, extraPromptRequestVersion=1, extraPromptPresetsRequestVersion=0;
let extraPromptEditorVersion=0;
let extraPromptPresets=PRESET_DATA, editingExtraPromptPresetId=null, extraPromptPresetBusy=false;
let resets=0, reloads=0, calls=[], finish, alerts=[];
const esc=String, alert=message=>alerts.push(message), confirm=()=>true;
const resetExtraPromptEditor=()=>{resets++; editingExtraPromptPresetId=null;};
const toggleExtraPromptInterval=()=>{};
const loadExtraPrompts=async()=>{reloads++;};
const upsertExtraPrompt=()=>{reloads++;};
const renderExtraPrompts=()=>{};
const extraPromptPayload=()=>({...extraPromptPresets[0],source_id:99});
let api=async(url,options)=>{calls.push([url, options]);return new Promise(resolve=>{finish=resolve;});};
""".replace("PRESET_DATA", json.dumps([PRESET], ensure_ascii=False))
        assertions = r"""
(async()=>{
editExtraPromptPreset(11);
assert.equal(editingExtraPromptPresetId,11);
assert.equal(nodes.extraPromptInterval.value,3);
assert.equal(nodes.extraPromptPosition.value,'after');
assert.equal(nodes.extraPromptLocked.checked,false);
const first=applyExtraPromptPreset(11);
await applyExtraPromptPreset(11);
assert.equal(calls.length,1);
assert.equal(calls[0][0],'/api/conversations/7/extra-prompt-presets/11');
currentConvId=8; extraPromptRequestVersion++;
finish({ok:true,json:async()=>({created:true,prompt:{id:31,locked:false}})});
await first;
assert.equal(reloads,0);
assert.equal(extraPromptPresetBusy,false);
const second=applyExtraPromptPreset(11);
finish({ok:true,json:async()=>({created:false,prompt:{id:31,locked:false}})});
await second;
assert.equal(reloads,1);
assert.match(nodes.extraPromptPresetStatus.textContent,/已有/);
let written;
api=async(url,options)=>{
 if(options){written=JSON.parse(options.body);assert.equal(options.method,'PUT');
 assert.equal(url,'/api/extra-prompt-presets/11');return {ok:true,json:async()=>({})};}
 return {ok:true,json:async()=>({presets:extraPromptPresets})};
};
await saveExtraPromptPreset();
assert.equal(written.interval_turns,3);
assert.equal(written.source_id,undefined);
assert.equal(editingExtraPromptPresetId,null);
api=async()=>({ok:false,json:async()=>({error:'保存失败'})});
await saveExtraPromptPreset();
assert.deepEqual(alerts,['保存失败']);
assert.equal(extraPromptPresetBusy,false);
})().catch(e=>{console.error(e);process.exitCode=1;});
"""
        result = subprocess.run(["node", "-"], input=harness + functions + assertions,
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
