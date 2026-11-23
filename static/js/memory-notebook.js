// The memory desk and diary book share the existing memory/diary data stores.
let fixedMemoryStackExpanded = false;
let diaryNotebookMonth = localDateInputValue().slice(0, 7);
let diaryNotebookDay = null;
let diaryNotebookRequest = 0;

function renderMemoryShelf(fixed) {
    const total = fixed.length;
    const visible = fixedMemoryStackExpanded ? fixed : fixed.slice(0, 3);
    const digits = value => String(value).padStart(2, '0');
    const entries = visible.map((block, i) =>
        renderKelivoMemoryCard(block, 'fixed', digits(i + 1) + ' / ' + digits(total))).join('');
    return `<p class="count">${total} 条固定记忆</p>
        <div class="list" id="fixed-memory-unpacked"><i class="spine" data-wipe></i>${entries}</div>
        ${total > 3 ? `<button type="button" class="textbtn" id="archive-expand" aria-controls="fixed-memory-unpacked"
            aria-expanded="${fixedMemoryStackExpanded}" onclick="toggleFixedMemoryStack()"><u>${fixedMemoryStackExpanded ? '收起' : '展开其余 ' + (total - 3) + ' 条'}</u> ${fixedMemoryStackExpanded ? '↑' : '↓'}</button>` : ''}
        <div><button type="button" class="ghost" onclick="openStandingMemoryEditor()"><i></i>写下固定记忆</button></div>`;
}

function toggleFixedMemoryStack() {
    fixedMemoryStackExpanded = !fixedMemoryStackExpanded;
    renderStandingLists();
    byId('archive-expand')?.focus({preventScroll:true});
}

function diaryNotebookEntries(day = diaryNotebookDay) {
    return longTermMemories.filter(memory => diaryNotebookDate(memory) === day)
        .sort((a, b) => Number(a.id) - Number(b.id));
}

function diaryNotebookDate(memory) {
    const date = longTermMemoryDate(memory);
    return longTermDateParts(date) ? date : '';
}

function syncMemoryModalScrollLock() {
    const open = Boolean(document.querySelector('.memory-editor-modal.open'));
    document.body.classList.toggle('memory-editor-open', open);
    if (byId('diary-notebook')?.classList.contains('open') && !document.querySelector('.memory-editor-modal.open')) {
        document.querySelector('.diary-notebook-content')?.focus({preventScroll: true});
    }
}

async function loadDiaryNotebook() {
    const notebook = byId('diary-notebook');
    notebook.classList.add('open');
    byId('diary-notebook-msg').textContent = diariesLoaded ? '' : '加载中…';
    renderDiaryNotebook();
    await Promise.all([loadDiaries(), loadDiaryPending()]);
    if (notebook.classList.contains('open')) {
        if (byId('diary-notebook-msg').textContent === '加载中…') {
            byId('diary-notebook-msg').textContent = diariesLoaded ? '' : '日记加载失败';
        }
        renderDiaryNotebook();
        if (diaryMonthFlipped) loadDiaryMonth(diaryNotebookMonth);
    }
}

function closeDiaryNotebook() {
    window.AshPhone?.back();
}

function chooseDiaryNotebookInitialDay() {
    if (diaryNotebookDay !== null || !diariesLoaded) return;
    const dated = [...longTermMemories].filter(memory => diaryNotebookDate(memory))
        .sort(compareLongTermMemoriesNewestFirst);
    diaryNotebookDay = dated.length ? longTermMemoryDate(dated[0]) : longTermMemories.length ? '' : localDateInputValue();
    if (diaryNotebookDay) diaryNotebookMonth = diaryNotebookDay.slice(0, 7);
}

