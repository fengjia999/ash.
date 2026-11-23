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
            throw new Error("等待超过 30 秒，操作结果尚未确认，请刷新核对后再操作");
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
let pendingJsonData = null;
let jsonImportInProgress = false;
let standingBlocks = [];
const standingMutationIds = new Set();
let standingLoadGeneration = 0;
let diariesLoadGeneration = 0;
let standingOverview = {content: "", block_count: 0, character_count: 0};
let standingEditingId = null;
const promotingFlowMemoryIds = new Set();
let longTermMemories = [];
let longTermPending = [];
let diariesLoaded = false;
let diariesDirty = false;
let diariesLoadPromise = null;
let diaryPendingLoaded = false;
let diaryPendingDirty = false;
let diaryPendingLoadPromise = null;
let longTermEditingId = null;
let longTermSelectionMode = false;
let longTermBatchDeleting = false;
let longTermKeywordsGenerating = false;
let longTermKeywordsProgress = "";
const longTermSelectedIds = new Set();
let ltmSummaryDraft = "";
let longTermSummaryTarget = null;
let longTermSummaryGeneration = 0;
const SUPPORTED_BACKUP_SCHEMA_VERSIONS = [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22];
let clearStoredOcrApiKey = false;
let openAiProviderProfiles = [];
let anthropicProviderProfiles = [];
const conversationFrameTimers = {detail: null};
let conversationActivationQueue = Promise.resolve();
let conversationActivationGeneration = 0;
const CONVERSATION_FRAME_TIMEOUT_MS = 15000;

// ============================================
// 初始化
// ============================================
document.addEventListener("DOMContentLoaded", () => {
    initTabs();
    initMemoryEditor();
    initLongTermMemoryEditor();
    initConversationFrames();
    const section = window.location.hash.slice(1);
    switchSection(section === "prompts" || (section && document.getElementById("section-" + section)) ? section : (document.body.classList.contains('phone-dashboard') ? 'home' : 'conversations'));
});

// ============================================
// 应用导航
// ============================================
function switchSection(name, options = {}) {
    if (name === "conversations") name = "chat";
    if (name === "prompts") name = "presets";
    if (name === "quotes") { switchSection("chat", options); openUsageBoard(); return; }
    if (!options.renderOnly && document.body?.classList?.contains("phone-dashboard") && window.AshPhone) {
        window.AshPhone.navigate(name);
        return;
    }
    if (typeof closeUsageBoard === "function") closeUsageBoard(false);
    document.querySelectorAll(".section").forEach(section => {
        section.classList.toggle("active", section.id === "section-" + name);
    });

    if (name === "export") {
        loadExportStats();
    }
    if (name === "standing") {
        window.AshArchive?.enter();
        loadFragmentPage();
        loadStandingMemory();
        const view = document.querySelector("[data-standing-view].active")?.dataset.standingView;
        if (view === "long-term") loadLongTermMemory();
    }
    if (name === "diary") loadDiaryNotebook();
    if (name === "quotes") {
        loadTokenUsage();
    }
    if (name === "heartbeats") {
        loadHeartbeatSettings();
        loadHeartbeatActivities();
    }
    if (name === "presets") {
        loadIdentityPresets();
        loadPromptConsoleFrame();
    }
    if (["suppliers", "supplier-route"].includes(name)) loadRouteSettings(name === "supplier-route");
    if (["suppliers", "supplier-openai", "supplier-anthropic", "settings"].includes(name)) {
        loadAnthropicProviders();
        loadOpenAiProviders();
    }
    if (["settings", "recall"].includes(name)) loadConversationModelSettings(name === "recall" ? "recall" : "generation");
    if (name === "settings") { loadOcrSettings(); loadMcpSettings(); }
    window.AshPhone?.presentSection(name);
}

function loadPromptConsoleFrame() {
    const frame = byId("prompt-console-frame");
    if (frame && !frame.getAttribute("src")) {
        frame.src = "/prompt?embedded=dashboard";
    }
}


function switchTo(section) {
    switchSection(section);
}

window.addEventListener("message", event => {
    const frame = byId("prompt-console-frame");
    if (event.origin !== window.location.origin || event.source !== frame?.contentWindow) return;
    if (event.data?.type !== "memory-gateway-prompt-height") return;
    const height = Number(event.data.height);
    if (Number.isFinite(height) && height > 0) frame.style.height = Math.min(50000, Math.max(240, Math.ceil(height))) + "px";
});

