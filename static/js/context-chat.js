/* Dashboard chat uses the signed dashboard session; upstream keys stay on Ash. */
let chatBusy = false;
let chatConfigBusy = false;
let chatController = null;
let chatConfigured = false;
let chatConfigGeneration = 0;
let chatEffectiveModel = "";
const chatElement = id => document.getElementById(id);
function isChatBusy() { return chatBusy; }

async function chatJson(url, options = {}, timeoutMs = 15000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await api(url, {...options, signal: controller.signal});
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.error) throw new Error(typeof data.error === 'string' ? data.error : `请求失败 (${response.status})`);
    return data;
  } catch (error) {
    if (controller.signal.aborted) throw new Error('请求等待超时，请刷新核对结果后重试');
    throw error;
  } finally {
    clearTimeout(timer);
  }
}
function updateChatAvailability() {
  if (!chatElement('sendBtn')) return;
  const active = !!currentConversationOverview?.is_active;
  chatElement('sendBtn').disabled = chatBusy || chatConfigBusy || !active || !chatConfigured || !chatEffectiveModel;
  chatElement('appendBtn').disabled = chatBusy;
  chatElement('phone-chat-continue').disabled = chatBusy || chatConfigBusy;
  chatElement('stopChat').hidden = !chatBusy;
  chatElement('msgInput').disabled = chatBusy;
  if (!chatBusy && !chatConfigBusy) chatElement('composerHint').textContent = active
    ? 'Enter 发送 · Shift+Enter 换行'
    : '正在浏览历史上下文；激活此会话后可继续聊天';
  window.AshChatUI?.syncState();
}
async function loadChatConfig() {
  const generation = ++chatConfigGeneration;
  chatConfigBusy = true; updateChatAvailability();
  try {
    const config = await chatJson('/api/chat/config');
    if (generation !== chatConfigGeneration) return;
    chatEffectiveModel = config.model || '';
    chatConfigured = Boolean(config.ready && chatEffectiveModel);
    window.AshChatUI?.setModelLabel(chatEffectiveModel);
    chatElement('chatStatus').textContent = chatConfigured ? '正在使用 Ash 的聊天配置' : '请在模型供应商中保存 API 和聊天模型';
  } catch (error) {
    if (generation !== chatConfigGeneration) return;
    chatConfigured = false; chatElement('chatStatus').textContent = error.message + '，请稍后重试';
  } finally {
    if (generation === chatConfigGeneration) { chatConfigBusy = false; updateChatAvailability(); }
  }
}

