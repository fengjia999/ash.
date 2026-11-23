(() => {
    'use strict';
    const $=id=>document.getElementById('qq-'+id);
    let connection=null,loading=false,busy=false,session=null,pollTimer=null,statusTimer=null,expectedId='',view='choices',generation=0;
    const active=()=>document.getElementById('section-bot-qq')?.classList.contains('active');
    async function api(path='',method='GET',body){
        const response=await authFetch('/api/bot-connections/qq'+path,{method,cache:'no-store',headers:{'Content-Type':'application/json'},...(body===undefined?{}:{body:JSON.stringify(body)})});
        const data=await readJsonResponse(response);
        if(!response.ok)throw new Error(data.error||'连接操作失败');
        return data;
    }
    function message(text='',error=false){$('message').textContent=text;$('message').classList.toggle('is-error',error);}
    function setBusy(value){busy=value;document.querySelectorAll('#section-bot-qq button,#section-bot-qq input').forEach(node=>{node.disabled=value;});}
    function setup(next){
        view=next;$('summary').hidden=next!=='summary';$('setup').hidden=next==='summary';
        $('choices').hidden=next!=='choices';$('existing-form').hidden=next!=='existing';$('qr-panel').hidden=next!=='qr';
        $('setup-back').hidden=next==='summary'||(next==='choices'&&!connection?.app_id);
    }
    function summary(config){connection=config;$('app-id').textContent=config.app_id;$('enabled').checked=config.enabled;
        $('time-enabled').checked=config.time_enabled!==false;$('debounce-seconds').value=config.debounce_seconds??30;
        setup('summary');scheduleStatus();}
    async function load(){
        if(loading||busy)return;loading=true;setBusy(true);message('正在读取…');$('retry').hidden=true;
        try{const data=await api();connection=data.connection;message();if(data.saved)summary(connection);else setup('choices');}
        catch(error){message(error.message,true);$('retry').hidden=false;}
        finally{loading=false;setBusy(false);}
    }
    async function cancel(){
        generation++;clearTimeout(pollTimer);
        const previous=session;session=null;
        if(previous){try{await api('/qr/'+previous,'DELETE');}catch{/* expiry also clears abandoned setup */}}
    }
    async function begin(appId=''){
        if(busy)return;
        setBusy(true);
        await cancel();const current=generation;expectedId=appId;setup('qr');message();
        $('expected-id').textContent=appId?'AppID '+appId:'';$('expected-id').hidden=!appId;
        $('qr-image').hidden=true;$('qr-image').removeAttribute('src');$('qr-state').textContent='正在生成二维码…';
        setBusy(true);
        try{
            const data=await api('/qr','POST',{app_id:appId});
            if(current!==generation||!active()){try{await api('/qr/'+data.id,'DELETE');}catch{}return;}
            session=data.id;schedulePoll(current);
        }catch(error){message(error.message,true);$('qr-state').textContent='生成失败';}
        finally{setBusy(false);if(current!==generation&&active())load();}
    }
    function schedulePoll(current){clearTimeout(pollTimer);pollTimer=setTimeout(()=>poll(current),1500);}
    async function poll(current){
        if(!session||current!==generation||!active())return;
        try{
            const data=await api('/qr/'+session+'/check','POST');
            if(current!==generation||!active())return;
            if(data.status==='authorized'){
                session=null;generation++;$('qr-image').hidden=true;$('qr-image').removeAttribute('src');
                summary(data.connection);$('status').textContent='正在连接…';message('授权成功');return;
            }
            if(['failed','expired','mismatch'].includes(data.status)){
                $('qr-image').hidden=true;$('qr-state').textContent=data.status==='expired'?'二维码已失效':'授权未完成';
                message(data.error||(data.status==='mismatch'?'Bot 与填写的 AppID 不一致':'请重新生成二维码'),true);return;
            }
            if(data.image){$('qr-image').src=data.image;$('qr-image').hidden=false;}
            else{$('qr-image').hidden=true;}
            $('qr-state').textContent=data.status==='waiting'?'等待扫码授权':'正在生成二维码…';schedulePoll(current);
        }catch(error){if(current===generation){message(error.message,true);$('qr-state').textContent='连接中断，请重试';}}
    }
    function scheduleStatus(){
        clearTimeout(statusTimer);
        if(!active()||document.hidden||view!=='summary')return;
        statusTimer=setTimeout(async()=>{
            if(!busy){try{const data=await api('/check','POST');if(!active()||view!=='summary')return;$('status').textContent=({connected:'已连接',connecting:'正在连接…',disabled:'已停用',error:'连接异常'})[data.status]||'未连接';$('status').dataset.state=data.status;if(data.error)message(data.error,true);}catch(error){message(error.message,true);}}
            scheduleStatus();
        },2500);
    }
    document.addEventListener('DOMContentLoaded',()=>{
        const section=document.getElementById('section-bot-qq');if(!section)return;
        new MutationObserver(()=>{if(active())load();else{clearTimeout(statusTimer);void cancel();}}).observe(section,{attributes:true,attributeFilter:['class']});
        if(active())load();
        document.addEventListener('visibilitychange',()=>{if(document.hidden)clearTimeout(statusTimer);else scheduleStatus();});
        $('scan').onclick=()=>begin();
        $('existing').onclick=()=>{message();setup('existing');$('existing-id').focus();};
        $('existing-form').onsubmit=event=>{event.preventDefault();begin($('existing-id').value.trim());};
        $('refresh-qr').onclick=()=>begin(expectedId);
        $('setup-back').onclick=async()=>{await cancel();message();if(view==='choices'&&connection?.app_id)summary(connection);else setup('choices');};
        $('reauthorize').onclick=()=>{clearTimeout(statusTimer);message();setup('choices');};
        $('retry').onclick=load;
        $('save-settings').onclick=async()=>{
            if(busy||!$('debounce-seconds').reportValidity())return;
            const debounce_seconds=Number($('debounce-seconds').value);
            setBusy(true);message();
            try{const data=await api('','PUT',{time_enabled:$('time-enabled').checked,debounce_seconds});summary(data.connection);message('设置已保存');}
            catch(error){message(error.message,true);}finally{setBusy(false);}
        };
        $('enabled').onchange=async()=>{
            if(busy)return;const enabled=$('enabled').checked;setBusy(true);message();
            try{const data=await api('','PUT',{enabled});summary(data.connection);$('status').textContent=enabled?'正在连接…':'已停用';$('status').dataset.state=enabled?'connecting':'disabled';}
            catch(error){$('enabled').checked=!!connection?.enabled;message(error.message,true);}
            finally{setBusy(false);}
        };
        $('reconnect').onclick=async()=>{
            if(busy)return;setBusy(true);message();
            try{await api('/reconnect','POST');connection.enabled=true;$('enabled').checked=true;$('status').textContent='正在连接…';$('status').dataset.state='connecting';scheduleStatus();}
            catch(error){message(error.message,true);}finally{setBusy(false);}
        };
    });
})();