function initConversationFrames() {
    ["detail"].forEach(mode => {
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
    status.dataset.state = state;
    if (conversationFrameTimers[mode]) {
        clearTimeout(conversationFrameTimers[mode]);
        conversationFrameTimers[mode] = null;
    }
    if (state === "ready") {
        status.hidden = true;
        return;
    }
    status.hidden = false;
    retry.hidden = state !== "error" && state !== "slow";
    text.textContent = message || (state === "error" ? "加载失败" : "正在加载…");
    if (state === "loading") {
        conversationFrameTimers[mode] = setTimeout(() => {
            setConversationFrameStatus(mode, "slow", "加载较慢，仍在等待；可继续等待或重试");
        }, CONVERSATION_FRAME_TIMEOUT_MS);
    }
}

function retryConversationFrame(mode) {
    if (mode === "detail") {
        const frame = byId("conversation-detail-frame");
        const src = frame?.dataset.contextSrc;
        if (!frame || !src) return;
        setConversationFrameStatus("detail", "loading", "正在重新加载消息…");
        frame.contentWindow.location.replace(src);
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
        return true;
    }).catch(error => {
        console.error("激活会话失败：", error);
        if (generation === conversationActivationGeneration) {
            alert("切换会话失败：" + error.message + "，请重新选择会话");
        }
        return false;
    });
    return conversationActivationQueue;
}

function openConversationDetail(conversationId, created = false, options = {}) {
    const id = Number(conversationId);
    if (!Number.isInteger(id) || id <= 0) return;
    const layer = byId("conversation-detail-layer");
    const frame = byId("conversation-detail-frame");
    if (!layer || !frame) return;
    if (frame.contentWindow?.isChatBusy?.()) { alert("请等待回复完成，或先停止接收，再切换会话"); return; }
    if (!options.renderOnly && window.AshPhone) {
        window.AshPhone.navigateConversation(id, created);
        return;
    }
    document.querySelectorAll(".section").forEach(section => section.classList.toggle("active", section.id === "section-conversations"));
    const params = new URLSearchParams({
        embedded: "detail",
        conversation_id: String(id),
    });
    if (created) params.set("created", "1");
    const src = "/context?" + params.toString();
    if (!frame.dataset.contextSrc || frame.dataset.conversationId !== String(id)) {
        frame.dataset.contextSrc = src;
        frame.dataset.conversationId = String(id);
        setConversationFrameStatus("detail", "loading", "正在加载消息…");
        frame.contentWindow.location.replace(src);
    }
    layer.classList.add("open");
    layer.setAttribute("aria-hidden", "false");
    window.AshPhone?.presentConversation();
}

function closeConversationDetail() {
    const layer = byId("conversation-detail-layer");
    const frame = byId("conversation-detail-frame");
    if (frame?.contentWindow?.isChatBusy?.()) return;
    if (!layer || !layer.classList.contains("open")) return;
    frame?.contentWindow?.AshChatUI?.saveDraft();
    window.AshPhone?.back();
}

window.addEventListener("message", event => {
    if (event.origin !== window.location.origin || !event.data) return;
    if (event.source !== byId("conversation-detail-frame")?.contentWindow) return;
    if (event.data.type === "memory-gateway-open-conversation") {
        openConversationDetail(event.data.conversationId, Boolean(event.data.created));
    } else if (event.data.type === "memory-gateway-close-conversation") {
        closeConversationDetail();
    } else if (event.data.type === "memory-gateway-context-status") {
        const mode = event.data.mode;
        if (mode !== "detail") return;
        if (mode === "detail") {
            const expected = Number(byId("conversation-detail-frame")?.dataset.conversationId || 0);
            const received = Number(event.data.conversationId || 0);
            if (expected && received && expected !== received) return;
        }
        setConversationFrameStatus(mode, event.data.status, event.data.message);
    }
});

document.addEventListener("keydown", event => {
    if (event.key === "Escape" && byId("section-conversations")?.classList.contains("active") && byId("conversation-detail-layer")?.classList.contains("open")) {
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

    } catch (e) {
        showImportResult("error", "❌ 请求失败：" + e.message);
    }
}

async function previewJson() {
    if (jsonImportInProgress) return;
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
        if (isBackupPayload && parsed.schema_version >= 22 && !Array.isArray(parsed.diary_monthly_summaries)) {
            showImportResult('error', '备份缺少月度总结，请重新导出完整文件');
            resetJsonPreview(); return;
        }
        if (isBackupPayload && parsed.schema_version >= 21 &&
            ['identity_presets','flow_memory_settings'].some(section => !Array.isArray(parsed[section]))) {
            showImportResult('error','备份缺少人物预设或流动记忆设置，请重新导出完整文件');
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
            const diaryCount = Array.isArray(parsed.long_term_memories)
                ? parsed.long_term_memories.filter(memory => {
                    const metadata = typeof memory?.metadata === "string"
                        ? JSON.parse(memory.metadata || "{}")
                        : (memory?.metadata || {});
                    return metadata.entry_kind !== "fragment";
                }).length
                : 0;
            const longTermPendingCount = Array.isArray(parsed.long_term_memory_proposals)
                ? parsed.long_term_memory_proposals.length
                : 0;
            const conversations = Array.isArray(parsed.conversations) ? parsed.conversations.length : 0;
            const messages = Array.isArray(parsed.context_messages) ? parsed.context_messages.length : 0;
            const prompts = Array.isArray(parsed.prompt_sections) ? parsed.prompt_sections.length : 0;
            const notes = Array.isArray(parsed.cover_notes) ? parsed.cover_notes.length : 0;
            const summaries = Array.isArray(parsed.conversations)
                ? parsed.conversations.reduce(
                    (count, conversation) => count
                        + (conversation.handoff_draft ? 1 : 0)
                        + (conversation.handoff_summary ? 1 : 0),
                    0
                )
                : 0;
            html += '<p><b>' + (parsed.backup_options?.include_messages === false ? '轻量备份' : '完整备份') + '</b></p>';
            html += '<div class="preview-item">记忆条目 ' + standing
                + ' 条 · 日记 ' + diaryCount + ' 篇 · 日记 Pending '
                + longTermPendingCount + ' 条</div>';
            html += '<div class="preview-item">' + (parsed.schema_version >= 22
                ? '月度总结 ' + parsed.diary_monthly_summaries.length + ' 份'
                : '旧版备份不含月度总结，恢复时将清除当前月度总结') + '</div>';
            html += '<div class="preview-item">会话 ' + conversations + ' 个 · 消息 ' + messages + ' 条</div>';
            html += '<div class="preview-item">提示词 ' + prompts + ' 段 · 交接摘要 ' + summaries + ' 份</div>';
            html += '<div class="preview-item">便签 ' + notes + ' 张 · 摆放位置请恢复“本机桌面”备份</div>';
            html += '<div class="preview-item">' + (parsed.schema_version >= 21
                ? '包含人物预设和流动记忆设置'
                : '旧版备份未包含人物预设和流动记忆设置，保留当前设置') + '</div>';
            html += '<label class="transfer-history-option"><input type="checkbox" id="restore-history-messages"'
                + (messages === 0 ? ' disabled' : '') + '>恢复历史消息（' + messages + ' 条，默认跳过）</label>';
            html += '<p class="transfer-restore-note">默认只恢复提示词、记忆、日记、会话信息和摘要。现有历史消息会被清除。</p>';
            html += '<div class="preview-item transfer-danger">恢复会覆盖当前记忆条目、日记和会话</div>';
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

        html += '<br><button id="confirm-json-import" type="button" class="btn ' + (isFullBackup ? 'btn-danger' : 'btn-primary') + '" onclick="confirmJsonImport()">'
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
    if (jsonImportInProgress) return;
    if (!pendingJsonData) {
        showImportResult("error", "请先预览");
        return;
    }

    const isFullBackup = pendingJsonData.kind === "memory_gateway_backup";
    const includeMessages = !isFullBackup || Boolean(byId("restore-history-messages")?.checked);
    // Remove the large arrays before uploading an existing full backup. The
    // server also clears message references and injection state consistently.
    const payload = isFullBackup && !includeMessages
        ? {...pendingJsonData, context_messages: [], conversation_extra_prompt_injections: []}
        : pendingJsonData;
    const historyNote = includeMessages ? "本次包含备份中的历史消息。" : "本次不恢复历史消息，现有历史消息也会被清除。";
    if (isFullBackup && !window.confirm("完整恢复会覆盖当前提示词、记忆、备份中包含的设置、后台任务和全部会话。" + historyNote + "确认继续吗？")) {
        return;
    }

    jsonImportInProgress = true;
    const button = byId("confirm-json-import");
    if (button) button.disabled = true;
    const controller = new AbortController();
    // Allow the server's ten-minute transaction deadline to return its result.
    const timeout = setTimeout(() => controller.abort(), 660000);
    const started = Date.now();
    const updateWaiting = () => {
        const elapsed = Math.floor((Date.now() - started) / 1000);
        showImportResult("info", (isFullBackup ? "恢复中..." : "导入中...")
            + " 已等待 " + elapsed + " 秒，请勿重复提交。"
            + (elapsed >= 30 ? "等待时间较长；服务端可能仍在处理，尚未确认完成。" : ""));
    };
    updateWaiting();
    const waitingTimer = setInterval(updateWaiting, 1000);

    try {
        const resp = await authFetch("/import/memories?include_messages=" + includeMessages, {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(payload),
            signal: controller.signal
        });

        const data = await readJsonResponse(resp);

        if (!resp.ok || data.error) {
            throw new Error(data.error || "HTTP " + resp.status);
        }

        if (data.kind === "memory_gateway_backup") {
            const restored = data.restored || {};
            const diaryCount = Array.isArray(payload.long_term_memories)
                ? payload.long_term_memories.filter(memory => {
                    const metadata = typeof memory?.metadata === "string"
                        ? JSON.parse(memory.metadata || "{}")
                        : (memory?.metadata || {});
                    return metadata.entry_kind !== "fragment";
                }).length
                : 0;
            showImportResult(
                "success",
                "✅ 恢复完成！记忆条目 " + (restored.standing_memory_blocks || 0)
                    + " 条，日记 " + diaryCount
                    + " 篇，长期 Pending " + (restored.long_term_memory_proposals || 0)
                    + " 条，会话 " + (restored.conversations || 0)
                    + " 个，消息 " + (restored.context_messages || 0) + " 条"
            );
        } else {
            showImportResult(
                "success",
                "✅ 导入完成！新增 " + data.imported + " 条，跳过 " + data.skipped + " 条（已存在），总计 " + data.total + " 条"
            );
        }

        if (isFullBackup && document.querySelector('[data-preset-name]')) void refreshIdentityPresetNames();
        resetJsonPreview();
    } catch (e) {
        showImportResult("error", controller.signal.aborted
            ? "等待超过 11 分钟，恢复结果尚未确认，请刷新核对数据并检查服务日志后再操作。"
            : "❌ 请求失败：" + e.message + "。如连接中断，请先核对数据再重试。");
    } finally {
        clearTimeout(timeout);
        clearInterval(waitingTimer);
        jsonImportInProgress = false;
        if (button) button.disabled = false;
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
        const diaryCount = Number((standingData.overview || {}).diary_count) || 0;
        const conversations = Array.isArray(conversationsData.conversations)
            ? conversationsData.conversations
            : [];
        const messageCount = conversations.reduce(
            (sum, conversation) => sum + (Number(conversation.message_count) || 0),
            0
        );
        el.textContent = "记忆条目 " + standingCount + " 条 · 日记 " + diaryCount + " 篇 · 会话 "
            + conversations.length + " 个 · 消息 " + messageCount + " 条";
    } catch (e) {
        el.textContent = "无法加载统计";
    }
}

function doExport() {
    const button = byId("export-download"), status = byId("export-progress");
    if (button.disabled) return;
    const includeMessages = Boolean(byId("export-history-messages")?.checked);
    const exportId = crypto.randomUUID().replaceAll("-", "");
    button.disabled = true; status.textContent = "连接数据库…";
    byId("export-download-frame").src = "/export/memories?include_messages=" + includeMessages + "&export_id=" + exportId;
    const stages = {connecting:"连接数据库",counting:"统计记忆",prompt_sections:"读取提示词",
        identity_presets:"读取人物预设",flow_memory_settings:"读取流动记忆设置",
        memories:"读取记忆",standing_memory_blocks:"读取常驻记忆",long_term_memories:"读取日记",
        long_term_memory_proposals:"读取日记待办",memory_update_proposals:"读取记忆待办",
        conversations:"读取会话",context_messages:"读取聊天消息",conversation_prompt_sources:"读取捕获提示词",
        conversation_extra_prompts:"读取额外提示词",extra_prompt_presets:"读取提示词预设",
        conversation_extra_prompt_injections:"读取注入记录",raw_memory_ledger:"读取记忆来源",
        diary_monthly_summaries:"读取月度总结",cover_notes:"读取便签",nocturne_extraction_jobs:"读取后台任务"};
    const started = Date.now(); let failures = 0, lastProgress = "";
    async function poll() {
        const controller = new AbortController(), timer = setTimeout(()=>controller.abort(),5000);
        try {
            const response = await authFetch("/api/export-progress/" + exportId, {signal:controller.signal});
            if (!response.ok) throw new Error("HTTP " + response.status);
            const data = await readJsonResponse(response);
            if (data.status === "missing") {
                status.textContent = "等待导出状态…";
                if (Date.now()-started > 30000) throw new Error("服务器未找到本次导出记录");
            } else {
                if (!["running", "failed", "interrupted", "completed"].includes(data.status)) {
                    throw new Error("服务器返回了无效的导出状态");
                }
                failures = 0;
                const stage = stages[data.section] || "读取数据";
                const size = (Number(data.bytes_sent || 0)/1024/1024).toFixed(2) + " MB";
                status.textContent = `${stage} · 已读取 ${Number(data.rows || 0).toLocaleString()} 条 · 已发送 ${size} · ${data.elapsed_seconds || 0} 秒`;
                lastProgress = status.textContent;
                if (data.status === "failed") status.textContent = `导出失败：${stage}（${data.error || "未知错误"}）`;
                if (data.status === "interrupted") status.textContent = `导出中断：${stage}，连接断开或请求被取消`;
                if (data.status === "completed") status.textContent = `发送完成 · ${size}`;
                if (data.status !== "running") { button.disabled = false; return; }
            }
        } catch (error) {
            const reason = controller.signal.aborted ? "进度请求超时" : (error.message || "网络连接失败");
            const detail = lastProgress ? "；最后进度：" + lastProgress : "；尚未收到导出进度";
            status.textContent = "暂时无法读取导出状态（" + reason + "），正在重试" + detail;
            if (++failures >= 3) {
                status.textContent = "无法确认导出结果（" + reason + "）" + detail + "。若下载已中断，请提供此提示和后端错误日志";
                button.disabled = false; return;
            }
        } finally { clearTimeout(timer); }
        setTimeout(poll,1000);
    }
    poll();
}

// ============================================
// 记忆
// ============================================
let fragmentCategory = "";
let fragmentImportanceMax = "";
let fragmentBefore = null;
let fragmentRequest = 0;
let editingFragment = null;
function openFragmentEditor(row = null) {
    const dialog = byId("fragment-editor"), form = dialog.querySelector("form");
    editingFragment = row;
    form.reset();
    form.elements.content.value = row?.content || "";
    for (const box of form.querySelectorAll("[name=category]")) box.checked = Boolean(row?.tags.includes(box.value));
    form.elements.importance.value = row?.importance ?? 5;
    byId("fragment-editor-title").textContent = row ? "编辑记忆片段" : "写记忆片段";
    byId("fragment-delete").hidden = !row;
    form.querySelector("[role=status]").textContent = "";
    dialog.showModal();
}
function deleteManualFragment(form) {
    if (editingFragment && confirm("删除这条记忆片段？删除后无法恢复。")) submitFragment(form, "DELETE");
}
function saveManualFragment(form) {
    return submitFragment(form, editingFragment ? "PUT" : "POST");
}
async function submitFragment(form, method) {
    const row = editingFragment, dialog = form.closest("dialog");
    const payload = {};
    const status = form.querySelector("[role=status]");
    if (method !== "DELETE") {
        payload.content = form.elements.content.value.trim();
        const importance = form.elements.importance.valueAsNumber;
        if (!row || importance !== (row.importance ?? 5)) {
            payload.importance = importance;
            if (row) payload.original_importance = row.importance ?? null;
        }
        payload.categories = [...form.querySelectorAll("input:checked")].map(node => node.value);
        if (!payload.content || !payload.categories.length) {status.textContent = "请填写正文并选择类别。"; return;}
    }
    if (row) {
        payload.original_content = row.content;
        payload.original_categories = row.tags;
    }
    const buttons = form.querySelectorAll("button");
    buttons.forEach(button => { button.disabled = true; });
    const preventClose = event => event.preventDefault();
    dialog.addEventListener("cancel", preventClose);
    try {
        await saveDashboardJson("/api/memory-fragments" + (row ? "/" + row.id : ""), {
            method, headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload)
        });
        dialog.close();
        if (row) await loadFragmentPage();
        else {
            byId("fragment-query").value = "";
            byId("fragment-importance").value = "";
            fragmentImportanceMax = "";
            selectFragmentCategory(byId("fragment-filters").querySelector("button"));
        }
    } catch (error) { status.textContent = error.message; }
    finally {
        buttons.forEach(button => { button.disabled = false; });
        dialog.removeEventListener("cancel", preventClose);
    }
}
function selectFragmentCategory(button) {
    for (const node of byId("fragment-filters").querySelectorAll("button")) node.setAttribute("aria-pressed", String(node === button));
    fragmentCategory = button.textContent === "全部" ? "" : button.textContent;
    loadFragmentPage();
}
async function loadFragmentPage(more = false) {
    const token = ++fragmentRequest;
    const next = byId("fragment-more");
    const query = new URLSearchParams({query:byId("fragment-query").value.trim(), category:fragmentCategory});
    const importanceSelect = byId("fragment-importance");
    fragmentImportanceMax = importanceSelect.value;
    importanceSelect.closest(".importance-chip").classList.toggle("is-active", Boolean(fragmentImportanceMax));
    if (fragmentImportanceMax) query.set("max_importance", fragmentImportanceMax);
    if (more && fragmentBefore) query.set("before", fragmentBefore);
    next.disabled = true;
    try {
        const rows = await saveDashboardJson("/api/memory-fragments?" + query);
        if (token !== fragmentRequest) return;
        window.AshArchive.renderFragments(rows, more);
        fragmentBefore = rows.at(-1)?.id;
        next.hidden = rows.length < 40;
    } catch (error) {
        if (token === fragmentRequest) {
            if (!more) {
                window.AshArchive.renderFragments([], false);
                fragmentBefore = null;
                next.hidden = true;
            }
            byId("fragment-empty").hidden = false;
            byId("fragment-empty").textContent = "读取失败：" + error.message;
        }
    } finally {
        if (token === fragmentRequest) next.disabled = false;
    }
}

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
    stats.textContent = active + " 条记忆" + (pending ? " · " + pending + " 条待确认" : "");
}

function switchStandingView(name) {
    const viewName = ["directory", "long-term"].includes(name)
        ? name
        : "directory";
    document.querySelectorAll("[data-standing-view]").forEach(button => {
        button.classList.toggle("active", button.dataset.standingView === viewName);
    });
    document.querySelectorAll(".standing-view").forEach(view => {
        view.classList.toggle("active", view.id === "standing-view-" + viewName);
    });
    if (viewName === "long-term") {
        loadVisibleLongTermView(viewName);
    }
}

function loadVisibleLongTermView(viewName) {
    if (viewName === "long-term") {
        loadDiaries();
        loadDiaryPending();
    }
}

// Refresh only the visible long-term-memory branch.
async function loadLongTermMemory() {
    const view = document.querySelector("[data-standing-view].active")?.dataset.standingView;
    if (view === "long-term" || byId("diary-notebook")?.classList.contains("open")) {
        return Promise.all([loadDiaries(), loadDiaryPending()]);
    }
}

function markDiariesDirty() {
    diariesDirty = true;
    ++diariesLoadGeneration;
}

function markDiaryPendingDirty() {
    diaryPendingDirty = true;
}


async function loadDiaries() {
    if (diariesLoaded && !diariesDirty) {
        renderLongTermMemories();
        return;
    }
    if (diariesLoadPromise) return diariesLoadPromise;
    const generation = ++diariesLoadGeneration;
    diariesLoadPromise = (async () => {
        try {
            const resp = await authFetch("/api/diaries");
            const data = await readJsonResponse(resp);
            if (!resp.ok || data.error) throw new Error(data.error || "HTTP " + resp.status);
            if (generation !== diariesLoadGeneration) return;
            longTermMemories = Array.isArray(data.diaries) ? data.diaries : [];
            diariesLoaded = true;
            diariesDirty = false;
            const availableIds = new Set(longTermMemories.map(memory => Number(memory.id)));
            [...longTermSelectedIds].forEach(id => {
                if (!availableIds.has(id)) longTermSelectedIds.delete(id);
            });
            renderLongTermMemories();
            renderPendingLongTermMemories();
        } catch (e) {
            if (generation !== diariesLoadGeneration) return;
            showLongTermMsg("error", "加载日记失败：" + e.message);
        } finally {
            diariesLoadPromise = null;
        }
    })();
    return diariesLoadPromise;
}

async function loadDiaryPending() {
    if (diaryPendingLoaded && !diaryPendingDirty) {
        renderPendingLongTermMemories();
        return;
    }
    if (diaryPendingLoadPromise) return diaryPendingLoadPromise;
    diaryPendingLoadPromise = (async () => {
        try {
            const resp = await authFetch("/api/diaries/pending");
            const data = await readJsonResponse(resp);
            if (!resp.ok || data.error) throw new Error(data.error || "HTTP " + resp.status);
            longTermPending = Array.isArray(data.pending) ? data.pending : [];
            diaryPendingLoaded = true;
            diaryPendingDirty = false;
            renderPendingLongTermMemories();
        } catch (e) {
            showLongTermMsg("error", "加载日记 Pending 失败：" + e.message);
        } finally {
            diaryPendingLoadPromise = null;
        }
    })();
    return diaryPendingLoadPromise;
}


function applySavedDiary(diary) {
    ++diariesLoadGeneration;
    const listItem = {
        id: diary.id,
        title: diary.title || "",
        diary_date: diary.diary_date || "",
        keywords: Array.isArray(diary.keywords) ? diary.keywords : [],
    };
    const index = longTermMemories.findIndex(item => Number(item.id) === Number(diary.id));
    if (index < 0) {
        longTermMemories.push(listItem);
        standingOverview.diary_count = (Number(standingOverview.diary_count) || 0) + 1;
    } else longTermMemories[index] = listItem;
    diariesLoaded = true;
    diariesDirty = true;
    renderStandingStats();
    renderLongTermMemories();
    renderPendingLongTermMemories();
}

// Bound comparisons so large proposals cannot freeze the review screen.
function pendingDiffParts(before, after, split = true) {
    let prefix = 0, suffix = 0;
    while (prefix < before.length && prefix < after.length && before[prefix] === after[prefix]) prefix++;
    while (suffix < before.length - prefix && suffix < after.length - prefix &&
        before[before.length - 1 - suffix] === after[after.length - 1 - suffix]) suffix++;
    const head = before.slice(0, prefix).join("");
    const tail = suffix ? before.slice(before.length - suffix).join("") : "";
    const left = before.slice(prefix, before.length - suffix);
    const right = after.slice(prefix, after.length - suffix);
    const parts = head ? [{kind: "same", text: head}] : [];
    if (left.length && right.length && left.length * right.length <= (split ? 1000000 : 4000000)) {
        const width = right.length + 1;
        const lengths = new Uint32Array((left.length + 1) * width);
        for (let i = left.length - 1; i >= 0; i--) {
            for (let j = right.length - 1; j >= 0; j--) {
                lengths[i * width + j] = left[i] === right[j]
                    ? 1 + lengths[(i + 1) * width + j + 1]
                    : Math.max(lengths[(i + 1) * width + j], lengths[i * width + j + 1]);
            }
        }
        let i = 0, j = 0;
        const append = (kind, text) => {
            if (parts.at(-1)?.kind === kind) parts.at(-1).text += text;
            else parts.push({kind, text});
        };
        while (i < left.length || j < right.length) {
            if (i < left.length && j < right.length && left[i] === right[j]) {
                append("same", left[i++]); j++;
            } else if (i < left.length && (j === right.length ||
                lengths[(i + 1) * width + j] >= lengths[i * width + j + 1])) {
                append("removed", left[i++]);
            } else append("added", right[j++]);
        }
    } else if (left.length && right.length && split) {
        const sentences = value => value.join("").match(/[^。！？.!?\n]+[。！？.!?\n]*|[。！？.!?\n]+/gu) || [];
        parts.push(...pendingDiffParts(sentences(left), sentences(right), false));
    } else {
        if (left.length) parts.push({kind: "removed", text: left.join("")});
        if (right.length) parts.push({kind: "added", text: right.join("")});
    }
    if (tail) parts.push({kind: "same", text: tail});
    return parts;
}

function pendingInlineDiff(beforeValue, afterValue) {
    const parts = pendingDiffParts(Array.from(String(beforeValue ?? "")), Array.from(String(afterValue ?? "")));
    return {
        before: parts.filter(part => part.kind !== "added").map(part => part.kind === "removed"
            ? '<del class="pending-diff-removed">' + escHtml(part.text) + '</del>' : escHtml(part.text)).join(""),
        after: parts.filter(part => part.kind !== "removed").map(part => part.kind === "added"
            ? '<mark class="pending-diff-added">' + escHtml(part.text) + '</mark>' : escHtml(part.text)).join(""),
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

function renderDiaryMergeSources(metadata) {
    const sources = metadata && metadata.merge_sources;
    if (!Array.isArray(sources) || !sources.length) return "";
    return '<details class="diary-merge-sources"><summary>查看合并前原文（' + sources.length + ' 篇）</summary>' +
        sources.map(source => '<section><h4>' + escHtml(source.title || "未命名") +
            ' · #' + Number(source.id) + '</h4><div style="white-space:pre-wrap">' +
            escHtml(source.content) + '</div>' + renderDiaryMergeSources(source.metadata) + '</section>').join("") + '</details>';
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
        const mergeSources = proposal.metadata && proposal.metadata.merge_sources;
        const operationLabel = Array.isArray(mergeSources) ? "合并 " + mergeSources.length + " 篇日记 · " + proposal.diary_date : operation === "edit"
            ? "修改 #" + targetId
            : (operation === "delete" ? "删除 #" + targetId : "创建日记");
        const target = proposal.target_diary || (targetId
            ? longTermMemories.find(memory => Number(memory.id) === targetId)
            : null);
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
                '<div class="pending-memory-diff">' + diffHtml + renderDiaryMergeSources(proposal.metadata) + '</div>' +
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
    if (typeof renderDiaryNotebook === "function") renderDiaryNotebook();
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
                '<button type="button" class="long-term-memory-main"' + (longTermSelectionMode ? ' aria-pressed="' + selected + '"' : '') + ' onclick="handleLongTermMemoryCardClick(' + memoryId + ')">' +
                    dateHtml +
                    '<span class="long-term-memory-copy">' +
                        '<span class="long-term-memory-title">' + escHtml(memory.title || "未命名") + '</span>' +
                        '<span class="diary-author-label">' + diaryAuthorLabel(memory) + '</span>' +
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
    const keywordButton = byId("long-term-generate-keywords");
    const busy = longTermBatchDeleting || longTermKeywordsGenerating;
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
        selectAll.disabled = !longTermMemories.length || busy;
    }
    if (deleteButton) {
        deleteButton.textContent = longTermBatchDeleting ? "删除中…" : "删除所选";
        deleteButton.disabled = !selectedCount || busy;
    }
    if (keywordButton) {
        keywordButton.disabled = !selectedCount || busy;
        keywordButton.textContent = longTermKeywordsGenerating ? longTermKeywordsProgress : "生成关键词";
    }
}

function toggleLongTermSelectionMode(force) {
    if (longTermKeywordsGenerating) return;
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
    if (longTermKeywordsGenerating) return;
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
    if (longTermKeywordsGenerating) return;
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
    const editingCurrent = Number(longTermEditingId || 0) === numericId
        && byId("long-term-memory-editor-modal")?.classList.contains("open");
    let memory = null;
    if (numericId > 0 && !editingCurrent) {
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
            id: numericId,
            title: (byId("long-term-memory-title") || {}).value || "",
            content: (byId("long-term-memory-content") || {}).value || "",
            diary_date: (byId("long-term-memory-date") || {}).value || "",
            keywords: parseLongTermKeywords(ltmSummaryDraft),
            author_role: byId("long-term-memory-author").value,
        };
    }
    ++longTermSummaryGeneration;
    longTermSummaryTarget = memory;
    setLongTermSummaryGenerating(false);
    const status = byId("long-term-summary-msg");
    if (status) status.textContent = "";
    byId("long-term-summary-content").value = normalizeLongTermKeywords(memory.keywords).join("\n");
    const modal = byId("long-term-summary-modal");
    modal.classList.add("open");
    modal.setAttribute("aria-hidden", "false");
    requestAnimationFrame(() => byId("long-term-summary-content").focus());
}

function closeLongTermSummaryEditor() {
    ++longTermSummaryGeneration;
    setLongTermSummaryGenerating(false);
    const modal = byId("long-term-summary-modal");
    if (modal) {
        if (modal.contains(document.activeElement)) document.activeElement.blur();
        modal.classList.remove("open");
        modal.setAttribute("aria-hidden", "true");
    }
    const status = byId("long-term-summary-msg");
    if (status) status.textContent = "";
    longTermSummaryTarget = null;
}

function setLongTermSummaryGenerating(busy) {
    const button = byId("long-term-summary-generate");
    button.disabled = busy;
    button.textContent = busy ? "生成中…" : "生成";
    byId("long-term-summary-save").disabled = busy;
    byId("long-term-summary-content").readOnly = busy;
}

async function generateLongTermSummaryKeywords() {
    const target = longTermSummaryTarget;
    if (!target || byId("long-term-summary-generate").disabled) return;
    const status = byId("long-term-summary-msg");
    if (!target.content?.trim()) { status.textContent = "请先填写日记正文"; return; }
    const generation = ++longTermSummaryGeneration;
    setLongTermSummaryGenerating(true);
    status.textContent = "";
    try {
        const response = await authFetch("/api/diaries/keywords-preview", {
            method: "POST", headers: {"Content-Type": "application/json"},
            body: JSON.stringify({title:target.title || "", content:target.content,
                author_role:target.author_role || "assistant"}),
        });
        const data = await readJsonResponse(response);
        if (generation !== longTermSummaryGeneration || target !== longTermSummaryTarget) return;
        if (!response.ok || data.error) throw new Error(data.error || "HTTP " + response.status);
        byId("long-term-summary-content").value = normalizeLongTermKeywords(data.keywords).join("\n");
    } catch (error) {
        if (generation === longTermSummaryGeneration) status.textContent = error.message;
    } finally {
        if (generation === longTermSummaryGeneration) setLongTermSummaryGenerating(false);
    }
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
            if (event.key === "Escape" && !event.isComposing) closeLongTermMemoryEditor();
            if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
                event.preventDefault();
                saveLongTermMemory();
            }
        });
    });
}

