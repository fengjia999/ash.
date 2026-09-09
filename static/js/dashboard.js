function escHtml(str) {
    if (str == null) return "";
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}
function fmtTime(isoStr) {
    if (!isoStr) return "-";
    const d = new Date(isoStr);
    if (isNaN(d.getTime())) return isoStr;   // 解析失败返回原字符串
    const pad = n => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
function authFetch(url, options = {}) {
    const method = String(options.method || "GET").toUpperCase();
    const headers = new Headers(options.headers || {});
    if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
        headers.set("X-CSRF-Token", window.__MG_CSRF__ || "");
    }
    return fetch(url, {...options, headers}).then(resp => {
        if (resp.status === 401) window.location.assign("/login");
        return resp;
    });
}

async function logoutDashboard(event) {
    if (event) event.preventDefault();
    await authFetch("/auth/logout", {method: "POST"});
    window.location.assign("/login");
}

async function readJsonResponse(resp) {
    const text = await resp.text();
    if (!text) return {};
    try {
        return JSON.parse(text);
    } catch (e) {
        throw new Error(resp.ok ? "服务器返回了无效响应" : text.slice(0, 240));
    }
}

async function saveDashboardJson(url, options) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 30000);
    try {
        const response = await authFetch(url, {...options, signal: controller.signal});
        const data = await readJsonResponse(response);
        if (!response.ok || data.error) throw new Error(data.error || "HTTP " + response.status);
        return data;
    } catch (error) {
        if (controller.signal.aborted) {
            throw new Error("等待超过 30 秒，保存结果尚未确认，请刷新核对后再操作");
        }
        throw error;
    } finally {
        clearTimeout(timer);
    }
}

function byId(id) {
    return document.getElementById(id);
}

// ============================================
// 全局状态
// ============================================
let allMemories = [];
let pendingJsonData = null;
let standingBlocks = [];
let standingLoadGeneration = 0;
let longTermLoadGeneration = 0;
let standingOverview = {content: "", block_count: 0, character_count: 0};
let promptSplicePreview = null;
let standingEditingId = null;
const promotingFlowMemoryIds = new Set();
let memoryFragments = [];
let longTermMemories = [];
let longTermPending = [];
let longTermEditingId = null;
let longTermSelectionMode = false;
let longTermBatchDeleting = false;
const longTermSelectedIds = new Set();
let ltmSummaryDraft = "";
let longTermSummaryTarget = null;
const SUPPORTED_BACKUP_SCHEMA_VERSIONS = [2, 3, 4, 5, 6, 7, 8, 9];
let clearStoredOcrApiKey = false;
let openAiProviderProfiles = [];
const conversationFrameTimers = {list: null, detail: null};
let conversationActivationQueue = Promise.resolve();
let conversationActivationGeneration = 0;
const CONVERSATION_FRAME_TIMEOUT_MS = 15000;

// ============================================
// 类型配置
// ============================================
const TYPE_CONFIG = {
    factual: { icon: '🌟', label: 'factual - 事实/偏好/习惯', color: '#3B82F6' },
    episodic: { icon: '📖', label: 'episodic - 重要事件', color: '#8B5CF6' },
    diary: { icon: '💭', label: 'diary - 我的日记', color: '#EC4899' },
    quote: { icon: '💬', label: 'quote - 对话原话', color: '#F59E0B' },
    temp: { icon: '⏰', label: 'temp - 临时备忘', color: '#6B7280' },
};

// ============================================
// 初始化
// ============================================
document.addEventListener("DOMContentLoaded", () => {
    initNavigation();
    initTabs();
    initMemoryEditor();
    initLongTermMemoryEditor();
    initConversationFrames();
    loadConversationListFrame();
    const section = window.location.hash.slice(1);
    switchSection(section && document.getElementById("section-" + section) ? section : "conversations");
});

// ============================================
// 侧边栏导航
// ============================================
function initNavigation() {
    const navItems = document.querySelectorAll(".nav-item[data-section]");

    navItems.forEach(item => {
        item.addEventListener("click", (e) => {
            e.preventDefault();
            const section = item.dataset.section;
            switchSection(section);
        });
    });
}

function switchSection(name) {
    document.body?.classList.remove("history-open");
    document.querySelectorAll(".nav-item[data-section]").forEach(item => {
        const active = item.dataset.section === name;
        item.classList.toggle("active", active);
        if (active) item.setAttribute("aria-current", "page");
        else item.removeAttribute("aria-current");
    });
    document.querySelector(".mobile-history-toggle")?.setAttribute?.("aria-expanded", "false");

    document.querySelectorAll(".section").forEach(section => {
        section.classList.toggle("active", section.id === "section-" + name);
    });

    if (name === "export") {
        loadExportStats();
    }
    if (name === "manage") {
        loadMemories();
    }
    if (name === "standing") {
        loadStandingMemory();
        const view = document.querySelector("[data-standing-view].active")?.dataset.standingView;
        if (["fragments", "long-term"].includes(view)) loadLongTermMemory();
    }
    if (name === "quotes") {
        loadTokenUsage();
    }
    if (name === "heartbeats") {
        loadHeartbeatSettings();
        loadHeartbeatActivities();
    }
    if (name === "settings") {
        loadAnthropicCredential();
        loadRouteSettings();
        loadOpenAiProviders();
        loadConversationModelSettings();
        loadOcrSettings();
    }
    if (name === "prompts") {
        loadPromptConsoleFrame();
    }
    if (name === "conversations") {
        loadConversationListFrame();
    }
}

function loadPromptConsoleFrame() {
    const frame = byId("prompt-console-frame");
    if (frame && !frame.getAttribute("src")) {
        frame.src = "/prompt?embedded=dashboard";
    }
}

function toggleHistorySidebar() {
    const open = document.body.classList.toggle("history-open");
    document.querySelector(".mobile-history-toggle")?.setAttribute("aria-expanded", String(open));
}

function switchTo(section) {
    switchSection(section);
}

function loadConversationListFrame() {
    const frame = byId("conversation-list-frame");
    if (frame && !frame.getAttribute("src")) {
        setConversationFrameStatus("list", "loading", "正在加载会话…");
        frame.src = "/context?embedded=list";
    }
}

function initConversationFrames() {
    ["list", "detail"].forEach(mode => {
        const frame = byId(`conversation-${mode}-frame`);
        frame?.addEventListener("load", () => {
            try {
                if (frame.contentWindow?.location.pathname === "/login") {
                    window.location.assign("/login");
                }
            } catch (_) {
                // Same-origin pages are expected; the child ready message owns state.
            }
        });
    });
}

function setConversationFrameStatus(mode, state, message = "") {
    const status = byId(`conversation-${mode}-status`);
    const text = byId(`conversation-${mode}-status-text`);
    const retry = byId(`conversation-${mode}-retry`);
    if (!status || !text || !retry) return;
    if (conversationFrameTimers[mode]) {
        clearTimeout(conversationFrameTimers[mode]);
        conversationFrameTimers[mode] = null;
    }
    if (state === "ready") {
        status.hidden = true;
        return;
    }
    status.hidden = false;
    retry.hidden = state !== "error";
    text.textContent = message || (state === "error" ? "加载失败" : "正在加载…");
    if (state === "loading") {
        conversationFrameTimers[mode] = setTimeout(() => {
            setConversationFrameStatus(mode, "error", "加载时间过长，可以重试");
        }, CONVERSATION_FRAME_TIMEOUT_MS);
    }
}

function retryConversationFrame(mode) {
    if (mode === "list") {
        const frame = byId("conversation-list-frame");
        if (!frame) return;
        setConversationFrameStatus("list", "loading", "正在重新加载会话…");
        frame.src = "/context?embedded=list";
        return;
    }
    if (mode === "detail") {
        const frame = byId("conversation-detail-frame");
        const src = frame?.dataset.contextSrc;
        if (!frame || !src) return;
        setConversationFrameStatus("detail", "loading", "正在重新加载消息…");
        frame.src = src;
    }
}

function requestConversationActivation(conversationId) {
    const id = Number(conversationId);
    const frame = byId("conversation-detail-frame");
    if (!frame || !Number.isInteger(id) || id <= 0) return Promise.resolve();
    // Keep retries pointed at selections made inside the detail frame too.
    frame.dataset.conversationId = String(id);
    frame.dataset.contextSrc = "/context?" + new URLSearchParams({
        embedded: "detail",
        conversation_id: String(id),
    }).toString();
    const generation = ++conversationActivationGeneration;
    // This queue lives in the dashboard so navigating/unloading an iframe cannot
    // leave an old activation racing with the next selection.
    conversationActivationQueue = conversationActivationQueue.then(async () => {
        if (generation !== conversationActivationGeneration) return;
        const response = await authFetch(`/api/conversations/${id}/activate`, {method: "POST"});
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.error || "切换会话失败");
    }).catch(error => {
        console.error("激活会话失败：", error);
        if (generation === conversationActivationGeneration) {
            alert("切换会话失败：" + error.message + "，请重新选择会话");
        }
    });
    return conversationActivationQueue;
}

function openConversationDetail(conversationId, created = false) {
    const id = Number(conversationId);
    if (!Number.isInteger(id) || id <= 0) return;
    const layer = byId("conversation-detail-layer");
    const frame = byId("conversation-detail-frame");
    if (!layer || !frame) return;
    if (frame.contentWindow?.isChatBusy?.()) { alert("请等待回复完成，或先停止接收，再切换会话"); return; }
    document.querySelectorAll(".section").forEach(section => section.classList.toggle("active", section.id === "section-conversations"));
    document.querySelectorAll(".nav-item[data-section]").forEach(item => item.classList.toggle("active", item.dataset.section === "conversations"));
    document.body.classList.remove("history-open");
    document.querySelector(".mobile-history-toggle")?.setAttribute("aria-expanded", "false");
    const params = new URLSearchParams({
        embedded: "detail",
        conversation_id: String(id),
    });
    if (created) params.set("created", "1");
    const src = "/context?" + params.toString();
    frame.dataset.contextSrc = src;
    frame.dataset.conversationId = String(id);
    setConversationFrameStatus("detail", "loading", "正在加载消息…");
    frame.src = src;
    layer.classList.add("open");
    layer.setAttribute("aria-hidden", "false");
}

function closeConversationDetail() {
    const layer = byId("conversation-detail-layer");
    const frame = byId("conversation-detail-frame");
    if (frame?.contentWindow?.isChatBusy?.()) return;
    if (!layer || !layer.classList.contains("open")) return;
    layer.classList.remove("open");
    layer.setAttribute("aria-hidden", "true");
    document.body.classList.remove("conversation-detail-open");
    if (frame) {
        frame.removeAttribute("src");
        delete frame.dataset.contextSrc;
        delete frame.dataset.conversationId;
    }
    if (conversationFrameTimers.detail) {
        clearTimeout(conversationFrameTimers.detail);
        conversationFrameTimers.detail = null;
    }
    const listFrame = byId("conversation-list-frame");
    conversationActivationQueue.then(() => {
        listFrame?.contentWindow?.postMessage(
            {type: "memory-gateway-refresh-conversations"},
            window.location.origin,
        );
    });
}

window.addEventListener("message", event => {
    if (event.origin !== window.location.origin || !event.data) return;
    if (event.data.type === "memory-gateway-chat-updated") {
        byId("conversation-list-frame")?.contentWindow?.postMessage({type: "memory-gateway-refresh-conversations"}, window.location.origin);
    } else if (event.data.type === "memory-gateway-open-conversation") {
        openConversationDetail(event.data.conversationId, Boolean(event.data.created));
    } else if (event.data.type === "memory-gateway-close-conversation") {
        closeConversationDetail();
    } else if (event.data.type === "memory-gateway-context-status") {
        const mode = event.data.mode;
        if (mode !== "list" && mode !== "detail") return;
        if (mode === "detail") {
            const expected = Number(byId("conversation-detail-frame")?.dataset.conversationId || 0);
            const received = Number(event.data.conversationId || 0);
            if (expected && received && expected !== received) return;
        }
        setConversationFrameStatus(mode, event.data.status, event.data.message);
    }
});

document.addEventListener("keydown", event => {
    if (event.key === "Escape" && byId("conversation-detail-layer")?.classList.contains("open")) {
        closeConversationDetail();
    }
});

// ============================================
// Tab 切换：导入页面
// ============================================
function initTabs() {
    const tabs = document.querySelectorAll(".tab[data-tab]");

    tabs.forEach(tab => {
        tab.addEventListener("click", () => {
            const tabName = tab.dataset.tab;

            document.querySelectorAll(".tab[data-tab]").forEach(t => {
                t.classList.toggle("active", t.dataset.tab === tabName);
            });

            document.querySelectorAll(".tab-panel").forEach(panel => {
                panel.classList.toggle("active", panel.id === "tab-" + tabName);
            });

            clearImportResult();
        });
    });

    [["jsonFile", "jsonFileName"], ["txtFile", "txtFileName"]].forEach(([inputId, labelId]) => {
        const input = byId(inputId);
        const label = byId(labelId);
        input?.addEventListener("change", () => {
            if (label && input.files?.[0]) label.textContent = input.files[0].name;
        });
    });
}

