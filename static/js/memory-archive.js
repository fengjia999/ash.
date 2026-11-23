(() => {
  const archive = document.getElementById('section-standing');
  const $ = (s, r = archive) => r.querySelector(s);
  const $$ = (s, r = archive) => Array.from(r.querySelectorAll(s));
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const EASE = 'cubic-bezier(.22,1,.36,1)', INK = 'cubic-bezier(.45,0,.2,1)';
  const NS = 'http://www.w3.org/2000/svg';
  const mk = (tag, attrs, parent) => {
    const n = document.createElementNS(NS, tag);
    for (const k in attrs) n.setAttribute(k, attrs[k]);
    if (parent) parent.append(n);
    return n;
  };
  const rng = seed => { let n = seed; return () => { n = (n * 1664525 + 1013904223) >>> 0; return n / 4294967296; }; };
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const CX = 215, CY = 118, N = 26;
  const ORDER = [2, 8, 13, 19, 24, 5, 11, 16, 22, 0, 6, 14];
  const positions = [...new Set([...ORDER, ...Array.from({length:N}, (_, i) => i)])];
  let selected = null, tab = 0, busy = false, visibleRows = [], seedIds = [];

  /* ---------- grow: rules draw, lines trace, nodes pop, text rises, top to bottom ---------- */
  function grow(roots, base) {
    if (reduce) return;
    const vh = innerHeight || 800;
    const at = e => (base + Math.min(Math.max(e.getBoundingClientRect().top / vh, 0), 1) * 1.1) * 1000;
    roots.forEach(root => {
      $$('[data-rule]', root).forEach(e => e.animate(
        [{ transform: 'scaleX(0)' }, { transform: 'scaleX(1)' }],
        { duration: 800, delay: at(e), easing: EASE, fill: 'backwards' }));
      $$('[data-wipe]', root).forEach(e => e.animate(
        [{ clipPath: 'inset(0 0 100% 0)' }, { clipPath: 'inset(0 0 0% 0)' }],
        { duration: 1100, delay: at(e), easing: INK, fill: 'backwards' }));
      $$('[data-draw]', root).forEach(e => e.animate(
        [{ strokeDashoffset: 1 }, { strokeDashoffset: 0 }],
        { duration: 900, delay: at(e) + (+e.dataset.d || 0) * 1000, easing: INK, fill: 'backwards' }));
      $$('[data-node]', root).forEach(e => e.animate(
        [{ transform: 'scale(0)' }, { transform: 'scale(1)' }],
        { duration: 420, delay: at(e) + 250 + (+e.dataset.d || 0) * 1000, easing: 'cubic-bezier(.34,1.56,.64,1)', fill: 'backwards' }));
      $$('[data-rise]', root).forEach(e => e.animate(
        [{ opacity: 0, transform: 'translateY(5px)' }, { opacity: 1, transform: 'none' }],
        { duration: 600, delay: at(e) + 150, easing: EASE, fill: 'backwards' }));
    });
  }

  /* ---------- dandelion: generated line art ---------- */
  const dande = $('#dande');
  const seeds = [];
  function buildDande() {
    const r = rng(6174);
    const draw = (d, cls, delay, parent) => {
      const p = mk('path', { d, class: 'sd ' + (cls || ''), pathLength: 1 }, parent);
      p.dataset.draw = ''; p.dataset.d = delay.toFixed(2);
      return p;
    };
    draw('M215 126C211 172 194 216 184 266', 'stem', 0, dande);
    draw('M191 228C166 220 142 230 128 250C152 254 178 250 191 228Z', 'stem', .5, dande).style.strokeWidth = '.7';
    draw('M120 266H300', '', .6, dande).style.stroke = 'var(--guide)';
    const field = mk('g', {}, dande);
    for (let i = 0; i < N; i++) {
      const ang = (i / N) * Math.PI * 2 + (r() - .5) * .1;
      const len = 66 + r() * 24, c = Math.cos(ang), s = Math.sin(ang);
      const sway = mk('g', { class: 'sway' }, field);
      sway.style.animationDelay = (-r() * 8).toFixed(2) + 's';
      sway.style.animationDuration = (6 + r() * 4).toFixed(2) + 's';
      const inner = mk('g', { class: 'seedin' }, sway);
      const d0 = .35 + i * .03;
      const bx = CX + c * 8, by = CY + s * 8, tx = CX + c * len * .8, ty = CY + s * len * .8;
      draw(`M${bx.toFixed(1)} ${by.toFixed(1)}L${tx.toFixed(1)} ${ty.toFixed(1)}`, '', d0, inner);
      for (let k = -3; k <= 3; k++) {
        const l = (k === 0 ? 21 : 19 - Math.abs(k) * 1.3) + r() * 2;
        const a = ang + k * .19, a2 = ang + k * .1;
        const ex = tx + Math.cos(a) * l, ey = ty + Math.sin(a) * l;
        const qx = tx + Math.cos(a2) * l * .62, qy = ty + Math.sin(a2) * l * .62;
        draw(`M${tx.toFixed(1)} ${ty.toFixed(1)}Q${qx.toFixed(1)} ${qy.toFixed(1)} ${ex.toFixed(1)} ${ey.toFixed(1)}`, '', d0 + .1, inner);
      }
      const node = mk('circle', { cx: tx.toFixed(1), cy: ty.toFixed(1), r: 3, class: 'node' }, inner);
      node.dataset.d = d0.toFixed(2);
      const hit = mk('circle', { cx: tx.toFixed(1), cy: ty.toFixed(1), r: 17, class: 'hit' }, inner);
      const seed = { g: sway, inner, node, c, s, mem: null };
      hit.addEventListener('click', () => { if (seed.mem && !seed.g.classList.contains('dim')) select(seed.mem.id, true); });
      seeds.push(seed);
    }
    mk('circle', { cx: CX, cy: CY, r: 7, class: 'sd', pathLength: 1 }, dande).style.stroke = 'var(--ink)';
    mk('circle', { cx: CX, cy: CY, r: 2.6, fill: 'var(--ink)' }, dande);
  }
  function syncSeeds() {
    const visibleIds = new Set(visibleRows.map(row => row.id));
    seeds.forEach((s, i) => {
      const id = seedIds[positions.indexOf(i)];
      const m = id == null ? null : {id};
      s.mem = m;
      const on = !!m && m.id === selected;
      s.g.classList.toggle('fill', !!m);
      s.g.classList.toggle('sel', on);
      s.g.classList.toggle('dim', !!m && !visibleIds.has(m.id));
      s.inner.style.transform = on ? `translate(${(s.c * 11).toFixed(1)}px,${(s.s * 11).toFixed(1)}px)` : '';
      if (m) s.node.dataset.node = ''; else delete s.node.dataset.node;
    });
  }

  /* ---------- cards, chips, search ---------- */
  function select(id, fromSeed) {
    selected = selected === id ? null : id;
    if (selected != null && !seedIds.includes(selected)) seedIds[N - 1] = selected;
    for (const card of $$('.archive-card')) {
      const on = card.dataset.id === String(selected);
      card.classList.toggle('on', on);
      $('h2 button', card).setAttribute('aria-pressed', String(on));
      if (on && fromSeed) card.scrollIntoView({behavior:reduce ? 'auto' : 'smooth', block:'center'});
    }
    syncSeeds();
  }

  function bindFragmentPin(card, row) {
    const pin = $('.fragment-pin', card), edit = $('.edit', card), status = $('[role=status]', card);
    function paint() {
      card.classList.toggle('is-pinned', !!row.pinned);
      pin.textContent = row.pinned ? '已 Pin' : 'Pin';
      pin.setAttribute('aria-pressed', String(!!row.pinned));
      pin.title = row.pinned ? '取消 Pin' : 'Pin，后台整理时保留这条片段';
      edit.textContent = '编辑';
    }
    async function toggle() {
      if (pin.disabled) return;
      pin.disabled = edit.disabled = true;
      status.textContent = '';
      try {
        const result = await saveDashboardJson('/api/memories/' + row.id + '/pin', {
          method:'PUT', headers:{'Content-Type':'application/json'},
          body:JSON.stringify({pinned:!row.pinned, original_content:row.content, original_categories:row.tags})
        });
        row.pinned = result.pinned;
        paint();
        if (!card.isConnected) await loadFragmentPage();
      } catch (error) { status.textContent = error.message; }
      finally { pin.disabled = edit.disabled = false; }
    }
    paint();
    pin.onclick = toggle;
    let start = null;
    card.addEventListener('pointerdown', event => {
      start = event.isPrimary && event.pointerType !== 'mouse' && !event.target.closest('button')
        ? {id:event.pointerId, x:event.clientX, y:event.clientY} : null;
    });
    card.addEventListener('pointercancel', () => { start = null; });
    card.addEventListener('pointerup', event => {
      if (start && start.id === event.pointerId) {
        const left = start.x - event.clientX, vertical = Math.abs(start.y - event.clientY);
        if (left >= 52 && left > 2 * vertical) toggle();
      }
      start = null;
    });
  }

  function renderFragments(rows, more) {
    const box = $('#fragment-entries');
    const filtered = !!(fragmentCategory || fragmentImportanceMax || $('#fragment-query').value.trim());
    if (!more) {
      visibleRows = [];
      box.replaceChildren();
      selected = null;
    }
    visibleRows.push(...rows);
    const ids = visibleRows.map(row => row.id);
    // Keep the unfiltered flower in place while dimming the other seeds.
    // Search hits outside its first page still receive a visible position.
    if (!filtered) seedIds = ids.slice(0, N);
    else {
      const visibleSeeds = new Set(ids.slice(0, N));
      for (const id of visibleSeeds) {
        if (seedIds.includes(id)) continue;
        const index = seedIds.length < N ? seedIds.length : seedIds.findIndex(seed => !visibleSeeds.has(seed));
        if (index >= 0) seedIds[index] = id;
      }
    }
    for (const row of rows) {
      const card = document.createElement('article');
      card.className = 'archive-card';
      card.dataset.id = row.id;
      card.innerHTML = '<i class="ctop" data-rule></i><i class="pin" data-node></i>' +
        '<div class="meta" data-rise><time></time><em></em></div>' +
        '<h2 data-rise><button type="button" aria-pressed="false"></button></h2>' +
        '<p data-rise></p><footer class="fragment-actions"><button type="button" class="fragment-pin"></button>' +
        '<button type="button" class="edit"></button></footer><small role="status"></small>';
      $('time', card).textContent = row.conversation_time || '录入 ' + String(row.created_at).slice(0, 10);
      $('em', card).textContent = row.tags.join(' · ') + ' · IMP ' + row.importance;
      const title = $('h2 button', card);
      title.textContent = '片刻 ' + String(row.id).padStart(2, '0');
      title.onclick = () => select(row.id, false);
      $('p', card).textContent = row.content;
      $('.edit', card).onclick = () => openFragmentEditor(row);
      bindFragmentPin(card, row);
      box.append(card);
    }
    box.classList.toggle('is-empty', !ids.length);
    $('#fragment-empty').hidden = !!ids.length;
    $('#fragment-empty').textContent = filtered ? '没有找到符合条件的片刻。' : '还没有片刻。从「写下片刻」开始。';
    $('#archive-fragment-count').textContent = ids.length + (rows.length === 40 ? '+ 条片刻' : ' 条片刻');
    syncSeeds();
  }

  let searchTimer;
  $('#fragment-query').addEventListener('input', () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => loadFragmentPage(), 180);
  });
  $('#fragment-importance').addEventListener('change', () => loadFragmentPage());

  let flowRAF = 0;
  function stopFlow() { cancelAnimationFrame(flowRAF); }
  function startFlow() {
    stopFlow();
    const path = $('.river path'), dot = $('#flowdot');
    const L = path.getTotalLength();
    const place = p => { const pt = path.getPointAtLength(p * L); dot.setAttribute('cx', pt.x); dot.setAttribute('cy', pt.y); };
    if (reduce) { place(.5); return; }
    const t0 = performance.now();
    const step = t => { place(((t - t0) / 9000) % 1); flowRAF = requestAnimationFrame(step); };
    flowRAF = requestAnimationFrame(step);
  }

  /* ---------- tabs: clip wipe, blue ink slides underneath ---------- */
  const panels = $$('.archive-panel'), tabBtns = $$('.archive-tab'), ink = $('.tab-ink');
  function placeInk() {
    const b = tabBtns[tab];
    ink.style.width = b.offsetWidth + 'px';
    ink.style.transform = 'translateX(' + b.offsetLeft + 'px)';
  }
  async function setTab(n, focus) {
    if (n === tab || busy) return;
    busy = true;
    const dir = n > tab ? 1 : -1, out = panels[tab], inn = panels[n];
    tab = n;
    archive.dataset.memoryView = ['fragments','fixed','flow'][n];
    tabBtns.forEach((b, i) => { b.setAttribute('aria-selected', String(i === n)); b.tabIndex = i === n ? 0 : -1; });
    if (focus) tabBtns[n].focus();
    placeInk();
    try {
      if (!reduce) {
        const a = out.animate(
          [{ clipPath: 'inset(0 0 0 0)', opacity: 1 }, { clipPath: dir > 0 ? 'inset(0 100% 0 0)' : 'inset(0 0 0 100%)', opacity: .25 }],
          { duration: 300, easing: 'cubic-bezier(.7,0,.84,0)', fill: 'forwards' });
        await a.finished; a.cancel();
      }
      out.hidden = true; inn.hidden = false;
      stopFlow();
      if (n === 2 && archive.classList.contains('active')) startFlow();
      if (!reduce) {
        grow([inn], .05);
        await inn.animate(
          [{ clipPath: dir > 0 ? 'inset(0 0 0 100%)' : 'inset(0 100% 0 0)', transform: 'translateX(' + dir * 12 + 'px)' },
           { clipPath: 'inset(0 0 0 0)', transform: 'none' }],
          { duration: 560, easing: EASE }).finished;
      }
    } catch (e) { out.hidden = true; inn.hidden = false; }
    busy = false;
  }
  tabBtns.forEach((b, i) => {
    b.addEventListener('click', () => setTab(i, false));
    b.addEventListener('keydown', e => {
      if (e.key === 'ArrowRight') setTab(Math.min(2, tab + 1), true);
      if (e.key === 'ArrowLeft') setTab(Math.max(0, tab - 1), true);
    });
  });

  /* ---------- entry: tide covers, the page regrows underneath, tide drains ---------- */
  const tideB = $('.tide.back'), tideF = $('.tide.front');
  const mv = (node, from, to, dur, delay) => node.animate(
    [{ transform: 'translateY(' + from + ')' }, { transform: 'translateY(' + to + ')' }],
    { duration: dur, delay, easing: INK, fill: 'forwards' }).finished;
  async function enter(first) {
    if (reduce) return;
    busy = true;
    [tideB, tideF].forEach(t => t.getAnimations().forEach(a => a.cancel()));
    if (first) {
      tideB.style.transform = tideF.style.transform = 'translateY(0)';
    } else {
      await Promise.all([mv(tideB, '104%', '0%', 800, 0), mv(tideF, '104%', '0%', 900, 100)]);
    }
    grow([$('.top'), panels[tab]], first ? .3 : .2);
    await sleep(first ? 260 : 160);
    await Promise.all([mv(tideF, '0%', '104%', 760, 0), mv(tideB, '0%', '104%', 760, 90)]);
    busy = false;
  }
  $('#archive-replay').addEventListener('click', () => { if (!busy) enter(false).catch(() => { busy = false; }); });

  /* ---------- go ---------- */
  let built = false;
  function open() {
    if (!built) {
      const fonts = document.createElement('link');
      fonts.rel = 'stylesheet';
      fonts.href = 'https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400&family=Noto+Serif+SC:wght@400;600&family=Source+Serif+4:ital,opsz,wght@0,8..60,400;0,8..60,500;0,8..60,600;1,8..60,400&display=swap';
      document.head.append(fonts);
      buildDande();
      built = true;
    }
    placeInk();
    syncSeeds();
    if (tab === 2) startFlow();
    if (!busy) enter(true).catch(() => { busy = false; });
  }
  new ResizeObserver(placeInk).observe($('.archive-tabs'));
  new MutationObserver(() => {
    if (!archive.classList.contains('active')) stopFlow();
  }).observe(archive, {attributes:true, attributeFilter:['class']});
  window.AshArchive = {enter:open, renderFragments};
})();
