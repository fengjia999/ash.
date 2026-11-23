import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which("node"), "Node.js is required for browser logic tests")
class DashboardSavingTests(unittest.TestCase):
    def test_pending_review_identifies_target_and_highlights_separate_changes(self):
        self.run_browser_test(r"""
const before = '她喜欢蓝色，也喜欢散步。她想去海边。';
const after = '她喜欢绿色，也喜欢散步。她去了海边。';
const diff = pendingInlineDiff(before, after);
assert.ok(diff.before.includes('<del class="pending-diff-removed">蓝</del>'));
assert.ok(diff.after.includes('<mark class="pending-diff-added">绿</mark>'));
assert.ok(diff.after.includes('，也喜欢散步。她'));
assert.ok(!diff.after.includes('<mark class="pending-diff-added">绿色，也喜欢散步。'));
assert.equal(pendingInlineDiff('🙂<script>', '🙂<img>').after.includes('<img>'), false);
standingBlocks = [{id: 7, status: 'active', title: '<旅行>', content: before}];
const html = renderPendingStandingMemoryCard({id: 30, content: after, metadata: {
    pending_operation: 'edit', target_block_id: 7, source_diary_ids: [1, 2]
}});
assert.ok(html.includes('查看原记忆 #7 · &lt;旅行&gt;'));
assert.ok(html.includes('openStandingMemoryEditor(7)'));
assert.ok(html.includes('来源日记 #1、#2'));
const same = '保留的长句。'.repeat(1500);
const large = pendingInlineDiff('开头甲。' + same + '结尾乙。', '开头丙。' + same + '结尾丁。');
assert.ok(large.after.includes(same));
assert.ok(!large.after.includes('<mark class="pending-diff-added">开头丙。' + same));
assert.ok(large.after.length < same.length + 300);
""")

    def test_import_skips_message_arrays_by_default_before_upload(self):
        self.run_browser_test(r"""
let confirmation = '', uploaded, endpoint;
window.confirm = text => { confirmation = text; return true; };
globalThis.setInterval = () => 42;
globalThis.clearInterval = () => {};
showImportResult = () => {};
resetJsonPreview = () => {};
const messages = [{id: 9, content: 'Large history'}];
pendingJsonData = {kind: 'memory_gateway_backup', context_messages: messages,
    conversation_extra_prompt_injections: [{message_id: 9}],
    conversations: [{id: 7, handoff_summary: 'Keep summary'}],
    long_term_memories: [{content: 'Keep diary'}]};
authFetch = async (url, options) => {
    endpoint = url;
    uploaded = JSON.parse(options.body);
    return new Response(JSON.stringify({kind: 'memory_gateway_backup', restored: {context_messages: 0}}));
};
await confirmJsonImport();
assert.equal(endpoint, '/import/memories?include_messages=false');
assert.deepEqual(uploaded.context_messages, []);
assert.deepEqual(uploaded.conversation_extra_prompt_injections, []);
assert.equal(uploaded.conversations[0].handoff_summary, 'Keep summary');
assert.equal(uploaded.long_term_memories[0].content, 'Keep diary');
assert.ok(confirmation.includes('本次不恢复历史消息，现有历史消息也会被清除'));
assert.equal(pendingJsonData.context_messages, messages);
// A checked option explicitly requests the original full history.
elements['restore-history-messages'] = {checked: true};
await confirmJsonImport();
assert.equal(endpoint, '/import/memories?include_messages=true');
assert.deepEqual(uploaded.context_messages, messages);
assert.equal(uploaded.conversation_extra_prompt_injections.length, 1);
assert.ok(confirmation.includes('包含备份中的历史消息'));
""")

    def test_history_options_default_to_lightweight_export_and_import(self):
        self.run_browser_test(r"""
const button = elements['export-download'] = {disabled: false};
elements['export-progress'] = {};
const frame = elements['export-download-frame'] = {};
authFetch = async () => new Response(JSON.stringify({status: 'completed', stage: 'memories'}));
doExport();
const lightweight = new URL(frame.src, 'https://ash.test');
button.disabled = false;
elements['export-history-messages'] = {checked: true};
doExport();
const full = new URL(frame.src, 'https://ash.test');
assert.equal(lightweight.pathname, '/export/memories');
assert.equal(lightweight.searchParams.get('include_messages'), 'false');
assert.equal(full.searchParams.get('include_messages'), 'true');
assert.notEqual(lightweight.searchParams.get('export_id'), full.searchParams.get('export_id'));
elements.jsonInput = {value: JSON.stringify({kind: 'memory_gateway_backup', schema_version: 18,
    context_messages: [{id: 1}], conversations: [{id: 7, handoff_summary: 'Summary'}]})};
const preview = elements.jsonPreview = {innerHTML: '', classList: {add: () => {}, remove: () => {}}};
await previewJson();
assert.ok(preview.innerHTML.includes('恢复历史消息（1 条，默认跳过）'));
assert.equal(/id="restore-history-messages"[^>]*\bchecked\b/.test(preview.innerHTML), false);
assert.ok(preview.innerHTML.includes('现有历史消息会被清除'));
elements.jsonInput.value = JSON.stringify({kind: 'memory_gateway_backup', schema_version: 18,
    backup_options: {include_messages: false}, context_messages: []});
await previewJson();
assert.ok(preview.innerHTML.includes('轻量备份'));
assert.ok(/id="restore-history-messages"[^>]*disabled/.test(preview.innerHTML));
""")

    def test_backup_preview_checks_new_settings_and_reports_notes(self):
        self.run_browser_test(r"""
let error = '';
showImportResult = (_, text) => { error = text; };
elements.jsonInput = {value: ''};
const preview = elements.jsonPreview = {innerHTML: '', classList: {add: () => {}, remove: () => {}}};
const payload = {kind: 'memory_gateway_backup', schema_version: 21,
    identity_presets: [{id: 1, assistant_name: '小灰'}], flow_memory_settings: [{id: 1, max_items: 37}],
    cover_notes: [{id: 18, content: '下次见 👀'}]};
elements.jsonInput.value = JSON.stringify(payload);
await previewJson();
assert.ok(preview.innerHTML.includes('包含人物预设和流动记忆设置'));
assert.ok(preview.innerHTML.includes('便签 1 张'));
assert.equal(pendingJsonData.identity_presets[0].assistant_name, '小灰');
delete payload.flow_memory_settings;
elements.jsonInput.value = JSON.stringify(payload);
await previewJson();
assert.ok(error.includes('备份缺少人物预设或流动记忆设置'));
assert.equal(pendingJsonData, null);
payload.schema_version = 20; delete payload.identity_presets;
elements.jsonInput.value = JSON.stringify(payload);
await previewJson();
assert.ok(preview.innerHTML.includes('保留当前设置'));
assert.ok(preview.innerHTML.includes('便签 1 张'));
""")

    def test_restore_deduplicates_submission_shows_wait_and_keeps_payload_snapshot(self):
        self.run_browser_test(r"""
window.confirm = () => true;
let tick, cleared = false, message = '', finish, calls = 0;
globalThis.setInterval = callback => { tick = callback; return 42; };
globalThis.clearInterval = id => { assert.equal(id, 42); cleared = true; };
showImportResult = (_, text) => { message = text; };
resetJsonPreview = () => { pendingJsonData = null; };
const button = elements['confirm-json-import'] = {};
pendingJsonData = {kind: 'memory_gateway_backup', long_term_memories: [{metadata: {}}]};
authFetch = (_, options) => {
    calls++;
    assert.equal(JSON.parse(options.body).long_term_memories.length, 1);
    return new Promise(resolve => { finish = resolve; });
};
const first = confirmJsonImport();
await confirmJsonImport();
assert.equal(calls, 1);
assert.equal(button.disabled, true);
assert.ok(message.includes('已等待 0 秒'));
const realNow = Date.now;
Date.now = () => realNow() + 31000;
tick();
Date.now = realNow;
assert.ok(message.includes('尚未确认完成'));
pendingJsonData = null;
finish(new Response(JSON.stringify({kind: 'memory_gateway_backup', restored: {context_messages: 405}})));
await first;
assert.ok(message.includes('恢复完成'));
assert.ok(message.includes('日记 1 篇'));
assert.equal(button.disabled, false);
assert.equal(jsonImportInProgress, false);
assert.equal(timers.size, 0);
assert.equal(cleared, true);
""")

    def test_restore_browser_timeout_reports_uncertain_result_and_releases_controls(self):
        self.run_browser_test(r"""
window.confirm = () => true;
globalThis.setInterval = () => 42;
globalThis.clearInterval = () => {};
let message = '';
showImportResult = (_, text) => { message = text; };
pendingJsonData = {kind: 'memory_gateway_backup'};
const button = elements['confirm-json-import'] = {};
authFetch = (_, options) => new Promise((resolve, reject) => {
    options.signal.addEventListener('abort', () => reject(new Error('aborted')));
});
const request = confirmJsonImport();
[...timers.values()][0]();
await request;
assert.ok(message.includes('结果尚未确认'));
assert.equal(message.includes('已回滚'), false);
assert.equal(button.disabled, false);
assert.equal(jsonImportInProgress, false);
assert.equal(timers.size, 0);
assert.ok(pendingJsonData);
""")

    def test_restore_server_failure_keeps_preview_and_clears_wait_timer(self):
        self.run_browser_test(r"""
window.confirm = () => true;
let cleared = false, message = '';
globalThis.setInterval = () => 42;
globalThis.clearInterval = () => { cleared = true; };
showImportResult = (_, text) => { message = text; };
pendingJsonData = {kind: 'memory_gateway_backup'};
authFetch = async () => new Response(JSON.stringify({error: '等待数据库锁超过 30 秒，恢复已回滚'}));
await confirmJsonImport();
assert.ok(message.includes('恢复已回滚'));
assert.ok(pendingJsonData);
assert.equal(jsonImportInProgress, false);
assert.equal(cleared, true);
assert.equal(timers.size, 0);
""")

    def test_keyword_editor_reopens_current_unsaved_diary_draft(self):
        self.run_browser_test(r"""
globalThis.requestAnimationFrame = callback => callback();
const modal = {contains: () => false, classList: {contains: name => name === 'open', add: () => {}, remove: () => {}}, setAttribute: () => {}};
elements['long-term-memory-editor-modal'] = modal;
elements['long-term-summary-modal'] = modal;
elements['long-term-summary-content'] = {value: '', focus: () => {}};
elements['long-term-summary-msg'] = {textContent: ''};
elements['long-term-memory-title'] = {value: 'Draft title'};
elements['long-term-memory-content'] = {value: 'Unsaved diary text'};
elements['long-term-memory-date'] = {value: '2026-10-08'};
elements['long-term-memory-author'] = {value: 'user'};
elements['long-term-summary-generate'] = {};
elements['long-term-summary-save'] = {};
renderLongTermSummaryPreview = () => {};
authFetch = async () => {throw new Error('must not fetch stale server data while editing');};
saveDashboardJson = async () => {throw new Error('keywords must remain part of current diary draft');};
for (const id of [7, null]) {
    longTermEditingId = id;
    ltmSummaryDraft = 'First keyword';
    await openLongTermSummaryEditor(id);
    assert.equal(elements['long-term-summary-content'].value, 'First keyword');
    elements['long-term-summary-content'].value = 'First keyword\nSecond keyword';
    await saveLongTermSummary();
    await openLongTermSummaryEditor(id);
    assert.equal(elements['long-term-summary-content'].value, 'First keyword\nSecond keyword');
    assert.equal(elements['long-term-memory-content'].value, 'Unsaved diary text');
    assert.equal(longTermSummaryTarget.id, Number(id || 0));
}
""")

    def test_diary_lists_cache_until_marked_dirty(self):
        self.run_browser_test(r"""
    renderLongTermMemories = () => {};
    renderPendingLongTermMemories = () => {};
    const calls = [];
    fetch = async url => {
        calls.push(url);
        if (url === '/api/diaries') return new Response(JSON.stringify({diaries: [{id: 2, title: 'd', diary_date: '2026-09-19', keywords: []}]}));
        if (url === '/api/diaries/pending') return new Response(JSON.stringify({pending: []}));
        throw new Error('unexpected request ' + url);
    };
    await loadDiaries();
    await loadDiaries();
    await loadDiaryPending();
    await loadDiaryPending();
    assert.deepEqual(calls, ['/api/diaries', '/api/diaries/pending']);

    applySavedDiary({id: 2, title: 'changed', diary_date: '2026-09-19', keywords: ['k']});
    assert.equal(diariesDirty, true);
    await loadDiaries();
    markDiaryPendingDirty();
    await loadDiaryPending();
    assert.deepEqual(calls, [
        '/api/diaries', '/api/diaries/pending',
        '/api/diaries', '/api/diaries/pending'
    ]);
""")


    def test_save_does_not_wait_for_reload_and_stale_reads_cannot_undo_it(self):
        self.run_browser_test(r"""
    standingEditingId = 7;
    standingBlocks = [{id: 7, status: 'active', layer: 'core', title: 'title', content: 'old'}];
    elements['memory-editor-content'] = {value: 'new'};
    elements['memory-editor-save'] = {disabled: false};
    let resolveOld;
    const paths = [];
    fetch = async (url, options) => {
        paths.push(url);
        if (options.method === 'PUT') return new Response(JSON.stringify({
            block: {...standingBlocks[0], content: 'new'}
        }));
        return new Promise(resolve => { resolveOld = resolve; });
    };
    let closed = false;
    closeStandingMemoryEditor = () => { closed = true; };
    const card = {outerHTML: ''};
    document.querySelector = () => card;
    renderStandingLists = () => { throw new Error('editing must not rebuild the whole list'); };
    renderStandingStats = () => {};
    showStandingMsg = () => {};
    const oldRead = loadStandingMemory();
    await saveStandingMemory();
    assert.equal(paths.length, 2, 'saving must not request a full list refresh');
    assert.equal(closed, true);
    assert.match(card.outerHTML, /new/);
    assert.equal(elements['memory-editor-save'].disabled, false);
    resolveOld(new Response(JSON.stringify({blocks: [{id: 7, content: 'old'}]})));
    await oldRead;
    assert.equal(standingBlocks[0].content, 'new');
    assert.equal(timers.size, 0);
""")

    def test_save_errors_are_visible_inside_the_open_editor(self):
        self.run_browser_test(r"""
    elements['memory-editor-modal'] = {classList: {contains: () => true}};
    elements['memory-editor-msg'] = {innerHTML: ''};
    elements['standing-msg'] = {innerHTML: ''};
    showStandingMsg('error', '保存结果尚未确认');
    assert.match(elements['memory-editor-msg'].innerHTML, /保存结果尚未确认/);
    assert.equal(elements['standing-msg'].innerHTML, '');
    elements['long-term-memory-editor-modal'] = {classList: {contains: () => true}};
    elements['long-term-memory-editor-msg'] = {innerHTML: ''};
    elements['long-term-msg'] = {innerHTML: ''};
    showLongTermMsg('error', 'network error');
    assert.match(elements['long-term-memory-editor-msg'].innerHTML, /network error/);
    assert.equal(elements['long-term-msg'].innerHTML, '');
""")

    def test_saved_memory_is_not_reported_as_failed_when_rendering_breaks(self):
        self.run_browser_test(r"""
    standingEditingId = 7;
    standingBlocks = [{id: 7, status: 'active', layer: 'core', title: 'title', content: 'old'}];
    elements['memory-editor-content'] = {value: 'new'};
    elements['memory-editor-save'] = {disabled: false};
    fetch = async (_url, options) => {
        assert.deepEqual(JSON.parse(options.body), {content: 'new'});
        return new Response(JSON.stringify({
            block: {...standingBlocks[0], content: 'new'}
        }));
    };
    let closed = false;
    closeStandingMemoryEditor = () => { closed = true; };
    renderStandingStats = () => { throw new Error('broken local render'); };
    const messages = [];
    showStandingMsg = (type, text) => { messages.push([type, text]); };
    const originalConsoleError = console.error;
    console.error = () => {};
    await saveStandingMemory();
    console.error = originalConsoleError;
    assert.equal(closed, true);
    assert.equal(standingBlocks[0].content, 'new');
    assert.equal(elements['memory-editor-save'].disabled, false);
    assert.deepEqual(messages, [['success', '已保存，请刷新页面查看最新内容']]);
""")

    def test_stalled_response_body_times_out_without_losing_draft(self):
        self.run_browser_test(r"""
    standingEditingId = 7;
    standingBlocks = [{id: 7, title: 'title', content: 'old'}];
    elements['memory-editor-content'] = {value: 'unsaved draft'};
    elements['memory-editor-save'] = {disabled: false};
    let message = '';
    showStandingMsg = (_, text) => { message = text; };
    closeStandingMemoryEditor = () => { throw new Error('editor must stay open'); };
    let bodyStarted;
    const readingBody = new Promise(resolve => { bodyStarted = resolve; });
    fetch = async (_, options) => ({
        status: 200, ok: true,
        text: () => new Promise((resolve, reject) => {
            options.signal.addEventListener('abort', () => reject(new Error('aborted')));
            bodyStarted();
        }),
    });
    const save = saveStandingMemory();
    await readingBody;
    assert.equal(elements['memory-editor-save'].disabled, true);
    assert.equal(timers.size, 1);
    [...timers.values()][0]();
    await save;
    assert.match(message, /操作结果尚未确认/);
    assert.equal(elements['memory-editor-content'].value, 'unsaved draft');
    assert.equal(elements['memory-editor-save'].disabled, false);
    assert.equal(standingBlocks[0].content, 'old');
    assert.equal(timers.size, 0);
""")

    def test_heartbeat_stopper_saves_confirmed_interval_and_rolls_back_failure(self):
        self.run_browser_test(r"""
    for (const id of ['heartbeatEnabled', 'heartbeatInterval', 'heartbeat-save',
        'heartbeatRoute', 'heartbeatProviderName', 'heartbeatModelName',
        'heartbeat-settings-note', 'heartbeat-settings-msg']) elements[id] = {};
    let steaming = false;
    elements['heartbeat-coffee'] = {classList: {toggle: (_, value) => { steaming = value; }}};
    const state = {enabled: false, interval_minutes: 30, effective_interval_minutes: 30,
        context_managed: true, route: 'anthropic', ready: true};
    applyHeartbeatSettings(state);
    elements.heartbeatInterval.value = '';
    elements.heartbeatEnabled.checked = true;
    let finishSave;
    fetch = async (_, options) => {
        assert.deepEqual(JSON.parse(options.body), {enabled: true, interval_minutes: 30});
        return new Promise(resolve => { finishSave = resolve; });
    };
    const saving = saveHeartbeatSettings(true);
    assert.equal(elements.heartbeatEnabled.disabled, true);
    assert.equal(steaming, false, 'steam waits for confirmed save');
    finishSave(new Response(JSON.stringify({...state, enabled: true})));
    await saving;
    assert.equal(steaming, true);
    assert.equal(elements.heartbeatInterval.value, '', 'stopper preserves interval draft');
    assert.equal(elements.heartbeatEnabled.disabled, false);
    elements.heartbeatEnabled.checked = false;
    fetch = async () => new Response(JSON.stringify({error: 'offline'}), {status: 503});
    await saveHeartbeatSettings(true);
    assert.equal(elements.heartbeatEnabled.checked, true);
    assert.equal(steaming, true);
    assert.match(elements['heartbeat-settings-msg'].textContent, /保存失败/);
""")

    def test_heartbeat_save_invalidates_old_read_and_validates_interval(self):
        self.run_browser_test(r"""
    for (const id of ['heartbeatEnabled', 'heartbeatInterval', 'heartbeat-save',
        'heartbeatRoute', 'heartbeatProviderName', 'heartbeatModelName',
        'heartbeat-settings-note', 'heartbeat-settings-msg']) elements[id] = {focus: () => {}};
    const state = {enabled: true, interval_minutes: 30, effective_interval_minutes: 30,
        context_managed: true, route: 'anthropic', ready: true};
    applyHeartbeatSettings(state);
    let oldRead;
    fetch = async (_, options) => options.method === 'PUT'
        ? new Response(JSON.stringify({...state, enabled: false}))
        : new Promise(resolve => { oldRead = resolve; });
    const read = loadHeartbeatSettings();
    elements.heartbeatEnabled.checked = false;
    await saveHeartbeatSettings(true);
    oldRead(new Response(JSON.stringify(state)));
    await read;
    assert.equal(elements.heartbeatEnabled.checked, false, 'stale read cannot reopen stopper');
    fetch = async () => { throw new Error('invalid interval must not be sent'); };
    for (const invalid of ['', '0', '1.5', '1441']) {
        elements.heartbeatInterval.value = invalid;
        await saveHeartbeatSettings();
        assert.match(elements['heartbeat-settings-msg'].textContent, /整数分钟/);
    }
""")

    def test_heartbeat_initial_load_failure_can_be_retried(self):
        self.run_browser_test(r"""
    for (const id of ['heartbeatEnabled', 'heartbeatInterval', 'heartbeat-save',
        'heartbeatRoute', 'heartbeatProviderName', 'heartbeatModelName',
        'heartbeat-settings-note', 'heartbeat-settings-msg']) elements[id] = {};
    const retry = elements['heartbeat-settings-retry'] = {hidden: true};
    fetch = async () => new Response(JSON.stringify({error: 'offline'}), {status: 503});
    await loadHeartbeatSettings();
    assert.equal(retry.hidden, false);
    assert.equal(retry.disabled, false);
    assert.equal(elements.heartbeatEnabled.disabled, true);
    let finishRead;
    fetch = async () => new Promise(resolve => {finishRead = resolve;});
    const loading = loadHeartbeatSettings();
    assert.equal(retry.disabled, true);
    assert.equal(elements['heartbeat-settings-note'].textContent, '载入中…');
    finishRead(new Response(JSON.stringify({enabled: true, interval_minutes: 45,
        effective_interval_minutes: 45, context_managed: true, route: 'anthropic', ready: true})));
    await loading;
    assert.equal(retry.hidden, true);
    assert.equal(retry.disabled, false);
    assert.equal(elements.heartbeatEnabled.disabled, false);
    assert.equal(elements.heartbeatInterval.value, 45);
    assert.equal(elements['heartbeat-settings-note'].textContent, '运行中');
""")

    def test_failed_avatar_and_stale_load_keep_the_default_and_current_photo(self):
        self.run_browser_test(r"""
    const classes = new Set();
    const button = elements['identity-avatar-user'] = {
        classList: {add: value => classes.add(value), remove: value => classes.delete(value)},
    };
    const image = elements['identity-avatar-user-image'] = {removeAttribute: () => {}};
    elements['identity-avatar-user-reset'] = {};
    identityAvatarState.user.image = 'saved photo';
    renderIdentityAvatar('user');
    image.onerror();
    assert.equal(image.hidden, true);
    assert.equal(classes.has('has-image'), false);
    assert.equal(identityAvatarState.user.image, 'saved photo');
    const snapshot = identityAvatarSnapshot();
    ++identityAvatarState.user.revision;
    identityAvatarState.user.image = 'new photo';
    applyIdentityAvatars({user_avatar: 'stale photo', assistant_avatar: ''}, snapshot);
    assert.equal(identityAvatarState.user.image, 'new photo');
    renderIdentityAvatar('user');
    image.onload();
    assert.equal(image.hidden, false);
    assert.equal(classes.has('has-image'), true);
""")

    def test_diary_editor_loads_and_saves_author_for_new_and_existing_pages(self):
        self.run_browser_test(r"""
    globalThis.requestAnimationFrame = fn => fn();
    document.body = {classList: {add: () => {}, remove: () => {}}};
    for (const id of ['long-term-memory-date', 'long-term-memory-title',
        'long-term-memory-content', 'long-term-memory-author',
        'long-term-memory-summary-preview', 'long-term-memory-editor-save']) {
        elements[id] = {value: '', focus: () => {}};
    }
    elements['long-term-memory-editor-modal'] = {
        contains: () => false, classList: {add: () => {}, remove: () => {}}, setAttribute: () => {},
    };
    showLongTermMsg = () => {};
    let saved;
    applySavedDiary = diary => { saved = diary; };
    const writes = [];
    fetch = async (url, options = {}) => {
        if (!options.method) return new Response(JSON.stringify({
            id: 7, title: 'Existing', content: 'Assistant story', author_role: 'assistant',
        }));
        const data = JSON.parse(options.body);
        writes.push(data);
        return new Response(JSON.stringify({diary: {id: 7, ...data}}));
    };
    await openLongTermMemoryEditor();
    assert.equal(elements['long-term-memory-author'].value, 'user');
    elements['long-term-memory-title'].value = 'My day';
    elements['long-term-memory-content'].value = 'I went to the beach.';
    await saveLongTermMemory();
    assert.equal(writes[0].author_role, 'user');
    assert.equal(saved.author_role, 'user');
    longTermMemories = [{id: 7}];
    await openLongTermMemoryEditor(7);
    assert.equal(elements['long-term-memory-author'].value, 'assistant');
    elements['long-term-memory-author'].value = 'user';
    await saveLongTermMemory();
    assert.equal(writes[1].author_role, 'user');
    assert.equal(diaryAuthorLabel(saved), '用户的日记');
    assert.equal(diaryAuthorLabel({}), '助手的日记');
""")



    def test_memory_approval_updates_local_state_and_preserves_children_on_edit(self):
        self.run_browser_test(r"""
document.querySelectorAll = () => [];
renderStandingStats = () => {};
renderStandingLists = () => {};
showStandingMsg = () => {};
let reads = 0;
loadStandingMemory = async () => { reads++; };
standingBlocks = [
    {id: 1, status: 'active', content: 'old'},
    {id: 2, status: 'active', parent_id: 1},
    {id: 3, status: 'pending', metadata: {pending_operation: 'edit', target_block_id: 1}}
];
authFetch = async () => new Response(JSON.stringify({operation: 'edit', block: {id: 1, status: 'active', content: 'new'}}));
await approveStandingMemory(3);
assert.equal(reads, 0);
assert.equal(standingBlocks.find(b => b.id === 1).content, 'new');
assert.equal(standingBlocks.find(b => b.id === 2).parent_id, 1);
assert.equal(standingBlocks.some(b => b.id === 3), false);
""")

    def test_memory_delete_deduplicates_requests_and_preserves_failed_item(self):
        self.run_browser_test(r"""
document.querySelectorAll = () => [];
globalThis.confirm = () => true;
renderStandingStats = () => {};
renderStandingLists = () => {};
let message = '';
showStandingMsg = (_, text) => { message = text; };
standingBlocks = [{id: 1, status: 'active'}, {id: 2, status: 'active', parent_id: 1}];
let finish, calls = 0;
authFetch = () => { calls++; return new Promise(resolve => { finish = resolve; }); };
const first = deleteStandingMemory(1);
await deleteStandingMemory(1);
assert.equal(calls, 1);
finish(new Response(JSON.stringify({error: 'busy'}), {status: 503}));
await first;
assert.equal(standingBlocks.length, 2);
assert.ok(message.includes('busy'));
authFetch = async () => new Response(JSON.stringify({status: 'ok', id: 1}));
await deleteStandingMemory(1);
assert.equal(standingBlocks.length, 1);
assert.equal(standingBlocks[0].parent_id, null);
""")

    def test_memory_delete_approval_removes_pending_and_target(self):
        self.run_browser_test(r"""
document.querySelectorAll = () => [];
globalThis.confirm = () => true;
renderStandingStats = () => {};
renderStandingLists = () => {};
showStandingMsg = () => {};
standingBlocks = [
    {id: 1, status: 'active'}, {id: 2, status: 'active', parent_id: 1},
    {id: 3, status: 'pending', metadata: {pending_operation: 'delete', target_block_id: 1}}
];
authFetch = async () => new Response(JSON.stringify({operation: 'delete', block: {id: 1}}));
await approveStandingMemory(3);
assert.deepEqual(standingBlocks, [{id: 2, status: 'active', parent_id: null}]);
""")

    def run_browser_test(self, test):
        source = (Path(__file__).resolve().parents[1] / "static/js/dashboard.js").read_text()
        source += "\n" + (Path(__file__).resolve().parents[1] / "static/js/identity-avatars.js").read_text()
        harness = r"""
const assert = require('node:assert/strict');
const elements = {};
const storage = new Map();
const localStorage = {
    getItem: key => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, value),
    removeItem: key => storage.delete(key),
};
const timers = new Map();
let nextTimer = 0;
const setTimeout = callback => { timers.set(++nextTimer, callback); return nextTimer; };
const clearTimeout = id => timers.delete(id);
const document = {
    addEventListener: () => {},
    getElementById: id => elements[id] || null,
    querySelector: () => null,
};
const window = {addEventListener: () => {}, location: {assign: () => {}}};
"""
        script = (harness + source + "\n(async () => {\n" + test
                  + "\n})().catch(error => { console.error(error); process.exitCode = 1; });")
        result = subprocess.run(
            ["node", "-"], input=script,
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