// ============================================
// 旧记忆碎片录（只读）
// ============================================
function setFragmentLedgerVisibility(hasFragments) {
    const nav = document.querySelector('.nav-item[data-section="manage"]');
    const section = byId("section-manage");
    if (nav) nav.hidden = !hasFragments;
    if (section) section.hidden = !hasFragments;
    if (!hasFragments && section?.classList.contains("active")) {
        switchSection("standing");
    }
}

function fragmentDateParts(value) {
    const formatted = fmtTime(value);
    if (!formatted || formatted === "-") {
        return {month: "unknown", day: "—", clock: ""};
    }
    return {
        month: formatted.slice(0, 7),
        day: formatted.slice(8, 10),
        clock: formatted.slice(11, 16),
    };
}

function fragmentMonthLabel(month) {
    if (month === "unknown") return "未注明日期";
    const [year, number] = month.split("-");
    return `${year}年${Number(number)}月`;
}

function fragmentTypeLabel(type) {
    const config = TYPE_CONFIG[type] || {icon: "✦", label: type || "碎片"};
    const parts = String(config.label || "").split(" - ");
    return {icon: config.icon || "✦", label: parts[1] || parts[0] || "碎片"};
}

function renderFragmentLedger(memories) {
    const container = byId("memorySections");
    if (!container) return;

    const sorted = Array.from(memories).sort((a, b) => {
        const aTime = new Date(a.created_at || 0).getTime() || 0;
        const bTime = new Date(b.created_at || 0).getTime() || 0;
        return bTime - aTime || (Number(b.id) || 0) - (Number(a.id) || 0);
    });
    const grouped = new Map();
    sorted.forEach(memory => {
        const date = fragmentDateParts(memory.created_at);
        if (!grouped.has(date.month)) grouped.set(date.month, []);
        grouped.get(date.month).push({memory, date});
    });

    container.innerHTML = Array.from(grouped.entries()).map(([month, entries]) => `
        <section class="fragment-month">
            <div class="fragment-month-heading">
                <span>${escHtml(fragmentMonthLabel(month))}</span>
                <i></i>
            </div>
            <div class="fragment-month-pages">
                ${entries.map(({memory, date}) => {
                    const type = String(memory.type || "factual");
                    const typeInfo = fragmentTypeLabel(type);
                    const source = String(memory.source_session || "").trim();
                    const importance = Number(memory.importance);
                    const tags = Array.isArray(memory.tags) ? memory.tags : [];
                    return `
                        <article class="fragment-entry" data-type="${escHtml(type)}">
                            <time class="fragment-entry-date">
                                <strong>${escHtml(date.day)}</strong>
                                <span>${escHtml(date.clock)}</span>
                            </time>
                            <div class="fragment-entry-paper">
                                <p>${escHtml(memory.content || "")}</p>
                                <footer>
                                    <span class="fragment-kind">${typeInfo.icon} ${escHtml(typeInfo.label)}</span>
                                    ${source ? `<span>${escHtml(source)}</span>` : ""}
                                    ${Number.isFinite(importance) ? `<span>记忆度 ${importance}</span>` : ""}
                                    ${tags.map(tag => `<span class="fragment-tag">#${escHtml(tag)}</span>`).join("")}
                                </footer>
                            </div>
                        </article>
                    `;
                }).join("")}
            </div>
        </section>
    `).join("");
}

async function loadMemories() {
    try {
        const resp = await authFetch("/api/memories");
        const data = await readJsonResponse(resp);
        if (!resp.ok || data.error) {
            throw new Error(data.error || "HTTP " + resp.status);
        }

        allMemories = Array.isArray(data.memories) ? data.memories : [];
        setFragmentLedgerVisibility(allMemories.length > 0);
        const stats = byId("stats");
        if (stats) stats.textContent = allMemories.length + " 枚旧记忆";
        renderFragmentLedger(allMemories);
    } catch (e) {
        const container = byId("memorySections");
        if (container && !container.innerHTML) {
            container.innerHTML = '<div class="memory-card-empty">载入失败</div>';
        }
    }
}

function showMsg(containerId, text, type) {
    const container = byId(containerId);
    if (!container) return;

    container.innerHTML = '<div class="msg msg-' + escHtml(type) + '">' + escHtml(text) + '</div>';
    setTimeout(() => {
        container.innerHTML = "";
    }, 4000);
}

// ============================================
// 导入功能
// ============================================
async function doTextImport() {
    const fileEl = byId("txtFile");
    const textEl = byId("txtInput");
    const skipEl = byId("skipScore");

    const file = fileEl && fileEl.files ? fileEl.files[0] : null;
    const text = textEl ? textEl.value.trim() : "";
    const skip = skipEl ? skipEl.checked : false;

    let content = "";

    if (file) {
        content = await file.text();
    } else if (text) {
        content = text;
    } else {
        showImportResult("error", "请先上传文件或输入文本");
        return;
    }

    const lines = content
        .split(/\r?\n/)
        .map(l => l.trim())
        .filter(l => l.length > 0);

    if (lines.length === 0) {
        showImportResult("error", "没有找到有效的记忆条目");
        return;
    }

    showImportResult(
        "info",
        skip
            ? "正在导入 " + lines.length + " 条记忆..."
            : "正在为 " + lines.length + " 条记忆自动评分，请稍候..."
    );

    try {
        const resp = await authFetch("/import/text", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
                lines,
                skip_scoring: skip
            })
        });

        const data = await resp.json();

        if (!resp.ok || data.error) {
            throw new Error(data.error || "HTTP " + resp.status);
        }

        showImportResult(
            "success",
            "✅ 导入完成！新增 " + data.imported + " 条，跳过 " + data.skipped + " 条（已存在），总计 " + data.total + " 条"
        );

        await loadMemories();
    } catch (e) {
        showImportResult("error", "❌ 请求失败：" + e.message);
    }
}

async function previewJson() {
    const fileEl = byId("jsonFile");
    const textEl = byId("jsonInput");
    const preview = byId("jsonPreview");

    if (!preview) return;

    const file = fileEl && fileEl.files ? fileEl.files[0] : null;
    const text = textEl ? textEl.value.trim() : "";

    let jsonStr = "";

    if (file) {
        jsonStr = await file.text();
    } else if (text) {
        jsonStr = text;
    } else {
        showImportResult("error", "请先上传文件或粘贴 JSON");
        return;
    }

    try {
        const parsed = JSON.parse(jsonStr);
        const mems = Array.isArray(parsed.memories) ? parsed.memories : [];
        const isBackupPayload = parsed.kind === "memory_gateway_backup";
        if (isBackupPayload
            && !SUPPORTED_BACKUP_SCHEMA_VERSIONS.includes(parsed.schema_version)) {
            showImportResult(
                "error",
                "❌ 不支持的完整备份版本：" + String(parsed.schema_version ?? "未知")
            );
            resetJsonPreview();
            return;
        }
        const isFullBackup = isBackupPayload;

        if (!isFullBackup && mems.length === 0) {
            showImportResult("error", "❌ 没有找到 memories 字段，请确认这是从导出功能导出的文件");
            resetJsonPreview();
            return;
        }

        pendingJsonData = parsed;

        let html = "";
        if (isFullBackup) {
            const standing = Array.isArray(parsed.standing_memory_blocks) ? parsed.standing_memory_blocks.length : 0;
            const longTerm = Array.isArray(parsed.long_term_memories) ? parsed.long_term_memories.length : 0;
            const longTermPendingCount = Array.isArray(parsed.long_term_memory_proposals)
                ? parsed.long_term_memory_proposals.length
                : 0;
            const conversations = Array.isArray(parsed.conversations) ? parsed.conversations.length : 0;
            const messages = Array.isArray(parsed.context_messages) ? parsed.context_messages.length : 0;
            const prompts = Array.isArray(parsed.prompt_sections) ? parsed.prompt_sections.length : 0;
            const extractionJobs = Array.isArray(parsed.memory_extraction_jobs) ? parsed.memory_extraction_jobs.length : 0;
            const forgettingPending = Array.isArray(parsed.fragment_forgetting_pending) ? parsed.fragment_forgetting_pending.length : 0;
            const summaries = Array.isArray(parsed.conversations)
                ? parsed.conversations.reduce(
                    (count, conversation) => count
                        + (conversation.handoff_draft ? 1 : 0)
                        + (conversation.handoff_summary ? 1 : 0),
                    0
                )
                : 0;
            html += '<p><b>完整备份</b></p>';
            html += '<div class="preview-item">记忆条目 ' + standing
                + ' 条 · 日记 ' + longTerm + ' 篇 · 日记 Pending '
                + longTermPendingCount + ' 条</div>';
            html += '<div class="preview-item">会话 ' + conversations + ' 个 · 消息 ' + messages + ' 条</div>';
            html += '<div class="preview-item">提示词 ' + prompts + ' 段 · 提取任务 '
                + extractionJobs + ' 个 · 待遗忘 ' + forgettingPending + ' 条</div>';
            html += '<div class="preview-item">交接摘要 ' + summaries + ' 份 · 旧碎片 ' + mems.length + ' 条</div>';
            html += '<div class="preview-item" style="color:var(--rust);">恢复会覆盖当前记忆条目、日记和会话</div>';
        } else {
            html += '<p><b>预览：共 ' + mems.length + ' 条旧碎片</b></p>';
            const show = mems.slice(0, 10);

            show.forEach(m => {
                const importance = escHtml(m.importance || "?");
                const content = escHtml((m.content || "").substring(0, 80));
                html += '<div class="preview-item">权重 ' + importance + ' | ' + content + '</div>';
            });

            if (mems.length > 10) {
                html += '<div class="preview-item" style="color:#999;">...还有 ' + (mems.length - 10) + ' 条</div>';
            }
        }

        html += '<br><button type="button" class="btn btn-primary" onclick="confirmJsonImport()">'
            + (isFullBackup ? "确认恢复" : "确认导入") + '</button>';
        preview.innerHTML = html;
        preview.classList.add("visible");

        clearImportMessage();
    } catch (e) {
        showImportResult("error", "❌ JSON 格式错误：" + e.message);
        resetJsonPreview();
    }
}

async function confirmJsonImport() {
    if (!pendingJsonData) {
        showImportResult("error", "请先预览");
        return;
    }

    const isFullBackup = pendingJsonData.kind === "memory_gateway_backup";
    if (isFullBackup && !window.confirm("完整恢复会覆盖当前提示词、记忆、后台任务和全部会话。确认继续吗？")) {
        return;
    }

    showImportResult("info", isFullBackup ? "恢复中..." : "导入中...");

    try {
        const resp = await authFetch("/import/memories", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(pendingJsonData)
        });

        const data = await resp.json();

        if (!resp.ok || data.error) {
            throw new Error(data.error || "HTTP " + resp.status);
        }

        if (data.kind === "memory_gateway_backup") {
            const restored = data.restored || {};
            showImportResult(
                "success",
                "✅ 恢复完成！记忆条目 " + (restored.standing_memory_blocks || 0)
                    + " 条，日记 " + (restored.long_term_memories || 0)
                    + " 条，长期 Pending " + (restored.long_term_memory_proposals || 0)
                    + " 条，会话 " + (restored.conversations || 0)
                    + " 个，消息 " + (restored.context_messages || 0) + " 条"
            );
        } else {
            showImportResult(
                "success",
                "✅ 导入完成！新增 " + data.imported + " 条，跳过 " + data.skipped + " 条（已存在），总计 " + data.total + " 条"
            );
        }

        resetJsonPreview();
        await loadMemories();
    } catch (e) {
        showImportResult("error", "❌ 请求失败：" + e.message);
    }
}

function showImportResult(type, text) {
    const container = byId("import-result");
    if (!container) return;

    container.innerHTML = '<div class="msg msg-' + escHtml(type) + '">' + escHtml(text) + '</div>';
}

function clearImportMessage() {
    const container = byId("import-result");
    if (container) {
        container.innerHTML = "";
    }
}

function resetJsonPreview() {
    const preview = byId("jsonPreview");
    if (preview) {
        preview.innerHTML = "";
        preview.classList.remove("visible");
    }
    pendingJsonData = null;
}

function clearImportResult() {
    clearImportMessage();
    resetJsonPreview();
}

