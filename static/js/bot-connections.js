/* Server-owned bot settings; credentials stay out of browser storage. */
(() => {
    'use strict';
    const $ = id => document.getElementById('bot-' + id);
    let loaded = false, busy = false, loading = false, statusTimer = null;
    async function request(endpoint, method = 'GET', body) {
        const response = await authFetch(endpoint, {
            method, headers: {'Content-Type':'application/json'}, cache:'no-store',
            ...(body === undefined ? {} : {body:JSON.stringify(body)}),
        });
        const data = await readJsonResponse(response);
        if (!response.ok) throw new Error(data.error || '连接操作失败');
        return data;
    }
    const api = (path = '', method = 'GET', body) => request('/api/bot-connections/imessage' + path,method,body);
    let catalogLoading = false;
    const element = (tag, className, text) => {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    };
    function connectionRow(provider, connection) {
        const row = element('button',connection ? 'bot-connection-row' : 'bot-provider-option');
        row.type = 'button';
        const destination = 'bot-' + provider.id;
        const available = provider.available && document.getElementById('section-' + destination);
        row.disabled = !available;
        if (available) row.dataset.phoneApp = destination;
        const symbol = element('span','bot-provider-symbol',provider.symbol || provider.name.slice(0,1));
        symbol.dataset.platform = provider.id; symbol.setAttribute('aria-hidden','true');
        if (provider.id === 'imessage') symbol.innerHTML = '<svg viewBox="0 0 32 32"><path d="M27 14.5c0 6-5 10.5-11.5 10.5a15 15 0 0 1-4-.5L5 27l1.4-5.3A10 10 0 0 1 4 14.5C4 8.7 9 4 15.5 4S27 8.7 27 14.5Z"/></svg>';
        row.append(symbol);
        const copy = element('span','bot-connection-copy');
        copy.append(element('strong','',connection?.name || provider.name));
        const description = connection?.account || provider.description;
        if (description) copy.append(element('small','',description));
        row.append(copy);
        row.append(element('span','bot-connection-badge',connection
            ? (connection.enabled ? '已启用' : '已停用')
            : (available ? '' : '待接入')));
        if (connection) row.querySelector('.bot-connection-badge').dataset.state = connection.enabled ? 'enabled' : 'disabled';
        if (available) { const chevron = element('span','bot-connection-chevron','›'); chevron.setAttribute('aria-hidden','true'); row.append(chevron); }
        return row;
    }
    async function loadCatalog() {
        if (catalogLoading) return;
        catalogLoading = true;
        void refreshIdentityPresetNames();
        $('list-message').textContent = '正在读取连接…';
        $('provider-message').textContent = '正在读取连接方式…';
        $('list-retry').hidden = true; $('provider-retry').hidden = true;
        try {
            const data = await request('/api/bot-connections');
            const providers = Array.isArray(data.providers) ? data.providers : [];
            const connections = Array.isArray(data.connections) ? data.connections : [];
            $('connections-list').replaceChildren(); $('provider-list').replaceChildren();
            for (const connection of connections) {
                const provider = providers.find(item => item.id === connection.provider);
                if (provider) $('connections-list').append(connectionRow(provider,connection));
            }
            if (!connections.length) {
                const empty = element('div','bot-empty');
                empty.append(element('p','','暂无连接'));
                $('connections-list').append(empty);
            }
            for (const provider of providers) {
                const row = connectionRow(provider);
                if (provider.available && connections.some(item => item.provider === provider.id)) {
                    row.querySelector('.bot-connection-badge').textContent = '管理已有连接';
                }
                $('provider-list').append(row);
            }
            $('list-message').textContent = ''; $('provider-message').textContent = '';
        } catch (error) {
            $('list-message').textContent = '读取失败：' + error.message;
            $('provider-message').textContent = '读取失败：' + error.message;
            $('list-retry').hidden = false; $('provider-retry').hidden = false;
        } finally { catalogLoading = false; }
    }
    function message(text, error = false) { $('message').textContent = text; $('message').classList.toggle('is-error',error); }
    function fill(config) {
        for (const key of ['project_id','home_user']) $(key).value = config[key] || '';
        $('allowed_users').value = (config.allowed_users || []).join('\n');
        for (const key of ['project_secret']) {
            $(key).value = '';
            $(key).placeholder = config[key + '_configured'] ? '已保存，留空保留' : '输入密钥';
        }
        $('enabled').checked = !!config.enabled;
        $('time_enabled').checked = config.time_enabled !== false;
        $('debounce_seconds').value = config.debounce_seconds ?? 30;
    }
    async function load() {
        if (loading || loaded) return;
        loading = true; setBusy(true); message('正在读取连接…');
        try {
            const data = await api(); fill(data.connection); loaded = true;
            message(data.saved ? '' : '填写连接信息');
            if (data.saved) scheduleStatus();
        } catch (error) { message('读取失败：' + error.message,true); }
        finally { loading = false; setBusy(false); }
    }
    function setBusy(value) {
        busy = value;
        document.querySelectorAll('#bot-connection-form input,#bot-connection-form textarea,#bot-connection-form button').forEach(node => { node.disabled = value; });
    }
    async function run(action) {
        if (busy || !loaded) return;
        setBusy(true);
        try { await action(); }
        catch (error) { message(error.message,true); }
        finally { setBusy(false); }
    }
    function scheduleStatus() {
        clearTimeout(statusTimer);
        if (document.hidden || !document.getElementById('section-bot-imessage')?.classList.contains('active')) return;
        statusTimer = setTimeout(async () => {
            if (!busy) {
                try { showStatus(await api('/check','POST')); }
                catch (error) { message(error.message,true); }
            }
            scheduleStatus();
        },3000);
    }
    function showStatus(data) {
        const statuses = {connected:'已连接',connecting:'正在连接 Photon…',reconnecting:'正在重连 Photon…',
            waiting:'等待配置',disabled:'已停用',error:'连接异常',unknown:'状态未知'};
        $('status').textContent = statuses[data.status] || '状态未知';
        $('status').dataset.state = data.status;
        message(data.error || '',!!data.error);
    }
    document.addEventListener('DOMContentLoaded', () => {
        const detail = document.getElementById('section-bot-imessage');
        const sections = ['section-bots','section-bot-add','section-bot-imessage'].map(id=>document.getElementById(id));
        if (sections.some(section=>!section)) return;
        const updateView = () => {
            if (detail.classList.contains('active')) { void refreshIdentityPresetNames(); load(); if(loaded)scheduleStatus(); }
            else clearTimeout(statusTimer);
            if (sections[0].classList.contains('active') || sections[1].classList.contains('active')) loadCatalog();
        };
        const observer = new MutationObserver(updateView);
        sections.forEach(section=>observer.observe(section,{attributes:true,attributeFilter:['class']}));
        updateView();
        $('list-retry').onclick = loadCatalog; $('provider-retry').onclick = loadCatalog;
        document.addEventListener('visibilitychange', () => { if(!document.hidden && loaded)scheduleStatus();else clearTimeout(statusTimer); });
        $('connection-form').addEventListener('submit', event => {
            event.preventDefault();
            run(async () => {
                message('正在保存并连接…');
                const body = {};
                for (const key of ['project_id','project_secret','home_user']) body[key] = $(key).value.trim();
                body.allowed_users = $('allowed_users').value.split(/[\n,，]/).map(value=>value.trim()).filter(Boolean);
                body.enabled = $('enabled').checked; body.time_enabled = $('time_enabled').checked;
                body.debounce_seconds = Number($('debounce_seconds').value);
                const data = await api('','PUT',body);
                fill(data.connection);
                $('status').textContent = body.enabled ? '正在连接' : '已停用';
                $('status').dataset.state = body.enabled ? 'connecting' : 'disabled';
                message(body.enabled ? '已保存，正在连接。' : '已保存并停用连接。');
                scheduleStatus();
            });
        });
        $('check').onclick = () => loaded ? run(async()=>{message('正在检查…');showStatus(await api('/check','POST'));}) : load();
        $('reconnect').onclick = () => run(async()=>{message('正在重连…');showStatus(await api('/reconnect','POST'));scheduleStatus();});
    });
})();