function diaryAuthorLabel(memory) {
    return memory?.author_role === "user" ? "用户的日记" : "助手的日记";
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
    byId("long-term-memory-author").value = memory ? (memory.author_role || "assistant") : "user";
    ltmSummaryDraft = memory
        ? normalizeLongTermKeywords(memory.keywords).join("\n")
        : "";
    renderLongTermSummaryPreview();
    byId("long-term-memory-content").value = memory ? (memory.content || "") : "";
    const mergeSources = byId("long-term-merge-sources");
    if (mergeSources) mergeSources.innerHTML = renderDiaryMergeSources(memory && memory.metadata);
    modal.classList.add("open");
    modal.setAttribute("aria-hidden", "false");
    document.body.classList.add("memory-editor-open");
    requestAnimationFrame(() => byId("long-term-memory-title").focus());
}

function closeLongTermMemoryEditor() {
    if (byId("long-term-memory-editor-msg")) byId("long-term-memory-editor-msg").textContent = "";
    const modal = byId("long-term-memory-editor-modal");
    if (modal) {
        if (modal.contains(document.activeElement)) document.activeElement.blur();
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
    if (typeof syncMemoryModalScrollLock === "function") syncMemoryModalScrollLock();
    longTermEditingId = null;
}

async function saveLongTermMemory() {
    const diary_date = byId("long-term-memory-date").value;
    const title = byId("long-term-memory-title").value.trim();
    const keywords = parseLongTermKeywords(ltmSummaryDraft);
    const content = byId("long-term-memory-content").value.trim();
    const author_role = byId("long-term-memory-author").value;
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
                body: JSON.stringify({title, keywords, content, diary_date, author_role}),
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
        longTermMemories = longTermMemories.filter(memory => Number(memory.id) !== Number(id));
        longTermSelectedIds.delete(Number(id));
        standingOverview.diary_count = Math.max(0, (Number(standingOverview.diary_count) || 0) - 1);
        diariesLoaded = true;
        markDiariesDirty();
        renderStandingStats();
        renderLongTermMemories();
    } catch (e) {
        showLongTermMsg("error", "删除失败：" + e.message);
    }
}