// ============================================
// 导出功能
// ============================================
async function loadExportStats() {
    const el = byId("export-stats");
    if (!el) return;

    try {
        const [standingResp, conversationsResp] = await Promise.all([
            authFetch("/api/standing-memory"),
            authFetch("/api/conversations?include_stats=true")
        ]);
        const [standingData, conversationsData] = await Promise.all([
            standingResp.json(),
            conversationsResp.json()
        ]);

        if (!standingResp.ok || standingData.error) {
            throw new Error(standingData.error || "HTTP " + standingResp.status);
        }
        if (!conversationsResp.ok || conversationsData.error) {
            throw new Error(conversationsData.error || "HTTP " + conversationsResp.status);
        }

        const standingCount = Array.isArray(standingData.blocks) ? standingData.blocks.length : 0;
        const longTermCount = Number((standingData.overview || {}).diary_count) || 0;
        const conversations = Array.isArray(conversationsData.conversations)
            ? conversationsData.conversations
            : [];
        const messageCount = conversations.reduce(
            (sum, conversation) => sum + (Number(conversation.message_count) || 0),
            0
        );
        el.textContent = "记忆条目 " + standingCount + " 条 · 日记 "
            + longTermCount + " 篇 · 会话 "
            + conversations.length + " 个 · 消息 " + messageCount + " 条";
    } catch (e) {
        el.textContent = "无法加载统计";
    }
}

function doExport() {
    window.location.assign("/export/memories");
}

// ============================================
// 记忆
// ============================================
async function loadStandingMemory() {
    const generation = ++standingLoadGeneration;
    try {
        const standingResp = await authFetch("/api/standing-memory?include_overview_content=false");
        const data = await standingResp.json();
        if (!standingResp.ok || data.error) {
            throw new Error(data.error || "HTTP " + standingResp.status);
        }
        if (generation !== standingLoadGeneration) return;
        standingBlocks = Array.isArray(data.blocks) ? data.blocks : [];
        standingOverview = data.overview && typeof data.overview === "object"
            ? data.overview
            : {content: "", block_count: 0, character_count: 0};
        renderStandingStats();
        renderStandingLists();
    } catch (e) {
        if (generation !== standingLoadGeneration) return;
        showStandingMsg("error", "加载记忆失败：" + e.message);
    }
}

function renderStandingStats() {
    const stats = byId("standing-stats");
    if (!stats) return;
    const active = standingBlocks.filter(b => b.status === "active").length;
    const pending = standingBlocks.filter(b => b.status === "pending").length;
    stats.textContent = active + " 条记忆，" + pending + " 个常驻 pending，"
        + (Number(standingOverview.fragment_count) || 0) + " 条碎片记忆，"
        + (Number(standingOverview.diary_count) || 0) + " 篇日记，"
        + (Number(standingOverview.diary_pending_count) || 0) + " 个日记 pending 请求";
}

function switchStandingView(name) {
    const viewName = ["directory", "fragments", "long-term"].includes(name)
        ? name
        : "directory";
    document.querySelectorAll("[data-standing-view]").forEach(button => {
        button.classList.toggle("active", button.dataset.standingView === viewName);
    });
    document.querySelectorAll(".standing-view").forEach(view => {
        view.classList.toggle("active", view.id === "standing-view-" + viewName);
    });
    if (["fragments", "long-term"].includes(viewName)) loadLongTermMemory();
}

async function loadLongTermMemory() {
    const generation = ++longTermLoadGeneration;
    try {
        const resp = await authFetch("/api/diaries");
        const data = await readJsonResponse(resp);
        if (!resp.ok || data.error) {
            throw new Error(data.error || "HTTP " + resp.status);
        }
        if (generation !== longTermLoadGeneration) return;
        memoryFragments = Array.isArray(data.fragments) ? data.fragments : [];
        longTermMemories = Array.isArray(data.diaries) ? data.diaries : [];
        longTermPending = Array.isArray(data.pending) ? data.pending : [];
        const availableIds = new Set(longTermMemories.map(memory => Number(memory.id)));
        [...longTermSelectedIds].forEach(id => {
            if (!availableIds.has(id)) longTermSelectedIds.delete(id);
        });
        renderLongTermMemories();
        renderMemoryFragments();
        loadMemoryExtractionStatus();
        loadFragmentForgetting();
        renderPendingLongTermMemories();
    } catch (e) {
        if (generation !== longTermLoadGeneration) return;
        showLongTermMsg("error", "加载日记失败：" + e.message);
    }
}

function applySavedDiary(diary) {
    ++longTermLoadGeneration;
    const index = longTermMemories.findIndex(item => Number(item.id) === Number(diary.id));
    if (index < 0) {
        longTermMemories.push(diary);
        standingOverview.diary_count = (Number(standingOverview.diary_count) || 0) + 1;
    } else longTermMemories[index] = diary;
    renderStandingStats();
    renderLongTermMemories();
    renderPendingLongTermMemories();
}

function renderMemoryFragments() {
    const list = byId("memory-fragment-list");
    const count = byId("memory-fragment-count");
    if (count) count.textContent = memoryFragments.length + " 条";
    if (!list) return;
    if (!memoryFragments.length) {
        list.innerHTML = '<div class="standing-empty">还没有归档的碎片记忆</div>';
        return;
    }
    const ordered = [...memoryFragments].sort((left, right) => Number(right.id) - Number(left.id));
    list.innerHTML = ordered.map(memory => {
        const memoryId = Number(memory.id);
        const content = String(memory.content || "").trim();
        const anchors = Array.isArray(memory.anchors) ? memory.anchors : [];
        const evidence = anchors.length
            ? '<details><summary>原话来源</summary>' + anchors.map(anchor =>
                '<blockquote>' + escHtml(anchor.quote) + '</blockquote><small>' +
                escHtml(anchor.role === 'user' ? '用户' : '助手') + ' · 会话 #' +
                escHtml(anchor.conversation_id) + ' · 消息 #' + escHtml(anchor.message_id) + '</small>'
              ).join('') + '</details>'
            : '<small>旧记录：暂无原话锚点</small>';
        return (
            '<article class="long-term-memory-card memory-fragment-card">' +
                '<div class="memory-fragment-content">' + escHtml(content || "空碎片") + evidence + '</div>' +
                '<button type="button" class="kelivo-icon-btn delete" title="删除" onclick="deleteMemoryFragment(' + memoryId + ')">删除</button>' +
            '</article>'
        );
    }).join("");
}

async function loadMemoryExtractionStatus() {
    const node = byId('memory-extraction-status');
    if (!node) return;
    try {
        const response = await authFetch('/api/memory-extraction/jobs');
        const data = await readJsonResponse(response);
        if (!response.ok || data.error) throw new Error('无法加载');
        const labels = {pending: '等待提取', running: '正在提取', completed: '提取完成', failed: '提取失败，请检查提取模型配置'};
        node.textContent = (data.jobs || []).slice(0, 3).map(job =>
            '会话 #' + job.source_conversation_id + '：' + (labels[job.status] || job.status)
        ).join(' · ');
    } catch (error) {
        node.textContent = '暂时无法读取后台提取状态';
    }
}

async function loadFragmentForgetting() {
    const node = byId('fragment-forgetting-list');
    if (!node) return;
    try {
        const response = await authFetch('/api/fragments/forgetting');
        const data = await readJsonResponse(response);
        if (!response.ok || data.error) throw new Error(data.error || '加载失败');
        node.innerHTML = (data.pending || []).map(item =>
            '<article class="memory-fragment-card long-term-memory-card"><div class="memory-fragment-content">' +
            escHtml(item.content) + (item.anchors || []).map(anchor =>
                '<blockquote>' + escHtml(anchor.quote) + '</blockquote><small>会话 #' +
                escHtml(anchor.conversation_id) + ' · 消息 #' + escHtml(anchor.message_id) + '</small>'
            ).join('') + '</div><button class="btn btn-secondary" onclick="resolveFragmentForgetting(' +
            Number(item.id) + ',false,this)">保留</button><button class="btn btn-danger" onclick="resolveFragmentForgetting(' +
            Number(item.id) + ',true,this)">确认遗忘</button></article>'
        ).join('') || '<p class="credential-help">暂无待遗忘碎片</p>';
    } catch (error) {
        node.textContent = '加载待遗忘失败：' + error.message;
    }
}

async function resolveFragmentForgetting(id, forget, button) {
    button.disabled = true;
    try {
        const response = await authFetch('/api/fragments/' + id + '/forgetting/' + (forget ? 'approve' : 'retain'), {method: 'POST'});
        const data = await readJsonResponse(response);
        if (!response.ok || data.error) throw new Error(data.error || '处理失败');
        await loadLongTermMemory();
    } catch (error) {
        showLongTermMsg('error', error.message);
    } finally {
        button.disabled = false;
    }
}

async function deleteMemoryFragment(id) {
    if (!confirm("确定删除碎片记忆 #" + id + "？")) return;
    try {
        const resp = await authFetch("/api/diaries/" + id, {method: "DELETE"});
        const data = await readJsonResponse(resp);
        if (!resp.ok || data.error) throw new Error(data.error || "HTTP " + resp.status);
        await Promise.all([loadLongTermMemory(), loadStandingMemory()]);
    } catch (e) {
        showLongTermMsg("error", "删除碎片记忆失败：" + e.message);
    }
}

function pendingInlineDiff(beforeValue, afterValue) {
    const before = Array.from(String(beforeValue == null ? "" : beforeValue));
    const after = Array.from(String(afterValue == null ? "" : afterValue));
    let prefix = 0;
    while (prefix < before.length && prefix < after.length && before[prefix] === after[prefix]) {
        prefix += 1;
    }
    let suffix = 0;
    while (
        suffix < before.length - prefix &&
        suffix < after.length - prefix &&
        before[before.length - 1 - suffix] === after[after.length - 1 - suffix]
    ) {
        suffix += 1;
    }
    const commonStart = before.slice(0, prefix).join("");
    const commonEnd = suffix ? before.slice(before.length - suffix).join("") : "";
    const removed = before.slice(prefix, before.length - suffix).join("");
    const added = after.slice(prefix, after.length - suffix).join("");
    return {
        before: escHtml(commonStart) +
            (removed ? '<del class="pending-diff-removed">' + escHtml(removed) + '</del>' : "") +
            escHtml(commonEnd),
        after: escHtml(commonStart) +
            (added ? '<mark class="pending-diff-added">' + escHtml(added) + '</mark>' : "") +
            escHtml(commonEnd),
    };
}

function renderPendingFieldDiff(label, beforeValue, afterValue, operation) {
    const before = String(beforeValue == null ? "" : beforeValue);
    const after = String(afterValue == null ? "" : afterValue);
    if (operation === "edit" && before === after) return "";
    if (operation === "create" && !after) return "";
    if (operation === "delete" && !before) return "";
    let body = "";
    if (operation === "create") {
        body = '<div class="pending-diff-line is-new"><span>新增</span><mark class="pending-diff-added">' +
            escHtml(after || "（空）") + '</mark></div>';
    } else if (operation === "delete") {
        body = '<div class="pending-diff-line is-old"><span>删除</span><del class="pending-diff-removed">' +
            escHtml(before || "（空）") + '</del></div>';
    } else {
        const diff = pendingInlineDiff(before, after);
        body = '<div class="pending-diff-line is-old"><span>原</span><div>' +
            (diff.before || '<span class="pending-diff-empty">（空）</span>') + '</div></div>' +
            '<div class="pending-diff-line is-new"><span>新</span><div>' +
            (diff.after || '<span class="pending-diff-empty">（空）</span>') + '</div></div>';
    }
    return '<section class="pending-diff-field"><div class="pending-diff-label">' +
        escHtml(label) + '</div>' + body + '</section>';
}

function renderLongTermPendingDiff(proposal, operation, target) {
    const proposalSummary = String(
        proposal.summary || normalizeLongTermKeywords(proposal.keywords).join("；")
    );
    const targetSummary = target
        ? String(target.summary || normalizeLongTermKeywords(target.keywords).join("；"))
        : "";
    const fields = [
        ["标题", target && target.title, proposal.title],
        ["日期", target && target.diary_date, proposal.diary_date],
        ["关键词", target && normalizeLongTermKeywords(target.keywords).join("、"),
            normalizeLongTermKeywords(proposal.keywords).join("、")],
        ["摘要", targetSummary, proposalSummary],
        ["正文", target && target.content, proposal.content],
    ];
    const html = fields.map(field => renderPendingFieldDiff(
        field[0], field[1], field[2], operation
    )).join("");
    return html || '<div class="pending-diff-empty">没有检测到字段变化</div>';
}

function renderPendingLongTermMemories() {
    const section = byId("long-term-pending-section");
    const list = byId("long-term-pending-list");
    const count = byId("long-term-pending-count");
    if (count) count.textContent = longTermPending.length + " 条";
    if (section) section.style.display = longTermPending.length ? "" : "none";
    if (!list) return;
    list.innerHTML = longTermPending.map(proposal => {
        const id = Number(proposal.id);
        const targetId = Number(proposal.target_diary_id || 0);
        const operation = String(proposal.operation || "create");
        const operationLabel = operation === "edit"
            ? "修改 #" + targetId
            : (operation === "delete" ? "删除 #" + targetId : "创建日记");
        const target = targetId
            ? longTermMemories.find(memory => Number(memory.id) === targetId)
            : null;
        const diffHtml = renderLongTermPendingDiff(proposal, operation, target);
        return (
            '<article class="pending-memory-card long-term-pending-card">' +
                '<div class="pending-memory-head">' +
                    '<span class="standing-tag status">' + escHtml(operationLabel) + '</span>' +
                    '<div class="row-actions">' +
                        '<button type="button" class="btn btn-primary btn-sm" onclick="approveLongTermMemoryProposal(' + id + ')">通过</button>' +
                        '<button type="button" class="btn btn-danger btn-sm" onclick="rejectLongTermMemoryProposal(' + id + ')">拒绝</button>' +
                    '</div>' +
                '</div>' +
                '<div class="pending-memory-diff">' + diffHtml + '</div>' +
            '</article>'
        );
    }).join("");
}