function renderDiaryNotebook() {
    if (!byId('diary-notebook')?.classList.contains('open')) return;
    chooseDiaryNotebookInitialDay();
    const [year, month] = diaryNotebookMonth.split('-').map(Number);
    byId('diary-calendar-month').textContent = year + '年' + month + '月';
    byId('diary-calendar-month-picker').value = diaryNotebookMonth;
    const firstWeekday = (new Date(year, month - 1, 1).getDay() + 6) % 7;
    const days = new Date(year, month, 0).getDate();
    const cells = Array(firstWeekday).fill('<span class="diary-calendar-blank" aria-hidden="true"></span>');
    for (let day = 1; day <= days; day++) {
        const date = diaryNotebookMonth + '-' + String(day).padStart(2, '0');
        const entries = diaryNotebookEntries(date);
        const keywords = [...new Set(entries.flatMap(memory => normalizeLongTermKeywords(memory.keywords)))];
        const label = date + (entries.length ? '，' + entries.length + ' 篇日记，' + keywords.join('、') : '，没有日记');
        cells.push('<button type="button" class="diary-calendar-day' + (entries.length ? ' has-diary' : '') + '" data-date="' + date + '" aria-label="' + escHtml(label) + '" aria-pressed="' + (diaryNotebookDay === date) + '" onclick="selectDiaryNotebookDay(\'' + date + '\')">' +
            '<span class="diary-calendar-number">' + day + '</span></button>');
    }
    byId('diary-calendar-grid').innerHTML = cells.join('');
    const undatedCount = diaryNotebookEntries('').length;
    byId('diary-undated-toggle').hidden = !undatedCount;
    byId('diary-undated-toggle').textContent = '未标日期 · ' + undatedCount + ' 篇';
    renderDiaryNotebookPage();
}

function selectDiaryNotebookDay(day) {
    if (day && !longTermDateParts(day)) return;
    diaryNotebookDay = day;
    renderDiaryNotebook();
    // Re-rendered calendar cells retain keyboard focus on the selected day.
    if (day) byId('diary-calendar-grid').querySelector('[data-date="' + day + '"]')?.focus({preventScroll: true});
}

function selectDiaryNotebookMonth(value) {
    if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(value) || Number(value.slice(0, 4)) < 1) return;
    diaryNotebookMonth = value;
    const entries = longTermMemories.filter(memory => diaryNotebookDate(memory).startsWith(diaryNotebookMonth)).sort(compareLongTermMemoriesNewestFirst);
    diaryNotebookDay = entries.length ? longTermMemoryDate(entries[0]) : diaryNotebookMonth + '-01';
    renderDiaryNotebook();
}

function renderDiaryNotebookPage() {
    ++diaryNotebookRequest;
    const entries = diaryNotebookEntries();
    byId('diary-reading-date').textContent = diaryNotebookDay || '未标日期';
    byId('diary-reading-list').innerHTML = entries.length ? entries.map(item => {
        const id = Number(item.id);
        return `<details class="diary-entry" ontoggle="readNotebookDiary(this, ${id})"><summary>${escHtml(item.title || '未命名')}</summary><div class="diary-entry-body"></div></details>`;
    }).join('') : `<p class="diary-empty">${diariesLoaded ? '暂无日记' : '加载中…'}</p>`;
}

async function readNotebookDiary(card, id) {
    if (!card.open || card.dataset.loaded || card.dataset.loading) return;
    const generation = diaryNotebookRequest;
    const body = card.querySelector('.diary-entry-body');
    const content = document.createElement('div');
    content.className = 'diary-reading-content';
    content.textContent = '加载中…';
    body.replaceChildren(content);
    card.dataset.loading = 'true';
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 15000);
    try {
        const response = await authFetch('/api/diaries/' + id, {signal:controller.signal});
        const diary = await readJsonResponse(response);
        if (!response.ok || diary.error) throw new Error(diary.error || 'HTTP ' + response.status);
        if (generation !== diaryNotebookRequest || !card.isConnected || !card.open) return;
        const edit = document.createElement('button');
        edit.type = 'button'; edit.className = 'diary-entry-edit'; edit.textContent = '编辑';
        edit.onclick = () => openLongTermMemoryEditor(id);
        content.textContent = diary.content || '';
        body.prepend(edit);
        card.dataset.loaded = 'true';
    } catch (error) {
        if (generation !== diaryNotebookRequest || !card.isConnected || !card.open) return;
        content.textContent = '加载失败';
        const retry = document.createElement('button');
        retry.type = 'button'; retry.textContent = '重试';
        retry.onclick = () => readNotebookDiary(card, id);
        content.append(document.createElement('br'), retry);
    } finally {
        clearTimeout(timer);
        delete card.dataset.loading;
    }
}

async function newNotebookDiary() {
    await openLongTermMemoryEditor();
    if (diaryNotebookDay) byId('long-term-memory-date').value = diaryNotebookDay;
}

function toggleDiaryNotebookManagement() {
    const management = byId('standing-view-long-term');
    management.hidden = !management.hidden;
    byId('diary-notebook-spread').hidden = !management.hidden;
    const button = byId('diary-notebook-manage-toggle');
    button.setAttribute('aria-expanded', String(!management.hidden));
    button.textContent = management.hidden ? '整理' : '完成';
    if (management.hidden) renderDiaryNotebook();
}

