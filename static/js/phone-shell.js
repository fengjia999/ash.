/* Ash app/identity bindings for the Merle desktop. Server data stays in existing APIs. */
(() => {
    'use strict';
    const local = window.AshLocal;
    const main = document.querySelector('.main-content');
    main.prepend(document.getElementById('phone-home-template').content.cloneNode(true));
    const $ = id => document.getElementById(id);
    const paths = {
        smile: '<circle cx="12" cy="12" r="9"/><path d="M8 9v1m8-1v1M7 14q5 7 10 0"/>',
        chat: '<path d="M20 11a8 8 0 0 1-8 8H5l-4 3 1.5-6A8.5 8.5 0 1 1 20 11Z"/><path d="M7 10h8m-8 4h5"/>',
        heart: '<path d="M20.8 4.6c-2.5-2.7-6.3-1.8-8.8 1-2.5-2.8-6.3-3.7-8.8-1C-1 9 4 15 12 21c8-6 13-12 8.8-16.4Z"/>',
        memory: '<path d="M4 3h15v18H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2m-2 14h16M8 7h7m-7 4h5"/>',
        pen: '<path d="m15 3 6 6-11 11-7 1 1-7L15 3Zm-3 3 6 6M4 15l5 5"/>',
        edit: '<path d="m16 3 5 5-12 12-6 1 1-6L16 3Zm-2 2 5 5"/>',
        usage: '<path d="M3 3v18h18M6 16l4-5 4 2 6-8m-5 0h5v5"/>',
        settings: '<path d="m9 3-1 3-3 1 1 3-2 2 2 2-1 3 3 1 1 3h5l1-3 3-1-1-3 2-2-2-2 1-3-3-1-1-3H9Z"/><circle cx="11.5" cy="12" r="3"/>',
        palette: '<path d="M12 3a9 9 0 1 0 0 18h1a2 2 0 0 0 1-4c-1-.5-.5-2 .5-2H17a4 4 0 0 0 4-4 9 9 0 0 0-9-8Z"/><circle cx="7" cy="10" r=".8"/><circle cx="11" cy="7" r=".8"/><circle cx="16" cy="8" r=".8"/>',
        back: '<path d="m14 5-7 7 7 7"/>', chevron: '<path d="m9 6 6 6-6 6"/>', arrow: '<path d="M4 12h15m-6-6 6 6-6 6"/>',
        plus: '<path d="M12 4v16M4 12h16"/>', close: '<path d="m6 6 12 12M6 18 18 6"/>',
        conversations: '<path d="M5 4h14M5 10h14M5 16h9M2 4h0m0 6h0m0 6h0"/><path d="m17 14 4 3-4 3"/>',
        cover: '<rect x="4" y="2" width="16" height="20" rx="3"/><path d="M8 2v20m4-14h4m-4 4h4"/>',
        person: '<circle cx="12" cy="7" r="4"/><path d="M4 21v-2a8 8 0 0 1 16 0v2Z"/>',
        sliders: '<path d="M5 3v18M12 3v18M19 3v18M2 8h6m1 8h6m1-9h6"/>',
        archive: '<path d="M3 3h18v5H3zM5 8v13h14V8m-10 5h6"/>',
    };
    const titles = {home: '主屏幕', bots: 'Bot 连接', 'bot-add': '添加连接', 'bot-imessage': 'iMessage', 'bot-qq': 'QQ', 'bot-feishu': '飞书', 'bot-weixin': '微信', favorites:'收藏', chat: 'Chat', preferences: '设置', 'phone-transfer': '备份与导入',
        heartbeats: '苏醒日记', standing: '记忆', diary:'日记', presets: '提示词', settings: '其它', recall: '召回设置', suppliers: '模型供应商',
        'supplier-route': '聊天配置', 'supplier-openai': 'OpenAI 供应商', 'supplier-anthropic': 'Anthropic 供应商', import: '导入', export: '备份'};
    let activeTab = 'chat', conversations = [], conversationsLoaded = false, conversationRequest = 0;
    let imageTarget = null, toastTimer, avatarGeneration = 0;
    let meRequest = 0;
    let favoritesRequest = 0;
    const assetURLs = new Map();
    function icon(name) { return window.AshMerleIcons?.[name] || `<svg viewBox="0 0 24 24" aria-hidden="true">${paths[name] || paths.settings}</svg>`; }
    function icons(root = document) { root.querySelectorAll('[data-phone-icon]').forEach(el => { el.innerHTML = icon(el.dataset.phoneIcon); }); }
    function face(role) { return `<svg viewBox="0 0 60 60" aria-hidden="true"><path d="M17 22v4m26-4v4M${role === 'user' ? '16 36q6 14 14 0 8 14 14 0' : '18 37q12 14 24 0'}"/><path d="m12 32-3 2m40-2 3 2" opacity=".5"/></svg>`; }
    function avatar(role, extra = '') { return `<span class="phone-avatar ${extra}" data-local-avatar="${role}">${face(role)}</span>`; }
    function toast(message) { clearTimeout(toastTimer); $('phone-toast').textContent = message; $('phone-toast').hidden = false; toastTimer = setTimeout(() => { $('phone-toast').hidden = true; }, 4300); }
    function save(change) { try { return local.update(change); } catch (_) { return null; } }
    function renderNames() {
        const state = local.get();
        document.querySelectorAll('[data-local-name]').forEach(el => { el.textContent = state.names[el.dataset.localName] || (el.dataset.localName === 'user' ? '我' : 'Ash'); });
    }
    async function cachedAsset(key, refresh = false) {
        if (!refresh && assetURLs.has(key)) return assetURLs.get(key);
        const blob = await local.asset(key);
        const old = assetURLs.get(key);
        const url = blob instanceof Blob ? URL.createObjectURL(blob) : '';
        assetURLs.set(key, url); if (old) URL.revokeObjectURL(old); return url;
    }
    async function paintAvatars(refresh = false) {
        const generation = ++avatarGeneration;
        for (const role of ['user', 'assistant']) {
            let source = ''; try { source = await cachedAsset('avatar-' + role, refresh); } catch (_) {}
            if (generation !== avatarGeneration) return;
            document.querySelectorAll(`[data-local-avatar="${role}"]`).forEach(el => {
                el.replaceChildren();
                if (source) { const image = document.createElement('img'); image.src = source; image.alt = ''; el.appendChild(image); }
                else el.innerHTML = face(role);
            });
        }
    }
    function sheet(title, html) {
        $('phone-sheet-title').textContent = title; $('phone-sheet-content').innerHTML = html;
        icons($('phone-personalize')); if (!$('phone-personalize').open) $('phone-personalize').showModal();
    }
    function profile(role, anchor) {
        const menu = $('phone-avatar-menu');
        if (menu.matches(':popover-open')) menu.hidePopover();
        menu.dataset.role = role;
        menu.showPopover();
        const box = anchor.getBoundingClientRect(), size = menu.getBoundingClientRect();
        const width = window.visualViewport?.width || innerWidth;
        const height = window.visualViewport?.height || innerHeight;
        menu.style.left = Math.max(8, Math.min(box.left + (box.width-size.width)/2, width-size.width-8))+'px';
        menu.style.top = Math.max(8, box.bottom+8+size.height <= height ? box.bottom+8 : box.top-size.height-8)+'px';
    }
    function editName(button) {
        if (document.querySelector('[data-phone-name-editor]')) return;
        const role = button.dataset.phoneName, previous = local.get().names[role];
        const input = document.createElement('input');
        input.className = 'phone-pair-name'; input.dataset.phoneNameEditor = role;
        input.value = previous; input.maxLength = 80; input.autocomplete = 'off';
        input.setAttribute('aria-label',role === 'user' ? '你的名字' : '对方的名字');
        let finished = false;
        function finish(cancel = false) {
            if (finished) return;
            finished = true;
            const name = input.value.trim();
            if (!cancel && name && name !== previous) save(state=>{state.names[role]=name;});
            input.replaceWith(button); renderNames();
        }
        input.onblur = () => finish();
        input.onkeydown = event => {
            if (event.isComposing || event.keyCode === 229) return;
            if (event.key === 'Enter' || event.key === 'Escape') {
                event.preventDefault(); finish(event.key === 'Escape'); button.focus({preventScroll:true});
            }
        };
        button.replaceWith(input); input.focus({preventScroll:true}); input.select();
    }
    function pairControls() {
        return ['user','assistant'].map(role=>`<div class="phone-pair-person"><button type="button" class="phone-pair-avatar" data-phone-profile="${role}" aria-label="${role === 'user' ? '你的头像' : '对方的头像'}">${avatar(role)}</button><button type="button" class="phone-pair-name" data-phone-name="${role}" aria-label="${role === 'user' ? '编辑你的名字' : '编辑对方的名字'}"><strong data-local-name="${role}"></strong></button></div>`).join('');
    }
    function chooseImage(key) { imageTarget = key; $('phone-local-image').click(); }
    // The simulated phone owns its navigation. Browser history only mirrors the
    // current screen so an edge swipe cannot walk through previously opened apps.
    let screen = null, stack = [], pendingScroll = 0;
    const parents = {'bot-add':'bots', 'bot-imessage':'bots', 'bot-qq':'bots', 'bot-feishu':'bots', 'bot-weixin':'bots', favorites:'chat', settings:'preferences', recall:'preferences', suppliers:'preferences', presets:'preferences',
        'phone-transfer':'preferences', import:'phone-transfer', export:'phone-transfer',
        'supplier-route':'suppliers', 'supplier-openai':'suppliers', 'supplier-anthropic':'suppliers'};
    const screenTitle = entry => entry?.name === 'chat'
        ? ({chat:'Chat',conversations:'Conversation',cover:'Cover',me:'Me'}[entry.tab] || 'Chat')
        : entry?.name === 'detail' ? '对话' : titles[entry?.name] || '主屏幕';
    const copyScreen = value => value ? {...value} : null;
    function saveNavigation() {
        if (!screen) return;
        const hash = screen.name === 'home' ? '' : '#' + (screen.name === 'detail' ? 'chat' : screen.name);
        history.replaceState({ashPhoneNavigation:1,screen:copyScreen(screen),stack:stack.map(copyScreen)}, '', location.pathname + location.search + hash);
    }
    function captureScreen() {
        cancelAnimationFrame(pendingScroll);
        if (!screen || screen.name === 'detail') return;
        screen.scroll = main.scrollTop;
        if (screen.name === 'chat') {
            screen.tab = activeTab;
            screen.panelScroll = document.querySelector('.phone-chat-panels').scrollTop;
        }
    }
    function updateBack() {
        const label = screenTitle(stack.at(-1));
        $('phone-back').setAttribute('aria-label', '返回' + label);
        $('phone-back').title = '返回' + label;
    }
    function initialScreen(name) {
        const saved = history.state?.ashPhoneNavigation === 1 ? history.state : null;
        if (saved?.screen?.name === name) {
            screen = copyScreen(saved.screen);
            stack = Array.isArray(saved.stack) ? saved.stack.map(copyScreen) : [];
            return;
        }
        stack = [{name:'home',scroll:0}];
        const ancestors = [];
        for (let parent = parents[name]; parent; parent = parents[parent]) ancestors.unshift(parent);
        for (const parent of ancestors) stack.push({name:parent,scroll:0});
        if (name === 'home') stack = [];
        screen = {name,tab:activeTab,scroll:0,panelScroll:0};
    }
    function navigate(name) {
        window.AshDesktop?.edit(false);
        if (!screen) initialScreen(name);
        else if (screen.name !== name) {
            captureScreen();
            stack = name === 'home' ? [] : [...stack,copyScreen(screen)];
            screen = {name,tab:activeTab,scroll:0,panelScroll:0};
        }
        saveNavigation();
        switchSection(name,{renderOnly:true});
    }
    function navigateConversation(conversationId, created = false) {
        const id = Number(conversationId);
        if (!Number.isInteger(id) || id <= 0) return;
        if (!screen) initialScreen('chat');
        if (screen.name !== 'detail' || screen.conversationId !== id) {
            captureScreen();
            stack.push(copyScreen(screen));
            screen = {name:'detail',conversationId:id};
        }
        saveNavigation();
        openConversationDetail(id,created,{renderOnly:true});
    }
    function back() {
        captureScreen();
        screen = stack.pop() || {name:'home',scroll:0};
        if (screen.name === 'home') stack = [];
        saveNavigation();
        renderScreen();
    }
    function renderScreen() {
        $('phone-personalize').close();
        if (screen.name === 'detail') openConversationDetail(screen.conversationId,false,{renderOnly:true});
        else switchSection(screen.name,{renderOnly:true});
    }
    function restoreScroll() {
        const expected = screen;
        main.scrollTop = screen.scroll || 0;
        pendingScroll = requestAnimationFrame(()=>{
            if (screen !== expected) return;
            main.scrollTop = screen.scroll || 0;
            if (screen.name === 'chat') document.querySelector('.phone-chat-panels').scrollTop = screen.panelScroll || 0;
        });
    }
    function presentSection(name) {
        const detail = $('conversation-detail-layer');
        detail.classList.remove('open'); detail.setAttribute('aria-hidden','true');
        document.getElementById('diary-notebook')?.classList.toggle('open',name==='diary');
        window.AshPhoneViewport?.refresh();
        $('page-phone').classList.toggle('active',name==='home');
        document.body.dataset.phoneView = name;
        $('phone-app-header').hidden = name === 'home'; $('phone-app-title').textContent = titles[name] || 'Ash';
        $('phone-header-action').hidden = name !== 'chat';
        $('phone-diary-tools').hidden = name !== 'diary';
        $('phone-supplier-add').hidden = !['supplier-openai','supplier-anthropic'].includes(name);
        if (name === 'favorites') renderFavorites();
        if (name === 'chat') { selectTab(screen.tab || activeTab); loadConversations(); loadUsage(); }
        updateBack();
        restoreScroll();
    }
    function presentConversation() {
        window.AshPhoneViewport?.refresh();
        $('page-phone').classList.remove('active');
        document.body.dataset.phoneView = 'detail'; $('phone-app-header').hidden = true;
        $('conversation-detail-frame')?.contentWindow?.AshChatUI?.syncBack();
        updateBack();
    }
    function selectTab(tab) {
        activeTab = tab;
        if (screen?.name === 'chat') { screen.tab = tab; saveNavigation(); updateBack(); }
        document.querySelectorAll('[data-chat-panel]').forEach(el => { el.hidden = el.dataset.chatPanel !== tab; });
        document.querySelectorAll('[data-chat-tab]').forEach(el => { if (el.dataset.chatTab === tab) el.setAttribute('aria-current','page'); else el.removeAttribute('aria-current'); });
        $('phone-app-title').textContent = {chat:'Chat',conversations:'Conversation',cover:'Cover',me:'Me'}[tab];
        $('phone-header-action').hidden = !['chat','conversations'].includes(tab);
        if (tab === 'me') loadMeConfiguration();
        if (tab === 'cover') window.AshNoteboard?.open();
    }
    async function renderFavorites() {
        const request = ++favoritesRequest, status = $('phone-favorites-status');
        $('phone-favorites-retry').hidden = true;
        try {
            const items = await local.keepsakes();
            if (request !== favoritesRequest) return;
            const list = document.createDocumentFragment();
            for (const item of items) {
                const row = document.createElement('button'); row.type = 'button'; row.className = 'phone-favorite';
                row.dataset.keepsakeId = item.id;
                const quote = document.createElement('span'); quote.className = 'phone-favorite-quote'; quote.textContent = item.content;
                const meta = document.createElement('span'); meta.className = 'phone-favorite-meta';
                const source = document.createElement('span'); source.textContent = [item.name || local.get().names[item.role], item.conversationName].filter(Boolean).join(' · ');
                const date = document.createElement('time'); date.textContent = (item.createdAt || item.savedAt).slice(0,10).replaceAll('-', '.');
                meta.append(source, date); row.append(quote, meta);
                row.onclick = () => readKeepsake(item); list.append(row);
            }
            $('phone-favorites-list').replaceChildren(list);
            status.textContent = items.length ? '' : '暂无收藏';
        } catch (error) {
            if (request !== favoritesRequest) return;
            status.textContent = '收藏读取失败：' + error.message; $('phone-favorites-retry').hidden = false;
        }
    }
    function readKeepsake(item) {
        sheet(item.name || local.get().names[item.role], '<blockquote class="phone-favorite-reading"></blockquote><p class="phone-favorite-source"></p><div class="phone-favorite-actions"><button type="button" id="phone-favorite-open-source">打开会话</button><button type="button" class="phone-favorite-remove" id="phone-favorite-remove">移除收藏</button></div>');
        $('phone-sheet-content').querySelector('blockquote').textContent = item.content;
        $('phone-sheet-content').querySelector('.phone-favorite-source').textContent = [item.conversationName, (item.createdAt || item.savedAt).slice(0,10)].filter(Boolean).join(' · ');
        $('phone-favorite-open-source').onclick = async event => {
            const button = event.currentTarget; button.disabled = true;
            try {
                await json(`/api/conversations/${item.conversationId}/messages?limit=1`);
                $('phone-personalize').close(); navigateConversation(item.conversationId);
            } catch (_) { toast('原会话暂时无法打开，收藏仍保留'); }
            finally { button.disabled = false; }
        };
        $('phone-favorite-remove').onclick = async event => {
            if (!confirm('移除这条收藏？')) return;
            const button = event.currentTarget; button.disabled = true;
            try { await local.removeKeepsake(item.id); $('phone-personalize').close(); await renderFavorites(); }
            catch (error) { toast(error.message); button.disabled = false; }
        };
    }
    async function loadMeConfiguration() {
        const generation = ++meRequest;
        const status = $('phone-me-status');
        $('phone-me-retry').hidden = true; status.textContent = '载入中…';
        for (const field of ['supplier','route','model']) $('phone-me-' + field).textContent = '—';
        try {
            const config = await json('/api/route-settings');
            if (generation !== meRequest) return;
            $('phone-me-supplier').textContent = config.provider_name || '自定义供应商';
            $('phone-me-route').textContent = {openai:'OpenAI 兼容',anthropic:'Anthropic',auto:'自动'}[config.provider] || '—';
            $('phone-me-model').textContent = config.model || '未设置';
            status.textContent = '';
        } catch (error) {
            if (generation !== meRequest) return;
            status.textContent = '加载失败：' + error.message;
            $('phone-me-retry').hidden = false;
        }
    }
    async function json(url, options = {}) { return saveDashboardJson(url, options); }
    async function loadConversations() {
        const generation = ++conversationRequest;
        const listScreen = screen, scroll = document.querySelector('.phone-chat-panels').scrollTop || screen?.panelScroll || 0;
        if (!conversationsLoaded) $('phone-conversation-list').innerHTML = '<p class="phone-list-notice">正在加载…</p>';
        try {
            const data = await json('/api/conversations'); if (generation !== conversationRequest) return;
            conversations = Array.isArray(data.conversations) ? data.conversations : [];
            conversationsLoaded = true;
            const active = conversations.find(item => item.is_active);
            $('phone-active-conversation').textContent = active?.name || '新建会话';
            $('phone-printer-name').textContent = active ? (active.name || '未命名会话') : '暂无当前会话';
            $('phone-printer-current').disabled = !active;
            $('phone-printer-current').onclick = active ? () => openConversationDetail(active.id) : null;
            renderConversations();
            if (screen === listScreen && screen?.name === 'chat') document.querySelector('.phone-chat-panels').scrollTop = scroll;
        } catch (error) {
            if (generation !== conversationRequest) return;
            if (conversationsLoaded) { toast('会话刷新失败，暂时显示上次的列表'); return; }
            $('phone-active-conversation').textContent = '会话暂时无法读取，轻触重试';
            $('phone-printer-name').textContent = '加载失败';
            setReceiptExpanded(true);
            const notice = document.createElement('div'); notice.className = 'phone-list-notice'; notice.textContent = error.message;
            const retry = document.createElement('button'); retry.type = 'button'; retry.textContent = '重新加载'; retry.onclick = loadConversations; notice.appendChild(retry); $('phone-conversation-list').replaceChildren(notice);
        }
    }
    function setReceiptExpanded(expanded) {
        $('phone-conversation-list').hidden = !expanded;
        $('phone-printer-feed').setAttribute('aria-expanded', String(expanded));
        $('phone-printer-feed').setAttribute('aria-label', expanded ? '收起会话纸条' : '展开会话纸条');
    }
    function renderConversations() {
        const container = $('phone-conversation-list'); container.replaceChildren();
        const groups = new Map();
        const sorted = [...conversations].sort((a,b) => (Date.parse(b.created_at) || 0) - (Date.parse(a.created_at) || 0));
        for (const conv of sorted) {
            const date = new Date(conv.created_at); const month = Number.isNaN(date.getTime()) ? '更早的会话' : `${date.getFullYear()}年${date.getMonth()+1}月`;
            if (!groups.has(month)) groups.set(month, []); groups.get(month).push(conv);
        }
        if (!sorted.length) { container.innerHTML = '<p class="phone-list-notice">暂无会话</p>'; return; }
        for (const [month, items] of groups) {
            const group = document.createElement('section'); group.className = 'phone-conversation-group';
            const heading = document.createElement('h3'); heading.className = 'phone-month-title'; heading.textContent = month;
            heading.id = 'conversation-month-' + groups.size + '-' + container.children.length;
            group.setAttribute('aria-labelledby', heading.id);
            const list = document.createElement('ul'); group.append(heading, list); container.appendChild(group);
            for (const conv of items) {
                const row = document.createElement('button'); row.type = 'button'; row.className = 'phone-conversation-row'; row.dataset.conversationId = conv.id;
                const info = document.createElement('span'), title = document.createElement('strong'), detail = document.createElement('small');
                title.textContent = conv.name || '未命名会话';
                const date = new Date(conv.updated_at || conv.created_at);
                const dateLabel = document.createElement('span'); dateLabel.className = 'phone-conversation-date';
                dateLabel.textContent = Number.isNaN(date.getTime()) ? '' : date.toLocaleDateString('zh-CN');
                detail.appendChild(dateLabel);
                if (conv.message_count != null) {
                    const count = document.createElement('span'); count.className = 'phone-conversation-count';
                    count.textContent = `${conv.message_count} 条消息`; detail.appendChild(count);
                }
                info.append(title, detail); row.appendChild(info);
                if (conv.is_active) { const tag = document.createElement('span'); tag.className = 'phone-active-tag'; tag.textContent = '当前'; row.appendChild(tag); }
                row.onclick = () => openConversationDetail(conv.id);
                const entry = document.createElement('li'); entry.className = 'phone-conversation-entry';
                const options = document.createElement('button'); options.type = 'button'; options.className = 'phone-icon-button'; options.textContent = '···'; options.setAttribute('aria-label', '管理会话：' + (conv.name || '未命名会话'));
                options.onclick = () => conversationOptions(conv); entry.append(row, options); list.appendChild(entry);
            }
        }
    }
    function conversationOptions(conv) {
        sheet('管理会话', '<div class="phone-settings-group"><button type="button" id="phone-rename-conversation"><span>重命名会话</span><span data-phone-icon="pen"></span></button><button type="button" id="phone-extra-prompts"><span>额外提示词</span><span data-phone-icon="pen"></span></button><button type="button" id="phone-delete-conversation"><span>删除会话</span><span data-phone-icon="close"></span></button></div>');
        $('phone-extra-prompts').onclick = () => {
            $('phone-personalize').close();
            ConversationPrompts.open(conv.id);
        };
        $('phone-rename-conversation').onclick = () => {
            sheet('重命名会话', '<form id="phone-conversation-form"><label>会话名称<input id="phone-conversation-name" maxlength="120" required></label><button class="phone-primary-button" type="submit">保存名称</button></form>');
            $('phone-conversation-name').value = conv.name || '';
            $('phone-conversation-form').onsubmit = async event => {
                event.preventDefault(); const name = $('phone-conversation-name').value.trim(); if (!name) return;
                const button = event.target.querySelector('button'); button.disabled = true;
                try {
                    await json('/api/conversations/' + conv.id, {method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({name})});
                    $('phone-personalize').close(); await loadConversations(); toast('会话名称已更新');
                } catch (error) { toast(error.message); } finally { button.disabled=false; }
            };
        };
        $('phone-delete-conversation').onclick = () => {
            sheet('删除这段会话？', '<p class="phone-local-note" style="margin-bottom:20px">会话和其中的消息将从 Ash 删除。</p><button type="button" class="phone-primary-button" id="phone-confirm-delete-conversation">确认删除</button>');
            $('phone-confirm-delete-conversation').onclick = async event => {
                const button=event.currentTarget; button.disabled=true;
                try {
                    const frame=$('conversation-detail-frame');
                    if(frame.contentWindow?.isChatBusy?.()) throw new Error('请等待回复结束，或先停止接收，再删除会话');
                    await json('/api/conversations/' + conv.id,{method:'DELETE'});
                    local.saveDraft(conv.id,'');
                    if(frame.dataset.conversationId===String(conv.id)) { frame.contentWindow.location.replace('about:blank'); delete frame.dataset.conversationId; delete frame.dataset.contextSrc; }
                    $('phone-personalize').close(); await loadConversations(); toast('会话已删除');
                } catch(error) { toast(error.message); } finally { button.disabled=false; }
            };
        };
    }
    async function openAssistant() {
        if ($('phone-open-chat').disabled || creating) return;
        $('phone-open-chat').disabled = true;
        try {
            const data = await json('/api/conversations'); conversations = data.conversations || [];
            const active = conversations.find(item => item.is_active);
            if (active) navigateConversation(active.id);
            else await newConversation();
        } catch (error) { toast(error.message); }
        finally { $('phone-open-chat').disabled = false; }
    }
    let creating = false;
    async function newConversation() {
        if (creating) return; creating = true;
        try {
            if ($('conversation-detail-frame').contentWindow?.isChatBusy?.()) throw new Error('请等待回复结束，或先停止接收，再新建会话');
            const data = await json('/api/conversations', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({name: '新的对话'})});
            if (!data.conversation?.id) throw new Error('创建结果无效，请刷新会话列表核对');
            // Creating in the phone is an explicit request to start talking in the new conversation.
            await requestConversationActivation(data.conversation.id);
            openConversationDetail(data.conversation.id, true);
        } catch (error) { toast(error.message); } finally { creating = false; }
    }
    let usageGeneration = 0;
    async function loadUsage() {
        const generation = ++usageGeneration;
        try {
            const data = await json('/api/token-usage/summary?days=7'); if (generation !== usageGeneration) return;
            const today = data.today || new Date().toISOString().slice(0,10);
            const row = (data.daily_usage || []).find(item => item.day === today);
            const total = document.createTextNode(usageFormat(row?.total_tokens || 0));
            const unit = document.createElement('small'); unit.textContent = ' tokens'; $('phone-usage-total').replaceChildren(total, unit);
            $('phone-usage-description').textContent = `${row?.request_count || 0} 次请求`;
            const rows = (data.daily_usage || []).slice(-12); const max = Math.max(1,...rows.map(r => Number(r.total_tokens)||0));
            document.querySelectorAll('.phone-mini-bars i').forEach((el,i) => { el.style.height = Math.max(3, 40 * (Number(rows[i]?.total_tokens)||0) / max) + 'px'; });
        } catch (_) { $('phone-usage-total').textContent = '—'; $('phone-usage-description').textContent = '用量暂时无法读取 · 轻触重试'; }
    }
    async function exportLocal() {
        try {
            const assets = {};
            for (const key of ['avatar-user', 'avatar-assistant', 'album-cover']) {
                const blob = await local.asset(key); if (!(blob instanceof Blob)) continue;
                assets[key] = await new Promise((resolve,reject) => { const reader = new FileReader(); reader.onload = () => resolve(reader.result); reader.onerror = reject; reader.readAsDataURL(blob); });
            }
            const desktop = await window.AshDesktop.export();
            const keepsakes = await local.keepsakes();
            const url = URL.createObjectURL(new Blob([JSON.stringify({format:'ash-phone-desktop',version:3,state:local.get(),assets,desktop,keepsakes})], {type:'application/json'}));
            const link = document.createElement('a'); link.href = url; link.download = 'ash-desktop-' + new Date().toISOString().slice(0,10) + '.json'; link.click(); setTimeout(() => URL.revokeObjectURL(url),1000);
        } catch (error) { toast('导出失败：' + error.message); }
    }
    async function importLocal(file) {
        try {
            if (file.size > 20*1024*1024) throw new Error('文件过大');
            const data = JSON.parse(await file.text());
            if (data.format !== 'ash-phone-desktop' || ![1,2,3].includes(data.version) || data.state?.version !== 1) throw new Error('不是可识别的 Ash 桌面备份');
            if (data.version === 3 && !Array.isArray(data.keepsakes)) throw new Error('收藏备份格式无效');
            const keepsakes = data.version === 3 ? data.keepsakes.map(local.normalizeKeepsake) : null;
            const desktop = data.version >= 2 ? data.desktop : desktopFromLegacy(data.state);
            if(data.version===1 && data.state.wallpaper==='photo') desktop.wallpaperImage=data.assets?.wallpaper || '';
            const imported = {};
            for (const key of ['avatar-user','avatar-assistant', ...(data.version === 3 ? ['album-cover'] : [])]) {
                const value = data.assets?.[key];
                if (!value) { imported[key] = null; continue; }
                if (typeof value !== 'string' || !/^data:image\/(png|jpeg|webp);base64,/.test(value)) throw new Error('备份图片格式无效');
                const [header, bytes] = value.split(',');
                const binary = atob(bytes); const buffer = Uint8Array.from(binary, c=>c.charCodeAt(0));
                imported[key] = await local.image(new File([buffer], key, {type:header.slice(5,header.indexOf(';'))}), {square:key.startsWith('avatar-')});
            }
            await window.AshDesktop.restore(desktop);
            // Profile pictures are independent of the native desktop's transactional media store.
            await local.replaceAssets(imported);
            if (keepsakes) await local.replaceKeepsakes(keepsakes);
            if (!save(state => Object.assign(state, data.state))) return;
            await paintAvatars(true); toast('本机桌面已恢复');
        } catch (error) { toast('导入失败：' + error.message); }
    }
    window.AshPhone = {navigate,navigateConversation,back,presentSection,presentConversation,
        returnTitle:()=>screenTitle(stack.at(-1)),toast,profile,sheet};
    // The desktop itself is Merle's module. This boundary supplies Ash destinations and identity.
    function desktopFromLegacy(legacy = {}) {
        legacy ||= {};
        const ids = {together:'widget-ash-together',note:'widget-ash-note',settings:'preferences',presets:'diary'};
        const allowed = new Set(['chat','heartbeats','standing','diary','preferences','theme',...Object.keys(ids)]);
        const map = id => ids[id] || id;
        const seen = new Set();
        const hasLegacyLayout = Array.isArray(legacy.pages) && legacy.pages.length;
        const pages = hasLegacyLayout
            ? legacy.pages.map(page => Array.isArray(page) ? page.filter(id=>allowed.has(id)).map(map) : [])
            : [['widget-ash-together','widget-ash-note','chat','heartbeats','standing','diary'],[]];
        for(let i=0;i<pages.length;i++) pages[i]=pages[i].filter(id=>{if(seen.has(id))return false;seen.add(id);return true;});
        const dock = hasLegacyLayout
            ? (seen.has('preferences') ? ['theme',null,null,null] : ['preferences','theme',null,null])
            : ['bots','preferences','theme',null];
        const positions = hasLegacyLayout ? {} : {
            'widget-ash-together': {row:0,col:0},
            'widget-ash-note': {row:2,col:0},
            chat: {row:2,col:2}, heartbeats: {row:2,col:3},
            standing: {row:3,col:2}, diary: {row:3,col:3},
        };
        for(const [id,pos] of Object.entries(legacy.positions || {})) if(allowed.has(id)) positions[map(id)] = pos;
        return {pages,dock,
            positions,hiddenPages:[],hidden:['chat','heartbeats','standing','diary','preferences'].filter(id=>!seen.has(id)&&!dock.includes(id)),customApps:{},icons:{},themePresets:[],
            widgets:{'widget-ash-together':{type:'together',size:'large',title:'',image:''},
                'widget-ash-note':{type:'note',size:'square',title:'给今天的一句话',text:legacy.note || '把平凡的日子，\n过成我们的小小世界。',image:'',look:'paper'}},
            wallpaper:({rose:'berry',sage:'tide'})[legacy.wallpaper] || 'dawn',wallpaperImage:'',wallpaperY:50,dim:15,ink:'auto',
            iconStyle:legacy.iconStyle || 'soft',iconOpacity:Number.isFinite(legacy.iconOpacity) ? legacy.iconOpacity : 100,mode:'auto'};
    }
    const legacyWallpaper = local.legacyDesktop()?.wallpaper === 'photo' && !localStorage.getItem('ash.phone.desktop.v2');
    window.AshDesktopConfig = {
        apps:Object.fromEntries([['chat','Chat','chat'],['heartbeats','苏醒','heart'],['standing','记忆','memory'],
            ['diary','日记','pen'],['bots','Bot','smile'],['preferences','设置','settings'],['theme','装扮','palette']]
            .map(([id,label,symbol])=>[id,{label,className:id,icon:icon(symbol)}])),
        migrateLayout(saved) {
            if (!saved || typeof saved !== 'object') return saved;
            const data = structuredClone(saved), map = id => id === 'presets' ? 'diary' : id;
            if (Array.isArray(data.pages)) data.pages = data.pages.map(page=>Array.isArray(page)?page.map(map):page);
            for (const field of ['dock','hidden']) if (Array.isArray(data[field])) data[field] = data[field].map(map);
            for (const field of ['positions','icons']) if (data[field]?.presets) {
                data[field].diary ??= data[field].presets; delete data[field].presets;
            }
            for (const preset of Array.isArray(data.themePresets) ? data.themePresets : []) {
                const icons = preset.appearance?.icons;
                if (icons?.presets) { icons.diary ??= icons.presets; delete icons.presets; }
            }
            return data;
        },
        defaultLayout:()=>desktopFromLegacy(local.legacyDesktop()),
        pairMarkup:()=>`<div class="phone-together-widget"><div class="phone-pair">${pairControls()}</div></div>`,
        pairSettings:()=>`<div class="phone-pair phone-pair-editor">${pairControls()}</div>`,
        profile, editName,
        renderIdentity:()=>queueMicrotask(()=>{renderNames();paintAvatars();}),
        fromLegacy:desktopFromLegacy,
        legacyWallpaper:()=>legacyWallpaper ? local.asset('wallpaper') : null,
    };
    window.openMainTab = navigate;
    window.showToast = toast;
    new MutationObserver(()=>window.dispatchEvent(new Event('merle:theme-change'))).observe(document.documentElement,{attributes:true,attributeFilter:['data-theme']});
    document.addEventListener('DOMContentLoaded', () => {
        document.querySelector('.coffee-desk')?.appendChild(document.querySelector('.coffee-recipe'));
        document.querySelector('.heartbeat-newspaper').open = true;
        icons(); renderNames(); paintAvatars();
        $('phone-home-button').onclick = () => navigate('home');
        $('phone-back').onclick = back;
        $('phone-header-action').onclick = newConversation;
        $('phone-supplier-add').onclick = () => document.body.dataset.phoneView === 'supplier-anthropic' ? toggleAnthropicProviderCreator() : toggleOpenAiProviderCreator();
        $('phone-open-chat').onclick = openAssistant;
        $('phone-printer-feed').onclick = () => setReceiptExpanded($('phone-conversation-list').hidden);
        $('phone-chat-usage').onclick = () => openUsageBoard();
        $('phone-me-config').onclick = () => navigate('supplier-route');
        $('phone-me-favorites').onclick = () => navigate('favorites');
        $('phone-favorites-retry').onclick = renderFavorites;
        $('phone-me-retry').onclick = loadMeConfiguration;
        $('phone-backup-settings').onclick = () => navigate('phone-transfer');
        $('phone-export-local').onclick = exportLocal; $('phone-import-local').onclick = () => $('phone-local-backup').click();
        $('phone-local-backup').onchange = async event => { if (event.target.files[0]) await importLocal(event.target.files[0]); event.target.value = ''; };
        $('phone-avatar-menu').onclick = async event => {
            const action = event.target.closest('[data-avatar-action]')?.dataset.avatarAction;
            if (!action) return;
            const role = $('phone-avatar-menu').dataset.role;
            $('phone-avatar-menu').hidePopover();
            if (action === 'image') chooseImage('avatar-'+role);
            else try { await local.asset('avatar-'+role,null); } catch (error) { toast(error.message); }
        };
        window.addEventListener('resize',()=>{const menu=$('phone-avatar-menu');if(menu.matches(':popover-open'))menu.hidePopover();});
        $('phone-local-image').onchange = async event => {
            const file = event.target.files[0], key = imageTarget; if (!file || !key) return;
            try {
                const blob = await local.image(file, {square:key.startsWith('avatar-')}); await local.asset(key,blob);
                await paintAvatars(true); toast('图片已保存在本机');
            } catch (error) { toast('图片未保存：' + error.message); } finally { event.target.value=''; }
        };
        document.addEventListener('click', event => {
            const actionable = event.target.closest('[data-phone-app],[data-phone-command],[data-phone-profile],[data-phone-name],[data-chat-tab]'); if (!actionable) return;
            if (actionable.closest('#phone-home') && !actionable.closest('.phone-customize')) return; // Merle owns desktop gestures and launches.
            if (actionable.dataset.phoneApp) navigate(actionable.dataset.phoneApp);
            if (actionable.dataset.phoneProfile) profile(actionable.dataset.phoneProfile, actionable);
            if (actionable.dataset.phoneName) editName(actionable);
            if (actionable.dataset.chatTab) selectTab(actionable.dataset.chatTab);
            const command = actionable.dataset.phoneCommand;
            if (command === 'appearance') window.AshDesktop.customize();
        });
        $('phone-personalize').addEventListener('click',event=>{ if (event.target === $('phone-personalize')) { const r=event.target.getBoundingClientRect(); if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom) event.target.close(); } });
    });
    window.addEventListener('ash-local-change', event => {
        if (screen?.name === 'favorites') renderFavorites();
        if (['keepsakes','note-layout'].includes(event.detail?.kind)) return;
        renderNames(); paintAvatars(event.detail?.kind === 'assets');
        $('conversation-detail-frame')?.contentWindow?.postMessage({type:'ash-local-presentation'}, location.origin);
    });
    window.addEventListener('ash-local-error', event=>toast(event.detail));
    window.addEventListener('message',event=>{
        if (event.origin !== location.origin || event.source !== $('conversation-detail-frame')?.contentWindow) return;
        if(event.data?.type === 'ash-keepsakes-changed' && screen?.name === 'favorites') renderFavorites();
        if(event.data?.type === 'memory-gateway-open-chat-configuration') navigate('supplier-route');
        if(event.data?.type === 'memory-gateway-chat-updated') { loadConversations(); loadUsage(); }
    });
})();