function normalizeLongTermKeywords(value) {
    const raw = Array.isArray(value) ? value : String(value || "").split(/[,，、\n]+/);
    const seen = new Set();
    return raw.map(item => String(item || "").trim()).filter(item => {
        if (!item || seen.has(item)) return false;
        seen.add(item);
        return true;
    });
}

function parseLongTermKeywords(value) {
    return normalizeLongTermKeywords(String(value || "").split(/[\n,，、;；]+/));
}

function localDateInputValue(date = new Date()) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");
    return year + "-" + month + "-" + day;
}

function longTermMemoryDate(memory) {
    const stored = String((memory && memory.diary_date) || "").slice(0, 10);
    if (/^\d{4}-\d{2}-\d{2}$/.test(stored)) return stored;
    const titleMatch = String((memory && memory.title) || "").match(/(?:^|\D)(\d{4}-\d{2}-\d{2})(?:\D|$)/);
    return titleMatch ? titleMatch[1] : "";
}

function longTermDateParts(value) {
    const match = String(value || "").match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (!match) return null;
    const year = Number(match[1]);
    const month = Number(match[2]);
    const day = Number(match[3]);
    const date = new Date(year, month - 1, day);
    if (
        date.getFullYear() !== year
        || date.getMonth() !== month - 1
        || date.getDate() !== day
    ) return null;
    return {
        year,
        month,
        day,
        weekday: ["周日", "周一", "周二", "周三", "周四", "周五", "周六"][date.getDay()],
    };
}

function compareLongTermMemoriesNewestFirst(left, right) {
    const leftDate = longTermMemoryDate(left);
    const rightDate = longTermMemoryDate(right);
    if (leftDate && rightDate) {
        return rightDate.localeCompare(leftDate) || Number(right.id) - Number(left.id);
    }
    if (leftDate) return -1;
    if (rightDate) return 1;
    return Number(right.id) - Number(left.id);
}

function renderLongTermMemories() {
    const list = byId("long-term-list");
    const count = byId("long-term-count");
    const missingKeywordCount = longTermMemories.filter(memory =>
        normalizeLongTermKeywords(memory.keywords).length === 0
    ).length;
    if (count) {
        count.textContent = longTermMemories.length + " 篇" +
            (missingKeywordCount ? " · " + missingKeywordCount + " 篇待关键词" : "");
    }
    updateLongTermSelectionControls();
    if (!list) return;
    if (!longTermMemories.length) {
        list.innerHTML = '<div class="standing-empty">还没有写下任何一页</div>';
        return;
    }

    const ordered = [...longTermMemories].sort(compareLongTermMemoriesNewestFirst);
    const groups = new Map();
    ordered.forEach(memory => {
        const parts = longTermDateParts(longTermMemoryDate(memory));
        const key = parts ? `${parts.year}-${String(parts.month).padStart(2, "0")}` : "undated";
        if (!groups.has(key)) groups.set(key, {parts, memories: []});
        groups.get(key).memories.push(memory);
    });

    list.innerHTML = [...groups.values()].map(group => {
        const monthLabel = group.parts
            ? `${group.parts.year} · ${String(group.parts.month).padStart(2, "0")}`
            : "未标日期";
        const entries = group.memories.map(memory => {
        const keywords = normalizeLongTermKeywords(memory.keywords);
        const summaryHtml = keywords.length
            ? '<span class="long-term-summary-preview">' + escHtml(keywords.map(value => "#" + value).join(" ")) + '</span>'
            : "";
        const dateValue = longTermMemoryDate(memory);
        const dateParts = longTermDateParts(dateValue);
        const dateHtml = dateParts
            ? '<time class="long-term-memory-date" datetime="' + escHtml(dateValue) + '">' +
                '<strong>' + String(dateParts.day).padStart(2, "0") + '</strong>' +
                '<span>' + dateParts.weekday + '</span>' +
              '</time>'
            : '<span class="long-term-memory-date is-empty"><strong>—</strong><span>未标注</span></span>';
        const memoryId = Number(memory.id);
        const selected = longTermSelectedIds.has(memoryId);
        const selectionControl = longTermSelectionMode
            ? '<input type="checkbox" class="long-term-memory-checkbox" aria-label="选择日记 ' +
                escHtml(memory.title || ("#" + memoryId)) + '" ' + (selected ? "checked" : "") +
                ' onclick="event.stopPropagation()" onchange="toggleLongTermMemorySelection(' + memoryId + ')">'
            : "";
        const itemActions = longTermSelectionMode ? "" : (
            '<button type="button" class="long-term-summary-button" onclick="openLongTermSummaryEditor(' + memoryId + ')">关键词</button>' +
            '<button type="button" class="kelivo-icon-btn delete" aria-label="删除日记" title="删除" onclick="deleteLongTermMemory(' + memoryId + ')">' +
                '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">' +
                    '<path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v5M14 11v5"/>' +
                '</svg>' +
            '</button>'
        );
        return (
            '<article class="long-term-memory-card' + (longTermSelectionMode ? ' is-selecting' : '') + (selected ? ' is-selected' : '') + '">' +
                selectionControl +
                '<button type="button" class="long-term-memory-main" onclick="handleLongTermMemoryCardClick(' + memoryId + ')">' +
                    dateHtml +
                    '<span class="long-term-memory-copy">' +
                        '<span class="long-term-memory-title">' + escHtml(memory.title || "未命名") + '</span>' +
                        summaryHtml +
                    '</span>' +
                '</button>' +
                itemActions +
            '</article>'
        );
        }).join("");
        return (
            '<section class="long-term-month">' +
                '<div class="long-term-month-label"><span>' + monthLabel + '</span><i></i></div>' +
                '<div class="long-term-month-entries">' + entries + '</div>' +
            '</section>'
        );
    }).join("");
}

function updateLongTermSelectionControls() {
    const toolbar = byId("long-term-selection-toolbar");
    const toggle = byId("long-term-select-toggle");
    const count = byId("long-term-selection-count");
    const selectAll = byId("long-term-select-all");
    const deleteButton = byId("long-term-delete-selected");
    const selectedCount = longTermSelectedIds.size;
    const allSelected = longTermMemories.length > 0
        && selectedCount === longTermMemories.length;
    if (toolbar) toolbar.hidden = !longTermSelectionMode;
    if (toggle) {
        toggle.classList.toggle("active", longTermSelectionMode);
        const label = toggle.querySelector("span");
        if (label) label.textContent = longTermSelectionMode ? "完成" : "多选";
    }
    if (count) count.textContent = "已选 " + selectedCount + " 条";
    if (selectAll) {
        selectAll.textContent = allSelected ? "取消全选" : "全选";
        selectAll.disabled = !longTermMemories.length || longTermBatchDeleting;
    }
    if (deleteButton) {
        deleteButton.textContent = longTermBatchDeleting ? "删除中…" : "删除所选";
        deleteButton.disabled = !selectedCount || longTermBatchDeleting;
    }
}

function toggleLongTermSelectionMode(force) {
    longTermSelectionMode = typeof force === "boolean" ? force : !longTermSelectionMode;
    if (!longTermSelectionMode) longTermSelectedIds.clear();
    renderLongTermMemories();
}

function handleLongTermMemoryCardClick(id) {
    if (longTermSelectionMode) {
        toggleLongTermMemorySelection(id);
        return;
    }
    openLongTermMemoryEditor(id);
}

function toggleLongTermMemorySelection(id) {
    const numericId = Number(id);
    if (!Number.isInteger(numericId) || numericId <= 0) return;
    if (longTermSelectedIds.has(numericId)) {
        longTermSelectedIds.delete(numericId);
    } else {
        longTermSelectedIds.add(numericId);
    }
    renderLongTermMemories();
}

function toggleSelectAllLongTermMemories() {
    const allSelected = longTermMemories.length > 0
        && longTermSelectedIds.size === longTermMemories.length;
    longTermSelectedIds.clear();
    if (!allSelected) {
        longTermMemories.forEach(memory => longTermSelectedIds.add(Number(memory.id)));
    }
    renderLongTermMemories();
}

function renderLongTermSummaryPreview() {
    const preview = byId("long-term-memory-summary-preview");
    if (!preview) return;
    const rendered = parseLongTermKeywords(ltmSummaryDraft).map(value => "#" + value).join(" ");
    preview.textContent = rendered;
    preview.title = rendered;
}

async function openLongTermSummaryEditor(id) {
    const numericId = Number(id || 0);
    let memory = null;
    if (numericId > 0) {
        try {
            const resp = await authFetch("/api/diaries/" + numericId);
            const data = await readJsonResponse(resp);
            if (!resp.ok || data.error) throw new Error(data.error || "HTTP " + resp.status);
            memory = data;
        } catch (e) {
            showLongTermMsg("error", "读取日记失败：" + e.message);
            return;
        }
    } else {
        memory = {
            id: 0,
            title: (byId("long-term-memory-title") || {}).value || "",
            content: (byId("long-term-memory-content") || {}).value || "",
            diary_date: (byId("long-term-memory-date") || {}).value || "",
            keywords: parseLongTermKeywords(ltmSummaryDraft),
        };
    }
    longTermSummaryTarget = memory;
    const status = byId("long-term-summary-msg");
    if (status) status.textContent = "";
    byId("long-term-summary-content").value = normalizeLongTermKeywords(memory.keywords).join("\n");
    const modal = byId("long-term-summary-modal");
    modal.classList.add("open");
    modal.setAttribute("aria-hidden", "false");
    requestAnimationFrame(() => byId("long-term-summary-content").focus());
}

function closeLongTermSummaryEditor() {
    const modal = byId("long-term-summary-modal");
    if (modal) {
        modal.classList.remove("open");
        modal.setAttribute("aria-hidden", "true");
    }
    const status = byId("long-term-summary-msg");
    if (status) status.textContent = "";
    longTermSummaryTarget = null;
}

async function saveLongTermSummary() {
    const target = longTermSummaryTarget || {};
    const keywords = parseLongTermKeywords(byId("long-term-summary-content").value);
    ltmSummaryDraft = keywords.join("\n");
    renderLongTermSummaryPreview();
    const editingCurrent = Number(longTermEditingId || 0) === Number(target.id || 0)
        && byId("long-term-memory-editor-modal")?.classList.contains("open");
    if (Number(target.id || 0) > 0 && !editingCurrent) {
        try {
            const data = await saveDashboardJson("/api/diaries/" + target.id, {
                method: "PUT",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({
                    title: target.title || "",
                    keywords,
                    content: target.content || "",
                    diary_date: longTermMemoryDate(target),
                }),
            });
            applySavedDiary(data.diary);
        } catch (e) {
            showLongTermMsg("error", "保存失败：" + e.message);
            return;
        }
    }
    closeLongTermSummaryEditor();
}

function initLongTermMemoryEditor() {
    ["long-term-memory-date", "long-term-memory-title", "long-term-memory-content"].forEach(id => {
        const input = byId(id);
        if (!input) return;
        input.addEventListener("keydown", event => {
            if (event.key === "Escape") closeLongTermMemoryEditor();
            if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
                event.preventDefault();
                saveLongTermMemory();
            }
        });
    });
}

async function openLongTermMemoryEditor(id) {
    const numericId = Number(id || 0);
    const directoryItem = numericId
        ? longTermMemories.find(item => Number(item.id) === numericId)
        : null;
    if (numericId && !directoryItem) return;
    let memory = directoryItem;
    if (numericId) {
        try {
            const resp = await authFetch("/api/diaries/" + numericId);
            const data = await readJsonResponse(resp);
            if (!resp.ok || data.error) throw new Error(data.error || "HTTP " + resp.status);
            memory = data;
        } catch (e) {
            showLongTermMsg("error", "读取日记失败：" + e.message);
            return;
        }
    }
    longTermEditingId = memory ? numericId : null;
    const modal = byId("long-term-memory-editor-modal");
    if (!modal) return;
    byId("long-term-memory-date").value = memory
        ? longTermMemoryDate(memory)
        : localDateInputValue();
    byId("long-term-memory-title").value = memory ? (memory.title || "") : "";
    ltmSummaryDraft = memory
        ? normalizeLongTermKeywords(memory.keywords).join("\n")
        : "";
    renderLongTermSummaryPreview();
    byId("long-term-memory-content").value = memory ? (memory.content || "") : "";
    modal.classList.add("open");
    modal.setAttribute("aria-hidden", "false");
    document.body.classList.add("memory-editor-open");
    requestAnimationFrame(() => byId("long-term-memory-title").focus());
}

