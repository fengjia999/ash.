// Runs in the head so saved preferences apply before the page is painted.
(() => {
    const key = "ash-dashboard-theme";
    const root = document.documentElement;
    const system = window.matchMedia('(prefers-color-scheme: dark)');
    const valid = value => ['auto', 'light', 'dark'].includes(value);
    let preference = 'auto';
    function updateButton() {
        const button = document.getElementById("theme-toggle");
        if (!button) return;
        const dark = root.dataset.theme === "dark";
        const label = dark ? "切换到日间模式" : "切换到夜间模式";
        button.setAttribute("aria-pressed", String(dark));
        button.setAttribute("aria-label", label);
        button.title = label;
    }
    function syncFrame(frame) {
        try {
            const child = frame.contentWindow;
            if (child?.AshTheme) child.AshTheme.setTheme(preference, {persist: false});
        } catch (_) { /* Only our same-origin editors share the theme. */ }
    }
    function applyTheme() {
        const theme = preference === 'auto' ? (system.matches ? 'dark' : 'light') : preference;
        const changed = root.dataset.theme !== theme || root.dataset.themePreference !== preference;
        root.dataset.theme = theme;
        root.dataset.themePreference = preference;
        const meta = document.querySelector('meta[name="theme-color"]');
        if (meta) meta.content = theme === "dark" ? "#1e211d" : "#f4f3ee";
        updateButton();
        document.querySelectorAll("iframe").forEach(syncFrame);
        if (changed) window.dispatchEvent(new CustomEvent('ash-theme-change', {detail:{preference, theme}}));
    }
    function setTheme(value, {persist = true} = {}) {
        if (!valid(value)) return;
        preference = value;
        if (persist) { try { localStorage.setItem(key, preference); } catch (_) {} }
        applyTheme();
    }
    let initial = 'auto';
    try {
        const saved = localStorage.getItem(key);
        if (valid(saved)) initial = saved;
        // Migrate the old desktop-only preference once, before the first paint.
        else {
            const legacy = JSON.parse(localStorage.getItem('ash.phone.desktop.v2') || 'null')?.mode;
            if (valid(legacy)) { initial = legacy; localStorage.setItem(key, initial); }
        }
    } catch (_) {}
    try {
        if (window.parent !== window && ["dark", "light"].includes(window.parent.document.documentElement.dataset.theme)) {
            initial = window.parent.AshTheme?.getPreference() || window.parent.document.documentElement.dataset.theme;
        }
    } catch (_) {}
    window.AshTheme = {setTheme, getPreference: () => preference};
    setTheme(initial, {persist: false});
    document.addEventListener("DOMContentLoaded", () => {
        updateButton();
        document.getElementById("theme-toggle")?.addEventListener("click", () => {
            setTheme(root.dataset.theme === "dark" ? "light" : "dark");
        });
    });
    document.addEventListener("load", event => {
        if (event.target?.tagName === "IFRAME") syncFrame(event.target);
    }, true);
    window.addEventListener("storage", event => {
        if (event.key === key || event.key === null) setTheme(valid(event.newValue) ? event.newValue : 'auto', {persist: false});
    });
    system.addEventListener('change', () => { if (preference === 'auto') applyTheme(); });
    window.addEventListener('pageshow', applyTheme);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) applyTheme(); });
})();
