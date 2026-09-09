/* Dashboard chat uses the signed dashboard session; upstream keys stay on Ash. */
let chatBusy = false;
let chatConfigBusy = false;
let chatController = null;
let chatConfigured = false;
const chatElement = id => document.getElementById(id);
function isChatBusy() { return chatBusy; }

async function chatJson(url, options = {}) {
  const response = await api(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.error) throw new Error(typeof data.error === 'string' ? data.error : `请求失败 (${response.status})`);
  return data;
}
function updateChatAvailability() {
  if (!chatElement('sendBtn')) return;
  const active = !!currentConversationOverview?.is_active;
  chatElement('sendBtn').disabled = chatBusy || chatConfigBusy || !active || !chatConfigured;
  chatElement('appendBtn').disabled = chatBusy;
  chatElement('activateChat').hidden = active;
  chatElement('activateChat').disabled = chatBusy || chatConfigBusy;
  for (const id of ['chatRoute', 'chatProvider', 'chatModel', 'refreshModels']) {
    chatElement(id).disabled = chatBusy || chatConfigBusy;
  }
  chatElement('stopChat').hidden = !chatBusy;
  chatElement('msgInput').disabled = chatBusy;
  if (!chatBusy && !chatConfigBusy) chatElement('composerHint').textContent = active
    ? 'Enter 发送 · Shift+Enter 换行 · 供应商切换对整个网关生效'
    : '正在浏览历史上下文；激活此会话后可继续聊天';
}
async function loadChatConfig(preferAvailableModel = false) {
  chatConfigBusy = true;
  updateChatAvailability();
  try {
    const [route, suppliers, models] = await Promise.all([
      chatJson('/api/route-settings'), chatJson('/api/openai-providers'), chatJson('/api/chat/models'),
    ]);
    chatElement('chatRoute').value = route.provider;
    const select = chatElement('chatProvider');
    select.replaceChildren();
    const profiles = suppliers.profiles || [];
    if (!profiles.some(p => p.is_active)) {
      select.add(new Option(suppliers.effective?.name || '环境变量', ''));
    }
    for (const profile of profiles) select.add(new Option(profile.name, String(profile.id)));
    select.value = suppliers.effective?.id == null ? '' : String(suppliers.effective.id);
    const availableModels = (models.data || []).map(model => model.id).filter(Boolean);
    const datalist = chatElement('chatModels');
    datalist.replaceChildren();
    for (const modelId of availableModels) datalist.appendChild(new Option(modelId, modelId));
    const input = chatElement('chatModel');
    const currentModel = input.value.trim();
    if (!currentModel || (preferAvailableModel && availableModels.length && !availableModels.includes(currentModel))) {
      input.value = availableModels.includes(models.default_model)
        ? models.default_model
        : availableModels[0] || models.default_model || '';
    }
    chatConfigured = true;
    const missing = availableModels.length && !availableModels.includes(input.value);
    chatElement('chatStatus').textContent = missing ? '当前模型不在列表中，请选择或确认模型 ID' : '模型可从列表选择，也可手动填写';
  } catch (error) {
    chatConfigured = false;
    chatElement('chatStatus').textContent = error.message + '，请刷新重试';
  } finally {
    chatConfigBusy = false;
    updateChatAvailability();
  }
}
async function changeChatRoute(kind) {
  chatConfigBusy = true;
  updateChatAvailability();
  let errorMessage = '';
  try {
    if (kind === 'route') await chatJson('/api/route-settings', {
      method: 'PUT', body: JSON.stringify({provider: chatElement('chatRoute').value}),
    });
    else if (chatElement('chatProvider').value) {
      await chatJson(`/api/openai-providers/${encodeURIComponent(chatElement('chatProvider').value)}/activate`, {method: 'POST'});
      await chatJson('/api/route-settings', {method: 'PUT', body: JSON.stringify({provider: 'openai'})});
    }
  } catch (error) { errorMessage = error.message; }
  await loadChatConfig(true);
  if (errorMessage) chatElement('chatStatus').textContent = errorMessage;
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

async function consumeChatStream(response, onDelta) {
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
  const model = chatElement('chatModel').value.trim();
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
  try {
    if (!trigger) {
      await chatJson(`/api/conversations/${convId}/messages`, {method: 'POST', body: JSON.stringify({role: currentRole, content})});
      input.value = '';
    } else {
      const pendingUser = document.createElement('div');
      pendingUser.className = 'msg user';
      const pendingBody = document.createElement('div'); pendingBody.className = 'msg-body';
      pendingBody.textContent = content; pendingUser.appendChild(pendingBody);
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
      if (response.headers.get('content-type')?.includes('text/event-stream')) {
        await consumeChatStream(response, delta => {
          const atBottom = area.scrollHeight - area.scrollTop - area.clientHeight < 100;
          reply += delta; renderChatText(body, reply);
          if (atBottom) area.scrollTop = area.scrollHeight;
        });
      } else {
        const data = await response.json();
        if (data.error) throw new Error(typeof data.error === 'string' ? data.error : '回复失败');
        reply = data.choices?.[0]?.message?.content || '';
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
  chatElement('chatRoute').onchange = () => changeChatRoute('route');
  chatElement('chatProvider').onchange = () => changeChatRoute('provider');
  chatElement('refreshModels').onclick = loadChatConfig;
  chatElement('stopChat').onclick = () => chatController?.abort();
  chatElement('activateChat').onclick = async () => {
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