function closeLongTermMemoryEditor() {
    if (byId("long-term-memory-editor-msg")) byId("long-term-memory-editor-msg").textContent = "";
    const modal = byId("long-term-memory-editor-modal");
    if (modal) {
        modal.classList.remove("open");
        modal.setAttribute("aria-hidden", "true");
    }
    ["long-term-memory-date", "long-term-memory-title", "long-term-memory-content"].forEach(id => {
        const input = byId(id);
        if (input) input.value = "";
    });
    ltmSummaryDraft = "";
    renderLongTermSummaryPreview();
    document.body.classList.remove("memory-editor-open");
    longTermEditingId = null;
}

async function saveLongTermMemory() {
    const diary_date = byId("long-term-memory-date").value;
    const title = byId("long-term-memory-title").value.trim();
    const keywords = parseLongTermKeywords(ltmSummaryDraft);
    const content = byId("long-term-memory-content").value.trim();
    if (!title || !content) {
        showLongTermMsg("error", "标题和完整内容不能为空");
        return;
    }
    const editing = Number(longTermEditingId) > 0;
    const saveButton = byId("long-term-memory-editor-save");
    if (saveButton?.disabled) return;
    if (byId("long-term-memory-editor-msg")) byId("long-term-memory-editor-msg").textContent = "";
    if (saveButton) {
        saveButton.disabled = true;
        saveButton.textContent = "保存中…";
    }
    try {
        const data = await saveDashboardJson(
            "/api/diaries" + (editing ? "/" + longTermEditingId : ""),
            {
                method: editing ? "PUT" : "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({title, keywords, content, diary_date}),
            }
        );
        closeLongTermMemoryEditor();
        applySavedDiary(data.diary);
        showLongTermMsg("success", "这一页已保存");
    } catch (e) {
        showLongTermMsg("error", "保存失败：" + e.message);
    } finally {
        if (saveButton) {
            saveButton.disabled = false;
            saveButton.textContent = "保存";
        }
    }
}

async function deleteLongTermMemory(id) {
    const memory = longTermMemories.find(item => Number(item.id) === Number(id));
    if (!confirm("确定删除日记“" + ((memory && memory.title) || ("#" + id)) + "”？")) return;
    try {
        const resp = await authFetch("/api/diaries/" + id, {method: "DELETE"});
        const data = await readJsonResponse(resp);
        if (!resp.ok || data.error) throw new Error(data.error || "HTTP " + resp.status);
        await loadLongTermMemory();
    } catch (e) {
        showLongTermMsg("error", "删除失败：" + e.message);
    }
}

async function deleteSelectedLongTermMemories() {
    const ids = [...longTermSelectedIds].sort((left, right) => left - right);
    if (!ids.length || longTermBatchDeleting) return;
    if (!confirm("确定永久删除选中的 " + ids.length + " 篇日记？此操作无法撤销。")) return;
    longTermBatchDeleting = true;
    updateLongTermSelectionControls();
    try {
        const resp = await authFetch("/api/diaries/batch-delete", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({ids}),
        });
        const data = await readJsonResponse(resp);
        if (!resp.ok || data.error) throw new Error(data.error || "HTTP " + resp.status);
        const deleted = Number(data.deleted) || 0;
        longTermSelectedIds.clear();
        longTermSelectionMode = false;
        await Promise.all([loadLongTermMemory(), loadStandingMemory()]);
        showLongTermMsg("success", "已删除 " + deleted + " 篇日记");
    } catch (e) {
        showLongTermMsg("error", "批量删除失败：" + e.message);
    } finally {
        longTermBatchDeleting = false;
        updateLongTermSelectionControls();
    }
}

async function approveLongTermMemoryProposal(id) {
    const proposal = longTermPending.find(item => Number(item.id) === Number(id));
    if (proposal && proposal.operation === "delete"
        && !confirm("确定通过删除日记 #" + proposal.target_diary_id + " 的请求？")) {
        return;
    }
    try {
        const resp = await authFetch(
            "/api/diaries/pending/" + id + "/approve",
            {method: "POST"}
        );
        const data = await readJsonResponse(resp);
        if (!resp.ok || data.error) throw new Error(data.error || "HTTP " + resp.status);
        showLongTermMsg("success", "请求已执行");
        await Promise.all([loadLongTermMemory(), loadStandingMemory()]);
    } catch (e) {
        showLongTermMsg("error", "执行失败：" + e.message);
    }
}

async function rejectLongTermMemoryProposal(id) {
    if (!confirm("确定拒绝这个日记 pending 请求？")) return;
    try {
        const resp = await authFetch(
            "/api/diaries/pending/" + id,
            {method: "DELETE"}
        );
        const data = await readJsonResponse(resp);
        if (!resp.ok || data.error) throw new Error(data.error || "HTTP " + resp.status);
        await Promise.all([loadLongTermMemory(), loadStandingMemory()]);
    } catch (e) {
        showLongTermMsg("error", "拒绝失败：" + e.message);
    }
}

function showLongTermMsg(type, text) {
    const container = byId("long-term-summary-modal")?.classList.contains("open")
        ? byId("long-term-summary-msg")
        : byId("long-term-memory-editor-modal")?.classList.contains("open")
            ? byId("long-term-memory-editor-msg") : byId("long-term-msg");
    if (!container) return;
    container.innerHTML = '<div class="msg msg-' + escHtml(type) + '">' + escHtml(text) + '</div>';
    if (type !== "error") {
        setTimeout(() => {
            if (container.innerHTML.indexOf(escHtml(text)) !== -1) container.innerHTML = "";
        }, 3500);
    }
}

function handlePromptPreviewToggle(event) {
    if (event.currentTarget.open && !promptSplicePreview) loadPromptSplicePreview();
}

async function loadPromptSplicePreview() {
    const statsEl = byId("prompt-splice-stats");
    const sectionsEl = byId("prompt-splice-sections");
    const copyBtn = byId("prompt-splice-copy");
    if (statsEl) statsEl.textContent = "加载中...";
    if (sectionsEl) sectionsEl.innerHTML = "";
    if (copyBtn) copyBtn.disabled = true;
    try {
        const resp = await authFetch("/api/prompt/splice-preview");
        const data = await readJsonResponse(resp);
        if (!resp.ok || data.error) throw new Error(data.error || "HTTP " + resp.status);
        promptSplicePreview = data;
        renderPromptSplicePreview();
    } catch (e) {
        promptSplicePreview = null;
        if (statsEl) statsEl.textContent = "加载失败：" + e.message;
        if (sectionsEl) sectionsEl.textContent = "无法读取拼接预览";
    }
}

function renderPromptSplicePreview() {
    const preview = promptSplicePreview || {};
    const content = String(preview.content || "");
    const sectionsEl = byId("prompt-splice-sections");
    const statsEl = byId("prompt-splice-stats");
    const copyBtn = byId("prompt-splice-copy");
    const noteEl = byId("prompt-splice-note");
    const sections = Array.isArray(preview.sections) ? preview.sections : [];
    if (sectionsEl) {
        sectionsEl.innerHTML = sections.map((section, index) => (
            '<details class="prompt-splice-section"' + (index === 0 ? " open" : "") + '>' +
                '<summary><span>' + escHtml(section.title || section.id || "提示词") + '</span>' +
                    '<small>' + (Number(section.character_count) || 0) + ' 字符</small></summary>' +
                '<pre class="standing-overview-content">' + escHtml(section.content || "（空）") + '</pre>' +
            '</details>'
        )).join("");
    }
    if (statsEl) {
        statsEl.textContent = sections.length + " 段 · " +
            (Number(preview.character_count) || 0) + " 字符";
    }
    if (copyBtn) copyBtn.disabled = !content;
    if (noteEl) noteEl.textContent = String(preview.dynamic_note || "");
}

async function copyPromptSplicePreview() {
    const content = String((promptSplicePreview || {}).content || "");
    if (!content) return;
    try {
        await navigator.clipboard.writeText(content);
        if (byId("prompt-splice-stats")) byId("prompt-splice-stats").textContent = "已复制全部";
    } catch (e) {
        if (byId("prompt-splice-stats")) byId("prompt-splice-stats").textContent = "复制失败：" + e.message;
    }
}

async function createLongTermDiaryDraft() {
    const btn = byId("long-term-diary-btn");
    if (!confirm("确定根据最近一次前端上下文写一篇日记？完成后会进入日记 Pending。")) {
        return;
    }
    const oldHtml = btn ? btn.innerHTML : "";
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="standing-diary-spinner"></span><span>书写中...</span>';
    }
    showLongTermMsg("success", "书写中...");
    try {
        const resp = await authFetch("/api/diaries/draft", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({}),
        });
        const data = await resp.json();
        if (!resp.ok || data.error) throw new Error(data.error || "HTTP " + resp.status);
        showLongTermMsg("success", "日记已写好，进入日记 Pending " + (data.created || 0) + " 篇");
        await loadLongTermMemory();
    } catch (e) {
        showLongTermMsg("error", "日记书写失败：" + e.message);
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = oldHtml;
        }
    }
}

function renderStandingLists() {
    const pending = sortStandingSiblings(standingBlocks.filter(b => b.status === "pending"));
    const active = sortStandingSiblings(standingBlocks.filter(b => b.status === "active"));
    const fixed = active.filter(block => block.layer !== "recent");
    const flow = active.filter(block => block.layer === "recent");
    const pendingEl = byId("standing-pending-list");
    const pendingSection = byId("standing-pending-section");
    const pendingCount = byId("standing-pending-count");
    const activeEl = byId("standing-active-list");
    const activeCount = byId("standing-active-count");
    const flowWindow = standingOverview && standingOverview.flow_window
        ? standingOverview.flow_window : {};
    const flowMaxItems = Math.min(100, Math.max(1, Number(flowWindow.max_items) || 8));
    const flowItemCount = Number(flowWindow.item_count) || flow.length;
    const flowWindowLabel = flowWindow.state === "hard"
        ? "正在整理超出上限的摘要"
        : "当前 " + flowItemCount + " / " + flowMaxItems + " 条";
    const flowWindowControl =
        '<div class="flow-window-control">' +
            '<span class="flow-window-status">' + escHtml(flowWindowLabel) + '</span>' +
            '<label title="超过上限的最旧交接摘要会自动归档到日记">' +
                '<span>保留最近</span>' +
                '<input type="number" id="flowMemoryMaxItems" min="1" max="100" step="1" inputmode="numeric" value="' + flowMaxItems + '">' +
                '<span>条</span>' +
            '</label>' +
            '<button type="button" onclick="saveFlowMemoryMaxItems(event)">保存</button>' +
        '</div>';

    if (pendingCount) pendingCount.textContent = pending.length + " 条";
    if (pendingSection) pendingSection.style.display = pending.length ? "" : "none";
    if (pendingEl) {
        pendingEl.innerHTML = pending.map(renderPendingStandingMemoryCard).join("");
    }
    if (activeCount) activeCount.textContent = fixed.length + " 条固定 · " + flow.length + " 条流动";
    if (activeEl) {
        const fixedHtml = fixed.length
            ? fixed.map(block => renderKelivoMemoryCard(block, "fixed")).join("")
            : '<div class="standing-empty">还没有固定记忆</div>';
        const flowHtml = flow.length
            ? flow.map(block => renderKelivoMemoryCard(block, "flow")).join("")
            : '<div class="standing-empty">还没有会话摘要</div>';
        activeEl.innerHTML =
            '<section class="memory-zone memory-zone-fixed">' +
                '<div class="memory-zone-head"><h3>固定区</h3><span>由你维护的稳定记忆</span></div>' +
                fixedHtml +
            '</section>' +
            '<section class="memory-zone memory-zone-flow">' +
                '<div class="memory-zone-head"><h3>流动区</h3>' + flowWindowControl + '</div>' +
                flowHtml +
            '</section>';
    }
}

async function saveFlowMemoryMaxItems(event) {
    if (event) event.preventDefault();
    const input = byId("flowMemoryMaxItems");
    const button = event && event.currentTarget ? event.currentTarget : null;
    const maxItems = Number(input && input.value);
    if (!Number.isInteger(maxItems) || maxItems < 1 || maxItems > 100) {
        showStandingMsg("error", "交接摘要保留条数需为 1-100 的整数");
        return;
    }
    const currentCount = Number(standingOverview?.flow_window?.item_count) || 0;
    if (maxItems < currentCount && !confirm(
        "保存后会立即把最旧的 " + (currentCount - maxItems) + " 条摘要归档到日记，继续吗？"
    )) return;
    if (button) button.disabled = true;
    try {
        const resp = await authFetch("/api/flow-memory-settings", {
            method: "PUT",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({max_items: maxItems}),
        });
        const data = await readJsonResponse(resp);
        if (!resp.ok || data.error) throw new Error(data.error || "HTTP " + resp.status);
        await loadStandingMemory();
        const promoted = Number(data.promoted_count) || 0;
        showStandingMsg(
            "success",
            "已保留最近 " + maxItems + " 条" +
                (promoted ? "，并将 " + promoted + " 条旧摘要归档到日记" : "")
        );
    } catch (e) {
        showStandingMsg("error", "保存交接摘要条数失败：" + e.message);
        if (button && button.isConnected) button.disabled = false;
    }
}

