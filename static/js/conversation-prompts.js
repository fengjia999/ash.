/* One conversation prompt editor, owned by conversation management. */
(() => {
  const api = (url, options = {}) => authFetch(url, {...options, headers:{'Content-Type':'application/json', ...options.headers}});
  async function apiJson(url, options = {}) {
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 20000);
    try {
      const response = await api(url, {...options, signal:controller.signal});
      const data = await response.json();
      if (!response.ok || data.error) throw new Error(data.error || `请求失败 (${response.status})`);
      return data;
    } finally { clearTimeout(timer); }
  }
  function esc(value) { const node=document.createElement('span'); node.textContent=value ?? ''; return node.innerHTML; }
// Prompt state
let promptConversationId = null;
let extraPromptBundle = {sources:[], prompts:[], injections:[]};
let extraPromptRequestVersion = 0;
let extraPromptPresets = [];
let editingExtraPromptPresetId = null;
let extraPromptPresetsRequestVersion = 0;
let extraPromptPresetBusy = false;
let extraPromptMutationBusy = false;
let extraPromptEditorVersion = 0;
let editingExtraPromptId = null;
let editingExtraPromptSourceId = null;
function openExtraPrompts(conversationId) {
  if (extraPromptMutationBusy || extraPromptPresetBusy) return;
  promptConversationId = Number(conversationId);
  if (!Number.isSafeInteger(promptConversationId) || promptConversationId <= 0) return;
  extraPromptBundle = {sources:[], prompts:[], injections:[]};
  resetExtraPromptEditor(false);
  setExtraPromptStatus('正在加载…');
  renderExtraPrompts();
  document.getElementById('extraPromptsModal').showModal();
  loadExtraPrompts();
  loadExtraPromptPresets();
}

async function loadExtraPromptPresets() {
  const version = ++extraPromptPresetsRequestVersion;
  try {
    const response = await api('/api/extra-prompt-presets');
    const data = await response.json();
    if (!response.ok || data.error) throw new Error(data.error || '加载预设失败');
    if (version !== extraPromptPresetsRequestVersion) return;
    extraPromptPresets = data.presets || [];
    renderExtraPromptPresets();
  } catch (err) {
    if (version === extraPromptPresetsRequestVersion) {
      document.getElementById('extraPromptPresets').textContent = err.message;
    }
  }
}

function renderExtraPromptPresets() {
  document.getElementById('extraPromptPresets').innerHTML = extraPromptPresets.length
    ? extraPromptPresets.map(preset => `
      <div class="extra-prompt-card">
        <strong>${esc(preset.title)}</strong>
        <div class="extra-prompt-meta">${preset.position === 'before' ? '消息前' : '消息后'} · ${preset.frequency === 'once' ? '仅一次' : `每 ${Number(preset.interval_turns)||1} 条`} · ${preset.locked ? '锁定' : '注入中'}</div>
        <details ontoggle="ConversationPrompts.renderExtraPromptBody(this, 'preset', ${Number(preset.id)})"><summary>查看内容</summary><div class="extra-prompt-content"></div></details>
        <div class="extra-prompt-row">
          <button class="btn btn-secondary extra-prompt-preset-action" onclick="ConversationPrompts.applyExtraPromptPreset(${Number(preset.id)})">应用到会话</button>
          <button class="btn btn-secondary extra-prompt-preset-action" onclick="ConversationPrompts.editExtraPromptPreset(${Number(preset.id)})">编辑</button>
          <button class="btn btn-secondary extra-prompt-preset-action" onclick="ConversationPrompts.deleteExtraPromptPreset(${Number(preset.id)})">删除</button>
        </div>
      </div>`).join('')
    : '';
  setExtraPromptPresetBusy(extraPromptPresetBusy);
}

function setExtraPromptPresetBusy(busy) {
  extraPromptPresetBusy = busy;
  document.querySelectorAll('.extra-prompt-preset-action').forEach(button => { button.disabled = busy; });
}

function editExtraPromptPreset(id) {
  const preset = extraPromptPresets.find(item => Number(item.id) === Number(id));
  if (!preset || extraPromptPresetBusy) return;
  resetExtraPromptEditor();
  editingExtraPromptPresetId = preset.id;
  document.getElementById('extraPromptTitle').value = preset.title;
  document.getElementById('extraPromptContent').value = preset.content;
  document.getElementById('extraPromptPosition').value = preset.position;
  document.getElementById('extraPromptFrequency').value = preset.frequency;
  document.getElementById('extraPromptInterval').value = preset.interval_turns;
  document.getElementById('extraPromptLocked').checked = preset.locked;
  document.getElementById('extraPromptEditorTitle').textContent = '编辑预设';
  document.getElementById('saveExtraPromptPresetBtn').textContent = '更新预设';
  toggleExtraPromptInterval();
}

async function saveExtraPromptPreset() {
  if (extraPromptPresetBusy) return;
  const payload = extraPromptPayload();
  if (!payload.title) return alert('请填写预设名称');
  if (!payload.content) return alert('提示词不能为空');
  // Presets keep configuration only, never conversation IDs or injection counters.
  delete payload.source_id;
  const presetId = editingExtraPromptPresetId;
  const conversationId = promptConversationId;
  const version = extraPromptRequestVersion;
  const editorVersion = extraPromptEditorVersion;
  setExtraPromptPresetBusy(true);
  try {
    const response = await api(presetId ? `/api/extra-prompt-presets/${presetId}` : '/api/extra-prompt-presets', {
      method: presetId ? 'PUT' : 'POST', body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok || data.error) throw new Error(data.error || '保存预设失败');
    if (promptConversationId === conversationId && extraPromptRequestVersion === version) {
      if (extraPromptEditorVersion === editorVersion) resetExtraPromptEditor(false);
      document.getElementById('extraPromptPresetStatus').textContent = '预设已保存，可在其他会话中应用。';
    }
    await loadExtraPromptPresets();
  } catch (err) {
    alert(err.message);
  } finally {
    setExtraPromptPresetBusy(false);
  }
}

async function applyExtraPromptPreset(id) {
  if (!promptConversationId || extraPromptPresetBusy) return;
  const conversationId = promptConversationId;
  setExtraPromptPresetBusy(true);
  try {
    const response = await api(`/api/conversations/${conversationId}/extra-prompt-presets/${id}`, {method: 'POST'});
    const data = await response.json();
    if (!response.ok || data.error) throw new Error(data.error || '应用预设失败');
    if (!data.prompt || !data.prompt.id) throw new Error('服务器未返回提示词，请重新打开面板核对');
    if (promptConversationId !== conversationId) return;
    ++extraPromptRequestVersion;
    upsertExtraPrompt(data.prompt);
    renderExtraPrompts();
    document.getElementById('extraPromptPresetStatus').textContent = !data.created
      ? '当前会话已有相同提示词块。'
      : data.prompt.locked ? '已应用；在提示词块中解锁后开始注入。' : '已应用，将按设定的频率注入。';
  } catch (err) {
    alert(err.message);
  } finally {
    setExtraPromptPresetBusy(false);
  }
}

async function deleteExtraPromptPreset(id) {
  if (extraPromptPresetBusy) return;
  const preset = extraPromptPresets.find(item => Number(item.id) === Number(id));
  if (!preset || !confirm(`删除预设「${preset.title}」？已应用到会话的提示词块会保留。`)) return;
  setExtraPromptPresetBusy(true);
  try {
    const response = await api(`/api/extra-prompt-presets/${id}`, {method: 'DELETE'});
    const data = await response.json();
    if (!response.ok || data.error) throw new Error(data.error || '删除预设失败');
    if (Number(editingExtraPromptPresetId) === Number(id)) resetExtraPromptEditor();
    await loadExtraPromptPresets();
  } catch (err) {
    alert(err.message);
  } finally {
    setExtraPromptPresetBusy(false);
  }
}

function loadExtraPrompts() {
  const conversationId = promptConversationId;
  const version = ++extraPromptRequestVersion;
  document.getElementById('captureFrontendPrompts').disabled = true;
  document.getElementById('autoInjectCapturedPrompts').disabled = true;
  return api(`/api/conversations/${conversationId}/extra-prompts`)
    .then(r => r.json().then(data => ({r, data})))
    .then(({r, data}) => {
      if (!r.ok || data.error) throw new Error(data.error || '加载失败');
      if (version !== extraPromptRequestVersion || promptConversationId !== conversationId) return;
      extraPromptBundle = data;
      renderExtraPrompts();
      setExtraPromptStatus('');
    }).catch(err => {
      if (version !== extraPromptRequestVersion || promptConversationId !== conversationId) return;
      setExtraPromptStatus('加载失败：' + err.message, 'error');
      renderExtraPrompts();
    });
}

function renderExtraPrompts() {
  document.getElementById('captureFrontendPrompts').disabled = false;
  document.getElementById('captureFrontendPrompts').checked =
    extraPromptBundle.capture_frontend_prompts !== false;
  document.getElementById('autoInjectCapturedPrompts').disabled =
    extraPromptBundle.capture_frontend_prompts === false;
  document.getElementById('autoInjectCapturedPrompts').checked =
    extraPromptBundle.auto_inject_captured_prompts !== false;
  const sources = extraPromptBundle.sources || [];
  document.getElementById('extraPromptSources').innerHTML = sources.length ? sources.map(source => `
    <div class="extra-prompt-card">
      <details ontoggle="ConversationPrompts.renderExtraPromptBody(this, 'source', ${Number(source.id)})"><summary>前端捕获 #${Number(source.id)} · ${String(source.content || '').length} 字</summary>
      <div class="extra-prompt-meta">捕获 #${source.id} · ${source.configured ? '已配置' : '未配置'} · ${source.initial_injected ? `首次已注入${source.initial_message_id ? ` · 消息 #${source.initial_message_id}` : ''}` : '首次未注入'} · ${esc(String(source.first_seen_at || '').slice(0,19))}</div>
      <textarea id="promptSource${source.id}" readonly></textarea>
      <div class="extra-prompt-row">
        <button class="btn btn-secondary" onclick="ConversationPrompts.usePromptSelection(${source.id})">用选中内容建块</button>
        <button class="btn btn-secondary extra-prompt-mutation-action" onclick="ConversationPrompts.togglePromptSourceConfigured(${source.id})">${source.configured ? '标记未配置' : '标记已配置'}</button>
      </div>
      </details>
    </div>`).join('') : '<div class="extra-prompt-empty">未捕获到 system prompt</div>';

  const prompts = extraPromptBundle.prompts || [];
  const conversationSection = document.getElementById('extraPromptConversationSection');
  if (conversationSection) conversationSection.hidden = !prompts.length;
  document.getElementById('extraPromptBlocks').innerHTML = prompts.length ? prompts.map(prompt => `
    <div class="extra-prompt-card">
      <details ontoggle="ConversationPrompts.renderExtraPromptBody(this, 'prompt', ${Number(prompt.id)})"><summary><strong>${esc(prompt.title || `提示词 #${prompt.id}`)}</strong> · ${String(prompt.content || '').length} 字</summary>
      <div class="extra-prompt-content"></div></details>
      <div class="extra-prompt-meta">${prompt.position === 'before' ? '消息前' : '消息后'} · ${prompt.frequency === 'once' ? '仅一次' : `每 ${Number(prompt.interval_turns)||1} 条`} · ${prompt.locked ? '已锁定' : '注入中'} · ${Number(prompt.injection_count)||0} 次</div>
      <div class="extra-prompt-row">
        <button class="btn btn-secondary" onclick="ConversationPrompts.editExtraPrompt(${prompt.id})">编辑</button>
        <button class="btn btn-secondary" onclick="ConversationPrompts.prepareExtraPromptPreset(${prompt.id})">存为预设</button>
        <button class="btn btn-secondary extra-prompt-mutation-action" onclick="ConversationPrompts.toggleExtraPrompt(${prompt.id})">${prompt.locked ? '解锁' : '锁定'}</button>
        <button class="btn btn-secondary extra-prompt-mutation-action" onclick="ConversationPrompts.deleteExtraPrompt(${prompt.id})">删除</button>
      </div>
    </div>`).join('') : '';

  const injections = extraPromptBundle.injections || [];
  const history = document.getElementById('extraPromptHistory');
  if (history) history.hidden = !injections.length;
  document.getElementById('extraPromptInjections').innerHTML = injections.length ? injections.slice(0,30).map(item => `
    <div class="extra-prompt-meta">${esc(item.title || `提示词 #${item.prompt_id}`)} · ${item.position === 'before' ? '消息前' : '消息后'} · 消息 #${item.message_id || '—'} · ${esc(String(item.created_at || '').slice(0,19))}</div>`).join('') : '';
  setExtraPromptMutationBusy(extraPromptMutationBusy);
}

function renderExtraPromptBody(details, kind, id) {
  if (!details.open || details.dataset.loaded) return;
  const items = kind === 'preset' ? extraPromptPresets
    : kind === 'source' ? extraPromptBundle.sources : extraPromptBundle.prompts;
  const item = (items || []).find(item => Number(item.id) === Number(id));
  if (!item) return;
  if (kind === 'source') details.querySelector('textarea').value = item.content || '';
  else details.querySelector('.extra-prompt-content').textContent = item.content || '';
  details.dataset.loaded = 'true';
}

function setExtraPromptStatus(message, state = '') {
  const status = document.getElementById('extraPromptStatus');
  status.textContent = message;
  status.dataset.state = state;
}

function setExtraPromptMutationBusy(busy) {
  extraPromptMutationBusy = busy;
  document.querySelectorAll('.extra-prompt-mutation-action').forEach(button => { button.disabled = busy; });
}

function upsertExtraPrompt(prompt) {
  const prompts = extraPromptBundle.prompts || [];
  const index = prompts.findIndex(item => Number(item.id) === Number(prompt.id));
  if (index < 0) prompts.push(prompt);
  else prompts[index] = prompt;
  extraPromptBundle.prompts = prompts;
}

async function saveExtraPromptCaptureSetting() {
  const conversationId = promptConversationId;
  const version = ++extraPromptRequestVersion;
  const capture = document.getElementById('captureFrontendPrompts');
  const inject = document.getElementById('autoInjectCapturedPrompts');
  const changes = {
    capture_frontend_prompts: capture.checked,
    auto_inject_captured_prompts: inject.checked,
  };
  capture.disabled = inject.disabled = true;
  try {
    const response = await api(`/api/conversations/${conversationId}/extra-prompt-settings`, {
      method:'PUT', body:JSON.stringify(changes)
    });
    const data = await response.json();
    if (!response.ok || data.error) throw new Error(data.error || '保存失败');
    if (promptConversationId === conversationId && version === extraPromptRequestVersion) {
      Object.assign(extraPromptBundle, changes);
    }
  } catch (err) {
    alert(err.message);
  } finally {
    if (promptConversationId === conversationId && version === extraPromptRequestVersion) renderExtraPrompts();
  }
}

function usePromptSelection(sourceId) {
  const area = document.getElementById('promptSource' + sourceId);
  const selected = area.value.slice(area.selectionStart, area.selectionEnd) || area.value;
  resetExtraPromptEditor();
  editingExtraPromptId = null;
  editingExtraPromptSourceId = sourceId;
  document.getElementById('extraPromptContent').value = selected;
  document.getElementById('extraPromptEditorTitle').textContent = '新提示词块';
}

async function togglePromptSourceConfigured(sourceId) {
  if (extraPromptMutationBusy) return;
  const source = (extraPromptBundle.sources || []).find(
    item => Number(item.id) === Number(sourceId)
  );
  if (!source) return;
  const conversationId = promptConversationId;
  setExtraPromptMutationBusy(true);
  try {
    const data = await apiJson(`/api/conversations/${conversationId}/prompt-sources/${sourceId}`, {
      method:'PUT', body:JSON.stringify({configured:!source.configured})
    });
    if (!data.source || !data.source.id) throw new Error('服务器未返回捕获内容');
    if (promptConversationId !== conversationId) return;
    ++extraPromptRequestVersion;
    extraPromptBundle.sources = (extraPromptBundle.sources || []).map(
      item => Number(item.id) === Number(sourceId) ? data.source : item
    );
    renderExtraPrompts();
    setExtraPromptStatus(data.source.configured ? '已标记为已配置。' : '已标记为未配置。');
  } catch (err) {
    if (promptConversationId === conversationId) setExtraPromptStatus('操作失败：' + err.message, 'error');
  } finally {
    setExtraPromptMutationBusy(false);
  }
}

function resetExtraPromptEditor(expanded = true) {
  extraPromptEditorVersion++;
  const editor = document.getElementById('extraPromptEditor');
  if (editor) {
    editor.open = expanded;
    if (expanded) editor.scrollIntoView?.({block: 'nearest'});
  }
  editingExtraPromptPresetId = null;
  const presetButton = document.getElementById('saveExtraPromptPresetBtn');
  if (presetButton) presetButton.textContent = '存为预设';
  editingExtraPromptId = null;
  editingExtraPromptSourceId = null;
  ['extraPromptTitle','extraPromptContent'].forEach(id => { const el=document.getElementById(id); if(el) el.value=''; });
  if (document.getElementById('extraPromptPosition')) document.getElementById('extraPromptPosition').value='before';
  if (document.getElementById('extraPromptFrequency')) document.getElementById('extraPromptFrequency').value='repeat';
  if (document.getElementById('extraPromptInterval')) document.getElementById('extraPromptInterval').value='1';
  if (document.getElementById('extraPromptLocked')) document.getElementById('extraPromptLocked').checked=true;
  if (document.getElementById('extraPromptEditorTitle')) document.getElementById('extraPromptEditorTitle').textContent='新提示词块';
  toggleExtraPromptInterval();
}

function editExtraPrompt(id) {
  const prompt = (extraPromptBundle.prompts || []).find(item => Number(item.id) === Number(id));
  if (!prompt) return;
  resetExtraPromptEditor();
  editingExtraPromptId = prompt.id;
  editingExtraPromptSourceId = prompt.source_id;
  document.getElementById('extraPromptTitle').value = prompt.title || '';
  document.getElementById('extraPromptContent').value = prompt.content || '';
  document.getElementById('extraPromptPosition').value = prompt.position;
  document.getElementById('extraPromptFrequency').value = prompt.frequency || 'repeat';
  document.getElementById('extraPromptInterval').value = Number(prompt.interval_turns) || 1;
  document.getElementById('extraPromptLocked').checked = Boolean(prompt.locked);
  document.getElementById('extraPromptEditorTitle').textContent = '编辑提示词块';
  toggleExtraPromptInterval();
}

function prepareExtraPromptPreset(id) {
  editExtraPrompt(id);
  editingExtraPromptId = null;
  editingExtraPromptSourceId = null;
  document.getElementById('extraPromptEditorTitle').textContent = '保存为预设';
  document.getElementById('extraPromptTitle').focus();
}

function toggleExtraPromptInterval() {
  const frequency = document.getElementById('extraPromptFrequency');
  const wrap = document.getElementById('extraPromptIntervalWrap');
  if (frequency && wrap) wrap.hidden = frequency.value === 'once';
}

function extraPromptPayload(prompt) {
  return prompt || {
    source_id: editingExtraPromptSourceId,
    title: document.getElementById('extraPromptTitle').value.trim(),
    content: document.getElementById('extraPromptContent').value.trim(),
    position: document.getElementById('extraPromptPosition').value,
    frequency: document.getElementById('extraPromptFrequency').value,
    interval_turns: Number(document.getElementById('extraPromptInterval').value) || 1,
    locked: document.getElementById('extraPromptLocked').checked,
  };
}

async function saveExtraPrompt() {
  if (extraPromptMutationBusy) return;
  const payload = extraPromptPayload();
  if (!payload.content) return setExtraPromptStatus('提示词不能为空', 'error');
  const conversationId = promptConversationId;
  if (!conversationId) return;
  const promptId = editingExtraPromptId;
  const editorVersion = extraPromptEditorVersion;
  const url = promptId
    ? `/api/conversations/${conversationId}/extra-prompts/${promptId}`
    : `/api/conversations/${conversationId}/extra-prompts`;
  setExtraPromptMutationBusy(true);
  setExtraPromptStatus('正在保存…');
  try {
    const data = await apiJson(url, {method: promptId ? 'PUT' : 'POST', body:JSON.stringify(payload)});
    if (!data.prompt || !data.prompt.id) throw new Error('保存响应缺少提示词，请重新打开面板核对');
    if (promptConversationId !== conversationId) return;
    ++extraPromptRequestVersion; // An older GET must not overwrite the saved result.
    upsertExtraPrompt(data.prompt);
    if (extraPromptEditorVersion === editorVersion) resetExtraPromptEditor(false);
    renderExtraPrompts();
    setExtraPromptStatus(data.prompt.locked
      ? '已保存到会话；当前已锁定，解锁后开始注入。'
      : '已保存到会话，将从后续轮次按设置注入。');
  } catch (err) {
    if (promptConversationId === conversationId) setExtraPromptStatus('保存失败：' + err.message, 'error');
  } finally {
    setExtraPromptMutationBusy(false);
  }
}

async function toggleExtraPrompt(id) {
  if (extraPromptMutationBusy) return;
  const prompt = (extraPromptBundle.prompts || []).find(item => Number(item.id) === Number(id));
  if (!prompt) return;
  const conversationId = promptConversationId;
  setExtraPromptMutationBusy(true);
  try {
    const data = await apiJson(`/api/conversations/${conversationId}/extra-prompts/${id}`, {
      method:'PUT', body:JSON.stringify({...prompt, locked:!prompt.locked})
    });
    if (!data.prompt || !data.prompt.id) throw new Error('服务器未返回提示词');
    if (promptConversationId !== conversationId) return;
    ++extraPromptRequestVersion;
    upsertExtraPrompt(data.prompt);
    renderExtraPrompts();
    setExtraPromptStatus(data.prompt.locked ? '已锁定，停止后续注入。' : '已解锁，后续轮次按设置注入。');
  } catch (err) {
    if (promptConversationId === conversationId) setExtraPromptStatus('操作失败：' + err.message, 'error');
  } finally {
    setExtraPromptMutationBusy(false);
  }
}

async function deleteExtraPrompt(id) {
  if (extraPromptMutationBusy || !confirm('删除这个提示词块？')) return;
  const conversationId = promptConversationId;
  setExtraPromptMutationBusy(true);
  try {
    await apiJson(`/api/conversations/${conversationId}/extra-prompts/${id}`, {method:'DELETE'});
    if (promptConversationId !== conversationId) return;
    ++extraPromptRequestVersion;
    extraPromptBundle.prompts = (extraPromptBundle.prompts || []).filter(item => Number(item.id) !== Number(id));
    if (Number(editingExtraPromptId) === Number(id)) resetExtraPromptEditor(false);
    renderExtraPrompts();
    setExtraPromptStatus('提示词块已删除；历史注入保持原样。');
  } catch (err) {
    if (promptConversationId === conversationId) setExtraPromptStatus('删除失败：' + err.message, 'error');
  } finally {
    setExtraPromptMutationBusy(false);
  }
}

// Public editor actions
window.ConversationPrompts = {
  open:openExtraPrompts,
  close:() => document.getElementById('extraPromptsModal').close(),
  changed:() => { extraPromptEditorVersion++; },
  applyExtraPromptPreset,
  deleteExtraPrompt,
  deleteExtraPromptPreset,
  editExtraPrompt,
  editExtraPromptPreset,
  prepareExtraPromptPreset,
  renderExtraPromptBody,
  resetExtraPromptEditor,
  saveExtraPrompt,
  saveExtraPromptCaptureSetting,
  saveExtraPromptPreset,
  toggleExtraPrompt,
  toggleExtraPromptInterval,
  togglePromptSourceConfigured,
  usePromptSelection,
};
document.getElementById('extraPromptsModal').addEventListener('close', () => {
  promptConversationId = null;
  ++extraPromptRequestVersion;
  ++extraPromptPresetsRequestVersion;
});
})();