async function generateSelectedDiaryKeywords() {
    const ids = [...longTermSelectedIds];
    if (!ids.length || longTermKeywordsGenerating || longTermBatchDeleting) return;
    const hasKeywords = longTermMemories.some(memory => ids.includes(Number(memory.id))
        && normalizeLongTermKeywords(memory.keywords).length);
    if (hasKeywords && !confirm("所选日记已有的关键词将被重新生成，是否继续？")) return;
    longTermKeywordsGenerating = true;
    let succeeded = 0;
    const failures = [];
    try {
        for (const [index, id] of ids.entries()) {
            longTermKeywordsProgress = "生成中 " + (index + 1) + "/" + ids.length + "…";
            updateLongTermSelectionControls();
            try {
                const response = await authFetch("/api/diaries/" + id + "/generate-keywords", {method: "POST"});
                const data = await readJsonResponse(response);
                if (!response.ok || data.error) throw new Error(data.error || "HTTP " + response.status);
                const memory = longTermMemories.find(item => Number(item.id) === Number(id));
                if (memory) memory.keywords = Array.isArray(data.keywords) ? data.keywords : [];
                succeeded++;
                longTermSelectedIds.delete(id);
            } catch (error) {
                failures.push("#" + id + "：" + error.message);
            }
        }
        if (succeeded) markDiariesDirty();
        renderLongTermMemories();
        showLongTermMsg(failures.length ? "error" : "success",
            "已为 " + succeeded + " 篇日记生成关键词" + (failures.length ? "；失败 " + failures.length + " 篇。" + failures.join("；") : ""));
    } finally {
        longTermKeywordsGenerating = false;
        updateLongTermSelectionControls();
    }
}

async function deleteSelectedLongTermMemories() {
    const ids = [...longTermSelectedIds].sort((left, right) => left - right);
    if (!ids.length || longTermBatchDeleting || longTermKeywordsGenerating) return;
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
        const deletedIds = new Set((data.deleted_ids || []).map(Number));
        longTermMemories = longTermMemories.filter(memory => !deletedIds.has(Number(memory.id)));
        longTermSelectedIds.clear();
        longTermSelectionMode = false;
        diariesLoaded = true;
        markDiariesDirty();
        renderLongTermMemories();
        await loadStandingMemory();
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
    if (proposal && proposal.metadata && Array.isArray(proposal.metadata.merge_sources)
        && !confirm("确认用这篇合并稿替换同一天的 " + proposal.metadata.merge_sources.length + " 篇原日记？原文会保存在合并日记中，可展开查看。")) return;
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
        markDiariesDirty();
        markDiaryPendingDirty();
        await Promise.all([loadDiaries(), loadDiaryPending(), loadStandingMemory()]);
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
        markDiaryPendingDirty();
        await Promise.all([loadDiaryPending(), loadStandingMemory()]);
    } catch (e) {
        showLongTermMsg("error", "拒绝失败：" + e.message);
    }
}