function normalizeStandingMetadata(metadata) {
    if (metadata && typeof metadata === "object" && !Array.isArray(metadata)) {
        return metadata;
    }
    if (typeof metadata === "string" && metadata.trim()) {
        try {
            const parsed = JSON.parse(metadata);
            return parsed && typeof parsed === "object" && !Array.isArray(parsed)
                ? parsed : {};
        } catch (e) {
            return {};
        }
    }
    return {};
}

function renderPendingStandingMemoryCard(block) {
    const id = Number(block.id);
    const metadata = normalizeStandingMetadata(block.metadata);
    const operation = String(metadata.pending_operation || "create");
    const targetId = Number(metadata.target_block_id || 0);
    const operationLabel = operation === "edit"
        ? "修改 #" + targetId
        : (operation === "delete" ? "删除 #" + targetId : "创建常驻记忆");
    const target = targetId
        ? standingBlocks.find(candidate =>
            candidate.status === "active" && Number(candidate.id) === targetId
        )
        : null;
    const diffHtml = renderPendingFieldDiff(
        "内容",
        target && target.content,
        block.content,
        operation,
    );
    return (
        '<article class="pending-memory-card standing-pending-card">' +
            '<div class="pending-memory-head">' +
                '<span class="standing-tag status">' + escHtml(operationLabel) + '</span>' +
                '<div class="row-actions">' +
                    '<button type="button" class="btn btn-primary btn-sm" onclick="approveStandingMemory(' + id + ')">通过</button>' +
                    '<button type="button" class="btn btn-danger btn-sm" onclick="deleteStandingMemory(' + id + ', true)">拒绝</button>' +
                '</div>' +
            '</div>' +
            '<div class="pending-memory-diff">' + diffHtml + '</div>' +
        '</article>'
    );
}

function renderKelivoMemoryCard(block, zone) {
    const id = Number(block.id);
    const enteredOn = String(block.created_at || "").slice(0, 10);
    const timelineMeta = zone === "flow"
        ? '<div class="kelivo-memory-timeline-meta"><strong>' +
            escHtml(block.title || "会话摘要") + '</strong><time>' +
            escHtml(enteredOn ? "进入流动区：" + enteredOn : "") + '</time></div>'
        : "";

    // 流动记忆可整理成日记
    const promoteButton = zone === "flow"
        ? '<button type="button" class="kelivo-icon-btn promote" data-promote-id="' + id + '" aria-label="归档到日记" title="归档到日记" onclick="promoteFlowMemoryToLongTerm(' + id + ')">' +
            '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">' +
                '<path d="M12 19V5M5 12l7-7 7 7"/>' +
            '</svg>' +
          '</button>'
        : "";

    return (
        '<article class="kelivo-memory-card" data-standing-block-id="' + id + '">' +
            timelineMeta +
            '<div class="kelivo-memory-content">' + escHtml(block.content || "") + '</div>' +
            '<div class="kelivo-memory-actions">' +
                promoteButton +
                '<button type="button" class="kelivo-icon-btn edit" aria-label="编辑记忆" title="编辑" onclick="openStandingMemoryEditor(' + id + ')">' +
                    '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">' +
                        '<path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"/>' +
                    '</svg>' +
                '</button>' +
                '<button type="button" class="kelivo-icon-btn delete" aria-label="删除记忆" title="删除" onclick="deleteStandingMemory(' + id + ')">' +
                    '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">' +
                        '<path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v5M14 11v5"/>' +
                    '</svg>' +
                '</button>' +
            '</div>' +
        '</article>'
    );
}

function sortStandingSiblings(blocks) {
    return blocks.slice().sort(compareStandingBlocks);
}

function compareStandingBlocks(a, b) {
    const sortA = Number.isFinite(Number(a.sort_order)) ? Number(a.sort_order) : 0;
    const sortB = Number.isFinite(Number(b.sort_order)) ? Number(b.sort_order) : 0;
    if (sortA !== sortB) return sortA - sortB;
    return Number(a.id) - Number(b.id);
}

function initMemoryEditor() {
    const textarea = byId("memory-editor-content");
    if (!textarea) return;
    textarea.addEventListener("keydown", event => {
        if (event.key === "Escape") {
            closeStandingMemoryEditor();
            return;
        }
        if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
            event.preventDefault();
            saveStandingMemory();
        }
    });
}

function openStandingMemoryEditor(id) {
    const numericId = Number(id || 0);
    const block = numericId
        ? standingBlocks.find(item => Number(item.id) === numericId && item.status === "active")
        : null;
    if (numericId && !block) return;
    standingEditingId = block ? numericId : null;
    const modal = byId("memory-editor-modal");
    const textarea = byId("memory-editor-content");
    if (!modal || !textarea) return;
    textarea.value = block ? (block.content || "") : "";
    modal.classList.add("open");
    modal.setAttribute("aria-hidden", "false");
    document.body.classList.add("memory-editor-open");
    requestAnimationFrame(() => textarea.focus());
}

function closeStandingMemoryEditor() {
    if (byId("memory-editor-msg")) byId("memory-editor-msg").textContent = "";
    const modal = byId("memory-editor-modal");
    const textarea = byId("memory-editor-content");
    if (modal) {
        modal.classList.remove("open");
        modal.setAttribute("aria-hidden", "true");
    }
    if (textarea) textarea.value = "";
    document.body.classList.remove("memory-editor-open");
    standingEditingId = null;
}

async function saveStandingMemory() {
    const editId = standingEditingId;
    const isEdit = Number.isFinite(Number(editId)) && Number(editId) > 0;
    const block = isEdit ? standingBlocks.find(b => Number(b.id) === Number(editId)) : null;
    const content = (byId("memory-editor-content") || {}).value || "";
    if (!content.trim()) {
        showStandingMsg("error", "记忆内容不能为空");
        return;
    }
    const generatedTitle = content.trim().split(/\r?\n/)[0].slice(0, 80) || "Memory";
    const payload = isEdit
        ? {title: (block && block.title) || generatedTitle, content}
        : {
            title: generatedTitle,
            content,
            parent_id: null,
            layer: "core",
            status: "active",
            inject_enabled: true,
            inject_every_n: 1,
            inject_on_first_turn: true,
            sort_order: nextStandingSortOrder(null, "active"),
            metadata: {},
        };
    const saveButton = byId("memory-editor-save");
    if (saveButton?.disabled) return;
    if (byId("memory-editor-msg")) byId("memory-editor-msg").textContent = "";
    if (saveButton) {
        saveButton.disabled = true;
        saveButton.textContent = "保存中…";
    }
    try {
        const data = await saveDashboardJson("/api/standing-memory" + (isEdit ? "/" + editId : ""), {
            method: isEdit ? "PUT" : "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(payload),
        });
        ++standingLoadGeneration;
        const index = standingBlocks.findIndex(item => Number(item.id) === Number(data.block.id));
        if (index < 0) standingBlocks.push(data.block);
        else standingBlocks[index] = data.block;
        promptSplicePreview = null;
        closeStandingMemoryEditor();
        showStandingMsg("success", "已保存");
        renderStandingStats();
        const card = document.querySelector(`[data-standing-block-id="${Number(data.block.id)}"]`);
        if (isEdit && card && data.block.status === "active") {
            card.outerHTML = renderKelivoMemoryCard(data.block, data.block.layer === "recent" ? "flow" : "fixed");
        } else {
            renderStandingLists();
        }
    } catch (e) {
        showStandingMsg("error", "保存失败：" + e.message);
    } finally {
        if (saveButton) {
            saveButton.disabled = false;
            saveButton.textContent = "保存";
        }
    }
}

function nextStandingSortOrder(parentId, status) {
    const siblings = standingBlocks.filter(block => {
        const blockParent = block.parent_id == null ? null : Number(block.parent_id);
        return block.status === status && blockParent === (parentId == null ? null : Number(parentId));
    });
    if (!siblings.length) return 10;
    return Math.max(...siblings.map(block => Number.isFinite(Number(block.sort_order)) ? Number(block.sort_order) : 0)) + 10;
}

async function approveStandingMemory(id) {
    const block = standingBlocks.find(item => Number(item.id) === Number(id));
    const metadata = normalizeStandingMetadata(block && block.metadata);
    if (metadata.pending_operation === "delete"
        && !confirm("确定通过删除记忆 #" + metadata.target_block_id + " 的请求？")) {
        return;
    }
    try {
        const resp = await authFetch("/api/standing-memory/" + id + "/approve", {
            method: "POST"
        });
        const data = await readJsonResponse(resp);
        if (!resp.ok || data.error) throw new Error(data.error || "HTTP " + resp.status);
        showStandingMsg("success", "请求已执行");
        await loadStandingMemory();
    } catch (e) {
        showStandingMsg("error", "执行失败：" + e.message);
    }
}

async function deleteStandingMemory(id, rejectingPending = false) {
    const message = rejectingPending
        ? "确定拒绝这个 pending 请求？"
        : "确定删除记忆 #" + id + "？";
    if (!confirm(message)) return;
    try {
        const resp = await authFetch("/api/standing-memory/" + id, {method: "DELETE"});
        const data = await resp.json();
        if (!resp.ok || data.error) throw new Error(data.error || "HTTP " + resp.status);
        await loadStandingMemory();
    } catch (e) {
        showStandingMsg("error", "删除失败：" + e.message);
    }
}

async function promoteFlowMemoryToLongTerm(id) {
    if (promotingFlowMemoryIds.has(id)) return;
    if (!confirm("将此流动记忆归档到日记？")) return;
    promotingFlowMemoryIds.add(id);
    const button = document.querySelector('[data-promote-id="' + id + '"]');
    if (button) button.disabled = true;
    showStandingMsg("info", "正在归档到日记...");
    try {
        const resp = await authFetch("/api/standing-memory/" + id + "/to-diary", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
                delete_original: true
            }),
        });
        const data = await resp.json();
        if (!resp.ok || data.error) throw new Error(data.error || "HTTP " + resp.status);

        showStandingMsg("success", "已归档到日记 #" + data.diary.id);

        // 刷新记忆列表
        await loadStandingMemory();

        // 如果当前在日记视图，也刷新它
        if (byId("standing-view-long-term").classList.contains("active")) {
            await loadLongTermMemory();
        }
    } catch (e) {
        showStandingMsg("error", "提升失败：" + e.message);
    } finally {
        promotingFlowMemoryIds.delete(id);
        if (button && button.isConnected) button.disabled = false;
    }
}

function showStandingMsg(type, text) {
    const container = byId("memory-editor-modal")?.classList.contains("open")
        ? byId("memory-editor-msg") : byId("standing-msg");
    if (!container) return;
    container.innerHTML = '<div class="msg msg-' + escHtml(type) + '">' + escHtml(text) + '</div>';
    if (type !== "error") {
        setTimeout(() => {
            if (container.innerHTML.indexOf(escHtml(text)) !== -1) container.innerHTML = "";
        }, 3500);
    }
}

// ============================================
// Heartbeat activity
// ============================================
async function loadAnthropicCredential() {
    const note = byId("anthropic-credential-note");
    const deleteButton = byId("anthropic-credential-delete");
    try {
        const resp = await authFetch("/api/anthropic-credential");
        const data = await readJsonResponse(resp);
        if (!resp.ok || data.error) throw new Error(data.error || "HTTP " + resp.status);
        if (data.source === "database") {
            if (note) note.textContent = "Dashboard Key 已保存 · 重启后继续有效";
        } else if (data.source === "environment") {
            if (note) note.textContent = "正在使用环境变量 API_KEY";
        } else {
            if (note) note.textContent = "未配置";
        }
        if (deleteButton) deleteButton.disabled = !data.stored_in_dashboard;
    } catch (e) {
        if (note) note.textContent = "加载失败：" + e.message;
        if (deleteButton) deleteButton.disabled = true;
    }
}

async function saveAnthropicCredential() {
    const input = byId("anthropicCredentialKey");
    const msg = byId("anthropic-credential-msg");
    const apiKey = input ? input.value.trim() : "";
    if (!apiKey) {
        if (msg) msg.textContent = "请先填写 Key";
        return;
    }
    if (msg) msg.textContent = "保存中…";
    try {
        await saveDashboardJson("/api/anthropic-credential", {
            method: "PUT",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({api_key: apiKey}),
        });
        if (input) input.value = "";
        if (msg) msg.textContent = "Key 已保存";
        await loadAnthropicCredential();
    } catch (e) {
        if (input) input.value = "";
        if (msg) msg.textContent = "保存失败：" + e.message;
    }
}

