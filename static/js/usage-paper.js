/* Shared by the conversation list (folded note) and dashboard (clipboard). */
let usageBoardReturnFocus = null;
let usageBoardOldOverflow = '';
let usageNoteLoading = null;
function usageNumber(value) { const n = Number(value); return Number.isFinite(n) && n > 0 ? n : 0; }
function usageFormat(value) {
    const n = usageNumber(value);
    return n >= 1e6 ? (n / 1e6).toFixed(2) + 'M' : n >= 1e3 ? (n / 1e3).toFixed(1) + 'K' : String(Math.round(n));
}
function openUsageNote() {
    window.parent.postMessage({type: 'memory-gateway-open-usage'}, window.location.origin);
}
async function loadUsageNote() {
    const records = document.getElementById('usage-note-records');
    if (!records || usageNoteLoading) return usageNoteLoading;
    usageNoteLoading = (async () => {
        try {
            const responses = await Promise.all([
                fetch('/api/token-usage/summary?days=1'),
                fetch('/api/token-usage/logs?limit=3&days=0'),
            ]);
            const data = await Promise.all(responses.map(r => r.json()));
            if (responses.some(r => r.status === 401)) { window.top.location.assign('/login'); return; }
            if (responses.some(r => !r.ok) || data.some(d => d.error)) throw Error('暂时无法读取');
            const today = data[0].today || new Date().toISOString().slice(0,10);
            const row = (data[0].daily_usage || []).find(r => r.day === today);
            document.getElementById('usage-note-today').textContent = usageFormat(row?.total_tokens);
            const nodes = (data[1].logs || []).slice(0,3).map(log => {
                const line = document.createElement('span'); line.className = 'usage-note-record';
                const time = document.createElement('small'); time.textContent = String(log.created_at || '').slice(5,16);
                const model = document.createElement('span'); model.textContent = log.model || '未标注模型';
                const total = document.createElement('small'); total.textContent = usageFormat(log.total_tokens);
                line.append(time, model, total); return line;
            });
            records.replaceChildren(...nodes);
            if (!nodes.length) records.textContent = '还没有请求记录，今天的纸页很安静。';
        } catch (_) { records.textContent = '暂时无法读取 · 轻触展开后重试'; document.getElementById('usage-note-today').textContent = '—'; }
        finally { usageNoteLoading = null; }
    })();
    return usageNoteLoading;
}
function ensureUsageBoard() {
    let overlay = document.getElementById('usage-board-overlay');
    if (overlay) return overlay;
    const content = document.getElementById('section-quotes');
    if (!content) return null;
    overlay = document.createElement('div'); overlay.id = 'usage-board-overlay'; overlay.className = document.body.classList.contains('phone-dashboard') ? 'usage-board-overlay phone-paper-app' : 'usage-board-overlay'; overlay.hidden = true;
    const board = document.createElement('div'); board.className = 'usage-board'; board.setAttribute('role','dialog'); board.setAttribute('aria-modal','true'); board.setAttribute('aria-label','用量统计');
    content.hidden = false; board.appendChild(content); overlay.appendChild(board);
    (document.querySelector('.phone-dashboard .dashboard') || document.body).appendChild(overlay);
    overlay.addEventListener('click', e => { if (e.target === overlay) closeUsageBoard(); });
    setupUsagePages();
    return overlay;
}
function openUsageBoard() {
    const overlay = ensureUsageBoard(); if (!overlay) return;
    if (overlay.hidden) { usageBoardReturnFocus = document.activeElement; usageBoardOldOverflow = document.body.style.overflow; }
    overlay.hidden = false; document.body.style.overflow = 'hidden';
    overlay.querySelector('.usage-board-close').focus();
    loadTokenUsage();
}
function closeUsageBoard(restoreFocus = true) {
    const overlay = document.getElementById('usage-board-overlay');
    if (!overlay || overlay.hidden) return;
    overlay.hidden = true; document.body.style.overflow = usageBoardOldOverflow;
    if (restoreFocus) {
        if (usageBoardReturnFocus?.id === 'conversation-list-frame') {
            usageBoardReturnFocus.contentWindow?.postMessage({type:'memory-gateway-usage-closed'},window.location.origin);
        } else usageBoardReturnFocus?.focus?.();
    }
    document.getElementById('conversation-list-frame')?.contentWindow?.postMessage({type:'memory-gateway-refresh-usage'},window.location.origin);
}
function usageCalendar(data, count = 180) {
    const today = /^\d{4}-\d{2}-\d{2}$/.test(data.today || '') ? data.today : new Date().toISOString().slice(0,10);
    const end = new Date(today + 'T00:00:00Z');
    const first = new Date(end); first.setUTCDate(first.getUTCDate() - count + 1);
    const start = new Date(first); start.setUTCDate(start.getUTCDate() - (start.getUTCDay() + 6) % 7);
    const rows = new Map((data.daily_usage || []).map(row => [row.day, row]));
    const totalDays = Math.ceil(((end - start) / 86400000 + 1) / 7) * 7;
    const cells = Array.from({length:totalDays},(_,i) => {
        const d = new Date(start); d.setUTCDate(d.getUTCDate() + i);
        const key = d.toISOString().slice(0,10), row = rows.get(key) || {};
        return {key, month:d.getUTCMonth()+1, day:d.getUTCDate(), week:Math.floor(i/7), weekday:i%7, outside:d<first || d>end, total:usageNumber(row.total_tokens), requests:usageNumber(row.request_count)};
    });
    const maximum = Math.max(1,...cells.filter(c=>!c.outside).map(c=>c.total));
    cells.forEach(c => { c.level = c.total ? Math.min(4,Math.max(1,Math.ceil(c.total / maximum * 4))) : 0; });
    return {cells, weeks:totalDays/7};
}
function renderUsageHeatmap(data) {
    const container = document.getElementById('usage-heatmap'); if (!container) return;
    const calendar = usageCalendar(data); container.replaceChildren();
    container.style.setProperty('--usage-weeks', calendar.weeks);
    ['一','二','三','四','五','六','日'].forEach((text,i) => {
        const label = document.createElement('span'); label.className='usage-weekday'; label.textContent=text; label.style.gridColumn='1'; label.style.gridRow=String(i+2); container.appendChild(label);
    });
    let previousMonth = null;
    const buttons = [];
    for (const cell of calendar.cells) {
        if (!cell.outside && cell.month !== previousMonth) {
            previousMonth = cell.month;
            if (cell.day <= 15) {
            const label = document.createElement('span'); label.className='usage-month'; label.textContent=cell.month+'月'; label.style.gridColumn=String(cell.week+2); label.style.gridRow='1'; container.appendChild(label);
            }
        }
        const button = document.createElement('button'); button.type='button'; button.className='usage-calendar-cell level-'+cell.level;
        button.style.gridColumn=String(cell.week+2); button.style.gridRow=String(cell.weekday+2);
        button.disabled=cell.outside; button.tabIndex=-1;
        const label = `${cell.key} · ${Math.round(cell.total).toLocaleString()} tokens · ${cell.requests} 次请求`;
        button.title=label; button.setAttribute('aria-label',label);
        if (cell.outside) button.classList.add('outside');
        else { buttons.push(button); button.onclick=()=> { document.getElementById('usage-day-detail').textContent=label; }; }
        container.appendChild(button);
    }
    if (buttons.length) buttons[buttons.length-1].tabIndex=0;
    buttons.forEach((button,i)=>button.addEventListener('keydown',e=>{
        const offsets={ArrowLeft:-7,ArrowRight:7,ArrowUp:-1,ArrowDown:1};
        const index = e.key==='Home'?0:e.key==='End'?buttons.length-1:e.key in offsets?i+offsets[e.key]:null;
        if(index===null) return; e.preventDefault(); const next=buttons[Math.max(0,Math.min(buttons.length-1,index))];
        buttons.forEach(b=>b.tabIndex=-1); next.tabIndex=0; next.focus(); next.click();
    }));
    document.getElementById('usage-heatmap-total').textContent=usageFormat(data.total_tokens)+' tokens';
}
function renderUsageOverview(data) {
    const container=document.getElementById('usage-overview'); if (!container) return;
    const rows=[['总请求数',data.request_count],['输入 Tokens',data.input_tokens],['输出 Tokens',data.output_tokens],['缓存 Tokens',usageNumber(data.cache_read_tokens)+usageNumber(data.cache_creation_tokens)]];
    const title=document.createElement('h3'); title.textContent='总览';
    const period=document.createElement('p'); period.className='usage-period-label'; period.textContent='最近 180 天的请求记录';
    const cards=rows.map(([label,value])=> { const card=document.createElement('div'); card.className='usage-overview-card'; const name=document.createElement('span'); name.textContent=label; const total=document.createElement('strong'); total.textContent=usageFormat(value); card.append(total,name); return card; });
    container.replaceChildren(title,period,...cards);
}
window.addEventListener('message',event=> {
    if(event.origin!==window.location.origin) return;
    const frame=document.getElementById('conversation-list-frame');
    if(event.data?.type==='memory-gateway-open-usage' && frame && event.source===frame.contentWindow) openUsageBoard();
    if(event.data?.type==='memory-gateway-usage-closed' && event.source===window.parent) document.getElementById('usage-note')?.focus();
    if(['memory-gateway-refresh-usage','memory-gateway-refresh-conversations'].includes(event.data?.type) && event.source===window.parent) loadUsageNote();
});
document.addEventListener('keydown',event=> {
    const overlay=document.getElementById('usage-board-overlay'); if(!overlay || overlay.hidden) return;
    if(event.key==='Escape') { event.preventDefault(); closeUsageBoard(); }
    if(event.key==='Tab') {
        const focusable=[...overlay.querySelectorAll('button:not(:disabled), [tabindex="0"], a[href]')].filter(e=>e.getClientRects().length && e.tabIndex>=0);
        const first=focusable[0], last=focusable[focusable.length-1];
        if(event.shiftKey && document.activeElement===first) {event.preventDefault(); last?.focus();}
        else if(!event.shiftKey && document.activeElement===last) {event.preventDefault(); first?.focus();}
    }
});
document.addEventListener('DOMContentLoaded',()=>{ensureUsageBoard(); loadUsageNote();});