// Construct Markdown nodes without interpreting model output as HTML.
function renderChatText(target, text) {
  target.replaceChildren();
  const parts = String(text || '').split(/(```[^\n]*\n[\s\S]*?```)/g);
  for (const part of parts) {
    if (part.startsWith('```') && part.endsWith('```')) {
      const pre = document.createElement('pre');
      const code = document.createElement('code');
      code.textContent = part.slice(part.indexOf('\n') + 1, -3);
      pre.appendChild(code); target.appendChild(pre);
    } else {
      for (const chunk of part.split(/(\*\*[^*\n]+\*\*|`[^`\n]+`)/g)) {
        if (chunk.startsWith('**') && chunk.endsWith('**')) {
          const strong = document.createElement('strong'); strong.textContent = chunk.slice(2, -2); target.appendChild(strong);
        } else if (chunk.startsWith('`') && chunk.endsWith('`')) {
          const code = document.createElement('code'); code.textContent = chunk.slice(1, -1); target.appendChild(code);
        } else target.appendChild(document.createTextNode(chunk));
      }
    }
  }
}

function chatReasoningText(message) {
  const text = message?.reasoning_content || message?.reasoning;
  if (typeof text === 'string' && text) return text;
  return (Array.isArray(message?.reasoning_details) ? message.reasoning_details : [])
    .filter(block => ['reasoning.text','reasoning.summary'].includes(block?.type))
    .map(block => block.text || block.summary || '').filter(text => typeof text === 'string').join('\n\n');
}

async function consumeChatStream(response, onDelta, onReasoning = () => {}) {
  if (!response.body) throw new Error('浏览器无法读取回复流');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '', doneSeen = false;
  function event(block) {
    const data = block.split('\n').filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n');
    if (!data) return;
    if (data.trim() === '[DONE]') { doneSeen = true; return; }
    const payload = JSON.parse(data);
    if (payload.error) throw new Error(typeof payload.error === 'string' ? payload.error : payload.error.message || '上游返回错误');
    const choice = payload.choices?.[0];
    const reasoning = chatReasoningText(choice?.delta);
    if (reasoning) onReasoning(reasoning);
    if (choice?.delta?.content) onDelta(choice.delta.content);
    if (choice?.delta?.tool_calls?.length) throw new Error('此会话请求了前端工具，请回到原客户端完成工具调用，或新建网页会话');
  }
  try {
    while (!doneSeen) {
      const {value, done} = await reader.read();
      buffer += done ? decoder.decode() : decoder.decode(value, {stream: true});
      buffer = buffer.replace(/\r\n/g, '\n');
      let boundary;
      while ((boundary = buffer.indexOf('\n\n')) !== -1) {
        event(buffer.slice(0, boundary)); buffer = buffer.slice(boundary + 2);
      }
      if (done) {
        if (buffer.trim()) event(buffer);
        if (!doneSeen) throw new Error('回复连接中断，请核对上下文后再继续');
        break;
      }
    }
  } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
}

async function sendChat(trigger) {
  if (chatBusy || !currentConvId) return;
  const input = chatElement('msgInput');
  const content = input.value.trim();
  if (!content) return;
  const convId = currentConvId;
  const model = chatEffectiveModel;
  if (trigger && (!currentConversationOverview?.is_active || !chatConfigured || chatConfigBusy || !model)) {
    chatElement('chatStatus').textContent = '请先激活此会话，并确认模型配置'; return;
  }
  chatBusy = true;
  chatController = new AbortController();
  updateChatAvailability();
  let reply = '', failed = false;
  const area = chatElement('msgArea');
  const preview = document.createElement('div');
  preview.className = 'msg assistant';
  const body = document.createElement('div'); body.className = 'msg-body';
  body.textContent = '正在等待回复…'; preview.appendChild(body);
  window.AshChatUI?.decorateMessage(preview);
  window.AshChatUI?.startReasoning(preview);
  try {
    if (!trigger) {
      await chatJson(`/api/conversations/${convId}/messages`, {method: 'POST', body: JSON.stringify({role: currentRole, content})});
      input.value = '';
      window.AshChatUI?.clearDraft(convId);
    } else {
      const pendingUser = document.createElement('div');
      pendingUser.className = 'msg user';
      const pendingBody = document.createElement('div'); pendingBody.className = 'msg-body';
      pendingBody.textContent = content; pendingUser.appendChild(pendingBody);
      window.AshChatUI?.decorateMessage(pendingUser);
      area.append(pendingUser, preview); area.scrollTop = area.scrollHeight;
      chatElement('chatStatus').textContent = '正在回复…';
      const response = await api(`/api/conversations/${convId}/chat`, {
        method: 'POST', signal: chatController.signal,
        body: JSON.stringify({model, stream: true, messages: [{role: 'user', content}]}),
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || `发送失败 (${response.status})`);
      }
      input.value = '';
      window.AshChatUI?.clearDraft(convId);
      if (response.headers.get('content-type')?.includes('text/event-stream')) {
        await consumeChatStream(response, delta => {
          const atBottom = area.scrollHeight - area.scrollTop - area.clientHeight < 100;
          reply += delta; renderChatText(body, reply);
          if (atBottom) area.scrollTop = area.scrollHeight;
        }, delta => window.AshChatUI?.appendReasoning(delta));
      } else {
        const data = await response.json();
        if (data.error) throw new Error(typeof data.error === 'string' ? data.error : '回复失败');
        reply = data.choices?.[0]?.message?.content || '';
        window.AshChatUI?.appendReasoning(chatReasoningText(data.choices?.[0]?.message));
      }
    }
    chatElement('chatStatus').textContent = trigger ? '回复完成' : '已追加到上下文';
  } catch (error) {
    failed = true;
    chatElement('chatStatus').textContent = error.name === 'AbortError'
      ? '已停止接收；上游可能仍在处理，请刷新上下文核对'
      : error.message;
  } finally {
    if (currentConvId === convId) {
      await loadMessages(convId);
      if (reply && (failed || content.startsWith('/'))) {
        renderChatText(body, (failed ? '未确认保存的部分回复：\n' : '') + reply);
        area.appendChild(preview);
      }
    }
    chatBusy = false; chatController = null; updateChatAvailability();
    input.focus();
    window.parent.postMessage({type: 'memory-gateway-chat-updated'}, window.location.origin);
  }
}

document.addEventListener('DOMContentLoaded', () => {
  if (CONTEXT_EMBED_MODE !== 'detail') return;
  chatElement('phone-chat-model').onclick = ()=>window.parent.postMessage({type:'memory-gateway-open-chat-configuration'},location.origin);
  chatElement('stopChat').onclick = () => chatController?.abort();
  chatElement('phone-chat-continue').onclick = async () => {
    chatConfigBusy = true; updateChatAvailability();
    try {
      await chatJson(`/api/conversations/${currentConvId}/activate`, {method: 'POST'});
      await loadMessages(currentConvId);
      window.parent.postMessage({type: 'memory-gateway-chat-updated'}, window.location.origin);
      chatElement('chatStatus').textContent = '已激活，可以继续聊天';
    } catch (error) { chatElement('chatStatus').textContent = error.message; }
    finally { chatConfigBusy = false; updateChatAvailability(); }
  };
  loadChatConfig();
});

window.addEventListener('message',event=>{
  if(event.origin===location.origin && event.source===window.parent && event.data?.type==='ash-chat-configuration-changed') loadChatConfig();
});