async function deleteAnthropicCredential() {
    if (!confirm("确定从数据库删除 Anthropic 路由 Key？正在进行的请求可能仍会完成。")) return;
    const msg = byId("anthropic-credential-msg");
    if (msg) msg.textContent = "删除中…";
    try {
        const resp = await authFetch("/api/anthropic-credential", {method: "DELETE"});
        const data = await readJsonResponse(resp);
        if (!resp.ok || data.error) throw new Error(data.error || "HTTP " + resp.status);
        if (msg) msg.textContent = data.source === "environment"
            ? "Dashboard Key 已删除，但环境变量 API_KEY 仍在生效"
            : "Key 已删除";
        await loadAnthropicCredential();
    } catch (e) {
        if (msg) msg.textContent = "删除失败：" + e.message;
    }
}

async function loadRouteSettings() {
    const note = byId("route-settings-note");
    try {
        const resp = await authFetch("/api/route-settings");
        const data = await readJsonResponse(resp);
        if (!resp.ok || data.error) throw new Error(data.error || "HTTP " + resp.status);
        byId("routeProvider").value = data.provider || "auto";
        if (note) note.textContent = "当前 " + (data.provider || "auto");
    } catch (e) {
        if (note) note.textContent = "加载失败：" + e.message;
    }
}

async function saveRouteSettings() {
    const msg = byId("route-settings-msg");
    if (msg) msg.textContent = "保存中...";
    try {
        await saveDashboardJson("/api/route-settings", {
            method: "PUT",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({provider: byId("routeProvider").value}),
        });
        if (msg) msg.textContent = "已保存";
        await loadRouteSettings();
        setTimeout(() => { if (msg && msg.textContent === "已保存") msg.textContent = ""; }, 3000);
    } catch (e) {
        if (msg) msg.textContent = "保存失败：" + e.message;
    }
}

function toggleOpenAiProviderCreator(forceOpen) {
    const form = byId("openai-provider-create");
    if (!form) return;
    const shouldOpen = typeof forceOpen === "boolean" ? forceOpen : form.hidden;
    form.hidden = !shouldOpen;
    if (shouldOpen) byId("openaiProviderName")?.focus();
}

function renderOpenAiProviders() {
    const container = byId("openai-provider-list");
    if (!container) return;
    if (!openAiProviderProfiles.length) {
        container.innerHTML = '<div class="openai-provider-empty">暂无预设</div>';
        return;
    }
    container.innerHTML = openAiProviderProfiles.map(profile => {
        const id = Number(profile.id);
        const active = Boolean(profile.is_active);
        return `
            <details class="openai-provider-item${active ? " is-active" : ""}" data-provider-id="${id}">
                <summary>
                    <span class="provider-status-dot"></span>
                    <span class="provider-summary-name">${escHtml(profile.name)}</span>
                    ${active ? '<span class="provider-active-mark">活跃</span>' : ""}
                    <svg class="provider-summary-chevron" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
                        <path d="m6 9 6 6 6-6"/>
                    </svg>
                </summary>
                <div class="provider-editor">
                    <div class="provider-form-grid">
                        <label class="heartbeat-setting-field">
                            <span>名称</span>
                            <input type="text" id="openaiProviderName-${id}" class="control-input" maxlength="80" value="${escHtml(profile.name)}" autocomplete="off">
                        </label>
                        <label class="heartbeat-setting-field provider-url-field">
                            <span>API URL</span>
                            <input type="url" id="openaiProviderUrl-${id}" class="control-input" value="${escHtml(profile.api_url)}" placeholder="https://openrouter.ai/api/v1" autocomplete="url">
                        </label>
                        <label class="heartbeat-setting-field">
                            <span>API Key</span>
                            <input type="password" id="openaiProviderKey-${id}" class="control-input" placeholder="${escHtml(profile.api_key_hint || "")}" autocomplete="new-password">
                        </label>
                    </div>
                    <div class="provider-form-actions">
                        <label class="provider-active-choice">
                            <input type="checkbox" id="openaiProviderActive-${id}" ${active ? "checked" : ""}>
                            <span>活跃</span>
                        </label>
                        <div>
                            <button type="button" class="provider-delete-button" onclick="deleteOpenAiProvider(${id})" title="删除" aria-label="删除">
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round">
                                    <path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6M10 10v6M14 10v6"/>
                                </svg>
                            </button>
                            <button type="button" class="btn btn-primary" onclick="saveOpenAiProvider(${id})">保存</button>
                        </div>
                    </div>
                </div>
            </details>
        `;
    }).join("");
}

function renderHistoryTitleProviders() {
    const select = byId("historyTitleProvider");
    if (!select) return;
    const selected = select.dataset.selectedProviderId || "";
    const legacyConfigured = select.dataset.legacyConfigured === "true";
    const firstLabel = legacyConfigured && !selected ? "原独立配置" : "供应商";
    select.innerHTML = [
        `<option value="">${firstLabel}</option>`,
        ...openAiProviderProfiles.map(profile =>
            `<option value="${Number(profile.id)}">${escHtml(profile.name)}</option>`
        ),
    ].join("");
    select.value = selected;
}

function renderHandoffSummaryProviders() {
    const select = byId("handoffSummaryProvider");
    if (!select) return;
    const selected = select.dataset.selectedProviderId || "";
    select.innerHTML = [
        '<option value="">环境变量</option>',
        ...openAiProviderProfiles.map(profile =>
            `<option value="${Number(profile.id)}">${escHtml(profile.name)}</option>`
        ),
    ].join("");
    select.value = selected;
}

function renderLongTermSummaryProviders() {
    const select = byId("longTermSummaryProvider");
    if (!select) return;
    const selected = select.dataset.selectedProviderId || "";
    select.innerHTML = [
        '<option value="">环境变量</option>',
        ...openAiProviderProfiles.map(profile =>
            `<option value="${Number(profile.id)}">${escHtml(profile.name)}</option>`
        ),
    ].join("");
    select.value = selected;
}

async function loadOpenAiProviders() {
    const note = byId("openai-provider-note");
    try {
        const resp = await authFetch("/api/openai-providers");
        const data = await readJsonResponse(resp);
        if (!resp.ok || data.error) throw new Error(data.error || "HTTP " + resp.status);
        openAiProviderProfiles = Array.isArray(data.profiles) ? data.profiles : [];
        renderOpenAiProviders();
        renderHistoryTitleProviders();
        renderHandoffSummaryProviders();
        renderLongTermSummaryProviders();
        if (note) note.textContent = data.effective?.name || "环境变量";
    } catch (e) {
        if (note) note.textContent = "加载失败";
        showOpenAiProviderMsg("加载失败：" + e.message);
    }
}

function showOpenAiProviderMsg(text) {
    const msg = byId("openai-provider-msg");
    if (!msg) return;
    msg.textContent = text || "";
}

async function createOpenAiProvider() {
    const payload = {
        name: byId("openaiProviderName").value.trim(),
        api_url: byId("openaiProviderUrl").value.trim(),
        api_key: byId("openaiProviderKey").value.trim(),
        is_active: Boolean(byId("openaiProviderActive").checked),
    };
    showOpenAiProviderMsg("保存中...");
    try {
        await saveDashboardJson("/api/openai-providers", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(payload),
        });
        byId("openaiProviderName").value = "";
        byId("openaiProviderUrl").value = "";
        byId("openaiProviderKey").value = "";
        byId("openaiProviderActive").checked = false;
        toggleOpenAiProviderCreator(false);
        showOpenAiProviderMsg("");
        await loadOpenAiProviders();
    } catch (e) {
        showOpenAiProviderMsg("保存失败：" + e.message);
    }
}

async function saveOpenAiProvider(id) {
    const payload = {
        name: byId("openaiProviderName-" + id).value.trim(),
        api_url: byId("openaiProviderUrl-" + id).value.trim(),
        api_key: byId("openaiProviderKey-" + id).value.trim(),
        is_active: Boolean(byId("openaiProviderActive-" + id).checked),
    };
    showOpenAiProviderMsg("保存中...");
    try {
        await saveDashboardJson("/api/openai-providers/" + id, {
            method: "PUT",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(payload),
        });
        showOpenAiProviderMsg("");
        await loadOpenAiProviders();
    } catch (e) {
        showOpenAiProviderMsg("保存失败：" + e.message);
    }
}

async function deleteOpenAiProvider(id) {
    if (!confirm("删除这个供应商？")) return;
    try {
        const resp = await authFetch("/api/openai-providers/" + id, {method: "DELETE"});
        const data = await readJsonResponse(resp);
        if (!resp.ok || data.error) throw new Error(data.error || "HTTP " + resp.status);
        showOpenAiProviderMsg("");
        await loadOpenAiProviders();
    } catch (e) {
        showOpenAiProviderMsg("删除失败：" + e.message);
    }
}

async function loadHeartbeatSettings() {
    const note = byId("heartbeat-settings-note");
    try {
        const resp = await authFetch("/api/heartbeat-settings");
        const data = await resp.json();
        if (!resp.ok || data.error) throw new Error(data.error || "HTTP " + resp.status);
        byId("heartbeatEnabled").checked = Boolean(data.enabled);
        byId("heartbeatInterval").value = data.interval_minutes || 30;
        byId("heartbeatProvider").value = data.provider || "openai";
        byId("heartbeatModel").value = data.model || "";
        if (note) {
            if (!data.context_managed) {
                note.textContent = "上下文管理未启用，心跳不会运行";
            } else if (data.provider === "anthropic" && Number(data.effective_interval_minutes) !== Number(data.interval_minutes)) {
                note.textContent = "为保持 1 小时缓存，实际按 " + data.effective_interval_minutes + " 分钟触发";
            } else {
                note.textContent = data.enabled ? "运行中，保存后无需重启" : "当前已关闭";
            }
        }
    } catch (e) {
        if (note) note.textContent = "设置加载失败：" + e.message;
    }
}

async function saveHeartbeatSettings() {
    const msg = byId("heartbeat-settings-msg");
    const payload = {
        enabled: Boolean(byId("heartbeatEnabled").checked),
        interval_minutes: parseInt(byId("heartbeatInterval").value, 10),
        provider: byId("heartbeatProvider").value,
        model: byId("heartbeatModel").value.trim(),
    };
    if (!Number.isFinite(payload.interval_minutes) || payload.interval_minutes < 1 || payload.interval_minutes > 1440) {
        if (msg) msg.textContent = "间隔需为 1-1440 分钟";
        return;
    }
    if (msg) msg.textContent = "保存中...";
    try {
        await saveDashboardJson("/api/heartbeat-settings", {
            method: "PUT",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(payload),
        });
        if (msg) msg.textContent = "已保存";
        await loadHeartbeatSettings();
        setTimeout(() => { if (msg && msg.textContent === "已保存") msg.textContent = ""; }, 3000);
    } catch (e) {
        if (msg) msg.textContent = "保存失败：" + e.message;
    }
}

async function loadConversationModelSettings() {
    const msg = byId("conversation-model-settings-msg");
    try {
        const resp = await authFetch("/api/conversation-model-settings");
        const data = await readJsonResponse(resp);
        if (!resp.ok || data.error) throw new Error(data.error || "HTTP " + resp.status);
        byId("historySearchEnabled").checked = Boolean(data.search_enabled);
        byId("historyEmbeddingUrl").value = data.embedding_api_url || "";
        byId("historyEmbeddingModel").value = data.embedding_model || "";
        byId("historyEmbeddingKey").value = "";
        byId("historyEmbeddingKey").placeholder = data.embedding_api_key_configured
            ? data.embedding_api_key_hint : "密钥";
        byId("longTermRecallTokenBudget").value =
            data.long_term_recall_token_budget || 1500;
        byId("historyTitleEnabled").checked = Boolean(data.title_enabled);
        byId("historyTitleProvider").dataset.selectedProviderId =
            data.title_provider_id == null ? "" : String(data.title_provider_id);
        byId("historyTitleProvider").dataset.legacyConfigured =
            String(Boolean(data.title_legacy_configured));
        renderHistoryTitleProviders();
        byId("historyTitleModel").value = data.title_model || "";
        byId("handoffSummaryProvider").dataset.selectedProviderId =
            data.handoff_provider_id == null ? "" : String(data.handoff_provider_id);
        renderHandoffSummaryProviders();
        byId("handoffSummaryModel").value = data.handoff_model || "";
        byId("handoffSummaryModel").placeholder = data.handoff_effective_model || "模型";
        byId("longTermSummaryProvider").dataset.selectedProviderId =
            data.long_term_summary_provider_id == null
                ? "" : String(data.long_term_summary_provider_id);
        renderLongTermSummaryProviders();
        byId("longTermSummaryModel").value = data.long_term_summary_model || "";
        byId("longTermSummaryModel").placeholder =
            data.long_term_summary_effective_model || "模型";
        if (msg) msg.textContent = "";
    } catch (e) {
        if (msg) msg.textContent = "加载失败：" + e.message;
    }
}

