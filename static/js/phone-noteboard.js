/* Paper shapes, tape and normalized drag placement adapted from Merle creativity.js.
   Ash owns note text on the server; only the arrangement belongs to this browser. */
(() => {
    'use strict';
    const $ = id => document.getElementById(id), surface = $('phone-note-surface'), layer = $('phone-notes-layer');
    const clamp = (value,min,max) => Math.min(max,Math.max(min,value));
    const hash = value => { let result=0; for (const char of String(value)) result=(result*31+char.charCodeAt(0))>>>0; return Math.imul(result,2654435761)>>>0; };
    let notes=[], request=0, drag=null, suppressClick=0, ready=false;
    let layout=window.AshLocal.get().noteLayout;
    const active = () => document.body.dataset.phoneView==='chat' && !$('phone-note-surface').closest('[data-chat-panel]').hidden;
    const say = text => window.AshPhone.toast(text);
    function placement(note,index) {
        return layout[note.id] || {x:index%2 ? .87 : .04, y:clamp(Math.floor(index/2)/Math.max(2,Math.ceil(notes.length/2)),0,1),
            rotation:((hash(note.id)%57)-28)/10,z:index+1};
    }
    function saveLayout() {
        window.AshLocal.update(state=>{state.noteLayout=layout;},'note-layout');
    }
    function presentation(note) {
        const seed=hash(note.id);
        return [['shape-tall','shape-square','shape-wide','shape-tall'][seed%4],
            ['tape-vertical','tape-horizontal','tape-left','tape-right','tape-double'][(seed>>>3)%5],
            (seed>>>6)%5===0?'note-lined':''].filter(Boolean).join(' ');
    }
    function render() {
        if (drag) return;
        surface.style.height=Math.max(580,260+Math.ceil(notes.length/2)*180)+'px';
        const fragment=document.createDocumentFragment();
        notes.forEach((note,index)=>{
            layout[note.id] ||= placement(note,index);
            const card=document.createElement('button');card.type='button';card.className='phone-wall-note '+presentation(note);card.dataset.noteId=note.id;
            card.style.setProperty('--note-rotation',layout[note.id].rotation+'deg');card.style.zIndex=layout[note.id].z;
            const author=document.createElement('span');author.className='phone-wall-author';author.textContent=window.AshLocal.get().names[note.author] || (note.author==='assistant'?'Ash':'我');
            const title=document.createElement('strong');title.textContent=note.title;
            const copy=document.createElement('span');copy.className='phone-wall-copy';copy.textContent=note.content;
            const time=document.createElement('time');time.textContent=(note.created_at || '').slice(0,10).replaceAll('-','.');
            card.append(author);if(note.title)card.append(title);card.append(copy,time);
            card.onclick=()=>{if(Date.now()>suppressClick)edit(note);};fragment.append(card);
        });
        layer.replaceChildren(fragment);$('phone-note-empty').hidden=notes.length>0;
        $('phone-note-arrange').disabled=notes.length<2;
        requestAnimationFrame(positionNotes);
    }
    function bounds(element) { return {x:Math.max(0,surface.clientWidth-element.offsetWidth-40),y:Math.max(0,surface.clientHeight-element.offsetHeight-64)}; }
    function positionNotes() {
        for(const card of layer.children) {
            if(drag?.card===card)continue;
            const position=layout[card.dataset.noteId], max=bounds(card);
            card.style.left=(20+position.x*max.x)+'px';card.style.top=(24+position.y*max.y)+'px';
        }
    }
    async function open() {
        const generation=++request;$('phone-note-retry').hidden=true;
        if(!ready)$('phone-note-status').textContent='载入中…';
        try {
            const result=await saveDashboardJson('/api/noteboard');
            if(generation!==request)return;
            notes=result.notes || [];ready=true;$('phone-note-status').textContent='';
            const ids=new Set(notes.map(note=>String(note.id)));
            let changed=false;
            for(const id of Object.keys(layout))if(!ids.has(id)){delete layout[id];changed=true;}
            notes.forEach((note,index)=>{if(!layout[note.id]){layout[note.id]=placement(note,index);changed=true;}});
            if(changed)try{saveLayout();}catch(_){say('便签已载入，摆放位置未能保存在本机');}
            render();
        } catch(error) {
            if(generation!==request)return;
            $('phone-note-status').textContent='便签读取失败';$('phone-note-retry').hidden=false;
        }
    }
    function edit(note=null) {
        window.AshPhone.sheet(note?'便签':'新增便签',`<form id="phone-note-editor">
            <input id="phone-note-title" maxlength="80" placeholder="标题" aria-label="标题" autocomplete="off">
            <textarea id="phone-note-content" maxlength="12000" placeholder="写点什么…" aria-label="便签正文" required></textarea>
            <p id="phone-note-error" role="status"></p>
            <div class="phone-note-editor-actions"><button type="button" id="phone-note-delete" ${note?'':'hidden'}>删除</button><button type="submit" class="phone-primary-button" id="phone-note-save">保存</button></div></form>`);
        $('phone-note-title').value=note?.title || '';$('phone-note-content').value=note?.content || '';
        const form=$('phone-note-editor');
        let saving=false;
        const busy = value => {saving=value;$('phone-note-save').disabled=value;$('phone-note-delete').disabled=value;};
        const fail=error=>{if(form.isConnected){$('phone-note-error').textContent=error.message;busy(false);}else say(error.message);if(error.message.includes('便签已更改'))open();};
        $('phone-note-editor').onsubmit=async event=>{
            event.preventDefault();if(saving)return;
            const content=$('phone-note-content').value.trim();if(!content){$('phone-note-content').focus();return;}
            busy(true);
            try {
                const result=await saveDashboardJson('/api/noteboard'+(note?'/'+note.id:''),{method:note?'PUT':'POST',headers:{'Content-Type':'application/json'},
                    body:JSON.stringify({title:$('phone-note-title').value,content,...(note?{revision:note.revision}:{})})});
                notes=notes.filter(item=>item.id!==result.note.id);notes.unshift(result.note);++request;
                if(!note) { // New paper opens near the visible top, without moving older notes.
                    layout[result.note.id]={x:.35,y:.04,rotation:((hash(result.note.id)%57)-28)/10,z:Math.max(0,...Object.values(layout).map(p=>p.z))+1};
                }
                try{saveLayout();}catch(_){say('便签已保存，摆放位置未能保存在本机');}
                if(form.isConnected)$('phone-personalize').close();render();
                if(active())document.querySelector('.phone-chat-panels').scrollTop=0;
            } catch(error){fail(error);}
        };
        $('phone-note-delete').onclick=async()=>{
            if(saving || !confirm('删除这张便签？'))return;busy(true);
            try{
                await saveDashboardJson(`/api/noteboard/${note.id}?revision=${note.revision}`,{method:'DELETE'});
                ++request;notes=notes.filter(item=>item.id!==note.id);delete layout[note.id];
                try{saveLayout();}catch(_){}
                if(form.isConnected)$('phone-personalize').close();render();
            }catch(error){fail(error);}
        };
    }
    function arrange() {
        notes.forEach((note,index)=>{layout[note.id]={x:index%2?.92:.02,y:(Math.floor(index/2)+.08*(index%2))/Math.max(1,Math.ceil(notes.length/2)),rotation:(Math.random()*5.6)-2.8,z:index+1};});
        try{saveLayout();render();}catch(_){say('摆放位置未保存');}
    }
    layer.addEventListener('pointerdown',event=>{
        const card=event.target.closest('.phone-wall-note');
        if(!card || event.button!==0 || !event.isPrimary)return;
        const original={...layout[card.dataset.noteId]};
        drag={card,id:event.pointerId,x:event.clientX,y:event.clientY,left:parseFloat(card.style.left),top:parseFloat(card.style.top),original,moved:false};
        card.setPointerCapture(event.pointerId);
    });
    layer.addEventListener('pointermove',event=>{
        if(!drag || event.pointerId!==drag.id)return;
        const dx=event.clientX-drag.x,dy=event.clientY-drag.y;
        if(Math.hypot(dx,dy)>5)drag.moved=true;
        if(!drag.moved)return;
        drag.card.classList.add('is-dragging');
        drag.card.style.zIndex=Math.max(0,...Object.values(layout).map(p=>p.z))+1;
        const max=bounds(drag.card);
        drag.card.style.left=clamp(drag.left+dx,20,20+max.x)+'px';drag.card.style.top=clamp(drag.top+dy,24,24+max.y)+'px';
        event.preventDefault();
    });
    function endDrag(event) {
        if(!drag || event.pointerId!==drag.id)return;
        const {card,moved,original}=drag;drag=null;card.classList.remove('is-dragging');
        if(card.hasPointerCapture(event.pointerId))card.releasePointerCapture(event.pointerId);
        if(event.type==='pointercancel') {layout[card.dataset.noteId]=original;positionNotes();return;}
        if(moved){
            suppressClick=Date.now()+300;const max=bounds(card);
            layout[card.dataset.noteId]={...original,x:max.x?(parseFloat(card.style.left)-20)/max.x:0,y:max.y?(parseFloat(card.style.top)-24)/max.y:0,z:Number(card.style.zIndex)};
            try{saveLayout();}catch(_){say('摆放位置未保存');}
        }
        positionNotes();
    }
    layer.addEventListener('pointerup',endDrag);layer.addEventListener('pointercancel',endDrag);
    new ResizeObserver(()=>{if(active())positionNotes();}).observe(surface);
    $('phone-note-add').onclick=()=>edit();$('phone-note-arrange').onclick=arrange;$('phone-note-retry').onclick=open;
    // Refresh only when visible; no background polling or generated summaries.
    document.addEventListener('visibilitychange',()=>{if(!document.hidden && active())open();});
    window.addEventListener('ash-local-change',event=>{
        if(event.detail?.kind==='state'){layout=window.AshLocal.get().noteLayout;if(active())render();}
    });
    window.AshNoteboard={open};
})();