document.addEventListener('keydown', event => {
    if (!byId('diary-notebook')?.classList.contains('open')) return;
    if (document.querySelector('.memory-editor-modal.open') || event.target.closest?.('.memory-editor-modal')) return;
    if (event.key === 'Escape') { event.preventDefault(); closeDiaryNotebook(); }

});

const diaryMonthSummaries = new Map();
let diaryMonthFlipped = false;
let diaryMonthTimer = null;
let diaryMonthLoading = false;

let diaryMonthAngle = 0;
function flipDiaryMonth(back, angle = back ? -180 : 0) {
    diaryMonthFlipped = back;
    diaryMonthAngle = angle;
    const card = byId('diary-calendar-flipper');
    card.style.transform = `rotateY(${angle}deg)`;
    for (const [id, inactive] of [['diary-calendar-front', back], ['diary-calendar-back', !back]]) {
        byId(id).inert = inactive;
        byId(id).setAttribute('aria-hidden', String(inactive));
    }
    clearTimeout(diaryMonthTimer);
    if (back) {
        renderDiaryMonth();
        loadDiaryMonth(diaryNotebookMonth);
    }
}

// Edge grips allow all directions; the middle retains native vertical scrolling.
(() => {
    const card = byId('diary-calendar-flipper');
    let drag = null;
    let suppressClick = false;
    for (const edge of ['top','right','bottom','left']) {
        const grip = document.createElement('span');
        grip.className = 'diary-card-grip diary-card-grip-' + edge;
        grip.setAttribute('aria-hidden', 'true');
        card.appendChild(grip);
    }
    card.addEventListener('pointerdown', event => {
        if (!event.isPrimary || event.button !== 0 || event.target.closest('input, .diary-month-actions')) return;
        const content = event.target.closest('.diary-month-content');
        if (content && window.getSelection()?.toString()) return;
        drag = {id: event.pointerId, x: event.clientX, y: event.clientY,
            time: performance.now(), angle: diaryMonthAngle, active: false, edge: Boolean(event.target.closest('.diary-card-grip')), lastY: event.clientY, lastX: event.clientX,
            lastTime: performance.now(), velocity: 0};
    });
    card.addEventListener('pointermove', event => {
        if (!drag || drag.id !== event.pointerId) return;
        const dx = event.clientX - drag.x, dy = event.clientY - drag.y;
        if (!drag.active) {
            if (!drag.edge && Math.abs(dy) > 10 && Math.abs(dy) > Math.abs(dx)) { drag = null; return; }
            if (Math.hypot(dx, drag.edge ? dy : 0) < 10) return;
            drag.active = true;
            suppressClick = true;
            card.setPointerCapture(event.pointerId);
            card.classList.add('is-dragging');
        }
        const now = performance.now();
        if (now > drag.lastTime) drag.velocity = Math.hypot(event.clientX - drag.lastX, drag.edge ? event.clientY - drag.lastY : 0) / (now - drag.lastTime);
        drag.lastY = event.clientY;
        drag.lastX = event.clientX;
        drag.lastTime = now;
        const rotation = Math.max(-170, Math.min(170, dx / card.clientWidth * 180));
        const tilt = drag.edge ? Math.max(-80, Math.min(80, -dy / card.clientHeight * 180)) : 0;
        card.style.transform = `rotateX(${tilt}deg) rotateY(${drag.angle + rotation}deg)`;
    });
    function release(event, cancelled = false) {
        if (!drag || drag.id !== event.pointerId) return;
        const state = drag;
        drag = null;
        if (!state.active) return;
        card.classList.remove('is-dragging');
        const dx = event.clientX - state.x, dy = state.edge ? event.clientY - state.y : 0;
        const distance = Math.hypot(dx / card.clientWidth, dy / card.clientHeight);
        const velocity = performance.now() - state.lastTime < 100 ? state.velocity : 0;
        const turn = !cancelled && (distance > .25 || (Math.hypot(dx, dy) > 14 && Math.abs(velocity) > .45));
        if (turn) flipDiaryMonth(!diaryMonthFlipped, state.angle + ((Math.abs(dx) >= Math.abs(dy) ? dx : -dy) > 0 ? 180 : -180));
        else card.style.transform = `rotateY(${state.angle}deg)`;
        if (card.hasPointerCapture(event.pointerId)) card.releasePointerCapture(event.pointerId);
        setTimeout(() => { suppressClick = false; }, 0);
    }
    card.addEventListener('pointerup', event => release(event));
    card.addEventListener('pointercancel', event => release(event, true));
    card.addEventListener('click', event => {
        if (suppressClick) { event.preventDefault(); event.stopPropagation(); }
    }, true);
    card.addEventListener('keydown', event => {
        if (event.target === card && (event.key === 'Enter' || event.key === ' ')) {
            event.preventDefault();
            flipDiaryMonth(!diaryMonthFlipped, diaryMonthAngle + 180);
        }
    });
})();

