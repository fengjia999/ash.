/* Adapted from the Merle app.js viewport handling.
 * Ash's outer dashboard owns viewport sizing, including focus inside its chat iframe.
 */
(() => {
    'use strict';
    const embedded = window !== window.top;
    let baseline = Math.max(innerHeight, window.visualViewport?.height || 0), resetBaseline = false;
    let frame = 0, keyboardOpen = false;
    const root = document.documentElement;
    function isField(element) {
        return !!element?.matches('textarea,select,[contenteditable="true"],input:not([type=button]):not([type=submit]):not([type=checkbox]):not([type=radio]):not([type=file]):not([type=range]):not([type=color])');
    }
    function focusedField() {
        let active = document.activeElement;
        try { if (active?.tagName === 'IFRAME') active = active.contentDocument?.activeElement; } catch (_) {}
        return isField(active);
    }
    function applyKeyboard(open) {
        const changed = keyboardOpen !== open;
        keyboardOpen = open; document.body.classList.toggle('phone-chat-keyboard-open', open);
        if (changed) window.dispatchEvent(new CustomEvent('ash-phone-keyboard', {detail:{open}}));
    }
    function refresh() {
        frame = 0;
        if (embedded) { parent.postMessage({type:'ash-phone-focus'}, location.origin); return; }
        const viewport = window.visualViewport;
        const height = viewport?.height || innerHeight, top = Math.max(0, viewport?.offsetTop || 0);
        const focused = focusedField();
        if (focused && baseline-height > 48) {
            // iOS offsetTop is panning. It must not be subtracted from keyboard height.
            const inset = Math.max(0, baseline-height);
            root.style.setProperty('--phone-visible-height', height+'px');
            root.style.setProperty('--phone-visible-top', top+'px');
            document.body.classList.add('phone-viewport-active');
            applyKeyboard(inset > 48);
        } else {
            if (resetBaseline) { baseline = Math.max(innerHeight, height); resetBaseline = false; }
            else baseline = Math.max(baseline, innerHeight, height);
            // CSS owns the normal viewport. Only the keyboard needs measured
            // bounds; installed Safari can under-report the full-screen height.
            root.style.removeProperty('--phone-visible-height');
            root.style.removeProperty('--phone-visible-top');
            document.body.classList.remove('phone-viewport-active'); applyKeyboard(false);
        }
        // Pass the installed shell's inset into the iframe: its own env() can
        // be zero. The composer paints the safe area, not an outer blank strip.
        const safeBottom = parseFloat(getComputedStyle(document.body).getPropertyValue('--phone-bottom-inset')) || 0;
        document.getElementById('conversation-detail-frame')?.contentWindow?.postMessage({type:'ash-phone-viewport',keyboardOpen,safeBottom}, location.origin);
    }
    function schedule() { if (!frame) frame = requestAnimationFrame(refresh); }
    document.addEventListener('focusin', schedule);
    document.addEventListener('focusout', () => { schedule(); setTimeout(schedule, 80); });
    window.visualViewport?.addEventListener('resize', schedule);
    window.visualViewport?.addEventListener('scroll', schedule);
    window.addEventListener('resize', schedule);
    window.addEventListener('pageshow', schedule);
    window.addEventListener('orientationchange', () => {
        resetBaseline = true; applyKeyboard(false); setTimeout(schedule, 80); setTimeout(schedule, 300);
    });
    window.addEventListener('message', event => {
        if (event.origin !== location.origin) return;
        if (embedded && event.source === parent && event.data?.type === 'ash-phone-viewport') {
            const inset = Number(event.data.safeBottom);
            root.style.setProperty('--phone-host-safe-bottom', (Number.isFinite(inset) ? Math.max(0,inset) : 0)+'px');
            applyKeyboard(!!event.data.keyboardOpen);
        }
        else if (!embedded && event.source === document.getElementById('conversation-detail-frame')?.contentWindow && event.data?.type === 'ash-phone-focus') schedule();
    });
    document.addEventListener('DOMContentLoaded', () => {
        if (!embedded) document.body.classList.add('phone-viewport-standalone');
        // Match Merle's viewport policy on Safari; leave one-finger scrolling to each app.
        document.addEventListener('gesturestart', event => event.preventDefault(), {passive:false});
        schedule();
    });
    window.AshPhoneViewport = {refresh:schedule};
})();
