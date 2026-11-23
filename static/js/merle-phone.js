/* Merle assets/phone.js, ported with an Ash app registry, paired-avatar widget and backup boundary.
 * Desktop layout, gestures and customization use the original implementation. */
(() => {
    const host = window.AshDesktopConfig;
    const APP_DEFINITIONS = Object.freeze(host.apps);
    const KEY = 'ash.phone.desktop.v2';
    const DEFAULT_ORDER = Object.keys(APP_DEFINITIONS);
    const ALL_APPS = [...DEFAULT_ORDER];
    const PRESETS = {dawn: ['素白', '#f8f8f6'], tide: ['雾绿', '#dce5df'], berry: ['花笺', '#eddfdf'], night: ['夜色', '#1F1E1D']};
    const WIDGETS = {together: ['双人头像', '头像与展示昵称', '♡'], clock: ['时钟', '把此刻留在桌面', '◷'], calendar: ['日历', '每一天都值得期待', '▦'], note: ['心情便签', '写下一句喜欢的话', '✎'], photo: ['照片', '装下喜欢的风景', '▧'], anniversary: ['纪念日', '记录特别的日子', '♡']};
    const WIDGET_SIZES = {together: ['large'], clock: ['large', 'wide', 'square'], calendar: ['large', 'square'], note: ['wide', 'square', 'large'], photo: ['large', 'square', 'portrait'], music: ['wide', 'square'], anniversary: ['wide', 'square']};
    const WIDGET_LOOKS = {paper: '折角纸卡', frame: '拍立得', collage: '照片拼贴'};
    const widgetLook = w => WIDGET_LOOKS[w.look] ? w.look : ({photo:'frame',clock:'collage',anniversary:'collage',music:'frame'}[w.type] || 'paper');
    const imagePosition = w => Number.isFinite(Number(w.imageY)) ? Math.max(0, Math.min(100, Number(w.imageY))) : 50;
    const SIZE_LABELS = {wide: '横条 · 4 × 1', square: '小卡 · 2 × 2', large: '横幅 · 4 × 2', portrait: '竖幅 · 2 × 3'};
    const widgetSize = w => WIDGET_SIZES[w.type].includes(w.size) ? w.size : WIDGET_SIZES[w.type][0];
    const $ = id => document.getElementById(id);
    const home = $('phone-home'), pages = $('phone-pages'), panel = $('phone-customize');
    if (!home || !pages) return;
    const media = window.merlePhoneMedia;
    const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
    const imageURL = value => media.isReference(value) || (typeof value === 'string' && /^data:image\/(jpeg|png|webp);base64,[a-z0-9+/=]+$/i.test(value)) ? value : '';
    const imageSource = value => media.source(value);
    const defaultLayout = () => {
        const value = {...host.defaultLayout(), wallpapers:[]};
        delete value.mode; // Application appearance is owned by AshTheme.
        return value;
    };
    const iconOpacity = value => typeof value==='number'&&Number.isFinite(value) ? Math.round(Math.max(0,Math.min(100,value))) : 100;
    const knownApp = (data, id) => Object.hasOwn(APP_DEFINITIONS, id) || Object.hasOwn(data.customApps, id);
    const allApps = data => [...ALL_APPS, ...Object.keys(data.customApps)];
    const customIcon = '<svg class="phone-symbol" viewBox="0 0 32 32" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="5" width="24" height="23" rx="5"/><path class="phone-symbol-secondary" d="M4 12h24m-13 5-4 4 4 3m6-7 4 4-4 3"/></svg>';
    function itemSpan(data, id) {
        const w = data.widgets[id];
        return w ? ({wide: [4, 1], square: [2, 2], large: [4, 2], portrait: [2, 3]})[widgetSize(w)] : [1, 1];
    }
    function overlaps(data, a, pa, b, pb) {
        const [aw, ah] = itemSpan(data, a), [bw, bh] = itemSpan(data, b);
        return pa.col < pb.col + bw && pb.col < pa.col + aw && pa.row < pb.row + bh && pb.row < pa.row + ah;
    }
    function vacantPosition(data, id, occupied, preferred) {
        const [width] = itemSpan(data, id), candidates = [];
        const lastRow = Math.max(preferred?.row || 0, ...occupied.map(other => data.positions[other].row + itemSpan(data, other)[1]), 0);
        for (let row = 0; row <= lastRow; row++) for (let col = 0; col <= 4 - width; col++) candidates.push({row, col});
        if (preferred) candidates.sort((a, b) => (Math.abs(a.row - preferred.row) + Math.abs(a.col - preferred.col)) - (Math.abs(b.row - preferred.row) + Math.abs(b.col - preferred.col)));
        return candidates.find(pos => occupied.every(other => !overlaps(data, id, pos, other, data.positions[other])));
    }
    // Keep saved empty cells. Legacy ordered desktops receive explicit grid coordinates.
    function normalizePositions(data) {
        const saved = data.positions && typeof data.positions === 'object' ? data.positions : {};
        data.positions = {};
        data.pages.forEach(items => {
            const occupied = [], pending = [];
            items.forEach(id => {
                const pos = saved[id], [width] = itemSpan(data, id);
                if (pos && Number.isInteger(pos.row) && pos.row >= 0 && pos.row <= 500 && Number.isInteger(pos.col) && pos.col >= 0 && pos.col <= 4 - width && occupied.every(other => !overlaps(data, id, pos, other, data.positions[other]))) {
                    data.positions[id] = {row: pos.row, col: pos.col}; occupied.push(id);
                } else pending.push(id);
            });
            pending.forEach(id => { data.positions[id] = vacantPosition(data, id, occupied); occupied.push(id); });
        });
    }
    function moveToCell(data, page, id, position) {
        const [width] = itemSpan(data, id);
        const next = {row: Math.max(0, Math.min(500, position.row)), col: Math.max(0, Math.min(4 - width, position.col))};
        const others = data.pages[page].filter(other => other !== id);
        const displaced = others.filter(other => overlaps(data, id, next, other, data.positions[other]));
        const occupied = [id, ...others.filter(other => !displaced.includes(other))];
        data.positions[id] = next;
        displaced.forEach(other => { data.positions[other] = vacantPosition(data, other, occupied, data.positions[other]); occupied.push(other); });
    }
    function positionStyle(id) {
        const pos = layout.positions[id], [width, height] = itemSpan(layout, id);
        return `grid-column: ${pos.col + 1} / span ${width}; grid-row: ${pos.row + 1} / span ${height};`;
    }
    function normalizeAppearance(value, data) {
        const source = value && typeof value === 'object' ? value : {};
        const icons = {};
        Object.entries(source.icons || {}).forEach(([id, image]) => { if (knownApp(data, id) && imageURL(image)) icons[id] = imageURL(image); });
        const clamp = (value, max, fallback) => Number.isFinite(+value) ? Math.max(0, Math.min(max, +value)) : fallback;
        const wallpaperImage = imageURL(source.wallpaperImage);
        const wallpapers = [...new Set((Array.isArray(source.wallpapers) ? source.wallpapers : []).map(imageURL).filter(Boolean))];
        if (wallpaperImage && !wallpapers.includes(wallpaperImage)) wallpapers.unshift(wallpaperImage);
        return {
            wallpapers,
            wallpaper: PRESETS[source.wallpaper] ? source.wallpaper : 'dawn', wallpaperImage: imageURL(source.wallpaperImage),
            wallpaperY: clamp(source.wallpaperY, 100, 50), dim: clamp(source.dim, 70, 15),
            ink: ['auto','light','dark'].includes(source.ink) ? source.ink : 'auto',
            iconStyle: ['soft','glass','round'].includes(source.iconStyle) ? source.iconStyle : 'soft',
            iconOpacity:iconOpacity(source.iconOpacity),
            mode: ['auto','light','dark'].includes(source.mode) ? source.mode : 'auto', icons,
        };
    }
    function readLayout(serialized) {
        try {
            const parsed = JSON.parse(serialized ?? localStorage.getItem(KEY) ?? 'null');
            const saved = host.migrateLayout ? host.migrateLayout(parsed) : parsed;
            if (!saved) return defaultLayout();
            const result = {...defaultLayout(), ...saved, widgets: {}, icons: {}, customApps: {}};
            Object.entries(saved.customApps || {}).forEach(([id, app]) => {
                if (/^webapp-[\w-]{1,100}$/.test(id) && app && typeof app.label === 'string') result.customApps[id] = {label: app.label.slice(0, 40), fileName: String(app.fileName || '').slice(0, 160)};
            });
            Object.entries(saved.widgets || {}).forEach(([id, w]) => {
                if (/^widget-[\w-]+$/.test(id) && w && WIDGETS[w.type]) result.widgets[id] = {
                    type: w.type, size: widgetSize(w), title: String(w.title || '').slice(0, 80), text: String(w.text || '').slice(0, 400),
                    date: /^\d{4}-\d{2}-\d{2}$/.test(w.date) ? w.date : '', image: imageURL(w.image),
                    look: widgetLook(w), imageY: imagePosition(w),
                };
            });
            Object.entries(saved.icons || {}).forEach(([id, url]) => { if (knownApp(result, id)) result.icons[id] = imageURL(url); });
            const seen = new Set();
            result.pages = (Array.isArray(saved.pages) ? saved.pages : [[]]).filter(Array.isArray).map(page => page.filter(id => {
                if ((!knownApp(result, id) && !result.widgets[id]) || seen.has(id)) return false;
                seen.add(id); return true;
            }));
            if (!result.pages.length) result.pages = [[]];
            result.hiddenPages = [...new Set(Array.isArray(saved.hiddenPages) ? saved.hiddenPages : [])].filter(i => Number.isInteger(i) && i >= 0 && i < result.pages.length);
            if (result.hiddenPages.length === result.pages.length) result.hiddenPages = result.hiddenPages.filter(i => i !== 0);
            const dockSource=Array.isArray(saved.dock)?saved.dock:['npc-chats','music'];
            result.dock=[null,null,null,null];
            dockSource.forEach((id,index)=>{
                if(!knownApp(result,id)||seen.has(id))return;
                seen.add(id);
                if(index<4)result.dock[index]=id;
                else result.pages[0].push(id);
            });
            result.hidden = allApps(result).filter(id => id !== 'theme' && !seen.has(id) && saved.hidden?.includes(id));
            const storePage = result.pages.findIndex((_, i) => !result.hiddenPages.includes(i));
            allApps(result).forEach(id => { if (!seen.has(id) && !result.hidden.includes(id)) result.pages[id === 'app-store' ? storePage : 0].push(id); });
            Object.keys(result.widgets).forEach(id => { if (!seen.has(id)) delete result.widgets[id]; });
            result.wallpaper = PRESETS[result.wallpaper] ? result.wallpaper : 'dawn';
            result.wallpaperImage = imageURL(result.wallpaperImage);
            result.wallpaperY = Number.isFinite(+result.wallpaperY) ? Math.min(100, Math.max(0, +result.wallpaperY)) : 50;
            result.dim = Number.isFinite(+result.dim) ? Math.min(70, Math.max(0, +result.dim)) : 15;
            result.ink = ['auto', 'light', 'dark'].includes(result.ink) ? result.ink : 'auto';
            Object.assign(result, normalizeAppearance(result, result));
            delete result.mode;
            // Retain previously saved appearances in local backups after removing the presets page.
            const presetIds = new Set();
            result.themePresets = (Array.isArray(saved.themePresets) ? saved.themePresets : []).filter(preset => {
                if (!preset || !/^theme-[\w-]{1,100}$/.test(preset.id) || presetIds.has(preset.id) || typeof preset.name !== 'string') return false;
                presetIds.add(preset.id); return true;
            }).map(preset => ({id:preset.id, name:preset.name.trim().slice(0,40) || '未命名主题', appearance:normalizeAppearance(preset.appearance, result)}));
            return result;
        } catch { return defaultLayout(); }
    }
    let layout = readLayout(), currentPage = 0, editing = false, selected = '', tab = 'wallpaper', widgetEditor = '', mediaReady = Promise.resolve();
    function revealWidget(id = '') {
        pages.querySelectorAll('.phone-widget').forEach(node => {
            const active = node.dataset.item === id && !editing;
            node.classList.toggle('is-widget-active', active);
            node.querySelector('.phone-widget-edit').hidden = !active;
            node.querySelector('.phone-widget-body').setAttribute('aria-expanded', String(active));
        });
    }
    normalizePositions(layout);
    let snapshot = window.merlePhoneMusicSnapshot || {}, pointer = null, suppressClickUntil = 0, returnFocus = null;
    const dockIcons = {};
    home.querySelectorAll('[data-phone-launch]').forEach(button => { dockIcons[button.dataset.phoneLaunch] = button.querySelector('.phone-app-icon').innerHTML; });
    function announce(message) {
        $('phone-customize-status').textContent = window.showToast ? '' : message;
        window.showToast?.(message);
    }
    // Commit atomically: quota failures must not leave an unsaved desktop on screen.
    function commit(change) {
        const before = JSON.stringify(layout);
        change();
        normalizePositions(layout);
        try { localStorage.setItem(KEY, JSON.stringify(layout)); }
        catch (error) {
            layout = JSON.parse(before);
            announce(error.name === 'QuotaExceededError' ? '本机存储空间不足，本次修改未保存。请释放浏览器空间后重试。' : '无法保存桌面设置，请允许浏览器使用本机存储后重试。');
            return false;
        }
        window.dispatchEvent(new Event('merle:phone-apps-changed'));
        collectImages(); return true;
    }
    function collectImages() {
        media.collect(() => {
            try { return [layout, JSON.parse(localStorage.getItem(KEY) || '{}')]; }
            catch { return [layout]; }
        }).catch(() => {});
    }
    function iconMarkup(id) {
        return imageSource(layout.icons[id]) ? `<img src="${imageSource(layout.icons[id])}" alt="" draggable="false">` : (APP_DEFINITIONS[id]?.icon || dockIcons[id] || customIcon);
    }
    function itemLabel(id) { return APP_DEFINITIONS[id]?.label || layout.customApps[id]?.label || WIDGETS[layout.widgets[id]?.type]?.[0] || ''; }
    function widgetContent(w) {
        if (w.type === 'together') return host.pairMarkup();
        const now = new Date();
        if (w.type === 'clock') return `<div class="phone-clock-caption"><span>${now.toLocaleDateString('zh-CN', {month:'long',day:'numeric',weekday:'short'})}</span>${w.title?`<span class="phone-clock-title">${escape(w.title)}</span>`:''}</div><time class="phone-widget-time" datetime="${String(now.getHours()).padStart(2,'0')}:${String(now.getMinutes()).padStart(2,'0')}">${now.toLocaleTimeString('zh-CN', {hour: '2-digit', minute: '2-digit', hour12: false})}</time>`;
        if (w.type === 'note') return `<span class="phone-widget-eyebrow">${escape(w.title || '给今天的一句话')}</span><p class="phone-note-text">${escape(w.text || '慢慢来，好事正在发生。')}</p><span class="phone-note-flower" aria-hidden="true">♡</span>`;
        if (w.type === 'photo') return `${imageSource(w.image) ? `<img class="phone-widget-photo" src="${imageSource(w.image)}" style="object-position:center ${imagePosition(w)}%" alt="${escape(w.title || '桌面照片')}" draggable="false">` : '<span class="phone-photo-placeholder" aria-hidden="true">♡</span>'}<span class="phone-photo-caption">${escape(w.title || 'little moments ♡')}</span>`;
        if (w.type === 'anniversary') {
            const date = new Date(`${w.date}T00:00:00`);
            const days = Number.isNaN(date.getTime()) ? null : Math.round((Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()) - Date.UTC(now.getFullYear(), now.getMonth(), now.getDate())) / 86400000);
            return `<span class="phone-widget-eyebrow">${escape(w.title || '特别的一天')}</span><strong class="phone-widget-day">${days === null ? '♡' : Math.abs(days)}<small>${days === null ? '' : ' 天'}</small></strong><small>${days === null ? '留给特别的一天' : days > 0 ? '距离那一天' : days === 0 ? '就是今天' : '已经一起走过'}</small>`;
        }
        if (w.type === 'calendar') {
            const count = new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate();
            const offset = (new Date(now.getFullYear(), now.getMonth(), 1).getDay() + 6) % 7;
            return `<span class="phone-widget-eyebrow">${escape(w.title || `${now.getFullYear()} / ${String(now.getMonth() + 1).padStart(2, '0')}`)}</span><div class="phone-mini-calendar">${['一','二','三','四','五','六','日'].map(d => `<small>${d}</small>`).join('')}${'<span></span>'.repeat(offset)}${Array.from({length: count}, (_, i) => `<span class="${i + 1 === now.getDate() ? 'today' : ''}">${i + 1}</span>`).join('')}</div>`;
        }
        return `<button type="button" class="phone-widget-music-open" data-widget-music-open aria-label="打开一起听"><span class="phone-record" aria-hidden="true">♫</span>${w.title ? `<span class="phone-widget-eyebrow">${escape(w.title)}</span>` : ''}<strong>${escape(snapshot.title || '挑一首歌吧')}</strong><small>${escape(snapshot.artist || '音乐会一直陪着你')}</small></button><button type="button" class="phone-widget-play" data-widget-music-play aria-label="${snapshot.playing ? '暂停' : '播放'}">${snapshot.playing ? 'Ⅱ' : '▶'}</button>`;
    }
    function decoratedWidgetContent(w) {
        if(w.type==='clock')return widgetContent(w);
        const image = imageSource(w.image) && w.type !== 'photo' ? `<img class="phone-widget-image" src="${imageSource(w.image)}" style="object-position:center ${imagePosition(w)}%" alt="" draggable="false">` : '';
        return image + widgetContent(w);
    }
    function saveWidgetFields(w, form) {
        const data = new FormData(form);
        w.size = String(data.get('size') || widgetSize(w));
        w.title = String(data.get('title') || '').trim();
        if(data.has('look'))w.look = WIDGET_LOOKS[data.get('look')] ? data.get('look') : 'paper';
        if(data.has('imageY'))w.imageY = imagePosition({imageY:data.get('imageY')});
        if (data.has('text')) w.text = String(data.get('text'));
        if (data.has('date')) w.date = String(data.get('date'));
    }
    function itemMarkup(id, inDock = false) {
        const w = layout.widgets[id];
        const remove = id === 'theme' ? '' : `<button type="button" class="phone-item-remove" data-remove="${id}" aria-label="移除${escape(itemLabel(id))}" ${editing ? '' : 'hidden'}>−</button>`;
        return `<div class="phone-desktop-item ${w ? `phone-widget phone-widget-${w.type}` : 'phone-app-item'} ${inDock?'phone-dock-item':''} ${selected === id ? 'is-selected' : ''}" data-item="${id}" ${w ? `data-size="${widgetSize(w)}" data-look="${w.type==='clock'?'clear':widgetLook(w)}" data-has-image="${!!w.image}"` : ''}>${remove}${w ? `<button type="button" class="phone-widget-edit" data-widget-edit="${id}" aria-label="编辑${escape(itemLabel(id))}" hidden>✎</button>` : ''}${w ? `<div class="phone-widget-body" role="button" tabindex="0" aria-label="显示${escape(itemLabel(id))}编辑按钮" aria-expanded="false">${decoratedWidgetContent(w)}</div>` : `<button type="button" class="phone-app" ${inDock?'data-phone-launch':'data-phone-app'}="${id}" aria-label="${editing ? '选择' : '打开'}${escape(itemLabel(id))}"><span class="phone-app-icon phone-app-icon-${APP_DEFINITIONS[id]?.className || 'web-app'}" aria-hidden="true">${iconMarkup(id)}</span><span>${escape(itemLabel(id))}</span></button>`}</div>`;
    }
    function renderDesktop() {
        if (!visiblePages().includes(currentPage)) currentPage = visiblePages()[0];
        pages.innerHTML = visiblePages().map(i => { const items = layout.pages[i]; return `<section class="phone-desktop-page" data-layout-page="${i}" aria-label="第 ${i + 1} 页"><div class="phone-app-grid">${items.map(id=>itemMarkup(id)).join('')}</div>${items.length ? '' : '<p class="phone-empty-page">留一点空白给喜欢的事物<br><small>添加组件，或在整理时将应用移到这里</small></p>'}</section>`; }).join('');
        pages.querySelectorAll('[data-item]').forEach(node => { node.style.cssText = positionStyle(node.dataset.item); });
        pages.scrollLeft = visiblePages().indexOf(currentPage) * pages.clientWidth;
        renderDock();
        renderNavigation(); host.renderIdentity();
    }
    function renderDock() {
        home.querySelector('.phone-dock').innerHTML=Array.from({length:4},(_,index)=>`<div class="phone-dock-slot${layout.dock[index]?'':' is-empty'}" data-dock-slot="${index}">${layout.dock[index]?itemMarkup(layout.dock[index],true):'<span class="phone-dock-empty" aria-hidden="true">＋</span>'}</div>`).join('');
    }
    function renderNavigation() {
        const dots = $('phone-page-dots');
        const focusedPage = dots.contains(document.activeElement) ? document.activeElement.dataset.page : null;
        dots.innerHTML = visiblePages().map(i => `<button type="button" data-page="${i}" aria-label="第 ${i + 1} 页" aria-current="${i === currentPage ? 'page' : 'false'}"></button>`).join('');
        if (focusedPage != null) dots.querySelector(`[data-page="${focusedPage}"]`)?.focus({ preventScroll: true });
        const active = dots.querySelector('[aria-current="page"]');
        if (active) dots.scrollLeft = active.offsetLeft - (dots.clientWidth - active.offsetWidth) / 2;
        $('phone-prev-page').disabled = currentPage === visiblePages()[0];
        $('phone-next-page').disabled = currentPage === visiblePages().at(-1);
        $('phone-selection-label').textContent = selected ? itemLabel(selected) : '点选应用或组件';
        $('phone-move-page').innerHTML = layout.pages.map((_, i) => `<option value="${i}" ${i === currentPage&&!layout.dock.includes(selected) ? 'selected' : ''}>第 ${i + 1} 页</option>`).join('')+`<option value="dock" ${layout.dock.includes(selected)?'selected':''} ${layout.widgets[selected]?'disabled':''}>底部 Dock</option>`;
        $('phone-move-item').disabled = !selected;
    }
    function visiblePages() { return layout.pages.map((_, i) => i).filter(i => !layout.hiddenPages.includes(i)); }
    function stepPage(delta, from = currentPage) { const visible = visiblePages(); goPage(visible[Math.max(0, Math.min(visible.length - 1, visible.indexOf(from) + delta))]); }
    function goPage(index) {
        revealWidget();
        const visible = visiblePages();
        currentPage = visible.includes(index) ? index : visible[0];
        pages.scrollTo({left: visiblePages().indexOf(currentPage) * pages.clientWidth, behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth'});
        renderNavigation();
    }
    function applyTheme() {
        home.dataset.wallpaper = layout.wallpaper;
        home.dataset.iconStyle = layout.iconStyle;
        home.dataset.ink = layout.ink;
        applyIconOpacity();
        home.classList.toggle('has-custom-wallpaper', !!imageSource(layout.wallpaperImage));
        const bg = $('phone-wallpaper');
        bg.style.backgroundImage = imageSource(layout.wallpaperImage) ? `linear-gradient(rgba(0,0,0,${layout.dim / 100}),rgba(0,0,0,${layout.dim / 100})),url("${imageSource(layout.wallpaperImage)}")` : '';
        bg.style.backgroundPosition = `center ${layout.wallpaperY}%`;
        syncSystemChrome();
    }
    function applyIconOpacity(value=layout.iconOpacity) {
        const percent=iconOpacity(value);
        for(const node of [home,panel])node.style.setProperty('--phone-icon-opacity',String(percent/100));
        const input=$('phone-icon-opacity-range'),output=$('phone-icon-opacity-value');
        if(input){input.value=String(percent);input.setAttribute('aria-valuetext',percent+'%');}
        if(output)output.value=percent+'%';
    }
    function syncSystemChrome() {
        const root = document.documentElement, active = $('page-phone').classList.contains('active');
        root.classList.toggle('phone-system-active', active);
        home.dataset.mode = root.dataset.theme;
        const systemBackground = getComputedStyle(home).getPropertyValue('--phone-paper').trim();
        if (active) {
            root.style.setProperty('--phone-system-background', systemBackground);
            root.style.setProperty('--phone-system-wallpaper', getComputedStyle($('phone-wallpaper')).backgroundImage);
        } else {
            root.style.removeProperty('--phone-system-background'); root.style.removeProperty('--phone-system-wallpaper');
        }
        document.querySelector('meta[name="theme-color"]')?.setAttribute('content', active ? systemBackground : root.dataset.theme === 'dark' ? '#1F1E1D' : '#FAF9F5');
    }
    function setEditing(value) {
        if (!value) finishPointer(true);
        editing = value; selected = '';
        revealWidget();
        home.classList.toggle('is-editing', value);
        $('phone-home-actions').hidden = !value;
        $('btn-phone-edit').setAttribute('aria-pressed', String(value));
        $('phone-move-bar').hidden = !value;
        home.querySelectorAll('[data-remove]').forEach(button => { button.hidden = !value; });
        home.querySelectorAll('[data-phone-app], [data-phone-launch]').forEach(button => button.setAttribute('aria-label', `${value ? '选择' : '打开'}${itemLabel(button.dataset.phoneApp||button.dataset.phoneLaunch)}`));
        pages.querySelectorAll('[data-item]').forEach(item => item.classList.remove('is-selected'));
        home.querySelector('.phone-dock').querySelectorAll('[data-item]').forEach(item=>item.classList.remove('is-selected'));
        renderNavigation();
    }
    function openCustomize(next = 'wallpaper', overview = false) {
        restoreSettingsEditor();
        returnFocus = document.activeElement;
        revealWidget();
        tab = ['wallpaper','icons','widgets','pages'].includes(next) ? next : 'wallpaper'; widgetEditor = ''; panel.inert = false;
        panel.classList.remove('is-previewing');
        $('btn-phone-customize-preview').setAttribute('aria-pressed','false');
        $('btn-phone-customize-preview').setAttribute('aria-label','预览桌面');
        panel.classList.toggle('is-page-overview', overview);
        panel.classList.add('show'); panel.setAttribute('aria-hidden', 'false');
        home.querySelector('main').inert = true; home.querySelector('footer').inert = true;
        renderPanel(); $('btn-phone-customize-close').focus();
    }
    function closeCustomize(restoreFocus = true) {
        applyIconOpacity();
        panel.classList.remove('show'); panel.setAttribute('aria-hidden', 'true'); panel.inert = true;
        home.querySelector('main').inert = false; home.querySelector('footer').inert = false;
        if (restoreFocus) { if (returnFocus?.isConnected && returnFocus.getClientRects().length) returnFocus.focus(); else pages.focus(); }
    }
    function launch(id, source = 'phone') {
        if (id === 'theme') {
            if ($('page-settings') && window.setSettingsSection) { window.openMainTab?.('settings'); window.setSettingsSection('appearance'); }
            else openCustomize();
            return;
        }
        setEditing(false);
        if (layout.customApps[id]) { window.merleAppStore?.openCustom(id, source); return; }
        window.openMainTab?.(id);
    }
    let settingsEditor = false;
    function restoreSettingsEditor() {
        if (!settingsEditor) return;
        closeCustomize(false);
        settingsEditor = false;
        panel.classList.remove('is-settings-editor');
        home.appendChild(panel);
        const sheet = panel.querySelector('.phone-customize-sheet');
        sheet.setAttribute('role', 'dialog'); sheet.setAttribute('aria-modal', 'true');
    }
    window.addEventListener('merle:settings-screen', event => {
        const {pageId, section} = event.detail;
        const host = pageId === 'page-settings' && document.querySelector(`[data-phone-settings-mount="${section}"]`);
        if (!host) { restoreSettingsEditor(); return; }
        settingsEditor = true; tab = section; widgetEditor = '';
        host.appendChild(panel); panel.inert = false;
        panel.classList.remove('is-page-overview'); panel.classList.add('show', 'is-settings-editor');
        panel.setAttribute('aria-hidden', 'false');
        const sheet = panel.querySelector('.phone-customize-sheet');
        sheet.setAttribute('role', 'region'); sheet.removeAttribute('aria-modal');
        renderPanel();
    });
    if ($('page-settings')) new MutationObserver(() => {
        if (!$('page-settings').classList.contains('active')) restoreSettingsEditor();
    }).observe($('page-settings'), {attributes:true, attributeFilter:['class']});
    function uploadField(label, kind, id = '') { return `<label class="phone-upload">${label}<input type="file" accept="image/png,image/jpeg,image/webp" aria-label="${escape(label)}" data-upload="${kind}" data-id="${id}"></label>`; }
    function appearanceRow(key, label, values) {
        const current = key === 'mode' ? window.AshTheme.getPreference() : layout[key];
        return `<div class="phone-appearance-row"><span>${label}</span><div class="phone-segmented" role="group" aria-label="${label}">${values.map(([value,text]) => `<button type="button" data-appearance-setting="${key}" data-value="${value}" aria-pressed="${current===value}">${text}</button>`).join('')}</div></div>`;
    }
    function wallpaperPanel() {
        return `<div class="phone-wallpaper-gallery">${layout.wallpapers.map((image,index) => `<article class="phone-wallpaper-card"><button type="button" class="phone-wallpaper-select" data-wallpaper-image="${index}" aria-label="使用壁纸 ${index+1}" aria-pressed="${layout.wallpaperImage===image}"><img src="${escape(imageSource(image))}" alt="壁纸 ${index+1}">${layout.wallpaperImage===image ? '<span class="phone-wallpaper-check" aria-hidden="true">✓</span>' : ''}</button><button type="button" class="phone-wallpaper-delete" data-delete-wallpaper="${index}" aria-label="删除壁纸 ${index+1}">×</button></article>`).join('')}<label class="phone-wallpaper-add"><span aria-hidden="true">＋</span><span>添加</span><input type="file" accept="image/png,image/jpeg,image/webp" aria-label="添加壁纸" data-upload="wallpaper"></label></div><div class="phone-appearance-options">${appearanceRow('ink','桌面文字',[['auto','自动'],['dark','深色'],['light','浅色']])}${appearanceRow('mode','应用外观',[['auto','跟随系统'],['light','浅色'],['dark','深色']])}</div>${layout.wallpaperImage ? `<details class="phone-wallpaper-adjust"><summary>调整壁纸</summary><label class="phone-field">画面位置<input type="range" min="0" max="100" value="${layout.wallpaperY}" data-setting="wallpaperY"></label><label class="phone-field">遮罩深度<input type="range" min="0" max="70" value="${layout.dim}" data-setting="dim"></label></details>` : ''}`;
    }
    function widgetCatalogIcon(type) {
        const paths = {together:'M20 5c-3-3-7-1-8 2-1-3-5-5-8-2-4 5 2 10 8 15 6-5 12-10 8-15Z',clock:'M12 7v5l4 3M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z',calendar:'M4 5h16v16H4ZM8 3v4m8-4v4M4 10h16m-9 4h2v4',note:'m16 3 5 5-12 12-6 1 1-6L16 3Zm-2 2 5 5',photo:'M3 4h18v16H3Zm0 12 5-5 5 5 3-3 5 5M8 8h.01',anniversary:'M3 8h18v4H3Zm2 4v9h14v-9M12 8v13M12 8C3 8 5 0 9 3l3 5Zm0 0c9 0 7-8 3-5l-3 5Z'};
        return `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${paths[type]}"/></svg>`;
    }
    function renderWidgetCatalog() {
        return `<div class="phone-widget-catalog">${Object.entries(WIDGETS).map(([type,[label]]) => `<details class="phone-widget-choice" data-widget-type="${type}"><summary><span class="phone-widget-catalog-icon">${widgetCatalogIcon(type)}</span><strong>${label}</strong></summary><div class="phone-widget-add"><div class="phone-size-options" role="group" aria-label="${label}尺寸">${WIDGET_SIZES[type].map((size,index)=>`<button type="button" data-widget-size="${size}" aria-pressed="${index===0}">${SIZE_LABELS[size].split(' · ')[1].replaceAll(' ','')}</button>`).join('')}</div><button type="button" class="phone-primary-button" data-add-widget="${type}" data-size="${WIDGET_SIZES[type][0]}">添加到桌面</button></div></details>`).join('')}</div>`;
    }
    function renderPanel() {
        $('phone-customize-title').textContent = '桌面外观';

        panel.querySelectorAll('[data-phone-tab]').forEach(button => button.setAttribute('aria-current', button.dataset.phoneTab === tab ? 'page' : 'false'));
        const content = $('phone-customize-content');
        if (tab === 'wallpaper') content.innerHTML = wallpaperPanel();
        if (tab === 'icons') content.innerHTML = `<div class="phone-style-options">${[['soft', '柔和'], ['glass', '玻璃'], ['round', '圆形']].map(([id, label]) => `<button data-icon-style="${id}" aria-pressed="${layout.iconStyle === id}">${label}</button>`).join('')}</div><div class="phone-icon-opacity-control"><label class="phone-field" for="phone-icon-opacity-range"><span>图标透明度</span><input id="phone-icon-opacity-range" type="range" min="0" max="100" step="1" value="${layout.iconOpacity}" data-setting="iconOpacity" aria-valuetext="${layout.iconOpacity}%"><output id="phone-icon-opacity-value" for="phone-icon-opacity-range">${layout.iconOpacity}%</output></label></div><div class="phone-icon-editor">${allApps(layout).map(id => `<div class="phone-icon-row"><span class="phone-app-icon">${iconMarkup(id)}</span><strong>${escape(itemLabel(id))}</strong>${uploadField('更换', 'icon', id)}<button type="button" data-clear-icon="${id}" ${layout.icons[id] ? '' : 'disabled'}>还原</button></div>`).join('')}</div>`;
        if (tab === 'widgets') {
            const w = layout.widgets[widgetEditor];
            if (w?.type === 'together') { content.innerHTML = host.pairSettings(); host.renderIdentity(); return; }
            content.innerHTML = w ? `<button class="phone-text-button" data-action="widget-list">‹ 所有组件</button><h3>编辑${WIDGETS[w.type][0]}</h3><form id="phone-widget-form"><label class="phone-field">尺寸<select name="size">${WIDGET_SIZES[w.type].map(size => `<option value="${size}" ${widgetSize(w) === size ? 'selected' : ''}>${SIZE_LABELS[size]}</option>`).join('')}</select></label><label class="phone-field">标题<input name="title" maxlength="80" value="${escape(w.title)}" placeholder="为它起个名字"></label>${w.type === 'note' ? `<label class="phone-field">文字<textarea name="text" rows="4" maxlength="400">${escape(w.text)}</textarea></label>` : ''}${w.type === 'anniversary' ? `<label class="phone-field">日期<input name="date" type="date" required value="${escape(w.date)}"></label>` : ''}${w.type==='clock'?'':`<label class="phone-field">款式<select name="look">${Object.entries(WIDGET_LOOKS).map(([id,label])=>`<option value="${id}" ${widgetLook(w)===id?'selected':''}>${label}</option>`).join('')}</select></label>${imageSource(w.image) ? `<img class="phone-photo-preview" src="${imageSource(w.image)}" alt="组件图片预览">` : ''}${uploadField(w.image ? '更换图片' : '选择图片', 'widget', widgetEditor)}${w.image ? '<button type="button" data-action="clear-widget-image">移除图片</button>' : ''}<label class="phone-field">图片位置<input name="imageY" type="range" min="0" max="100" value="${imagePosition(w)}"></label>`}<button type="submit" class="phone-primary-button">保存组件</button><button type="button" class="phone-text-button phone-destructive" data-delete-widget="${widgetEditor}">删除组件</button></form>` : renderWidgetCatalog();
        }
        if (tab === 'pages') content.innerHTML = `<div class="phone-page-overview">${layout.pages.map((items, i) => `<article class="phone-page-card ${layout.hiddenPages.includes(i) ? 'is-hidden-page' : ''}"><div class="phone-page-preview" aria-hidden="true"><div class="phone-page-mini-grid">${items.map(id => { const w = layout.widgets[id]; return `<span class="phone-page-mini-item ${w ? 'phone-page-mini-widget' : ''}" style="${positionStyle(id)}">${w ? (imageSource(w.image) ? `<img src="${imageSource(w.image)}" alt="">` : escape(WIDGETS[w.type][2])) : iconMarkup(id)}</span>`; }).join('')}</div><span class="phone-page-mini-dock"></span></div><label class="phone-page-check"><input type="checkbox" data-page-visible="${i}" ${layout.hiddenPages.includes(i) ? '' : 'checked'} ${visiblePages().length === 1 && !layout.hiddenPages.includes(i) ? 'disabled' : ''}><span>第 ${i + 1} 页</span></label><button type="button" class="phone-text-button" data-delete-page="${i}" ${layout.pages.length < 2 ? 'disabled' : ''}>删除页面</button></article>`).join('')}</div><button class="phone-primary-button" data-action="add-page">＋ 添加一页</button><p class="phone-field-note">至少保留一页显示。删除页面会将内容移到相邻页。</p><h3 class="phone-section-title">隐藏的应用</h3><div class="phone-hidden-apps">${layout.hidden.map(id => `<button data-restore="${id}">＋ ${escape(itemLabel(id))}</button>`).join('')}</div>`;

        applyIconOpacity();
        if (tab === 'pages') content.querySelectorAll('.phone-page-preview').forEach(node => { node.style.backgroundImage = getComputedStyle($('phone-wallpaper')).backgroundImage; node.style.backgroundSize = 'cover'; node.style.backgroundPosition = `center ${layout.wallpaperY}%`; });
    }
    function refresh() { applyTheme(); renderDesktop(); }
    function addPage() { if (commit(() => layout.pages.push([]))) { currentPage = layout.pages.length - 1; renderDesktop(); } }
    function removeItem(id) {
        if (id === 'theme') return;
        commit(() => { layout.pages.forEach(p => { const i = p.indexOf(id); if (i >= 0) p.splice(i, 1); }); layout.dock=layout.dock.map(item=>item===id?null:item); if (layout.widgets[id]) delete layout.widgets[id]; else if (!layout.hidden.includes(id)) layout.hidden.push(id); });
        if (selected === id) selected = ''; renderDesktop();
    }
    // Encode a bounded image Blob; only its short reference enters localStorage.
    async function readImage(file, kind) {
        if (!file || !['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) throw new Error('请选择 JPG、PNG 或 WebP 图片');
        if (file.size > 20 * 1024 * 1024) throw new Error('请选择小于 20 MB 的图片');
        const url = URL.createObjectURL(file);
        try {
            const img = new Image(); img.src = url; await img.decode();
            const size = kind === 'icon' ? 192 : kind === 'wallpaper' ? 1440 : 720;
            const scale = Math.min(1, size / Math.max(img.width, img.height));
            const canvas = document.createElement('canvas'); canvas.width = Math.max(1, Math.round(img.width * scale)); canvas.height = Math.max(1, Math.round(img.height * scale));
            canvas.getContext('2d').drawImage(img, 0, 0, canvas.width, canvas.height);
            const budget = kind === 'icon' ? 48 * 1024 : kind === 'wallpaper' ? 768 * 1024 : 256 * 1024;
            let blob;
            for (const quality of [.84, .74, .64]) {
                blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/webp', quality));
                if (!blob) throw new Error('无法处理这张图片，请换一张试试');
                if (blob.size <= budget || blob.type !== 'image/webp') break;
            }
            return blob;
        } finally { URL.revokeObjectURL(url); }
    }
    panel.addEventListener('click', event => {
        const b = event.target.closest('button'); if (!b) return;
        if (b.dataset.phoneTab) { tab = b.dataset.phoneTab; widgetEditor = ''; renderPanel(); }
        if (b.dataset.wallpaperImage !== undefined) {
            const image = layout.wallpapers[Number(b.dataset.wallpaperImage)];
            if (image) { commit(() => { layout.wallpaperImage=image; }); refresh(); renderPanel(); }
        }
        if (b.dataset.deleteWallpaper !== undefined) {
            const index = Number(b.dataset.deleteWallpaper);
            if (layout.wallpapers[index]) {
                commit(() => {
                    const [removed] = layout.wallpapers.splice(index,1);
                    if (layout.wallpaperImage===removed) layout.wallpaperImage=layout.wallpapers[Math.min(index,layout.wallpapers.length-1)] || '';
                });
                refresh(); renderPanel();
            }
        }
        if (b.dataset.appearanceSetting) {
            if (b.dataset.appearanceSetting === 'mode') window.AshTheme.setTheme(b.dataset.value);
            else commit(() => { layout[b.dataset.appearanceSetting]=b.dataset.value; });
            applyTheme(); renderPanel();
        }
        if (b.dataset.widgetSize) {
            const entry=b.closest('.phone-widget-choice');
            entry.querySelectorAll('[data-widget-size]').forEach(button=>button.setAttribute('aria-pressed',String(button===b)));
            entry.querySelector('[data-add-widget]').dataset.size=b.dataset.widgetSize;
        }
        if (b.dataset.iconStyle) { commit(() => { layout.iconStyle = b.dataset.iconStyle; }); refresh(); renderPanel(); }
        if (b.dataset.clearIcon) { commit(() => { delete layout.icons[b.dataset.clearIcon]; }); refresh(); renderPanel(); }
        if (b.dataset.addWidget) {
            const id = `widget-${globalThis.crypto?.randomUUID?.() || `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`}`;
            if (commit(() => { layout.widgets[id] = {type: b.dataset.addWidget, size:b.dataset.size, title: '', text: '', image: '', date: ''}; layout.pages[currentPage].push(id); })) { widgetEditor = id; renderDesktop(); renderPanel(); announce(`已添加到第 ${currentPage + 1} 页`); }
        }
        if (b.dataset.deleteWidget) { removeItem(b.dataset.deleteWidget); widgetEditor = ''; renderPanel(); }
        if (b.dataset.goPage !== undefined) { goPage(+b.dataset.goPage); closeCustomize(); }
        if (b.dataset.deletePage !== undefined && layout.pages.length > 1) {
            const index = +b.dataset.deletePage;
            commit(() => { const items = layout.pages.splice(index, 1)[0]; layout.pages[Math.max(0, index - 1)].push(...items); layout.hiddenPages = layout.hiddenPages.filter(i => i !== index).map(i => i > index ? i - 1 : i); if (layout.hiddenPages.length === layout.pages.length) layout.hiddenPages = layout.hiddenPages.filter(i => i !== Math.max(0, index - 1)); });
            currentPage = Math.min(currentPage, layout.pages.length - 1); renderDesktop(); renderPanel();
        }
        if (b.dataset.restore) { commit(() => { layout.hidden = layout.hidden.filter(id => id !== b.dataset.restore); layout.pages[currentPage].push(b.dataset.restore); }); renderDesktop(); renderPanel(); }
        if (b.dataset.action === 'add-page') { addPage(); renderPanel(); }
        if (b.dataset.action === 'widget-list') { widgetEditor = ''; renderPanel(); }
        if (b.dataset.action === 'clear-widget-image') { commit(() => { saveWidgetFields(layout.widgets[widgetEditor], $('phone-widget-form')); layout.widgets[widgetEditor].image = ''; }); renderDesktop(); renderPanel(); }
    });
    panel.addEventListener('input', event => {
        if(event.target.dataset.setting==='iconOpacity')applyIconOpacity(+event.target.value);
    });
    panel.addEventListener('change', async event => {
        const input = event.target;
        if (input.dataset.pageVisible !== undefined) {
            const index = +input.dataset.pageVisible;
            if (!input.checked && visiblePages().length === 1) { input.checked = true; return; }
            commit(() => { layout.hiddenPages = input.checked ? layout.hiddenPages.filter(i => i !== index) : [...layout.hiddenPages, index]; });
            renderDesktop(); renderPanel();
            panel.querySelector(`[data-page-visible="${index}"]`)?.focus();
            return;
        }
        if (input.dataset.setting==='iconOpacity') {
            commit(()=>{layout.iconOpacity=iconOpacity(+input.value);});
            applyIconOpacity();return;
        }
        if (input.dataset.setting) {
            const saved = commit(() => { layout[input.dataset.setting] = input.tagName === 'SELECT' ? input.value : +input.value; });
            applyTheme(); renderPanel();
        }
        if (input.dataset.upload) {
            const file = input.files[0]; if (!file) return;
            const kind = input.dataset.upload, id = input.dataset.id;
            input.disabled = true;
            let stagedImage;
            try {
                await mediaReady;
                const data = stagedImage = await media.store(await readImage(file, kind));
                if (kind === 'widget' && !layout.widgets[id]) return;
                if (kind === 'icon' && !knownApp(layout, id)) return;
                const ok = commit(() => {
                    if (kind === 'wallpaper') { layout.wallpaperImage=data; if (!layout.wallpapers.includes(data)) layout.wallpapers.push(data); }
                    if (kind === 'icon') layout.icons[id] = data;
                    if (kind === 'widget') {
                        const form = $('phone-widget-form');
                        if (id === widgetEditor && form) {
                            saveWidgetFields(layout.widgets[id], form);
                        }
                        layout.widgets[id].image = data;
                    }
                });
                refresh(); renderPanel(); if (ok) announce('图片已保存');
            } catch (error) {
                if (!media.closed) announce(error.name === 'QuotaExceededError' ? '图片未保存：本机存储空间不足，请释放浏览器空间后重试。' : error.name === 'SecurityError' || error.name === 'InvalidStateError' ? '无法保存图片，请允许浏览器使用本机存储后重试。' : error.message === 'The source image cannot be decoded.' ? '无法读取这张图片，请换一张试试' : error.message);
            }
            finally { if (stagedImage) media.release([stagedImage]); collectImages(); input.disabled = false; input.value = ''; }
        }
    });
    panel.addEventListener('submit', event => {
        if (event.target.id !== 'phone-widget-form') return;
        event.preventDefault();
        if (commit(() => saveWidgetFields(layout.widgets[widgetEditor], event.target))) {
            renderDesktop();
            if (settingsEditor) { widgetEditor = ''; renderPanel(); } else closeCustomize();
            announce('组件已保存');
        }
    });
    $('btn-phone-edit').addEventListener('click', () => openCustomize('pages', true));
    $('btn-phone-widgets').addEventListener('click', () => openCustomize('widgets'));
    $('btn-phone-customize-close').addEventListener('click', closeCustomize);
    $('btn-phone-customize-preview').addEventListener('click', event => {
        const preview=panel.classList.toggle('is-previewing');
        event.currentTarget.setAttribute('aria-pressed',String(preview));
        event.currentTarget.setAttribute('aria-label',preview ? '返回外观设置' : '预览桌面');
    });
    $('phone-manage-pages').addEventListener('click', () => openCustomize('pages'));
    $('phone-prev-page').addEventListener('click', () => stepPage(-1));
    $('phone-next-page').addEventListener('click', () => stepPage(1));
    $('phone-add-page').addEventListener('click', addPage);
    $('phone-page-dots').addEventListener('click', event => { const b = event.target.closest('[data-page]'); if (b) goPage(+b.dataset.page); });
    function detachApp(id) {
        layout.pages.forEach(p=>{const index=p.indexOf(id);if(index>=0)p.splice(index,1);});
        layout.dock=layout.dock.map(item=>item===id?null:item);
        layout.hidden=layout.hidden.filter(item=>item!==id);
    }
    function moveIntoDock(id, index) {
        if(!knownApp(layout,id)){announce('Dock 只放应用，组件请留在桌面。');return false;}
        const sourceSlot=layout.dock.indexOf(id);
        if(index===undefined){if(sourceSlot>=0)return true;index=layout.dock.findIndex(item=>!item);}
        if(index<0){announce('底部最多放 4 个应用，先移出一个再放入。');return false;}
        index=Math.max(0,Math.min(3,index));
        if(sourceSlot===index)return true;
        const displaced=layout.dock[index],sourcePage=layout.pages.findIndex(page=>page.includes(id)),sourcePosition=layout.positions[id];
        return commit(()=>{
            detachApp(id);layout.dock[index]=id;
            if(displaced){
                if(sourceSlot>=0)layout.dock[sourceSlot]=displaced;
                else{
                    layout.pages[sourcePage>=0?sourcePage:currentPage].push(displaced);
                    if(sourcePosition)layout.positions[displaced]={...sourcePosition};
                }
            }
        });
    }
    function moveOntoPage(id, target, position) {
        return commit(()=>{
            detachApp(id);layout.pages[target].push(id);
            layout.hiddenPages=layout.hiddenPages.filter(i=>i!==target);
            if(position){layout.positions[id]=position;moveToCell(layout,target,id,position);}
        });
    }
    $('phone-move-item').addEventListener('click', () => {
        if (!selected) return;
        const destination=$('phone-move-page').value;
        if(destination==='dock'){moveIntoDock(selected);renderDesktop();return;}
        const target = +destination;
        if (moveOntoPage(selected,target)) { currentPage = target; renderDesktop(); }
    });
    home.addEventListener('pointerdown', () => { if (!pointer) suppressClickUntil = 0; });
    home.addEventListener('click', event => {
        if (!event.target.closest('.phone-widget, .phone-customize')) revealWidget();
        if (editing && Date.now() >= suppressClickUntil && !event.target.closest('button, input, select, textarea, [data-item], .phone-customize, nav')) setEditing(false);
    });
    home.addEventListener('click', event => {
        if(event.target.closest('.phone-customize, .phone-drag-preview'))return;
        if(!event.target.closest('#phone-pages, .phone-dock'))return;
        if (Date.now() < suppressClickUntil && event.detail !== 0 && !event.target.closest('[data-widget-edit]')) return;
        const item = event.target.closest('[data-item]'); if (!item) { if (editing) setEditing(false); return; }
        const id = item.dataset.item;
        if (event.target.closest('[data-remove]')) { removeItem(id); return; }
        if (event.target.closest('[data-widget-edit]')) { openCustomize('widgets'); widgetEditor = id; renderPanel(); return; }
        if (editing) { selected = id; home.querySelectorAll('[data-item]').forEach(n => n.classList.toggle('is-selected', n === item)); renderNavigation(); return; }
        if (event.target.closest('[data-widget-music-play]')) { window.dispatchEvent(new CustomEvent('merle:phone-music-toggle')); return; }
        if (event.target.closest('[data-widget-music-open]')) { launch('music'); return; }
        if (event.target.closest('[data-phone-name-editor]')) return;
        const name = event.target.closest('[data-phone-name]');
        if (name) { host.editName(name); return; }
        const profile = event.target.closest('[data-phone-profile]');
        if (profile) { host.profile(profile.dataset.phoneProfile, profile); return; }
        if (layout.widgets[id]) revealWidget(id); else launch(id);
    });
    let scrollFrame;
    home.addEventListener('pointerover', event => {
        const widget = event.target.closest('.phone-widget');
        if (event.pointerType === 'mouse' && widget && !editing && !pointer && !panel.classList.contains('show')) revealWidget(widget.dataset.item);
    });
    pages.addEventListener('scroll', () => {
        cancelAnimationFrame(scrollFrame);
        scrollFrame = requestAnimationFrame(() => { const index = visiblePages()[Math.round(pages.scrollLeft / (pages.clientWidth || 1))]; if (index !== undefined && index !== currentPage) { currentPage = index; renderNavigation(); } });
    }, {passive: true});
    // Capture on the stable viewport, never on a node that is reordered or redrawn.
    // Item gestures own touch input from pointerdown so a long press can continue
    // directly into a drag on iOS/Android. Quick gestures still scroll or page.
    function selectItem(id) {
        selected = id;
        home.querySelectorAll('[data-item]').forEach(node => node.classList.toggle('is-selected', node.dataset.item === id));
        renderNavigation();
    }
    function beginDrag() {
        if (!pointer || pointer.mode === 'scroll') return;
        clearTimeout(pointer.timer);
        const rect = pointer.node.getBoundingClientRect();
        if (!editing) setEditing(true);
        pointer.mode = 'drag';
        pointer.order = JSON.parse(JSON.stringify(layout.positions));
        selectItem(pointer.item);
        pointer.offsetX = pointer.x - rect.left; pointer.offsetY = pointer.y - rect.top;
        const ghost = pointer.node.cloneNode(true);
        ghost.classList.add('phone-drag-preview'); ghost.classList.remove('is-selected');
        ghost.removeAttribute('data-item'); ghost.setAttribute('aria-hidden', 'true'); ghost.inert = true;
        ghost.style.width = `${rect.width}px`; ghost.style.height = `${rect.height}px`;
        pointer.node.classList.add('is-drag-source');
        home.appendChild(ghost); pointer.ghost = ghost;
        placeDragPreview();
        navigator.vibrate?.(18);
        pointer.frame = requestAnimationFrame(scrollWhileDragging);
    }
    function placeDragPreview() {
        if (!pointer?.ghost) return;
        const bounds = home.getBoundingClientRect();
        pointer.ghost.style.left = `${pointer.clientX - bounds.left - pointer.offsetX}px`;
        pointer.ghost.style.top = `${pointer.clientY - bounds.top - pointer.offsetY}px`;
    }
    function reorderAtPointer() {
        if (pointer?.mode !== 'drag') return;
        const dock=home.querySelector('.phone-dock'),dockBounds=dock.getBoundingClientRect();
        const overDock=pointer.clientX>=dockBounds.left&&pointer.clientX<=dockBounds.right&&pointer.clientY>=dockBounds.top&&pointer.clientY<=dockBounds.bottom;
        dock.classList.toggle('is-drop-target',overDock&&!layout.widgets[pointer.item]);
        if(overDock||pointer.fromDock)return;
        const grid = pointer.node.parentElement, bounds = grid.getBoundingClientRect();
        const x = pointer.clientX - bounds.left, y = pointer.clientY - bounds.top;
        if (x < 0 || x > bounds.width || pointer.clientY < pointer.section.getBoundingClientRect().top || pointer.clientY > pointer.section.getBoundingClientRect().bottom) return;
        const style = getComputedStyle(grid), gap = parseFloat(style.columnGap), rowHeight = parseFloat(style.gridAutoRows), rowGap = parseFloat(style.rowGap);
        const cellWidth = (bounds.width - gap * 3) / 4;
        const col = Math.floor(x / (cellWidth + gap)), row = Math.max(0, Math.floor(y / (rowHeight + rowGap)));
        const [width] = itemSpan(layout, pointer.item), next = {col: Math.min(4 - width, col), row};
        const previous = layout.positions[pointer.item];
        if (previous.col === next.col && previous.row === next.row) return;
        const positions = new Map([...grid.children].map(node => [node, node.getBoundingClientRect()]));
        grid.querySelectorAll('[data-item]').forEach(node => node.getAnimations().forEach(animation => animation.cancel()));
        layout.positions = JSON.parse(JSON.stringify(pointer.order));
        moveToCell(layout, pointer.page, pointer.item, next);
        grid.querySelectorAll('[data-item]').forEach(node => { node.style.cssText = positionStyle(node.dataset.item); });
        if (!matchMedia('(prefers-reduced-motion: reduce)').matches) grid.querySelectorAll('[data-item]').forEach(node => {
            if (node === pointer.node) return;
            const before = positions.get(node), after = node.getBoundingClientRect();
            node.animate([{transform: `translate(${before.left - after.left}px, ${before.top - after.top}px)`}, {transform: 'none'}], {duration: 180, easing: 'ease-out'});
        });
    }
    function scrollWhileDragging() {
        if (pointer?.mode !== 'drag') return;
        const section = pointer.section, bounds = section.getBoundingClientRect();
        const speed = pointer.clientY < bounds.top + 42 ? -9 : pointer.clientY > bounds.bottom - 42 ? 9 : 0;
        if (speed) { section.scrollTop += speed; reorderAtPointer(); }
        pointer.frame = requestAnimationFrame(scrollWhileDragging);
    }
    let blankPress = null;
    function finishBlankPress() {
        if (!blankPress) return;
        clearTimeout(blankPress.timer);
        if (blankPress.fired) suppressClickUntil = Date.now() + 400;
        blankPress = null;
    }
    pages.addEventListener('pointerdown', event => {
        if (!event.isPrimary || event.button !== 0 || event.target.closest('[data-item]')) return;
        finishBlankPress();
        blankPress = {id: event.pointerId, x: event.clientX, y: event.clientY, fired: false};
        blankPress.timer = setTimeout(() => {
            if (!blankPress || !$('page-phone').classList.contains('active')) return;
            blankPress.fired = true; setEditing(true);
        }, 430);
    });
    window.addEventListener('pointermove', event => {
        if (blankPress && event.pointerId === blankPress.id && Math.hypot(event.clientX - blankPress.x, event.clientY - blankPress.y) > 8) finishBlankPress();
    });
    window.addEventListener('pointerup', finishBlankPress);
    window.addEventListener('pointercancel', finishBlankPress);
    home.addEventListener('pointerdown', event => {
        if (pointer || !event.isPrimary || event.button !== 0 || event.target.closest('[data-remove], [data-widget-edit], [data-phone-name-editor]')) return;
        if(event.target.closest('.phone-customize, .phone-drag-preview'))return;
        const item = event.target.closest('[data-item]'); if (!item) return;
        const fromDock=!!item.closest('.phone-dock');
        const section = fromDock?pages.querySelector(`[data-layout-page="${currentPage}"]`):item.closest('.phone-desktop-page');
        pointer = {id: event.pointerId, item: item.dataset.item, node: item, target: event.target.closest('button, [role="button"]') || item,
            section, fromDock, page: +section.dataset.layoutPage, x: event.clientX, y: event.clientY,
            clientX: event.clientX, clientY: event.clientY, startScroll: pages.scrollLeft, startTop: section.scrollTop,
            order: null, timer: null, mode: 'pending'};
        home.setPointerCapture(event.pointerId);
        pointer.timer = setTimeout(beginDrag, 430);
    });
    home.addEventListener('pointermove', event => {
        if (!pointer || event.pointerId !== pointer.id) return;
        pointer.clientX = event.clientX; pointer.clientY = event.clientY;
        const dx = event.clientX - pointer.x, dy = event.clientY - pointer.y;
        if (pointer.mode === 'pending' && Math.hypot(dx, dy) < 8) return;
        clearTimeout(pointer.timer);
        event.preventDefault();
        if (pointer.mode === 'pending') {
            if (editing) beginDrag();
            else { pointer.mode = 'scroll'; pointer.axis = pointer.fromDock?'dock':Math.abs(dx) > Math.abs(dy) ? 'x' : 'y'; pages.classList.add('is-gesturing'); }
        }
        if (pointer.mode === 'drag') { placeDragPreview(); reorderAtPointer(); }
        else if (pointer.axis === 'x') pages.scrollLeft = pointer.startScroll - dx;
        else if(pointer.axis==='y')pointer.section.scrollTop = pointer.startTop - dy;
    }, {passive: false});
    function finishPointer(cancel = false) {
        if (!pointer) return;
        const finished = pointer; pointer = null;
        clearTimeout(finished.timer); cancelAnimationFrame(finished.frame);
        finished.ghost?.remove(); finished.node.classList.remove('is-drag-source');
        pages.classList.remove('is-gesturing');
        if (home.hasPointerCapture(finished.id)) home.releasePointerCapture(finished.id);
        const dock=home.querySelector('.phone-dock'),dockBounds=dock.getBoundingClientRect();
        dock.classList.remove('is-drop-target');
        suppressClickUntil = Date.now() + 400;
        if (finished.order) {
            const next = layout.positions; layout.positions = finished.order;
            const overDock=finished.clientX>=dockBounds.left&&finished.clientX<=dockBounds.right&&finished.clientY>=dockBounds.top&&finished.clientY<=dockBounds.bottom;
            if(!cancel&&overDock)moveIntoDock(finished.item,Math.floor((finished.clientX-dockBounds.left)/dockBounds.width*4));
            else if(!cancel&&finished.fromDock){
                const grid=finished.section.querySelector('.phone-app-grid'),bounds=grid.getBoundingClientRect(),sectionBounds=finished.section.getBoundingClientRect();
                if(finished.clientX>=bounds.left&&finished.clientX<=bounds.right&&finished.clientY>=sectionBounds.top&&finished.clientY<=sectionBounds.bottom){
                    const style=getComputedStyle(grid),gap=parseFloat(style.columnGap),cellWidth=(bounds.width-gap*3)/4;
                    const position={col:Math.min(3,Math.max(0,Math.floor((finished.clientX-bounds.left)/(cellWidth+gap)))),row:Math.max(0,Math.floor((finished.clientY-bounds.top)/(parseFloat(style.gridAutoRows)+parseFloat(style.rowGap))))};
                    moveOntoPage(finished.item,finished.page,position);
                }
            }else if(!cancel)commit(() => { layout.positions = next; });
            const scrollTop = finished.section.scrollTop;
            renderDesktop(); pages.querySelector(`[data-layout-page="${finished.page}"]`).scrollTop = scrollTop;
        } else if (finished.mode === 'scroll' && finished.axis === 'x') {
            const dx = finished.clientX - finished.x;
            stepPage(!cancel && Math.abs(dx) > 45 ? (dx < 0 ? 1 : -1) : 0, finished.page);
        } else if (!cancel && finished.mode === 'pending') {
            // Pointer capture retargets the native click to the viewport. Dispatch
            // the original tap once; the following native click is suppressed.
            finished.target.click();
        }
    }
    home.addEventListener('pointerup', () => finishPointer());
    home.addEventListener('pointercancel', () => finishPointer(true));
    window.addEventListener('pointerup', event => { if (event.pointerId === pointer?.id) finishPointer(); });
    window.addEventListener('pointercancel', event => { if (event.pointerId === pointer?.id) finishPointer(true); });
    home.addEventListener('lostpointercapture', () => { if (pointer) finishPointer(true); });
    home.addEventListener('contextmenu', event => {if(event.target.closest('[data-item]')&&!event.target.closest('[data-phone-name-editor]'))event.preventDefault();});
    home.addEventListener('keydown', event => {
        if(event.target.closest('.phone-customize, [data-phone-name-editor]'))return;
        const item = event.target.closest('[data-item]');
        if (['Enter', ' '].includes(event.key) && event.target.matches('.phone-widget-body')) { event.preventDefault(); event.target.click(); return; }
        const delta = {ArrowLeft: -1, ArrowRight: 1, ArrowUp: -4, ArrowDown: 4}[event.key];
        if (!delta) return;
        if (editing && item) {
            event.preventDefault(); const id = item.dataset.item;
            if(layout.dock.includes(id)){
                if(event.key==='ArrowLeft'||event.key==='ArrowRight'){
                    moveIntoDock(id,Math.max(0,Math.min(layout.dock.length-1,layout.dock.indexOf(id)+(event.key==='ArrowLeft'?-1:1))));renderDesktop();home.querySelector(`[data-item="${id}"] .phone-app`)?.focus();
                }return;
            }
            const pos = layout.positions[id], page = layout.pages.findIndex(p => p.includes(id));
            commit(() => moveToCell(layout, page, id, {row: pos.row + (event.key === 'ArrowUp' ? -1 : event.key === 'ArrowDown' ? 1 : 0), col: pos.col + (event.key === 'ArrowLeft' ? -1 : event.key === 'ArrowRight' ? 1 : 0)}));
            renderDesktop(); pages.querySelector(`[data-item="${id}"] .phone-app, [data-item="${id}"] .phone-widget-body`)?.focus();
        } else if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') { event.preventDefault(); stepPage(delta); }
    });
    document.addEventListener('keydown', event => {
        if (!$('page-phone').classList.contains('active') || event.defaultPrevented || document.querySelector(':popover-open')) return;
        if (event.key === 'Escape') { if (panel.classList.contains('show')) closeCustomize(); else if (pointer?.order) finishPointer(true); else setEditing(false); }
        if (event.key === 'Tab' && panel.classList.contains('show')) {
            const nodes = [...panel.querySelectorAll('button:not(:disabled), input:not(:disabled), select, textarea')].filter(n => n.getClientRects().length && getComputedStyle(n).visibility !== 'hidden');
            const first = nodes[0], last = nodes.at(-1);
            if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
            if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
        }
    });
    function updateWidgets(types) {
        if (pointer) return;
        pages.querySelectorAll('[data-item]').forEach(node => { const w = layout.widgets[node.dataset.item]; if (w && types.includes(w.type)) {
            const body = node.querySelector('.phone-widget-body');
            const focusedControl = body.contains(document.activeElement) && w.type === 'music'
                ? document.activeElement.hasAttribute('data-widget-music-play') ? '[data-widget-music-play]' : '[data-widget-music-open]' : '';
            body.innerHTML = decoratedWidgetContent(w);
            if (focusedControl) body.querySelector(focusedControl)?.focus({preventScroll: true});
        } });
    }
    window.addEventListener('merle:phone-music-state', event => { snapshot = event.detail || {}; updateWidgets(['music']); });
    window.addEventListener('merle:theme-change', syncSystemChrome);
    // Keep the store and desktop on the same transactional layout, including custom apps.
    window.merlePhoneApps = Object.freeze({
        whenReady: () => mediaReady,
        list: () => allApps(layout).map(id => ({id, label: itemLabel(id), icon: iconMarkup(id), className: APP_DEFINITIONS[id]?.className || 'web-app', custom: !!layout.customApps[id], fileName: layout.customApps[id]?.fileName || '', installed: !layout.hidden.includes(id)})),
        install(id) {
            if (!knownApp(layout, id)) return false;
            if (!layout.hidden.includes(id)) return true;
            if (!commit(() => { layout.hidden = layout.hidden.filter(item => item !== id); layout.pages[currentPage].push(id); })) return false;
            renderDesktop(); return true;
        },
        add(app) {
            if (!/^webapp-[\w-]{1,100}$/.test(app.id) || typeof app.label !== 'string' || !app.label.trim() || knownApp(layout, app.id)) return false;
            if (!commit(() => { layout.customApps[app.id] = {label: app.label.trim().slice(0, 40), fileName: String(app.fileName || '').slice(0, 160)}; layout.pages[currentPage].push(app.id); })) return false;
            renderDesktop(); return true;
        },
        forget(id) {
            if (!Object.hasOwn(layout.customApps, id)) return false;
            if (!commit(() => { layout.pages = layout.pages.map(page => page.filter(item => item !== id)); layout.dock = layout.dock.map(item => item === id ? null : item); layout.hidden = layout.hidden.filter(item => item !== id); delete layout.customApps[id]; delete layout.icons[id]; delete layout.positions[id]; })) return false;
            renderDesktop(); return true;
        },
        launch(id, source = 'store') { if (id === 'theme' || knownApp(layout, id)) launch(id, source); },
        customize: openCustomize,
    });
    new MutationObserver(() => { if (!$('page-phone').classList.contains('active')) { finishPointer(true); setEditing(false); if (!settingsEditor && panel.classList.contains('show')) closeCustomize(); } syncSystemChrome(); }).observe($('page-phone'), {attributes: true, attributeFilter: ['class']});
    window.addEventListener('ash-theme-change', () => {
        syncSystemChrome();
        panel.querySelectorAll('[data-appearance-setting="mode"]').forEach(button => {
            button.setAttribute('aria-pressed', String(button.dataset.value === window.AshTheme.getPreference()));
        });
    });
    new ResizeObserver(() => {
        pages.scrollLeft = visiblePages().indexOf(currentPage) * pages.clientWidth;
        renderNavigation();
    }).observe(pages);
    window.AshDesktop = {
        get: () => ({...structuredClone(layout), mode:window.AshTheme.getPreference()}),
        edit: setEditing, customize: openCustomize, close: closeCustomize,
        async export() {
            await mediaReady;
            const copy = {...structuredClone(layout), mode:window.AshTheme.getPreference()};
            for (const [object, key] of media.fields(copy)) {
                if (!media.isReference(object[key])) continue;
                const url = imageSource(object[key]);
                if (!url) throw new Error('桌面图片尚未加载，请稍后重试');
                const blob = await (await fetch(url)).blob();
                object[key] = await new Promise((resolve,reject) => {const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=reject;reader.readAsDataURL(blob);});
            }
            return copy;
        },
        async restore(value) {
            if (!value || !Array.isArray(value.pages) || !value.pages.length) throw new Error('桌面布局格式无效');
            await mediaReady; finishPointer(true);
            const candidate = readLayout(JSON.stringify(value));
            normalizePositions(candidate);
            const replacements = await media.migrate(candidate);
            try {
                media.fields(candidate).forEach(([object,key])=>{if(replacements.has(object[key]))object[key]=replacements.get(object[key]);});
                await media.hydrate(candidate);
                if (!commit(()=>{layout=candidate;})) throw new Error('桌面未能保存');
                if (['auto','light','dark'].includes(value.mode)) window.AshTheme.setTheme(value.mode);
                currentPage=0; refresh();
            } finally {media.release(replacements.values()); collectImages();}
        },
    };
    refresh();
    if (!localStorage.getItem(KEY)) commit(()=>{});
    mediaReady = (async () => {
        try { await media.hydrate(layout); }
        catch { if (!media.closed) announce('部分桌面图片暂时无法读取，原有设置已保留。'); }
        const legacyWallpaper = await host.legacyWallpaper();
        if (legacyWallpaper instanceof Blob && !layout.wallpaperImage) {
            const image = await media.store(legacyWallpaper);
            commit(()=>{layout.wallpaperImage=image; if (!layout.wallpapers.includes(image)) layout.wallpapers.push(image);}); media.release([image]);
        }
        if (media.closed) return;
        // Restore image bytes without replacing an in-progress widget form.
        const updateImages = () => {
            if (media.closed) return;
            if (pointer || blankPress) { setTimeout(updateImages, 100); return; }
            refresh();
            if (panel.classList.contains('show') && !$('phone-widget-form')) renderPanel();
            window.dispatchEvent(new Event('merle:phone-apps-changed'));
        };
        updateImages();
        let replacements;
        try {
            replacements = await media.migrate(layout);
            if (media.closed || !replacements.size) return;
            // A drag has temporary coordinates until drop/cancel. Do not persist
            // those coordinates as a side effect of the image migration.
            while ((pointer || blankPress) && !media.closed) await new Promise(resolve => setTimeout(resolve, 100));
            if (media.closed) return;
            const changes = media.fields(layout).filter(([object, key]) => replacements.has(object[key]));
            if (changes.length && commit(() => changes.forEach(([object, key]) => { object[key] = replacements.get(object[key]); }))) updateImages();
        } catch { if (!media.closed) announce('旧桌面图片暂未迁移，原有图片已保留，可稍后重试。'); }
        finally { if (replacements) media.release(replacements.values()); if (!media.closed) collectImages(); }
    })();
    function updateStatusTime() {
        const time = $('phone-status-time');
        if (!time) return;
        const now = new Date();
        time.textContent = now.toLocaleTimeString('zh-CN', {hour: '2-digit', minute: '2-digit', hour12: false});
        time.dateTime = now.toISOString();
    }
    updateStatusTime();
    document.addEventListener('visibilitychange', () => { if (!document.hidden) updateStatusTime(); });
    setInterval(() => { updateStatusTime(); updateWidgets(['clock', 'calendar', 'anniversary']); }, 15000);
})();
