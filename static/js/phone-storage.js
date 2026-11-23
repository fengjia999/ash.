/* Browser-only presentation state. This module never makes network requests. */
(() => {
    'use strict';
    const KEY = 'ash.phone.v1';
    const defaults = () => ({version: 1, names: {user: '我', assistant: 'Ash'}, noteLayout: {}});
    function normalize(value) {
        const clean = defaults();
        for (const role of ['user', 'assistant']) {
            if (typeof value?.names?.[role] === 'string') clean.names[role] = value.names[role].slice(0,80);
        }
        for (const [id, layout] of Object.entries(value?.noteLayout || {}).slice(0, 2000)) {
            if (!/^\d+$/.test(id) || !layout || !['x','y','rotation','z'].every(key => Number.isFinite(layout[key]))) continue;
            clean.noteLayout[id] = {x:Math.max(0,Math.min(1,layout.x)), y:Math.max(0,Math.min(1,layout.y)),
                rotation:Math.max(-3.5,Math.min(3.5,layout.rotation)), z:Math.max(1,Math.min(1000000,layout.z))};
        }
        return clean;
    }
    let legacy = null;
    try { legacy = JSON.parse(localStorage.getItem(KEY)); } catch (_) {}
    let state = normalize(legacy);
    function announce(kind = 'state') { window.dispatchEvent(new CustomEvent('ash-local-change', {detail:{kind}})); }
    function problem() { window.dispatchEvent(new CustomEvent('ash-local-error', {detail: '浏览器未能保存本地数据，请检查存储空间与网站权限。'})); }
    function update(change, kind = 'state') {
        const candidate = JSON.parse(JSON.stringify(state));
        change(candidate);
        const next = normalize(candidate);
        try { localStorage.setItem(KEY, JSON.stringify(next)); } catch (error) { problem(); throw error; }
        state = next; announce(kind); return state;
    }
    let database;
    function db() {
        if (!database) database = new Promise((resolve, reject) => {
            if (!window.indexedDB) { reject(new Error('当前浏览器无法使用本地存储')); return; }
            const request = indexedDB.open('ash-phone-local', 2);
            request.onupgradeneeded = () => {
                for (const name of ['assets', 'keepsakes'])
                    if (!request.result.objectStoreNames.contains(name)) request.result.createObjectStore(name);
            };
            request.onsuccess = () => {
                request.result.onversionchange = () => { request.result.close(); database = null; };
                resolve(request.result);
            };
            request.onerror = () => reject(request.error);
            request.onblocked = () => reject(new Error('请关闭其他 Ash 页面后重试'));
        }).catch(error => { database = null; throw error; });
        return database;
    }
    async function asset(key, value) {
        const connection = await db();
        const write = arguments.length > 1;
        return new Promise((resolve, reject) => {
            const transaction = connection.transaction('assets', write ? 'readwrite' : 'readonly');
            const store = transaction.objectStore('assets');
            const request = write ? (value == null ? store.delete(key) : store.put(value, key)) : store.get(key);
            transaction.oncomplete = () => { if (write) announce('assets'); resolve(write ? value : request.result); };
            transaction.onerror = () => reject(transaction.error || request.error);
            transaction.onabort = () => reject(transaction.error || new Error('本地保存中断'));
        });
    }
    async function image(file, {square = true} = {}) {
        if (!file?.type.startsWith('image/')) throw new Error('请选择图片文件');
        if (file.size > 20 * 1024 * 1024) throw new Error('请选择 20MB 以内的图片');
        const url = URL.createObjectURL(file);
        try {
            const picture = await new Promise((resolve, reject) => {
                const img = new Image(); img.onload = () => resolve(img);
                img.onerror = () => reject(new Error('无法读取图片，请尝试 PNG、JPEG 或 WebP'));
                img.src = url;
            });
            const width = picture.naturalWidth, height = picture.naturalHeight;
            if (!width || !height) throw new Error('图片尺寸无效');
            const side = Math.min(width, height);
            const scale = Math.min(1, (square ? 512 : 1600) / (square ? side : Math.max(width, height)));
            const canvas = document.createElement('canvas');
            canvas.width = Math.max(1, Math.round((square ? side : width) * scale));
            canvas.height = Math.max(1, Math.round((square ? side : height) * scale));
            const context = canvas.getContext('2d');
            if (!context) throw new Error('浏览器无法处理这张图片');
            context.drawImage(picture, square ? (width - side) / 2 : 0, square ? (height - side) / 2 : 0,
                square ? side : width, square ? side : height, 0, 0, canvas.width, canvas.height);
            return await new Promise((resolve, reject) => canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error('图片处理失败')), 'image/webp', .88));
        } finally { URL.revokeObjectURL(url); }
    }
    async function replaceAssets(values) {
        const connection = await db();
        return new Promise((resolve, reject) => {
            const transaction = connection.transaction('assets', 'readwrite');
            const store = transaction.objectStore('assets');
            for (const [key, value] of Object.entries(values)) { if (value == null) store.delete(key); else store.put(value, key); }
            transaction.oncomplete = () => { announce('assets'); resolve(); };
            transaction.onerror = transaction.onabort = () => reject(transaction.error || new Error('本地图片恢复失败'));
        });
    }
    const keepsakeChannel = typeof BroadcastChannel === 'function' ? new BroadcastChannel('ash-keepsakes') : null;
    if (keepsakeChannel) keepsakeChannel.onmessage = () => announce('keepsakes');
    function announceKeepsakes() {
        announce('keepsakes');
        keepsakeChannel?.postMessage('changed');
        // Also reaches the embedded chat on browsers without BroadcastChannel.
        if (window.parent !== window) window.parent.postMessage({type:'ash-keepsakes-changed'}, location.origin);
    }
    function normalizeKeepsake(value) {
        const conversationId = Number(value?.conversationId), messageId = Number(value?.messageId);
        if (!Number.isSafeInteger(conversationId) || conversationId <= 0 || !Number.isSafeInteger(messageId) || messageId <= 0
            || !['user','assistant'].includes(value?.role) || typeof value?.content !== 'string' || !value.content.trim())
            throw new Error('收藏内容无效');
        const id = conversationId + ':' + messageId;
        return {id, conversationId, messageId, role:value.role, content:value.content,
            name:typeof value.name === 'string' ? value.name.slice(0,80) : '',
            conversationName:typeof value.conversationName === 'string' ? value.conversationName.slice(0,200) : '',
            createdAt:typeof value.createdAt === 'string' ? value.createdAt.slice(0,40) : '',
            savedAt:typeof value.savedAt === 'string' && Number.isFinite(Date.parse(value.savedAt)) ? value.savedAt : new Date().toISOString()};
    }
    async function keepsakes() {
        const connection = await db();
        return new Promise((resolve, reject) => {
            const transaction = connection.transaction('keepsakes', 'readonly');
            const request = transaction.objectStore('keepsakes').getAll();
            transaction.oncomplete = () => resolve(request.result.sort((a,b) => b.savedAt.localeCompare(a.savedAt) || a.id.localeCompare(b.id)));
            transaction.onerror = transaction.onabort = () => reject(transaction.error || new Error('收藏读取失败'));
        });
    }
    async function saveKeepsake(value) {
        const item = normalizeKeepsake(value), connection = await db();
        return new Promise((resolve, reject) => {
            const transaction = connection.transaction('keepsakes', 'readwrite'), store = transaction.objectStore('keepsakes');
            const request = store.get(item.id);
            request.onsuccess = () => { if (!request.result) store.put(item, item.id); };
            transaction.oncomplete = () => { announceKeepsakes(); resolve(request.result || item); };
            transaction.onerror = transaction.onabort = () => reject(transaction.error || new Error('收藏未能保存，请检查浏览器存储空间'));
        });
    }
    async function removeKeepsake(id) {
        const connection = await db();
        return new Promise((resolve, reject) => {
            const transaction = connection.transaction('keepsakes', 'readwrite');
            transaction.objectStore('keepsakes').delete(id);
            transaction.oncomplete = () => { announceKeepsakes(); resolve(); };
            transaction.onerror = transaction.onabort = () => reject(transaction.error || new Error('移除收藏失败'));
        });
    }
    async function replaceKeepsakes(values) {
        if (!Array.isArray(values)) throw new Error('收藏备份格式无效');
        const items = values.map(normalizeKeepsake), connection = await db();
        return new Promise((resolve, reject) => {
            const transaction = connection.transaction('keepsakes', 'readwrite'), store = transaction.objectStore('keepsakes');
            store.clear(); for (const item of items) store.put(item, item.id);
            transaction.oncomplete = () => { announceKeepsakes(); resolve(); };
            transaction.onerror = transaction.onabort = () => reject(transaction.error || new Error('收藏恢复失败'));
        });
    }
    function draftKey(id) { return 'ash.phone.draft.' + Number(id); }
    function readDraft(id) { try { return localStorage.getItem(draftKey(id)) || ''; } catch (_) { return ''; } }
    function saveDraft(id, text) {
        if (!Number.isInteger(Number(id)) || Number(id) <= 0) return;
        try { if (text) localStorage.setItem(draftKey(id), text); else localStorage.removeItem(draftKey(id)); }
        catch (_) { problem(); }
    }
    window.AshLocal = {legacyDesktop: () => structuredClone(legacy), get: () => JSON.parse(JSON.stringify(state)), update, asset, replaceAssets, image, readDraft, saveDraft,
        keepsakes, saveKeepsake, removeKeepsake, replaceKeepsakes, normalizeKeepsake};
    window.addEventListener('storage', event => {
        if (event.key === KEY) { try { state = normalize(JSON.parse(event.newValue)); announce(); } catch (_) {} }
    });
})();