function renderDiaryMonth() {
    const month = diaryNotebookMonth;
    const data = diaryMonthSummaries.get(month);
    const busy = diaryMonthLoading || data?.status === 'running';
    byId('diary-month-title').textContent = month.replace('-', ' · ') + ' 月度总结';
    byId('diary-month-content').textContent = data?.content || '';
    byId('diary-month-status').textContent = diaryMonthLoading ? '加载中…' : data?.status === 'running' ? '生成中…' : data?.error || '';
    byId('diary-month-generate').textContent = data?.status === 'running' ? '生成中…' : data?.content ? '重新生成' : '生成';
    byId('diary-month-generate').disabled = busy;
    byId('diary-month-copy').hidden = !data?.content;
}

async function loadDiaryMonth(month) {
    diaryMonthLoading = true;
    if (month === diaryNotebookMonth) renderDiaryMonth();
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
        const response = await authFetch('/api/diary-months/' + month, {cache: 'no-store', signal: controller.signal});
        const data = await readJsonResponse(response);
        if (!response.ok) throw new Error(data.error || '加载失败');
        diaryMonthSummaries.set(month, data);
    } catch (error) {
        const previous = diaryMonthSummaries.get(month) || {};
        diaryMonthSummaries.set(month, {...previous, error: '连接中断，正在恢复…'});
    } finally {
        clearTimeout(timeout);
        diaryMonthLoading = false;
        if (month === diaryNotebookMonth && diaryMonthFlipped) {
            renderDiaryMonth();
            const data = diaryMonthSummaries.get(month);
            if (data?.status === 'running' || data?.error === '连接中断，正在恢复…') {
                clearTimeout(diaryMonthTimer);
                diaryMonthTimer = setTimeout(() => {
                    if (diaryMonthFlipped && !document.hidden) loadDiaryMonth(month);
                }, 3000);
            }
        }
    }
}

async function generateDiaryMonth() {
    const month = diaryNotebookMonth;
    if (diaryMonthLoading || diaryMonthSummaries.get(month)?.status === 'running') return;
    const previous = diaryMonthSummaries.get(month) || {};
    if (previous.error?.includes('费用') && !confirm('上次请求的结果未确认，可能已产生费用。重新生成会发起新的模型请求，是否继续？')) return;
    diaryMonthSummaries.set(month, {...previous, status: 'running', error: ''});
    renderDiaryMonth();
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
        const response = await authFetch('/api/diary-months/' + month, {
            method: 'POST', headers: {'Content-Type': 'application/json'}, signal: controller.signal,
            body: JSON.stringify({request_id: crypto.randomUUID()}),
        });
        const data = await readJsonResponse(response);
        if (!response.ok) {
            diaryMonthSummaries.set(month, {...previous, status: 'failed', error: data.error || '生成失败'});
            return;
        }
        diaryMonthSummaries.set(month, data);
    } catch (_) {
        // Only read status after an uncertain submission; never repeat a paid call.
    } finally {
        clearTimeout(timeout);
        if (month === diaryNotebookMonth && diaryMonthFlipped) {
            renderDiaryMonth();
            if (diaryMonthSummaries.get(month)?.status === 'running') loadDiaryMonth(month);
        }
    }
}

async function copyDiaryMonth() {
    const content = diaryMonthSummaries.get(diaryNotebookMonth)?.content;
    if (!content) return;
    try {
        await navigator.clipboard.writeText(content);
        byId('diary-month-status').textContent = '已复制';
    } catch (_) {
        const selection = window.getSelection();
        const range = document.createRange();
        range.selectNodeContents(byId('diary-month-content'));
        selection.removeAllRanges();
        selection.addRange(range);
        byId('diary-month-status').textContent = '请长按或使用复制快捷键复制正文';
    }
}

document.addEventListener('visibilitychange', () => {
    if (!document.hidden && diaryMonthFlipped) loadDiaryMonth(diaryNotebookMonth);
});
