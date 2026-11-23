/* Keep desktop image bytes out of the synchronous, shared localStorage budget. */
(() => {
    'use strict';
    const DATABASE = 'ash_phone_media_v2', STORE = 'images', GRACE_MS = 24 * 60 * 60 * 1000;
    const urls = new Map(), staged = new Map(), pending = new Set();
    let database = null, closed = false, sweeping = Promise.resolve();
    const isReference = value => typeof value === 'string' && /^phone-image:[\w-]{1,100}$/.test(value);
    const isInline = value => typeof value === 'string' && /^data:image\/(?:jpeg|png|webp);base64,[a-z0-9+/=]+$/i.test(value);
    function fields(layout) {
        const appearances = [layout, ...(Array.isArray(layout.themePresets) ? layout.themePresets.map(preset => preset.appearance).filter(Boolean) : [])];
        return [...appearances.flatMap(appearance => [[appearance, 'wallpaperImage'], ...(Array.isArray(appearance.wallpapers) ? appearance.wallpapers.map((_,index)=>[appearance.wallpapers,index]) : []), ...Object.keys(appearance.icons || {}).map(id => [appearance.icons, id])]), ...Object.values(layout.widgets || {}).map(widget => [widget, 'image'])];
    }
    const references = layout => new Set(fields(layout).map(([object, key]) => object[key]).filter(isReference));
    function open() {
        if (closed) return Promise.reject(new DOMException('桌面存储正在清理', 'AbortError'));
        if (!database) database = new Promise((resolve, reject) => {
            let abandoned = false;
            const request = indexedDB.open(DATABASE, 1);
            request.onupgradeneeded = () => request.result.createObjectStore(STORE, {keyPath:'id'});
            request.onsuccess = () => {
                const db = request.result;
                if (closed || abandoned) { db.close(); reject(new DOMException('桌面存储正在清理', 'AbortError')); return; }
                db.onversionchange = () => { db.close(); database = null; };
                resolve(db);
            };
            request.onerror = () => { database = null; reject(request.error); };
            request.onblocked = () => { abandoned = true; database = null; reject(new Error('请关闭其他小手机页面后重试')); };
        });
        return database;
    }
    async function transaction(mode, action) {
        const db = await open();
        if (closed) throw new DOMException('桌面存储正在清理', 'AbortError');
        const operation = new Promise((resolve, reject) => {
            const tx = db.transaction(STORE, mode);
            const request = action(tx.objectStore(STORE));
            tx.oncomplete = () => resolve(request?.result);
            tx.onabort = tx.onerror = () => reject(tx.error || request?.error || new Error('桌面图片保存失败'));
        });
        pending.add(operation);
        try { return await operation; } finally { pending.delete(operation); }
    }
    function cache(id, blob) {
        if (!urls.has(id)) urls.set(id, URL.createObjectURL(blob));
        return id;
    }
    async function store(blob) {
        if (!(blob instanceof Blob) || !['image/jpeg','image/png','image/webp'].includes(blob.type)) throw new Error('无法保存这张图片，请换一张试试');
        let suffix;
        if (globalThis.crypto?.subtle) {
            const hash = await crypto.subtle.digest('SHA-256', await blob.arrayBuffer());
            suffix = Array.from(new Uint8Array(hash), byte => byte.toString(16).padStart(2,'0')).join('');
        } else suffix = globalThis.crypto?.randomUUID?.() || `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
        const id = `phone-image:${suffix}`;
        await transaction('readwrite', images => images.put({id, blob, unusedSince:0}));
        if (closed) throw new DOMException('桌面存储正在清理', 'AbortError');
        staged.set(id, (staged.get(id) || 0) + 1);
        return cache(id, blob);
    }
    function release(ids) {
        for (const id of ids) {
            if (staged.get(id) > 1) staged.set(id, staged.get(id) - 1);
            else staged.delete(id);
        }
    }
    async function hydrate(layout) {
        const missing = [...references(layout)].filter(id => !urls.has(id));
        if (!missing.length) return;
        const db = await open();
        if (closed) return;
        await new Promise((resolve, reject) => {
            const tx = db.transaction(STORE, 'readonly'), records = [];
            missing.forEach(id => {
                const request = tx.objectStore(STORE).get(id);
                request.onsuccess = () => records.push(request.result);
            });
            tx.oncomplete = () => {
                if (closed) { resolve(); return; }
                records.forEach(record => { if (record?.blob instanceof Blob) cache(record.id, record.blob); });
                if (records.some(record => !record)) reject(new Error('部分桌面图片暂时无法读取，原有布局已保留'));
                else resolve();
            };
            tx.onabort = tx.onerror = () => reject(tx.error || new Error('暂时无法读取桌面图片'));
        });
    }
    async function migrate(layout) {
        const inline = new Set(fields(layout).map(([object, key]) => object[key]).filter(isInline));
        const replacements = new Map();
        try {
            for (const value of inline) {
                const [header, base64] = value.split(','), bytes = Uint8Array.from(atob(base64), char => char.charCodeAt(0));
                replacements.set(value, await store(new Blob([bytes], {type:header.slice(5, header.indexOf(';'))})));
            }
        } catch (error) { release(replacements.values()); throw error; }
        return replacements;
    }
    function collect(getLayouts) {
        // Delayed deletion also protects an upload staged by another tab before
        // it has committed its layout. Never delete an image on its first sweep.
        sweeping = sweeping.catch(() => {}).then(async () => {
            if (closed) return;
            const live = new Set([...getLayouts().flatMap(layout => [...references(layout)]), ...staged.keys()]);
            const now = Date.now();
            await transaction('readwrite', images => {
                const request = images.openCursor();
                request.onsuccess = () => {
                    const cursor = request.result; if (!cursor) return;
                    const record = cursor.value;
                    if (live.has(record.id)) { if (record.unusedSince) cursor.update({...record, unusedSince:0}); }
                    else if (!record.unusedSince) cursor.update({...record, unusedSince:now});
                    else if (record.unusedSince <= now - GRACE_MS) cursor.delete();
                    cursor.continue();
                };
            });
            // Refreshes no longer retain every previously selected wallpaper in RAM.
            const latest = new Set([...getLayouts().flatMap(layout => [...references(layout)]), ...staged.keys()]);
            urls.forEach((url, id) => { if (!latest.has(id)) { URL.revokeObjectURL(url); urls.delete(id); } });
        });
        return sweeping;
    }
    async function clearData() {
        closed = true;
        await Promise.allSettled([...pending, sweeping]);
        if (database) { try { (await database).close(); } catch {} }
        database = null;
        urls.forEach(url => URL.revokeObjectURL(url)); urls.clear();
        staged.clear();
        await new Promise((resolve, reject) => {
            const request = indexedDB.deleteDatabase(DATABASE);
            request.onsuccess = resolve; request.onerror = () => reject(request.error);
            request.onblocked = () => reject(new Error('请关闭其他小手机页面后再清理桌面图片'));
        });
    }
    window.merlePhoneMedia = Object.freeze({
        isReference, fields, references, store, release, hydrate, migrate, collect, clearData,
        source: value => isReference(value) ? urls.get(value) || '' : isInline(value) ? value : '',
        get closed() { return closed; },
    });
})();
