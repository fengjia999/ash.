/* Local drafts and the phone presentation of the existing streaming chat. */
(() => {
    'use strict';
    let timer, draftId = null, generation = 0;
    const urls = new Map();
    let liveMessage = null, liveReasoning = '', reasoningDialog, activeReasoningButton = null;
    let savedKeepsakes = new Set(), keepsakeGeneration = 0;
    let recallDialog;
    async function openMessageRecall(messageId) {
        if (!recallDialog) {
            recallDialog=document.createElement('dialog');recallDialog.className='phone-reasoning-dialog phone-recall-dialog';
            recallDialog.innerHTML='<header><h2>本轮召回</h2><button type="button" aria-label="关闭召回">×</button></header><div class="phone-recall-content"></div>';
            recallDialog.querySelector('button').onclick=()=>recallDialog.close();document.body.appendChild(recallDialog);
        }
        const content=recallDialog.querySelector('.phone-recall-content');content.textContent='读取中…';recallDialog.showModal();
        try {
            const response=await fetch('/api/context-messages/'+Number(messageId)+'/recall');
            if(!response.ok)throw new Error('HTTP '+response.status);
            const data=await response.json();content.replaceChildren();
            if(data.fragments?.length){
                for(const fragment of data.fragments){
                    const card=document.createElement('p');card.textContent=fragment;content.append(card);
                }
                return;
            }
            if(!data.results?.length){content.textContent=data.recorded?'本轮没有注入召回内容。':'这条消息没有召回记录。';return;}
            for(const result of data.results){
                const card=document.createElement('section');card.className='phone-recall-card';
                for(const item of result.messages){
                    const label=document.createElement('small');label.textContent=(item.role==='user'?'用户':'助手')+' · '+String(item.date||'').slice(0,10);
                    const text=document.createElement('p');text.textContent=item.text;card.append(label,text);
                }
                const actions=document.createElement('div');actions.className='phone-recall-feedback';
                for(const [value,label] of [['useful','有用'],['useless','无用']]){
                    const button=document.createElement('button');button.type='button';button.dataset.feedback=value;button.setAttribute('aria-label',label);button.setAttribute('aria-pressed',String(result.feedback===value));
                    button.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 10v12M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H5a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 3a3.13 3.13 0 0 1 3 2.88Z"/></svg>';
                    button.onclick=async()=>{
                        const decision=button.getAttribute('aria-pressed')==='true'?'reset':value;
                        actions.querySelectorAll('button').forEach(b=>b.disabled=true);
                        try{
                            const saved=await fetch('/api/context-messages/'+Number(messageId)+'/recall/feedback',{method:'POST',headers:getH(),body:JSON.stringify({turn_id:result.turn_id,value:decision})});
                            if(!saved.ok)throw new Error('HTTP '+saved.status);
                            actions.querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.feedback===decision)));
                            status.textContent='';
                        }catch(error){status.textContent='保存失败：'+error.message;}
                        finally{actions.querySelectorAll('button').forEach(b=>b.disabled=false);}
                    };actions.appendChild(button);
                }
                const status=document.createElement('span');status.setAttribute('role','status');actions.appendChild(status);
                card.appendChild(actions);content.appendChild(card);
            }
        }catch(error){content.textContent='读取失败：'+error.message;}
    }
    function paintKeepsakeButton(button) {
        const saved = savedKeepsakes.has(button.dataset.keepsakeId);
        button.disabled = saved;
        button.setAttribute('aria-pressed', String(saved));
        button.title = saved ? '已收藏' : '收藏';
        button.setAttribute('aria-label', button.title);
    }
    async function syncKeepsakes() {
        const request = ++keepsakeGeneration;
        try {
            const items = await window.AshLocal.keepsakes();
            if (request !== keepsakeGeneration) return;
            savedKeepsakes = new Set(items.map(item => item.id));
            document.querySelectorAll('.phone-save-keepsake').forEach(paintKeepsakeButton);
        } catch (_) { /* Saving reports storage failures at the point of action. */ }
    }
    function setMessageReasoning(message, text) {
        if (!message || !text.trim()) return;
        let button = message.querySelector('.phone-message-reasoning');
        if (!button) {
            button = document.createElement('button');
            button.type = 'button'; button.className = 'phone-message-reasoning';
            button.setAttribute('aria-label','查看这条回复的思考');
            button.setAttribute('aria-haspopup','dialog');
            button.onclick = () => {
                activeReasoningButton = button;
                reasoningDialog.querySelector('.phone-reasoning-content').textContent = button.reasoningText;
                reasoningDialog.showModal();
            };
            message.querySelector('.phone-message-body').appendChild(button);
        }
        button.reasoningText = text;
        if (activeReasoningButton === button && reasoningDialog?.open)
            reasoningDialog.querySelector('.phone-reasoning-content').textContent = text;
    }
    function startReasoning(message) { liveMessage = message; liveReasoning = ''; }
    function appendReasoning(text) {
        if (typeof text === 'string' && text) {
            liveReasoning += text; setMessageReasoning(liveMessage, liveReasoning);
        }
    }
    function saveDraft() {
        clearTimeout(timer);
        const input = document.getElementById('msgInput');
        if (draftId && input) window.AshLocal.saveDraft(draftId, input.value);
    }
    function restoreDraft(id) {
        clearTimeout(timer); draftId = id;
        const input = document.getElementById('msgInput');
        if (input) { input.value = window.AshLocal.readDraft(id); resize(); }
    }
    function clearDraft(id) {
        clearTimeout(timer); window.AshLocal.saveDraft(id, '');
        resize();
    }
    function resize() {
        const input = document.getElementById('msgInput'); if (!input) return;
        input.style.height = 'auto'; input.style.height = Math.min(130, Math.max(22,input.scrollHeight)) + 'px';
    }
    function toggleOptions() {
        const open = document.body.classList.toggle('phone-chat-options-open');
        document.getElementById('phone-chat-more')?.setAttribute('aria-expanded',String(open));
    }
    async function identity() {
        const request = ++generation;
        const state = window.AshLocal.get();
        const name = state.names.assistant || 'Ash';
        const heading = document.getElementById('phone-chat-assistant-name'); if (heading) heading.textContent=name;
        for (const role of ['user','assistant']) {
            let blob; try { blob=await window.AshLocal.asset('avatar-'+role); } catch (_) {}
            if(request !== generation) return;
            const previous=urls.get(role); const url=blob instanceof Blob ? URL.createObjectURL(blob) : '';
            urls.set(role,url); if(previous) URL.revokeObjectURL(previous);
            if(url) document.body.style.setProperty('--chat-avatar-'+role, `url("${url}")`);
            else document.body.style.removeProperty('--chat-avatar-'+role);
            const avatar=document.querySelector(`[data-chat-avatar="${role}"]`);
            if(avatar) { avatar.replaceChildren(); if(url) { const image=document.createElement('img'); image.src=url; image.alt=''; avatar.appendChild(image); }
                else { avatar.innerHTML='<svg viewBox="0 0 60 60" aria-hidden="true"><path d="M17 22v4m26-4v4M18 37q12 14 24 0"/></svg>'; } }
        }
    }
    function syncState() {
        const notice=document.getElementById('phone-chat-notice'); if(!notice) return;
        const status=document.getElementById('chatStatus').textContent;
        const inactive=typeof currentConversationOverview !== 'undefined' && currentConversationOverview && !currentConversationOverview.is_active;
        const routine=/^(正在使用 Ash 的聊天配置|正在读取配置|回复完成|已追加到上下文|已激活，可以继续聊天)/.test(status);
        notice.hidden=!inactive && (routine || !status);
        document.getElementById('phone-chat-notice-text').textContent=inactive ? '历史会话' : status;
        document.getElementById('phone-chat-continue').hidden=!inactive;
    }
    function decorateMessage(message, reasoning = '', record = null) {
        if(message.querySelector('.phone-message-body')) return;
        const content=message.querySelector('.msg-body'); if(!content) return;
        const envelope=document.createElement('div');envelope.className='phone-message-body';
        const bubble=document.createElement('div');bubble.className='phone-message-bubble';
        const note=message.querySelector('.msg-prompt-note');if(note)bubble.appendChild(note);
        bubble.appendChild(content);envelope.appendChild(bubble);
        const header=message.querySelector('.msg-header');if(header){header.classList.add('phone-message-time');envelope.appendChild(header);}
        message.prepend(envelope);
        setMessageReasoning(message, reasoning);
        const actions=message.querySelector('.msg-actions');
        if(actions) {
            envelope.appendChild(actions);
            const copy=document.createElement('button');copy.type='button';copy.className='msg-act-btn phone-copy-message';copy.textContent='复制';
            copy.onclick=async()=>{
                try { await navigator.clipboard.writeText(content.innerText);copy.textContent='已复制'; }
                catch (_) { copy.textContent='复制失败'; }
                setTimeout(()=>{copy.textContent='复制';},1500);
            };
            actions.prepend(copy);
            if(record?.id && ['user','assistant'].includes(record.role)){
                const star=document.createElement('button');star.type='button';star.className='msg-act-btn phone-message-recall';
                star.setAttribute('aria-label','查看本轮召回');star.setAttribute('aria-haspopup','dialog');
                star.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m12 3 2.8 5.7 6.3.9-4.6 4.5 1.1 6.3-5.6-3-5.6 3 1.1-6.3L3 9.6l6.2-.9L12 3Z"/></svg>';
                star.onclick=()=>openMessageRecall(record.id);actions.appendChild(star);
            }
            if (record && ['user','assistant'].includes(record.role) && String(record.content || '').trim()) {
                const conversationId = currentConvId;
                const conversationName = currentConversationOverview?.name || '';
                const bookmark = document.createElement('button'); bookmark.type = 'button';
                bookmark.className = 'msg-act-btn phone-save-keepsake';
                bookmark.dataset.keepsakeId = conversationId + ':' + record.id;
                bookmark.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3h12v18l-6-4-6 4V3Z"/></svg>';
                paintKeepsakeButton(bookmark); copy.after(bookmark);
                bookmark.onclick = async () => {
                    bookmark.disabled = true;
                    try {
                        const item = await window.AshLocal.saveKeepsake({conversationId, messageId:record.id,
                            conversationName, role:record.role, content:String(record.content),
                            createdAt:record.created_at || '', name:window.AshLocal.get().names[record.role]});
                        savedKeepsakes.add(item.id); paintKeepsakeButton(bookmark);
                    } catch (error) {
                        bookmark.disabled = false;
                        bookmark.title = '收藏失败：' + error.message;
                        document.getElementById('chatStatus').textContent = bookmark.title;
                    }
                };
            }
        }
    }
    function syncBack() {
        try {
            const target = window.parent.AshPhone?.returnTitle() || 'Chat';
            const button = document.querySelector('.topbar-left .menu-btn');
            button.title = button.ariaLabel = '返回' + target;
        } catch (_) {}
    }
    function setModelLabel(model) {
        const label = document.querySelector('#phone-chat-model .phone-chat-model-label');
        if (label) label.textContent = model || '待配置';
        document.getElementById('phone-chat-model').title = model ? '聊天配置 · ' + model : '聊天配置';
    }
    window.AshChatUI = {saveDraft,restoreDraft,clearDraft,syncState,decorateMessage,syncBack,setModelLabel,
        startReasoning,appendReasoning};
    document.addEventListener('DOMContentLoaded',()=>{
        const input=document.getElementById('msgInput'); if(!input) return;
        identity(); syncKeepsakes();
        reasoningDialog = document.createElement('dialog'); reasoningDialog.className = 'phone-reasoning-dialog';
        reasoningDialog.setAttribute('aria-labelledby','phone-reasoning-title');
        const heading = document.createElement('header'), title = document.createElement('h2'), close = document.createElement('button');
        title.id = 'phone-reasoning-title'; title.textContent = '思考'; title.tabIndex = -1; title.autofocus = true;
        close.type = 'button'; close.textContent = '×'; close.setAttribute('aria-label','关闭思考');
        close.onclick = () => reasoningDialog.close(); heading.append(title,close);
        const content = document.createElement('div'); content.className = 'phone-reasoning-content';
        reasoningDialog.append(heading,content); document.body.appendChild(reasoningDialog);
        reasoningDialog.addEventListener('close',()=>{activeReasoningButton=null;});
        reasoningDialog.addEventListener('click',event=>{if(event.target===reasoningDialog){const box=reasoningDialog.getBoundingClientRect();if(event.clientX<box.left||event.clientX>box.right||event.clientY<box.top||event.clientY>box.bottom)reasoningDialog.close();}});
        syncBack();
        input.addEventListener('input',()=>{clearTimeout(timer);timer=setTimeout(saveDraft,250);resize();});
        document.getElementById('phone-chat-more').onclick=toggleOptions;
        document.getElementById('phone-chat-identity').onclick=()=>openCurrentConversationSettings();
        new MutationObserver(syncState).observe(document.getElementById('chatStatus'),{childList:true,subtree:true,characterData:true});
        // On an initially empty conversation, selectConv may have run before this listener.
        if(typeof currentConvId !== 'undefined' && currentConvId && draftId !== currentConvId) restoreDraft(currentConvId);
        resize();setModelLabel(typeof chatEffectiveModel === 'string' ? chatEffectiveModel : '');
        const composer=document.getElementById('composer');
        new ResizeObserver(()=>document.body.style.setProperty('--chat-compose-height',composer.offsetHeight+'px')).observe(composer);
        const topbar=document.querySelector('.app > .topbar');
        new ResizeObserver(()=>document.body.style.setProperty('--chat-header-space',topbar.offsetHeight+'px')).observe(topbar);
        const area=document.getElementById('msgArea');
        let press=null, suppressTapUntil=0;
        function closeActions() { document.querySelectorAll('.phone-message-actions-open').forEach(el=>el.classList.remove('phone-message-actions-open')); }
        document.addEventListener('pointerdown',event=>{if(!event.target.closest('.msg'))closeActions();});
        document.addEventListener('focusin',event=>{if(!event.target.closest('.msg'))closeActions();});
        function cancelPress(event) {
            if (!press || (event?.pointerId !== undefined && event.pointerId !== press.id)) return;
            clearTimeout(press.timer); press=null;
        }
        // Merle bindBubbleLongPress: 500ms hold, cancel after 10px or a scroll/cancel.
        area.addEventListener('pointerdown',event=>{
            if (!event.isPrimary) { cancelPress(); return; }
            if (event.button !== 0 || event.target.closest('button,a,input,textarea,pre,code') || (typeof selectionMode!=='undefined'&&selectionMode)) return;
            const bubble=event.target.closest('.phone-message-bubble'), message=bubble?.closest('.msg');
            if (!message) return;
            cancelPress();
            press={id:event.pointerId,x:event.clientX,y:event.clientY,message};
            press.timer=setTimeout(()=>{
                if (!press || !message.isConnected) return;
                closeActions(); message.classList.add('phone-message-actions-open');
                suppressTapUntil=Date.now()+800; navigator.vibrate?.(20); press.timer=null;
            },500);
        });
        window.addEventListener('pointermove',event=>{
            if (press?.id === event.pointerId && Math.hypot(event.clientX-press.x,event.clientY-press.y)>10) cancelPress(event);
        },{passive:true});
        window.addEventListener('pointerup',event=>{
            if (press?.id === event.pointerId && press.timer===null) suppressTapUntil=Date.now()+400;
            cancelPress(event);
        });
        window.addEventListener('pointercancel',cancelPress);
        window.addEventListener('blur',()=>{cancelPress();closeActions();});
        area.addEventListener('scroll',()=>{cancelPress();closeActions();},{passive:true});
        area.addEventListener('contextmenu',event=>{
            if(event.target.closest('.phone-message-bubble')&&!event.target.closest('a,pre,code')) event.preventDefault();
        });
        area.addEventListener('click',event=>{
            if (event.detail && Date.now()<suppressTapUntil && !event.target.closest('button,a')) { event.preventDefault(); event.stopImmediatePropagation(); }
        },true);
        area.addEventListener('click',event=>{
            const message=event.target.closest('.msg');
            if(!message||event.target.closest('button')||(typeof selectionMode!=='undefined'&&selectionMode)||!getSelection()?.isCollapsed)return;
            if(event.pointerType==='touch'||event.pointerType==='pen') { closeActions(); return; }
            const opening=!message.classList.contains('phone-message-actions-open');
            closeActions();
            if(opening)message.classList.add('phone-message-actions-open');
        });
        // Keep the active composer visible when the outer shell resizes for the keyboard.
        window.addEventListener('ash-phone-keyboard',event=>{
            if(event.detail.open && document.activeElement===input) requestAnimationFrame(()=>{area.scrollTop=area.scrollHeight;});
        });
    });
    window.addEventListener('pagehide',saveDraft);
    document.addEventListener('visibilitychange',()=>{if(document.hidden) saveDraft();});
    window.addEventListener('ash-local-change',event=>{
        if(event.detail?.kind === 'keepsakes') syncKeepsakes();
        else identity();
    });
    window.addEventListener('ash-local-error',event=>{
        const notice=document.getElementById('phone-chat-notice');if(notice){notice.hidden=false;document.getElementById('phone-chat-notice-text').textContent=event.detail;}
    });
    window.addEventListener('message',event=>{if(event.origin===location.origin&&event.source===parent&&event.data?.type==='ash-local-presentation')identity();});
})();