function showLongTermMsg(type, text) {
    let container = byId("long-term-summary-modal")?.classList.contains("open")
        ? byId("long-term-summary-msg")
        : byId("long-term-memory-editor-modal")?.classList.contains("open")
            ? byId("long-term-memory-editor-msg") : byId("long-term-msg");
    if (container === byId("long-term-msg") && byId("diary-notebook")?.classList.contains("open")
        && byId("standing-view-long-term")?.hidden) {
        container = byId("diary-notebook-msg");
    }
    if (!container) return;
    container.innerHTML = '<div class="msg msg-' + escHtml(type) + '">' + escHtml(text) + '</div>';
    if (type !== "error") {
        setTimeout(() => {
            if (container.innerHTML.indexOf(escHtml(text)) !== -1) container.innerHTML = "";
        }, 3500);
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
    const flowWindow = standingOverview && standingOverview.flow_window
        ? standingOverview.flow_window : {};
    const flowMaxItems = Math.min(100, Math.max(1, Number(flowWindow.max_items) || 8));
    const flowItemCount = Number(flowWindow.item_count) || flow.length;
    const flowWindowLabel = flowWindow.state === "hard"
        ? "正在整理超出上限的摘要"
        : "当前 " + flowItemCount + " / " + flowMaxItems + " 条";
    if (pendingCount) pendingCount.textContent = pending.length + " 条";
    if (pendingSection) pendingSection.hidden = !pending.length;
    if (pendingEl) pendingEl.innerHTML = pending.map(renderPendingStandingMemoryCard).join("");
    if (activeEl) activeEl.innerHTML = renderMemoryShelf(fixed);
    byId("archive-flow-count").textContent = flowWindowLabel;
    const limit = byId("flowMemoryMaxItems");
    limit.disabled = false;
    limit.value = flowMaxItems;
    byId("archive-flow-save").disabled = false;
    byId("archive-flow-list").innerHTML = flow.length
        ? flow.map(block => renderKelivoMemoryCard(block, "flow")).join("")
        : '<p class="river-note" data-rise>还没有会话摘要</p>';
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
    const targetTitle = target ? String(target.title || target.content || "").split("\n")[0].slice(0, 80) : "";
    const targetHtml = target
        ? '<button type="button" class="btn btn-secondary btn-sm" onclick="openStandingMemoryEditor(' + targetId + ')">查看原记忆 #' + targetId + ' · ' + escHtml(targetTitle) + '</button>'
        : (targetId ? '<span class="pending-diff-empty">原记忆 #' + targetId + ' 已不存在，请拒绝此提案</span>' : '');
    const sourceIds = Array.isArray(metadata.source_diary_ids)
        ? metadata.source_diary_ids.filter(value => Number.isSafeInteger(value) && value > 0) : [];
    const sourceHtml = sourceIds.length > 0
        ? '<div class="pending-diff-label">来源日记' + (sourceIds.length ? ' ' + sourceIds.map(value => '#' + value).join('、') : '') + '</div>' : '';
    return (
        '<article class="pending-memory-card standing-pending-card" data-standing-block-id="' + id + '">' +
            '<div class="pending-memory-head">' +
                '<span class="standing-tag status">' + escHtml(operationLabel) + '</span>' +
                '<div class="row-actions">' +
                    '<button type="button" class="btn btn-primary btn-sm" onclick="approveStandingMemory(' + id + ')">通过</button>' +
                    '<button type="button" class="btn btn-danger btn-sm" onclick="deleteStandingMemory(' + id + ', true)">拒绝</button>' +
                '</div>' +
            '</div>' +
            '<div class="pending-memory-diff">' + targetHtml + sourceHtml + diffHtml + '</div>' +
        '</article>'
    );
}

function renderKelivoMemoryCard(block, zone, number = "") {
    const id = Number(block.id);
    const enteredOn = String(block.created_at || "").slice(0, 10);
    const title = zone === "flow" ? escHtml(block.title || "会话摘要") : "";
    const promoteButton = zone === "flow"
        ? '<button type="button" class="kelivo-icon-btn promote" data-promote-id="' + id + '" aria-label="归档到日记" title="归档到日记" onclick="promoteFlowMemoryToLongTerm(' + id + ')">' +
            '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">' +
                '<path d="M12 19V5M5 12l7-7 7 7"/>' +
            '</svg>' +
          '</button>'
        : "";
    return `<article class="stand" data-standing-block-id="${id}">
        <i class="ctop" data-rule></i><i class="pin" data-node></i>
        <span class="no">${zone === "flow" ? escHtml(enteredOn) : escHtml(number)}</span>
        <button class="read" type="button" aria-label="编辑记忆" onclick="openStandingMemoryEditor(${id})">
            ${title ? `<strong>${title}</strong>` : ""}<p>${escHtml(block.content || "")}</p>
        </button>
        <div class="standing-actions">${promoteButton}
            <button type="button" onclick="deleteStandingMemory(${id})">删除</button>
        </div>
    </article>`;
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
    byId("memory-editor-modal").addEventListener("pointerdown", event => {
        // Keep keyboard layout stable until the button's click has completed.
        if (document.activeElement === textarea && event.target.closest("button")) event.preventDefault();
    });
    textarea.addEventListener("input", scheduleMemoryCaret);
    window.visualViewport?.addEventListener("resize", scheduleMemoryCaret);
    window.addEventListener("resize", scheduleMemoryCaret);
    for (const type of ["pointerdown", "wheel"]) textarea.addEventListener(type, () => {
        cancelAnimationFrame(memoryCaretFrame);
        memoryCaretFrame = 0;
    }, {passive: true});
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

let memoryCaretFrame = 0;
function scheduleMemoryCaret() {
    cancelAnimationFrame(memoryCaretFrame);
    // The shared viewport owner resizes the shell first, then measure its textarea.
    memoryCaretFrame = requestAnimationFrame(() => {
        memoryCaretFrame = requestAnimationFrame(keepMemoryCaretVisible);
    });
}

function keepMemoryCaretVisible() {
    memoryCaretFrame = 0;
    const textarea = byId("memory-editor-content");
    if (!textarea || textarea.readOnly || document.activeElement !== textarea) return;
    const style = getComputedStyle(textarea);
    const mirror = document.createElement("div");
    mirror.style.cssText = "position:fixed;left:-10000px;top:0;visibility:hidden;white-space:pre-wrap;overflow-wrap:break-word;";
    for (const key of ["font", "lineHeight", "letterSpacing", "padding", "border", "boxSizing", "wordBreak", "tabSize"]) mirror.style[key] = style[key];
    mirror.style.width = textarea.clientWidth + "px";
    mirror.textContent = textarea.value.slice(0, textarea.selectionEnd);
    const caret = document.createElement("span");
    caret.textContent = textarea.value.slice(textarea.selectionEnd) || "\u200b";
    mirror.append(caret);
    document.body.append(mirror);
    const top = caret.offsetTop, line = parseFloat(style.lineHeight) || 26;
    if (top < textarea.scrollTop + 8) textarea.scrollTop = Math.max(0, top - 8);
    else if (top + line > textarea.scrollTop + textarea.clientHeight - 8) {
        textarea.scrollTop = top + line - textarea.clientHeight + 8;
    }
    mirror.remove();
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
    requestAnimationFrame(() => textarea.focus({preventScroll: true}));
}

function closeStandingMemoryEditor() {
    cancelAnimationFrame(memoryCaretFrame);
    memoryCaretFrame = 0;
    if (byId("memory-editor-msg")) byId("memory-editor-msg").textContent = "";
    const modal = byId("memory-editor-modal");
    const textarea = byId("memory-editor-content");
    if (modal) {
        modal.classList.remove("open");
        modal.setAttribute("aria-hidden", "true");
    }
    if (textarea) { textarea.blur(); textarea.value = ""; }
    document.body.classList.remove("memory-editor-open");
    standingEditingId = null;
}

async function saveStandingMemory() {
    const editId = standingEditingId;
    const isEdit = Number.isFinite(Number(editId)) && Number(editId) > 0;
    const content = (byId("memory-editor-content") || {}).value || "";
    if (!content.trim()) {
        showStandingMsg("error", "记忆内容不能为空");
        return;
    }
    const generatedTitle = content.trim().split(/\r?\n/)[0].slice(0, 80) || "Memory";
    const payload = isEdit
        ? {content}
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
    let data;
    try {
        data = await saveDashboardJson("/api/standing-memory" + (isEdit ? "/" + editId : ""), {
            method: isEdit ? "PUT" : "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(payload),
        });
        if (!data.block || !Number.isFinite(Number(data.block.id))) {
            throw new Error("服务器未返回保存后的记忆");
        }
    } catch (e) {
        showStandingMsg("error", "保存失败：" + e.message);
        return;
    } finally {
        if (saveButton) {
            saveButton.disabled = false;
            saveButton.textContent = "保存";
        }
    }

    ++standingLoadGeneration;
    const index = standingBlocks.findIndex(item => Number(item.id) === Number(data.block.id));
    if (index < 0) standingBlocks.push(data.block);
    else standingBlocks[index] = data.block;
    closeStandingMemoryEditor();
    let renderFailed = false;
    try {
        renderStandingStats();
        const card = document.querySelector(`[data-standing-block-id="${Number(data.block.id)}"]`);
        if (isEdit && card && data.block.status === "active") {
            card.outerHTML = renderKelivoMemoryCard(data.block, data.block.layer === "recent" ? "flow" : "fixed");
        } else {
            renderStandingLists();
        }
    } catch (e) {
        renderFailed = true;
        console.error("常驻记忆已保存，但列表刷新失败：", e);
    }
    showStandingMsg("success", renderFailed ? "已保存，请刷新页面查看最新内容" : "已保存");
}

function nextStandingSortOrder(parentId, status) {
    const siblings = standingBlocks.filter(block => {
        const blockParent = block.parent_id == null ? null : Number(block.parent_id);
        return block.status === status && blockParent === (parentId == null ? null : Number(parentId));
    });
    if (!siblings.length) return 10;
    return Math.max(...siblings.map(block => Number.isFinite(Number(block.sort_order)) ? Number(block.sort_order) : 0)) + 10;
}

function setStandingMutationBusy(id, busy) {
    document.querySelectorAll(`[data-standing-block-id="${Number(id)}"] button`).forEach(button => {
        button.disabled = busy;
    });
}

function applyStandingMutation(removedIds, updatedBlock = null) {
    ++standingLoadGeneration; // Ignore list reads started before this mutation completed.
    const removed = new Set(removedIds.map(Number));
    standingBlocks = standingBlocks.filter(block => !removed.has(Number(block.id)));
    // Only deleted blocks reparent children; edits keep the existing hierarchy.
    if (updatedBlock) removed.delete(Number(updatedBlock.id));
    standingBlocks.forEach(block => {
        if (block.parent_id != null && removed.has(Number(block.parent_id))) block.parent_id = null;
    });
    if (updatedBlock) standingBlocks.push(updatedBlock);
    if (standingOverview.flow_window) {
        standingOverview.flow_window.item_count = standingBlocks.filter(
            block => block.status === "active" && block.layer === "recent"
        ).length;
    }
    try {
        renderStandingStats();
        renderStandingLists();
        standingMutationIds.forEach(id => setStandingMutationBusy(id, true));
        return true;
    } catch (error) {
        console.error("记忆操作已完成，但列表刷新失败：", error);
        return false;
    }
}

async function approveStandingMemory(id) {
    id = Number(id);
    if (standingMutationIds.has(id)) return;
    const block = standingBlocks.find(item => Number(item.id) === id);
    const metadata = normalizeStandingMetadata(block && block.metadata);
    if (metadata.pending_operation === "delete"
        && !confirm("确定通过删除记忆 #" + metadata.target_block_id + " 的请求？")) return;
    standingMutationIds.add(id);
    setStandingMutationBusy(id, true);
    showStandingMsg("info", "正在执行…");
    try {
        const data = await saveDashboardJson("/api/standing-memory/" + id + "/approve", {method: "POST"});
        if (!data.block || !Number.isFinite(Number(data.block.id))) throw new Error("服务器未返回处理后的记忆");
        const rendered = applyStandingMutation([id, data.block.id], data.operation === "delete" ? null : data.block);
        showStandingMsg("success", rendered ? "请求已执行" : "请求已执行，请刷新页面查看最新内容");
    } catch (e) {
        showStandingMsg("error", "执行失败：" + e.message);
    } finally {
        standingMutationIds.delete(id);
        setStandingMutationBusy(id, false);
    }
}

async function deleteStandingMemory(id, rejectingPending = false) {
    id = Number(id);
    if (standingMutationIds.has(id)) return;
    const message = rejectingPending ? "确定拒绝这个 pending 请求？" : "确定删除记忆 #" + id + "？";
    if (!confirm(message)) return;
    standingMutationIds.add(id);
    setStandingMutationBusy(id, true);
    showStandingMsg("info", "正在删除…");
    try {
        await saveDashboardJson("/api/standing-memory/" + id, {method: "DELETE"});
        const rendered = applyStandingMutation([id]);
        const success = rejectingPending ? "已拒绝" : "已删除";
        showStandingMsg("success", rendered ? success : success + "，请刷新页面查看最新内容");
    } catch (e) {
        showStandingMsg("error", "删除失败：" + e.message);
    } finally {
        standingMutationIds.delete(id);
        setStandingMutationBusy(id, false);
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
        markDiariesDirty();
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
let apiConfigurationGeneration = 0, apiConfigurationKeySource = null;
let apiConfigurationPresets = [];
let apiConfigurationSuppliers = [], apiConfigurationSupplierSource = null;
let apiModelsGeneration = 0;
function resetApiModels() {
    ++apiModelsGeneration;
    byId("route-model-picker").hidden = true;
    byId("routeModels").replaceChildren();
    byId("route-models-msg").textContent = "";
    byId("route-fetch-models").disabled = false;
}
const routeThinkingLevels = ['auto','low','medium','high','max'];
function syncRouteThinking() {
    const label=['Auto','Low','Medium','High','Max'][Number(byId('routeThinking').value)];
    byId('route-thinking-value').textContent=label;
    const slider = byId('routeThinking');
    const step = Number(slider.value);
    slider.parentElement.style.setProperty('--thinking-fill', `calc(12px + (100% - 24px) * ${step / 4})`);
    slider.parentElement.querySelectorAll('.route-thinking-dots i').forEach((dot, index) => {
        dot.classList.toggle('is-active', index <= step);
    });
    byId('routeThinking').setAttribute('aria-valuetext',label);
}
function apiConfigurationDraft() {
    return {thinking_effort:routeThinkingLevels[Number(byId("routeThinking").value)], provider:byId("routeProvider").value, api_url:byId("routeApiUrl").value.trim(),
        api_key:byId("routeApiKey").value.trim(), model:byId("routeModel").value.trim(),
        ...(apiConfigurationKeySource == null ? {} : {source_preset_id:apiConfigurationKeySource}),
        ...(apiConfigurationSupplierSource || {})};
}
function fillApiConfiguration(config) {
    byId('routeThinking').value=Math.max(0,routeThinkingLevels.indexOf(config.thinking_effort || 'auto'));
    syncRouteThinking();
    apiConfigurationSupplierSource = null;
    byId("routeSupplier").value = "";
    byId("routeProvider").value = config.provider || "auto";
    byId("routeApiUrl").value = config.api_url || "";
    byId("routeModel").value = config.model || "";
    byId("routeApiKey").value = "";
    byId("routeApiKey").placeholder = config.api_key_configured
        ? "已保存 " + config.api_key_hint : "填写密钥";
    resetApiModels();
}
async function loadApiConfigurationSuppliers(generation) {
    const groups = await Promise.all(["openai", "anthropic"].map(async provider => {
        const data = await saveDashboardJson("/api/" + provider + "-providers");
        return {provider, profiles:data.profiles || []};
    }));
    if (generation !== apiConfigurationGeneration) return;
    apiConfigurationSuppliers = [];
    const select = byId("routeSupplier");
    select.replaceChildren(new Option("当前配置 / 手动填写", ""));
    for (const {provider, profiles} of groups) {
        if (!profiles.length) continue;
        const group = document.createElement("optgroup");
        group.label = provider === "openai" ? "OpenAI 兼容" : "Anthropic";
        for (const profile of profiles) {
            const value = provider + ":" + profile.id;
            apiConfigurationSuppliers.push({...profile, provider, value});
            group.append(new Option(profile.name, value));
        }
        select.append(group);
    }
}
function selectApiConfigurationSupplier(value) {
    const supplier = apiConfigurationSuppliers.find(item => item.value === value);
    apiConfigurationKeySource = null;
    apiConfigurationSupplierSource = supplier ? {source_provider_type:supplier.provider, source_provider_id:supplier.id} : null;
    if (supplier) {
        byId("routeProvider").value = supplier.provider;
        byId("routeApiUrl").value = supplier.api_url;
        byId("routeApiKey").value = "";
        byId("routeApiKey").placeholder = supplier.api_key_configured ? "已保存 " + supplier.api_key_hint : "填写密钥";
    } else {
        byId("routeApiKey").placeholder = "留空保留当前密钥";
    }
    resetApiModels();
}
async function loadRouteSettings(fillForm = true) {
    const generation = fillForm ? ++apiConfigurationGeneration : null;
    try {
        const data = await saveDashboardJson("/api/route-settings");
        byId("settings-route-label").textContent = [data.provider, data.model].filter(Boolean).join(" · ");
        if (!fillForm || generation !== apiConfigurationGeneration) return;
        apiConfigurationKeySource = null;
        fillApiConfiguration(data);
        byId("route-settings-note").textContent = "";
        await Promise.all([loadApiConfigurationPresets(), loadApiConfigurationSuppliers(generation)]);
    } catch (e) {
        if (fillForm && generation === apiConfigurationGeneration) byId("route-settings-note").textContent = "加载失败：" + e.message;
    }
}
async function persistApiConfiguration(config) {
    await saveDashboardJson("/api/route-settings", {method:"PUT", headers:{"Content-Type":"application/json"}, body:JSON.stringify(config)});
    byId("conversation-detail-frame")?.contentWindow?.postMessage({type:"ash-chat-configuration-changed"},location.origin);
}
async function saveRouteSettings() {
    const msg = byId("route-settings-msg"), button = byId("api-configuration-form").querySelector('[type="submit"]');
    button.disabled = true; msg.textContent = "保存中…";
    try {
        await persistApiConfiguration(apiConfigurationDraft());
        await loadRouteSettings(); msg.textContent = "设置已保存";
    } catch (e) { msg.textContent = "保存失败：" + e.message; }
    finally { button.disabled = false; }
}
async function loadApiConfigurationPresets() {
    const data = await saveDashboardJson("/api/api-presets");
    apiConfigurationPresets = data.presets || [];
    const list = byId("api-preset-list"); list.replaceChildren();
    if (!apiConfigurationPresets.length) { list.textContent = "还没有保存的配置"; return; }
    for (const preset of apiConfigurationPresets) {
        const row = document.createElement("div"); row.className = "api-preset-row";
        const load = document.createElement("button"); load.type = "button"; load.className = "api-preset-fill";
        const name = document.createElement("strong"); name.textContent = preset.name;
        const detail = document.createElement("small"); detail.textContent = preset.provider + " · " + preset.model;
        load.append(name,detail); load.setAttribute("aria-label", "填入预设 " + preset.name);
        load.onclick = () => {
            ++apiConfigurationGeneration; apiConfigurationKeySource = preset.id;
            fillApiConfiguration(preset); byId("api-preset-name").value = preset.name;
            byId("route-settings-note").textContent = "";
            byId("route-settings-msg").textContent = "已填入「" + preset.name + "」，点击保存设置后生效";
            byId("api-configuration-form").scrollIntoView({block:"start"});
        };
        const remove = document.createElement("button"); remove.type = "button"; remove.className = "btn btn-danger"; remove.textContent = "删除";
        remove.setAttribute("aria-label", "删除预设 " + preset.name);
        remove.onclick = async () => {
            remove.disabled = true;
            try {
                await saveDashboardJson("/api/api-presets/" + preset.id, {method:"DELETE"});
                if (apiConfigurationKeySource === preset.id) { byId("routeApiKey").placeholder = "预设已删除，请填写密钥或重新加载当前设置"; }
                await loadApiConfigurationPresets();
            } catch (error) { byId("route-settings-msg").textContent = error.message; remove.disabled = false; }
        };
        row.append(load,remove); list.append(row);
    }
}
async function saveApiConfigurationPreset() {
    const name = byId("api-preset-name").value.trim(); if (!name) return;
    const button = byId("api-preset-form").querySelector('[type="submit"]'); button.disabled = true;
    try {
        const data = await saveDashboardJson("/api/api-presets", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({name,...apiConfigurationDraft()})});
        apiConfigurationKeySource = data.preset.id;
        fillApiConfiguration(data.preset); await loadApiConfigurationPresets();
        byId("route-settings-msg").textContent = "预设已保存，当前使用的设置未改变";
    } catch (error) { byId("route-settings-msg").textContent = "预设保存失败：" + error.message; }
    finally { button.disabled = false; }
}
document.addEventListener("DOMContentLoaded",()=>{
    for (const id of ["routeProvider", "routeApiUrl", "routeApiKey"]) {
        byId(id).addEventListener("input", resetApiModels);
    }
    byId("routeModel").addEventListener("input", () => {
        if (byId("route-fetch-models").disabled) resetApiModels();
        byId("routeModels").value = byId("routeModel").value.trim();
    });
    byId("routeModels").onchange = event => {
        if (event.target.value) byId("routeModel").value = event.target.value;
    };
    byId("route-fetch-models").onclick = async event => {
        resetApiModels();
        const generation = apiModelsGeneration, msg = byId("route-models-msg");
        const button = event.currentTarget; button.disabled = true;
        msg.textContent = "正在拉取模型…";
        try {
            const data = await saveDashboardJson("/api/api-presets/models", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(apiConfigurationDraft())});
            if (generation !== apiModelsGeneration) return;
            const models = (data.data || []).map(item=>new Option(item.id,item.id));
            const picker = byId("routeModels");
            picker.replaceChildren(new Option("请选择模型", ""), ...models);
            picker.value = models.some(option => option.value === byId("routeModel").value.trim()) ? byId("routeModel").value.trim() : "";
            byId("route-model-picker").hidden = !models.length;
            msg.textContent = models.length ? "已拉取 " + models.length + " 个模型，可从列表选择或手动填写模型 ID" : "接口返回了空模型列表，可手动填写模型 ID";
        } catch (error) {
            if (generation === apiModelsGeneration) msg.textContent = "拉取失败：" + error.message;
        } finally {
            if (generation === apiModelsGeneration) button.disabled = false;
        }
    };
});

let identityPresetNameRequest = 0;

function renderIdentityPresetNames(data) {
    document.querySelectorAll('[data-preset-name]').forEach(node => {
        const role = node.dataset.presetName;
        node.textContent = String(data[role + '_name'] || '').trim() || (role === 'user' ? '用户' : '助手');
    });
}

async function refreshIdentityPresetNames() {
    const request = ++identityPresetNameRequest;
    try {
        const response = await authFetch('/api/identity-presets');
        const data = await readJsonResponse(response);
        if (!response.ok || data.error) return;
        if (request === identityPresetNameRequest) renderIdentityPresetNames(data);
    } catch (_) {
        // Retain the last server name, or the neutral label before the first load.
    }
}

async function loadIdentityPresets() {
    const nameRequest = ++identityPresetNameRequest;
    const avatarSnapshot = typeof identityAvatarSnapshot === "function" ? identityAvatarSnapshot() : null;
    const note = byId("identity-presets-note");
    const msg = byId("identity-presets-msg");
    try {
        const resp = await authFetch("/api/identity-presets");
        const data = await readJsonResponse(resp);
        if (!resp.ok || data.error) throw new Error(data.error || "HTTP " + resp.status);
        if (nameRequest === identityPresetNameRequest) renderIdentityPresetNames(data);
        byId("identityUserName").value = data.user_name || "";
        byId("identityAssistantName").value = data.assistant_name || "";
        if (typeof applyIdentityAvatars === "function") applyIdentityAvatars(data, avatarSnapshot);
        if (note) note.textContent = "";
        if (msg) msg.textContent = "";
    } catch (e) {
        if (note) note.textContent = "加载失败";
        if (msg) msg.textContent = "加载失败：" + e.message;
    }
}

async function saveIdentityPresets() {
    const msg = byId("identity-presets-msg");
    const payload = {
        user_name: byId("identityUserName").value.trim(),
        assistant_name: byId("identityAssistantName").value.trim(),
    };
    if (Boolean(payload.user_name) !== Boolean(payload.assistant_name)) {
        if (msg) msg.textContent = "请同时填写两个名字，或同时留空以关闭人物预设";
        return;
    }
    if (msg) msg.textContent = "保存中…";
    ++identityPresetNameRequest;
    try {
        await saveDashboardJson("/api/identity-presets", {
            method: "PUT",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(payload),
        });
        await loadIdentityPresets();
        if (msg) msg.textContent = payload.user_name ? "人物预设已保存" : "人物预设已关闭";
    } catch (e) {
        if (msg) msg.textContent = "保存失败：" + e.message;
    }
}

function toggleAnthropicProviderCreator(forceOpen) {
    const form = byId("anthropic-provider-create");
    if (!form) return;
    const shouldOpen = typeof forceOpen === "boolean" ? forceOpen : form.hidden;
    form.hidden = !shouldOpen;
    if (shouldOpen) byId("anthropicProviderName")?.focus();
}

function renderAnthropicProviders() {
    renderSettingsProviders("anthropic", anthropicProviderProfiles);
}

async function loadAnthropicProviders() {
    const note = byId("anthropic-provider-note");
    try {
        const resp = await authFetch("/api/anthropic-providers");
        const data = await readJsonResponse(resp);
        if (!resp.ok || data.error) throw new Error(data.error || "HTTP " + resp.status);
        anthropicProviderProfiles = Array.isArray(data.profiles) ? data.profiles : [];
        renderAnthropicProviders();
        if (note) note.textContent = data.effective?.name || "环境变量";
    } catch (e) {
        if (note) note.textContent = "加载失败";
        showAnthropicProviderMsg("加载失败：" + e.message);
    }
}

function showAnthropicProviderMsg(text) {
    const msg = byId("anthropic-provider-msg");
    if (!msg) return;
    msg.textContent = text || "";
}

async function createAnthropicProvider() {
    const payload = {
        name: byId("anthropicProviderName").value.trim(),
        api_url: byId("anthropicProviderUrl").value.trim(),
        api_key: byId("anthropicProviderKey").value.trim(),
        is_active: Boolean(byId("anthropicProviderActive").checked),
    };
    showAnthropicProviderMsg("保存中...");
    try {
        await saveDashboardJson("/api/anthropic-providers", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(payload),
        });
        byId("anthropicProviderName").value = "";
        byId("anthropicProviderUrl").value = "";
        byId("anthropicProviderKey").value = "";
        byId("anthropicProviderActive").checked = false;
        toggleAnthropicProviderCreator(false);
        showAnthropicProviderMsg("");
        await loadAnthropicProviders();
    } catch (e) {
        showAnthropicProviderMsg("保存失败：" + e.message);
    }
}

async function saveAnthropicProvider(id) {
    const payload = {
        name: byId("anthropicProviderName-" + id).value.trim(),
        api_url: byId("anthropicProviderUrl-" + id).value.trim(),
        api_key: byId("anthropicProviderKey-" + id).value.trim(),
        is_active: Boolean(byId("anthropicProviderActive-" + id).checked),
    };
    showAnthropicProviderMsg("保存中...");
    try {
        await saveDashboardJson("/api/anthropic-providers/" + id, {
            method: "PUT",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(payload),
        });
        showAnthropicProviderMsg("");
        await loadAnthropicProviders();
    } catch (e) {
        showAnthropicProviderMsg("保存失败：" + e.message);
    }
}

async function deleteAnthropicProvider(id) {
    if (!confirm("删除这个供应商？")) return;
    try {
        const resp = await authFetch("/api/anthropic-providers/" + id, {method: "DELETE"});
        const data = await readJsonResponse(resp);
        if (!resp.ok || data.error) throw new Error(data.error || "HTTP " + resp.status);
        showAnthropicProviderMsg("");
        await loadAnthropicProviders();
    } catch (e) {
        showAnthropicProviderMsg("删除失败：" + e.message);
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
    renderSettingsProviders("openai", openAiProviderProfiles);
}

function renderHistoryTitleProviders() {
    const select = byId("historyTitleProvider");
    if (!select) return;
    const selected = select.dataset.selectedProviderId || "";
    const legacyConfigured = select.dataset.legacyConfigured === "true";
    const firstLabel = legacyConfigured && !selected ? "原独立配置" : "环境变量";
    select.innerHTML = [
        `<option value="">${firstLabel}</option>`,
        ...openAiProviderProfiles.map(profile =>
            `<option value="${Number(profile.id)}">${escHtml(profile.name)}</option>`
        ),
    ].join("");
    select.value = selected;
}

const MODEL_TASK_CONTROLS = [
    ["handoffSummaryProvider", "handoffSummaryModel", "handoff"],
    ["temporarySummaryProvider", "temporarySummaryModel", "temporary_summary"],
    ["diaryKeywordProvider", "diaryKeywordModel", "diary_keyword"],
    ["fragmentProvider", "fragmentModel", "fragment_extract"],
    ["diaryMergeProvider", "diaryMergeModel", "diary_merge"],
];

function renderModelTaskProvider(selectId) {
    const select = byId(selectId);
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

function renderHandoffSummaryProviders() {
    renderModelTaskProvider("handoffSummaryProvider");
}

function renderTemporarySummaryProviders() {
    renderModelTaskProvider("temporarySummaryProvider");
}

function renderLongTermSummaryProviders() {
    renderModelTaskProvider("memoryExtractionProvider");
}

function renderAllModelTaskProviders() {
    MODEL_TASK_CONTROLS.forEach(([selectId]) => renderModelTaskProvider(selectId));
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
        renderAllModelTaskProviders();
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

let heartbeatSavedSettings = null;
let heartbeatSettingsSaving = false;
let heartbeatSettingsLoading = false;
let heartbeatSettingsRequest = 0;

function syncHeartbeatCoffee() {
    const enabled = byId("heartbeatEnabled");
    const locked = heartbeatSettingsSaving || !heartbeatSavedSettings;
    if (enabled) enabled.disabled = locked;
    if (byId("heartbeatInterval")) byId("heartbeatInterval").disabled = locked;
    if (byId("heartbeat-save")) byId("heartbeat-save").disabled = locked;
    const retry = byId("heartbeat-settings-retry");
    if (retry) retry.disabled = heartbeatSettingsLoading || heartbeatSettingsSaving;
    byId("heartbeat-coffee")?.classList.toggle("is-awake", Boolean(
        heartbeatSavedSettings?.enabled && heartbeatSavedSettings?.ready
    ));
}

function applyHeartbeatSettings(data) {
    const note = byId("heartbeat-settings-note");
    heartbeatSavedSettings = data;
    byId("heartbeatEnabled").checked = Boolean(data.enabled);
    byId("heartbeatInterval").value = data.interval_minutes || 30;
    byId("heartbeatRoute").textContent = data.route_name || "—";
    byId("heartbeatProviderName").textContent = data.provider_name || "—";
    byId("heartbeatModelName").textContent = data.model || "—";
    ["heartbeatRoute", "heartbeatProviderName", "heartbeatModelName"].forEach(id => {
        byId(id).title = byId(id).textContent;
    });
    if (note) {
        if (!data.context_managed) {
            note.textContent = "不可用";
        } else if (!data.route) {
            note.textContent = "等待首次对话";
        } else if (!data.ready) {
            note.textContent = "供应商不可用";
        } else if (Number(data.effective_interval_minutes) !== Number(data.interval_minutes)) {
            note.textContent = "实际间隔 " + data.effective_interval_minutes + " 分钟";
        } else {
            note.textContent = data.enabled ? "运行中" : "已关闭";
        }
    }
}

async function loadHeartbeatSettings() {
    if (heartbeatSettingsSaving) return;
    const request = ++heartbeatSettingsRequest;
    const note = byId("heartbeat-settings-note");
    const retry = byId("heartbeat-settings-retry");
    heartbeatSettingsLoading = true;
    if (note) note.textContent = "载入中…";
    syncHeartbeatCoffee();
    try {
        const resp = await authFetch("/api/heartbeat-settings");
        const data = await resp.json();
        if (request !== heartbeatSettingsRequest) return;
        if (!resp.ok || data.error) throw new Error(data.error || "HTTP " + resp.status);
        applyHeartbeatSettings(data);
        if (retry) retry.hidden = true;
    } catch (e) {
        if (request === heartbeatSettingsRequest) {
            if (note) note.textContent = "设置加载失败：" + e.message;
            if (retry) retry.hidden = false;
        }
    } finally {
        if (request === heartbeatSettingsRequest) {
            heartbeatSettingsLoading = false;
            syncHeartbeatCoffee();
        }
    }
}

async function saveHeartbeatSettings(toggleOnly = false) {
    if (heartbeatSettingsSaving || !heartbeatSavedSettings) return;
    const msg = byId("heartbeat-settings-msg");
    const intervalInput = byId("heartbeatInterval");
    const draftInterval = intervalInput.value;
    const payload = {
        enabled: Boolean(byId("heartbeatEnabled").checked),
        // The stopper always works, even with an unfinished interval edit.
        interval_minutes: toggleOnly ? heartbeatSavedSettings.interval_minutes : Number(draftInterval),
    };
    if (!Number.isInteger(payload.interval_minutes) || payload.interval_minutes < 1 || payload.interval_minutes > 1440) {
        if (msg) msg.textContent = "间隔需为 1-1440 的整数分钟";
        intervalInput.focus();
        return;
    }
    heartbeatSettingsSaving = true;
    heartbeatSettingsLoading = false;
    ++heartbeatSettingsRequest;
    syncHeartbeatCoffee();
    if (msg) msg.textContent = "保存中…";
    try {
        const saved = await saveDashboardJson("/api/heartbeat-settings", {
            method: "PUT",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(payload),
        });
        applyHeartbeatSettings({ ...heartbeatSavedSettings, ...saved });
        if (toggleOnly) intervalInput.value = draftInterval;
        if (msg) msg.textContent = toggleOnly ? (payload.enabled ? "心跳已开启" : "心跳已关闭") : "间隔已保存";
    } catch (e) {
        byId("heartbeatEnabled").checked = Boolean(heartbeatSavedSettings.enabled);
        if (msg) msg.textContent = "保存失败：" + e.message;
    } finally {
        heartbeatSettingsSaving = false;
        syncHeartbeatCoffee();
    }
}

async function loadConversationModelSettings(scope = "all") {
    try {
        const resp = await authFetch("/api/conversation-model-settings");
        const data = await readJsonResponse(resp);
        if (!resp.ok || data.error) throw new Error(data.error || "HTTP " + resp.status);
        if (scope !== "generation") {
            byId("crossConversationRecallEnabled").checked = Boolean(data.cross_conversation_recall_enabled);
            byId("historyEmbeddingUrl").value = data.embedding_api_url || "";
            byId("historyEmbeddingModel").value = data.embedding_model || "";
            byId("historyEmbeddingKey").value = "";
            byId("historyEmbeddingKey").placeholder = data.embedding_api_key_configured
                ? "已配置，留空保留" : "密钥";
            const status = byId("conversation-vector-status");
            status.textContent = data.search_enabled ? "已配置" : "未配置";
            status.dataset.active = String(Boolean(data.search_enabled));
        }
        if (scope !== "recall") {
            byId("fragmentInterval").value = data.fragment_interval ?? 3;
            byId("historyTitleProvider").dataset.selectedProviderId =
                data.title_provider_id == null ? "" : String(data.title_provider_id);
            byId("historyTitleProvider").dataset.legacyConfigured =
                String(Boolean(data.title_legacy_configured));
            renderHistoryTitleProviders();
            byId("historyTitleModel").value = data.title_model || "";
            MODEL_TASK_CONTROLS.forEach(([selectId, modelId, prefix]) => {
                const select = byId(selectId);
                const input = byId(modelId);
                select.dataset.selectedProviderId = data[prefix + "_provider_id"] == null
                    ? "" : String(data[prefix + "_provider_id"]);
                input.value = data[prefix + "_model"] || "";
                input.placeholder = data[prefix + "_effective_model"] || "模型";
            });
            renderAllModelTaskProviders();
        }
        setConversationModelSettingsMessage("");
    } catch (e) {
        const status = byId("conversation-vector-status");
        status.textContent = "加载失败";
        status.dataset.active = "false";
        setConversationModelSettingsMessage("加载失败：" + e.message);
    }
}

function setConversationModelSettingsMessage(text) {
    ["recall-settings-msg", "conversation-model-settings-msg"].forEach(id => {
        const node = byId(id);
        if (node) node.textContent = text || "";
    });
}

async function saveConversationModelSettings(scope = "all") {
    let payload = {
        fragment_interval:Number(byId("fragmentInterval").value),
        cross_conversation_recall_enabled: Boolean(byId("crossConversationRecallEnabled").checked),
        embedding_api_url: byId("historyEmbeddingUrl").value.trim(),
        embedding_model: byId("historyEmbeddingModel").value.trim(),
        embedding_api_key: byId("historyEmbeddingKey").value.trim(),
        title_provider_id: byId("historyTitleProvider").value
            ? Number(byId("historyTitleProvider").value) : null,
        title_model: byId("historyTitleModel").value.trim(),
    };
    MODEL_TASK_CONTROLS.forEach(([selectId, modelId, prefix]) => {
        payload[prefix + "_provider_id"] = byId(selectId).value
            ? Number(byId(selectId).value) : null;
        payload[prefix + "_model"] = byId(modelId).value.trim();
    });
    setConversationModelSettingsMessage("保存中...");
    try {
        if (scope !== "all") {
            // This endpoint also stores title settings. Preserve the server's values
            // for the other page, never submit that page's unsaved form draft.
            const current = await saveDashboardJson("/api/conversation-model-settings");
            const ownFields = scope === "recall"
                ? ["cross_conversation_recall_enabled", "embedding_api_url", "embedding_model", "embedding_api_key"]
                : ["fragment_interval","title_provider_id", "title_model", ...MODEL_TASK_CONTROLS.flatMap(([, , prefix])=>[prefix + "_provider_id", prefix + "_model"])];
            payload = {title_provider_id:current.title_provider_id ?? null, title_model:current.title_model || "",
                long_term_recall_limit:current.long_term_recall_limit ?? 5,
                ...Object.fromEntries(ownFields.map(key=>[key,payload[key]]))};
        }
        await saveDashboardJson("/api/conversation-model-settings", {
            method: "PUT",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(payload),
        });
        setConversationModelSettingsMessage("已保存");
        await loadConversationModelSettings(scope);
        setConversationModelSettingsMessage("已保存");
        setTimeout(() => {
            const current = byId("conversation-model-settings-msg");
            if (current && current.textContent === "已保存") {
                setConversationModelSettingsMessage("");
            }
        }, 3000);
    } catch (e) {
        setConversationModelSettingsMessage("保存失败：" + e.message);
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
        if (note) note.textContent = "";
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
let usageLogBusy = false;
async function loadTokenUsage() {
    if (usageLogBusy) return;
    usageLogBusy = true;
    const stats = byId("usage-stats");
    if (stats) stats.textContent = "加载中...";
    try {
        const [summaryResp, logsResp, monthResp] = await Promise.all([
            authFetch("/api/token-usage/summary?days=7"),
            authFetch("/api/token-usage/logs?limit=100&days=0"),
            authFetch("/api/token-usage/summary?days=180"),
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
        if (typeof renderUsageOverview === "function") renderUsageOverview(monthSummary);
    } catch (e) {
        if (stats) stats.textContent = "加载失败：" + e.message;
        const logBody = byId("usage-log-body");
        if (logBody) logBody.textContent = '加载失败：' + e.message;
    } finally { usageLogBusy = false; }
}

function renderUsageSummary(data, monthData) {
    const today = monthData.today || new Date().toISOString().slice(0, 10);
    const todayRow = (monthData.daily_usage || []).find(row => row.day === today) || {};
    setText("usage-today", fmtToken(todayRow.total_tokens || 0));
    setText("usage-week", fmtToken(data.total_tokens || 0));
    setText("usage-requests", fmtToken(data.request_count || 0));
    setText("usage-cache", fmtToken(data.cache_read_tokens || 0));
    const stats = byId("usage-stats");
    if (stats) stats.textContent = "今日 " + fmtToken(todayRow.total_tokens || 0) + " · 近 7 天 " + fmtToken(data.total_tokens || 0) + " tokens";
}

function renderModelRanking(data) {
    const tbody = byId("usage-ranking-body");
    const count = byId("usage-ranking-count");
    const rows = (data.model_ranking || []).slice().sort((a,b) => usageNumber(b.request_count) - usageNumber(a.request_count) || usageNumber(b.total_tokens) - usageNumber(a.total_tokens));
    if (count) count.textContent = rows.length + " 个模型";
    if (!tbody) return;
    if (!rows.length) {
        tbody.innerHTML = '<div class="memory-card-empty">暂无用量记录</div>';
        return;
    }
    const maxRequests = Math.max(...rows.map(row => usageNumber(row.request_count)), 1);
    tbody.style?.setProperty('--usage-rank-count-width', Math.max(42,...rows.map(row => usageNumber(row.request_count).toLocaleString().length * 9)) + 'px');
    tbody.innerHTML = rows.map((row, index) => {
        const requests = usageNumber(row.request_count);
        const width = requests / maxRequests * 100;
        const model = row.model || '未标注模型';
        const initial = /claude/i.test(model) ? 'C' : /gpt/i.test(model) ? 'G' : 'M';
        return `
            <details class="usage-rank-item">
                <summary title="${escHtml(model)} · ${escHtml(row.provider || '-')} · ${requests.toLocaleString()} 次请求">
                    <span class="usage-rank-track"><i class="usage-rank-fill" style="width:${width}%" aria-hidden="true"></i><span class="usage-rank-label"><span class="usage-rank-initial" aria-hidden="true">${initial}</span><span>${escHtml(model)}</span></span></span>
                    <strong class="usage-rank-count">${requests.toLocaleString()}</strong>
                </summary>
                <div class="usage-rank-info"><span>${index + 1}. ${escHtml(model)} · ${escHtml(row.provider || '-')}</span><span>输入 ${fmtToken(row.input_tokens || 0)} · 输出 ${fmtToken(row.output_tokens || 0)} · 总计 ${fmtToken(row.total_tokens || 0)} tokens</span></div>
            </details>
        `;
    }).join("");
}

function renderUsageLogs(data) {
    const logs = data.logs || [];
    byId('usage-log-count').textContent = logs.length + ' 条';
    byId('usage-log-body').innerHTML = logs.map(log => `<details class="usage-log-entry"><summary>
        <time>${escHtml(String(log.created_at || '').slice(5,16))}</time>
        <span class="usage-log-model">${escHtml(log.model || '—')}</span><strong>${fmtToken(log.total_tokens)}</strong>
        </summary><div class="usage-log-details"><span>${escHtml(log.created_at || '')}</span><span>${escHtml(log.provider || '')} · ${log.stream ? '流式' : '非流式'}</span>
        <span>输入 ${fmtToken(log.input_tokens)}</span><span>输出 ${fmtToken(log.output_tokens)}</span>
        <span>缓存读取 ${fmtToken(log.cache_read_tokens)}</span><span>缓存写入 ${fmtToken(log.cache_creation_tokens)}</span></div></details>`).join('') || '<p class="memory-card-empty">暂无请求记录</p>';
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


let mcpSettingsBusy = false;
let mcpEditorSequence = 0;
function setMcpState(message, retry = false) {
    byId("mcp-state").hidden = !message;
    byId("mcp-settings-msg").textContent = message;
    byId("mcp-retry").hidden = !retry;
}
function markMcpChanged() {
    byId("mcp-footer").hidden = false;
    setMcpState("");
}
function addMcpServer(server = {}, editing = true) {
    if (mcpSettingsBusy && editing) return;
    const card = document.createElement("article");
    card.className = "mcp-server";
    card.dataset.serverId = server.id || "";
    const editorId = `mcp-editor-${++mcpEditorSequence}`;
    card.innerHTML = `<div class="mcp-server-header">
        <button type="button" class="mcp-server-disclosure" aria-expanded="${editing}" aria-controls="${editorId}">
            <span class="mcp-server-heading"><span class="mcp-server-name"></span><span class="mcp-server-meta"></span></span>
            <span class="mcp-server-chevron" aria-hidden="true"></span>
        </button>
        <label class="heartbeat-switch"><input data-mcp="enabled" type="checkbox" aria-label="启用服务"><span></span></label>
        </div>
        <div class="mcp-server-editor" id="${editorId}"${editing ? "" : " hidden"}>
        <div class="mcp-server-fields">
        <label class="route-config-row"><span>名称</span><input data-mcp="name" placeholder="服务名称"></label>
        <label class="route-config-row"><span>地址</span><input data-mcp="url" type="url" placeholder="https://example.com/mcp" autocomplete="off" spellcheck="false"></label>
        <div class="route-config-row"><label for="${editorId}-token">Token</label><input id="${editorId}-token" data-mcp="bearer_token" type="password" autocomplete="new-password"><button type="button" class="mcp-text-button" data-action="clear">清除</button></div>
        </div>
        <p class="mcp-service-status" role="status" data-mcp="status"></p>
        <div class="mcp-server-actions"><button type="button" class="mcp-text-button" data-action="test">测试连接</button><button type="button" class="mcp-text-button btn-danger" data-action="remove">删除服务</button></div>
        </div>`;
    const disclosure = card.querySelector(".mcp-server-disclosure");
    const editor = card.querySelector(".mcp-server-editor");
    disclosure.onclick = () => {
        editor.hidden = !editor.hidden;
        disclosure.setAttribute("aria-expanded", String(!editor.hidden));
    };
    for (const field of ["name", "url"]) card.querySelector(`[data-mcp="${field}"]`).value = server[field] || "";
    const token = card.querySelector('[data-mcp="bearer_token"]');
    token.placeholder = server.token_configured ? "已保存，留空保留" : "可选";
    card.querySelector('[data-mcp="enabled"]').checked = server.enabled !== false;
    card.querySelector(".mcp-server-name").textContent = server.name || server.url || "新服务";
    card.querySelector('[data-mcp="enabled"]').setAttribute("aria-label", `启用 ${server.name || server.url || "新服务"}`);
    card.querySelector('[data-action="remove"]').setAttribute("aria-label", `删除服务 ${server.name || server.url || "新服务"}`);
    card.querySelector(".mcp-server-meta").textContent = editing ? "待保存" : server.enabled === false ? "已停用" : server.status?.error ? "未连接" : `${server.status?.tools?.length || 0} 个工具`;
    const status = card.querySelector('[data-mcp="status"]');
    status.textContent = server.status?.error || (server.status?.tools?.join("、") || "");
    const clearButton = card.querySelector('[data-action="clear"]');
    clearButton.hidden = !server.token_configured;
    clearButton.onclick = () => {
        card.dataset.clearToken = "true";
        token.value = "";
        token.placeholder = "保存后清除";
        clearButton.hidden = true;
        markMcpChanged();
    };
    card.addEventListener("input", () => {
        const name = card.querySelector('[data-mcp="name"]').value.trim() || card.querySelector('[data-mcp="url"]').value.trim() || "新服务";
        card.querySelector(".mcp-server-name").textContent = name;
        card.querySelector('[data-mcp="enabled"]').setAttribute("aria-label", `启用 ${name}`);
        card.querySelector('[data-action="remove"]').setAttribute("aria-label", `删除服务 ${name}`);
        card.querySelector(".mcp-server-meta").textContent = "待保存";
        markMcpChanged();
    });
    card.querySelector('[data-action="remove"]').onclick = () => {
        if (mcpSettingsBusy) return;
        card.remove();
        markMcpChanged();
        if (!byId("mcp-servers").children.length) setMcpState("暂无服务");
    };
    card.querySelector('[data-action="test"]').onclick = async (event) => {
        const button = event.currentTarget;
        button.disabled = true;
        status.textContent = "连接中…";
        try {
            const resp = await authFetch("/api/mcp-settings/test", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(readMcpServer(card))});
            if (resp.status === 404) throw new Error("连接测试暂不可用");
            const data = await readJsonResponse(resp);
            if (!resp.ok || data.error) throw new Error(data.error || "连接失败，请稍后重试");
            status.textContent = "连接成功" + (data.tools.length ? " · " + data.tools.join("、") : " · 暂无工具");
        } catch (error) { status.textContent = error.message; }
        finally { button.disabled = false; }
    };
    byId("mcp-servers").appendChild(card);
    if (editing) {
        markMcpChanged();
        card.querySelector('[data-mcp="name"]').focus();
    }
}
function readMcpServer(card) {
    const server = {id: card.dataset.serverId, clear_token: card.dataset.clearToken === "true"};
    for (const field of ["name", "url", "bearer_token", "enabled"]) {
        const input = card.querySelector(`[data-mcp="${field}"]`);
        server[field] = input.type === "checkbox" ? input.checked : input.value.trim();
    }
    return server;
}
function renderMcpServers(servers) {
    byId("mcp-servers").replaceChildren();
    servers.forEach(server => addMcpServer(server, false));
}
async function loadMcpSettings() {
    if (mcpSettingsBusy) return;
    mcpSettingsBusy = true;
    byId("mcp-add").hidden = byId("mcp-footer").hidden = true;
    setMcpState("载入中…");
    try {
        const resp = await authFetch("/api/mcp-settings");
        if (!resp.ok) throw new Error("服务列表暂不可用");
        const data = await readJsonResponse(resp);
        if (data.error) throw new Error("服务列表暂不可用");
        renderMcpServers(data.servers);
        setMcpState(data.servers.length ? "" : "暂无服务");
        byId("mcp-add").hidden = false;
    } catch (error) {
        setMcpState("服务列表暂不可用", true);
        console.warn("MCP settings load failed:", error.message);
    } finally { mcpSettingsBusy = false; }
}
async function saveMcpSettings() {
    if (mcpSettingsBusy) return;
    const servers = Array.from(byId("mcp-servers").children, readMcpServer);
    mcpSettingsBusy = true;
    byId("mcp-add").disabled = byId("mcp-save").disabled = true;
    byId("mcp-servers").querySelectorAll("input, button").forEach(input => input.disabled = true);
    byId("mcp-save").textContent = "保存中…";
    try {
        const resp = await authFetch("/api/mcp-settings", {method: "PUT", headers: {"Content-Type": "application/json"}, body: JSON.stringify({servers})});
        if (resp.status === 404) throw new Error("保存暂不可用，请稍后重试");
        const data = await readJsonResponse(resp);
        if (!resp.ok || data.error) throw new Error(data.error || "保存失败，请稍后重试");
        renderMcpServers(data.servers);
        byId("mcp-footer").hidden = true;
        setMcpState(data.servers.some(server => server.status.error) ? "已保存，部分服务未连接" : data.servers.length ? "" : "暂无服务");
    } catch (error) { setMcpState(error.message); }
    finally {
        mcpSettingsBusy = false;
        byId("mcp-save").textContent = "保存";
        byId("mcp-add").disabled = byId("mcp-save").disabled = false;
        byId("mcp-servers").querySelectorAll("input, button").forEach(input => input.disabled = false);
    }
}

function showRecallPanel(name) {
    ['search','weights','config'].forEach(key=>byId('recall-panel-'+key).hidden=key!==name);
    const heading=byId('memory-retrieval').querySelector('.memory-page-heading');
    heading.hidden=name!=='search';
}
function openRecallDialog(title, text) {
    const dialog=byId('recall-detail-dialog');
    dialog.querySelector('h3').textContent=title;
    dialog.querySelector('.recall-dialog-content').textContent=text;
    dialog.showModal();
}
function openRecallRanking(button) {
    const dialog=byId('recall-detail-dialog');
    dialog.querySelector('h3').textContent='排序依据';
    dialog.querySelector('.recall-dialog-content').replaceChildren(button.nextElementSibling.content.cloneNode(true));
    dialog.showModal();
}
