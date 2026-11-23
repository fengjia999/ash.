/* Provider activation keeps the existing API and credential handling. */
const settingsProviderBusy = new Set();

async function setSettingsProviderActive(route, id, enabled) {
    const profiles = route === 'anthropic' ? anthropicProviderProfiles : openAiProviderProfiles;
    const profile = profiles.find(item => Number(item.id) === Number(id));
    if (!profile || settingsProviderBusy.has(route)) {
        return;
    }
    const report = route === 'anthropic' ? showAnthropicProviderMsg : showOpenAiProviderMsg;
    const reload = route === 'anthropic' ? loadAnthropicProviders : loadOpenAiProviders;
    settingsProviderBusy.add(route);
    const list = byId(route + '-provider-list');
    list.querySelectorAll('button, input').forEach(input => { input.disabled = true; });
    report('正在保存活跃供应商…');
    try {
        // Activation uses its dedicated endpoint: never overwrite edited names or keys.
        await saveDashboardJson('/api/' + route + '-providers/' + id + (enabled ? '/activate' : ''), {
            method: enabled ? 'POST' : 'PUT',
            headers: {'Content-Type': 'application/json'},
            ...(enabled ? {} : {body: JSON.stringify({name: profile.name, api_url: profile.api_url, is_active: false})}),
        });
        report('');
        await reload();
    } catch (error) {
        report('保存失败：' + error.message);
    } finally {
        settingsProviderBusy.delete(route);
        list.querySelectorAll('button, input').forEach(input => { input.disabled = false; });
    }
}

function toggleSettingsProviderEditor(route, id, button) {
    const form = byId(route + '-provider-editor-' + id);
    form.hidden = !form.hidden;
    button.setAttribute('aria-expanded', String(!form.hidden));
    button.textContent = form.hidden ? '编辑' : '取消';
    if (!form.hidden) form.querySelector('input:not([hidden])').focus();
}

function renderSettingsProviders(route, profiles) {
    const container = byId(route + '-provider-list');
    if (!container) return;
    if (!profiles.length) {
        container.innerHTML = '<div class="openai-provider-empty">暂无预设</div>';
        return;
    }
    const prefix = route === 'anthropic' ? 'anthropic' : 'openai';
    const action = route === 'anthropic' ? 'Anthropic' : 'OpenAi';
    container.innerHTML = profiles.map(profile => {
        const id = Number(profile.id), active = Boolean(profile.is_active);
        return `<details class="openai-provider-item${active ? ' is-active' : ''}" data-provider-id="${id}">
            <summary><span class="provider-status-dot" aria-hidden="true"></span><span class="provider-summary-name">${escHtml(profile.name)}</span>${active ? '<span class="provider-active-mark">活跃</span>' : ''}<svg class="provider-summary-chevron" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="m6 9 6 6 6-6"/></svg></summary>
            <div class="provider-preview">
                <p class="provider-address">${escHtml(profile.api_url)}</p>
                <div class="provider-row-actions">
                    <button type="button" class="btn${active ? '' : ' btn-primary'}" onclick="setSettingsProviderActive('${route}',${id},${!active})">${active ? '停用' : '设为活跃'}</button>
                    <button type="button" class="btn" aria-expanded="false" aria-controls="${route}-provider-editor-${id}" onclick="toggleSettingsProviderEditor('${route}',${id},this)">编辑</button>
                    <button type="button" class="btn btn-danger" onclick="delete${action}Provider(${id})">删除</button>
                </div>
            </div>
            <div class="provider-editor" id="${route}-provider-editor-${id}" hidden>
                <div class="provider-form-grid">
                    <label class="heartbeat-setting-field"><span>名称</span><input id="${prefix}ProviderName-${id}" class="control-input" maxlength="80" value="${escHtml(profile.name)}" autocomplete="off"></label>
                    <label class="heartbeat-setting-field"><span>地址</span><input type="url" id="${prefix}ProviderUrl-${id}" class="control-input" value="${escHtml(profile.api_url)}" autocomplete="url"></label>
                    <label class="heartbeat-setting-field"><span>密钥</span><input type="password" id="${prefix}ProviderKey-${id}" class="control-input" placeholder="${escHtml(profile.api_key_hint || '填写密钥')}" autocomplete="new-password"></label>
                </div>
                <input type="checkbox" id="${prefix}ProviderActive-${id}" ${active ? 'checked' : ''} hidden>
                <div class="provider-form-actions"><button type="button" class="btn btn-primary" onclick="save${action}Provider(${id})">保存</button></div>
            </div>
        </details>`;
    }).join('');
}