function setupUsagePages() {
    const pages = document.getElementById('usage-pages');
    if (!pages || pages.dataset.ready) return;
    pages.dataset.ready = 'true';
    const tabs = [...document.querySelectorAll('[data-usage-page]')];
    const go = index => pages.scrollTo({left: index * pages.clientWidth,
        behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth'});
    tabs.forEach((tab, index) => {
        tab.addEventListener('click', () => go(index));
        tab.addEventListener('keydown', event => {
            if (!['ArrowLeft','ArrowRight'].includes(event.key)) return;
            event.preventDefault();
            const next = Math.max(0, Math.min(tabs.length - 1, index + (event.key === 'ArrowRight' ? 1 : -1)));
            tabs[next].focus(); go(next);
        });
    });
    let active = 0, frame;
    pages.addEventListener('scroll', () => {
        cancelAnimationFrame(frame);
        frame = requestAnimationFrame(() => {
            active = Math.round(pages.scrollLeft / (pages.clientWidth || 1));
            tabs.forEach((tab, i) => {
                if (i === active) tab.setAttribute('aria-current', 'page');
                else tab.removeAttribute('aria-current');
                pages.children[i].inert = i !== active;
            });
        });
    }, {passive: true});
    [...pages.children].forEach((page, i) => { page.inert = i !== 0; });
    new ResizeObserver(() => { if (pages.clientWidth) pages.scrollLeft = active * pages.clientWidth; }).observe(pages);
}