async function saveConversationModelSettings() {
    const msg = byId("conversation-model-settings-msg");
    const recallTokenBudget = Number(byId("longTermRecallTokenBudget").value);
    if (!Number.isInteger(recallTokenBudget)
        || recallTokenBudget < 256
        || recallTokenBudget > 8000) {
        if (msg) msg.textContent = "自动召回额度需为 256-8000 的整数";
        return;
    }
    const payload = {
        search_enabled: Boolean(byId("historySearchEnabled").checked),
        embedding_api_url: byId("historyEmbeddingUrl").value.trim(),
        embedding_model: byId("historyEmbeddingModel").value.trim(),
        embedding_api_key: byId("historyEmbeddingKey").value.trim(),
        long_term_recall_token_budget: recallTokenBudget,
        title_enabled: Boolean(byId("historyTitleEnabled").checked),
        title_provider_id: byId("historyTitleProvider").value
            ? Number(byId("historyTitleProvider").value) : null,
        title_model: byId("historyTitleModel").value.trim(),
        handoff_provider_id: byId("handoffSummaryProvider").value
            ? Number(byId("handoffSummaryProvider").value) : null,
        handoff_model: byId("handoffSummaryModel").value.trim(),
        long_term_summary_provider_id: byId("longTermSummaryProvider").value
            ? Number(byId("longTermSummaryProvider").value) : null,
        long_term_summary_model: byId("longTermSummaryModel").value.trim(),
    };
    if (msg) msg.textContent = "保存中...";
    try {
        await saveDashboardJson("/api/conversation-model-settings", {
            method: "PUT",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(payload),
        });
        if (msg) msg.textContent = "已保存";
        await loadConversationModelSettings();
        if (msg) msg.textContent = "已保存";
        setTimeout(() => {
            if (msg && msg.textContent === "已保存") msg.textContent = "";
        }, 3000);
    } catch (e) {
        if (msg) msg.textContent = "保存失败：" + e.message;
    }
}

async function loadOcrSettings() {
    const note = byId("ocr-settings-note");
    try {
        const resp = await authFetch("/api/ocr-settings");
        const data = await readJsonResponse(resp);
        if (!resp.ok || data.error) throw new Error(data.error || "HTTP " + resp.status);
        byId("ocrEnabled").checked = Boolean(data.enabled);
        byId("ocrApiUrl").value = data.api_url || "";
        byId("ocrModel").value = data.model || "";
        byId("ocrApiKey").value = "";
        byId("ocrApiKey").placeholder = data.api_key_configured ? data.api_key_hint : "";
        byId("ocrClearKey").disabled = !data.api_key_configured;
        clearStoredOcrApiKey = false;
        if (note) note.textContent = data.enabled ? "已启用" : "已关闭";
    } catch (e) {
        if (note) note.textContent = "加载失败：" + e.message;
    }
}

function clearOcrApiKey() {
    clearStoredOcrApiKey = true;
    const input = byId("ocrApiKey");
    input.value = "";
    input.placeholder = "保存后清除";
    byId("ocrClearKey").disabled = true;
}

async function saveOcrSettings() {
    const msg = byId("ocr-settings-msg");
    const apiKey = byId("ocrApiKey").value.trim();
    const payload = {
        enabled: Boolean(byId("ocrEnabled").checked),
        api_url: byId("ocrApiUrl").value.trim(),
        model: byId("ocrModel").value.trim(),
        api_key: apiKey,
        clear_api_key: clearStoredOcrApiKey && !apiKey,
    };
    if (msg) msg.textContent = "保存中...";
    try {
        await saveDashboardJson("/api/ocr-settings", {
            method: "PUT",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(payload),
        });
        if (msg) msg.textContent = "已保存";
        await loadOcrSettings();
        setTimeout(() => { if (msg && msg.textContent === "已保存") msg.textContent = ""; }, 3000);
    } catch (e) {
        if (msg) msg.textContent = "保存失败：" + e.message;
    }
}

async function loadHeartbeatActivities() {
    const count = byId("heartbeat-activity-count");
    const container = byId("heartbeat-activity-list");
    if (count) count.textContent = "加载中...";
    if (!container) return;
    try {
        const resp = await authFetch("/api/heartbeat-activities?limit=100");
        const data = await resp.json();
        if (!resp.ok || data.error) throw new Error(data.error || "HTTP " + resp.status);
        const activities = Array.isArray(data.activities) ? data.activities : [];
        if (count) count.textContent = activities.length + " 条";
        if (!activities.length) {
            container.innerHTML = '<div class="memory-card-empty">暂无心跳活动</div>';
            return;
        }
        container.innerHTML = activities.map(renderHeartbeatActivity).join("");
    } catch (e) {
        if (count) count.textContent = "加载失败";
        container.innerHTML = '<div class="memory-card-empty">加载失败：' + escHtml(e.message) + '</div>';
    }
}

function renderHeartbeatActivity(activity) {
    const events = Array.isArray(activity.tool_events) ? activity.tool_events : [];
    const statusLabels = {
        idle: "无操作",
        acted: "已行动",
        max_rounds: "达到轮次上限",
        context_limit: "上下文超限",
        error: "失败",
    };
    const tools = events.length ? events.map(event => {
        const input = JSON.stringify(event.input || {}, null, 2);
        return '<div class="heartbeat-tool-event ' + (event.ok ? "ok" : "error") + '">' +
            '<div class="heartbeat-tool-head"><strong>' + escHtml(event.name || "tool") + '</strong>' +
            '<span>' + (event.ok ? "完成" : "失败") + '</span></div>' +
            '<div class="heartbeat-tool-grid"><pre>' + escHtml(input) + '</pre><pre>' + escHtml(event.result || "") + '</pre></div>' +
        '</div>';
    }).join("") : '<div class="heartbeat-no-tools">未调用工具</div>';
    const finalText = activity.final_text
        ? '<div class="heartbeat-final-text">' + escHtml(activity.final_text) + '</div>'
        : '';
    return '<article class="heartbeat-activity-card">' +
        '<div class="heartbeat-activity-head">' +
            '<div><strong>' + escHtml(activity.created_at || "-") + '</strong>' +
            '<span>离开 ' + escHtml(activity.elapsed_minutes || 0) + ' 分钟</span></div>' +
            '<span class="heartbeat-status status-' + escHtml(activity.status || "idle") + '">' +
                escHtml(statusLabels[activity.status] || activity.status || "完成") +
            '</span>' +
        '</div>' +
        '<div class="heartbeat-meta">' + escHtml(activity.provider || "-") + ' · ' + escHtml(activity.model || "-") +
            ' · ' + events.length + ' 次工具调用</div>' +
        finalText +
        '<details class="heartbeat-tools" ' + (events.length ? '' : 'disabled') + '>' +
            '<summary>活动详情</summary>' + tools +
        '</details>' +
    '</article>';
}

// ============================================
// Token Usage
// ============================================
async function loadTokenUsage() {
    const stats = byId("usage-stats");
    if (stats) stats.textContent = "加载中...";
    try {
        const [summaryResp, logsResp, monthResp] = await Promise.all([
            authFetch("/api/token-usage/summary?days=7"),
            authFetch("/api/token-usage/logs?limit=100&days=7"),
            authFetch("/api/token-usage/summary?days=30"),
        ]);
        const summary = await summaryResp.json();
        const logsData = await logsResp.json();
        const monthSummary = await monthResp.json();
        if (!summaryResp.ok || summary.error) throw new Error(summary.error || "HTTP " + summaryResp.status);
        if (!logsResp.ok || logsData.error) throw new Error(logsData.error || "HTTP " + logsResp.status);
        if (!monthResp.ok || monthSummary.error) throw new Error(monthSummary.error || "HTTP " + monthResp.status);
        renderUsageSummary(summary, monthSummary);
        renderModelRanking(summary);
        renderUsageHeatmap(monthSummary);
        renderUsageLogs(logsData);
    } catch (e) {
        if (stats) stats.textContent = "加载失败：" + e.message;
        const logBody = byId("usage-log-body");
        if (logBody) logBody.innerHTML = '<tr><td colspan="9"><div class="memory-card-empty">加载失败：' + escHtml(e.message) + '</div></td></tr>';
    }
}

function renderUsageSummary(data, monthData) {
    const today = new Date().toISOString().slice(0, 10);
    const todayRow = (monthData.daily_usage || []).find(row => row.day === today) || {};
    setText("usage-today", fmtToken(todayRow.total_tokens || 0));
    setText("usage-week", fmtToken(data.total_tokens || 0));
    setText("usage-requests", fmtToken(data.request_count || 0));
    setText("usage-cache", fmtToken(data.cache_read_tokens || 0));
    const stats = byId("usage-stats");
    if (stats) stats.textContent = "近 7 天 " + fmtToken(data.total_tokens || 0) + " tokens";
}

function renderModelRanking(data) {
    const tbody = byId("usage-ranking-body");
    const count = byId("usage-ranking-count");
    const rows = data.model_ranking || [];
    if (count) count.textContent = rows.length + " 个模型";
    if (!tbody) return;
    if (!rows.length) {
        tbody.innerHTML = '<tr><td colspan="7"><div class="memory-card-empty">暂无用量记录</div></td></tr>';
        return;
    }
    const maxTokens = Math.max(...rows.map(row => Number(row.total_tokens || 0)), 1);
    tbody.innerHTML = rows.map((row, index) => {
        const total = Number(row.total_tokens || 0);
        const width = Math.max(4, Math.round(total / maxTokens * 100));
        return `
            <tr>
                <td>${index + 1}</td>
                <td><span class="usage-model-name">${escHtml(row.model || "-")}</span></td>
                <td>${escHtml(row.provider || "-")}</td>
                <td>${fmtToken(row.request_count || 0)}</td>
                <td>${fmtToken(row.input_tokens || 0)}</td>
                <td>${fmtToken(row.output_tokens || 0)}</td>
                <td>
                    <div>${fmtToken(total)}</div>
                    <div class="usage-token-bar"><span style="width:${width}%"></span></div>
                </td>
            </tr>
        `;
    }).join("");
}

function renderUsageHeatmap(data) {
    const container = byId("usage-heatmap");
    const totalEl = byId("usage-heatmap-total");
    if (!container) return;
    const byDay = new Map((data.daily_usage || []).map(row => [row.day, row]));
    const days = [];
    const now = new Date();
    for (let i = 29; i >= 0; i--) {
        const d = new Date(now);
        d.setDate(now.getDate() - i);
        const key = d.toISOString().slice(0, 10);
        days.push({key, row: byDay.get(key) || {day: key, total_tokens: 0, request_count: 0}});
    }
    const maxTokens = Math.max(...days.map(day => Number(day.row.total_tokens || 0)), 1);
    if (totalEl) totalEl.textContent = fmtToken(data.total_tokens || 0) + " tokens";
    container.innerHTML = days.map(day => {
        const total = Number(day.row.total_tokens || 0);
        const level = total <= 0 ? 0 : Math.min(4, Math.ceil(total / maxTokens * 4));
        const label = day.key + " / " + fmtToken(total) + " tokens / " + fmtToken(day.row.request_count || 0) + " requests";
        return '<div class="usage-day-cell level-' + level + '" title="' + escHtml(label) + '">' +
            '<span>' + escHtml(day.key.slice(5)) + '</span>' +
            '<strong>' + fmtToken(total) + '</strong>' +
        '</div>';
    }).join("");
}

function renderUsageLogs(data) {
    const tbody = byId("usage-log-body");
    const count = byId("usage-log-count");
    const logs = data.logs || [];
    if (count) count.textContent = logs.length + " 条";
    if (!tbody) return;
    if (!logs.length) {
        tbody.innerHTML = '<tr><td colspan="9"><div class="memory-card-empty">暂无请求记录</div></td></tr>';
        return;
    }
    tbody.innerHTML = logs.map(log => `
            <tr>
                <td class="col-time"><span class="time-text">${escHtml(log.created_at || "-")}</span></td>
                <td><span class="usage-model-name">${escHtml(log.model || "-")}</span></td>
                <td>${escHtml(log.provider || "-")}</td>
                <td>${log.stream ? "yes" : "no"}</td>
                <td>${fmtToken(log.input_tokens || 0)}</td>
                <td>${fmtToken(log.output_tokens || 0)}</td>
                <td>${fmtToken(log.total_tokens || 0)}</td>
                <td>${fmtToken(log.cache_read_tokens || 0)}</td>
                <td>${fmtToken(log.cache_creation_tokens || 0)}</td>
            </tr>
        `).join("");
}

function fmtToken(n) {
    n = Number(n || 0);
    if (n >= 1000000) return (n / 1000000).toFixed(n >= 10000000 ? 0 : 1) + "M";
    if (n >= 1000) return (n / 1000).toFixed(n >= 10000 ? 0 : 1) + "K";
    return String(Math.round(n));
}

function setText(id, text) {
    const el = byId(id);
    if (el) el.textContent = text;
}
