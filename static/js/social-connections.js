(() => {
 'use strict';
 document.addEventListener('DOMContentLoaded',()=>document.querySelectorAll('.social-bot').forEach(section=>{
  const provider=section.dataset.provider,$=name=>section.querySelector('[data-social="'+name+'"]'),form=$('form'),field=name=>form.elements.namedItem(name);
  let config=null,busy=false,loading=false,session=null,generation=0,timer=null,statusTimer=null,verifyCode='',statusMessage='';
  const active=()=>section.classList.contains('active');
  const message=(text='',error=false)=>{$('message').textContent=text;$('message').classList.toggle('is-error',error);};
  const setBusy=value=>{busy=value;section.querySelectorAll('button,input,select').forEach(node=>node.disabled=value);};
  async function api(path='',method='GET',body){const response=await authFetch('/api/bot-connections/'+provider+path,{method,cache:'no-store',headers:{'Content-Type':'application/json'},...(body===undefined?{}:{body:JSON.stringify(body)})});const data=await readJsonResponse(response);if(!response.ok)throw new Error(data.error||'连接操作失败');return data;}
  function fill(value,saved=true){config=value;form.hidden=provider==='weixin'&&!saved;
   field('enabled').checked=saved?!!value.enabled:true;field('time_enabled').checked=value.time_enabled!==false;field('debounce_seconds').value=value.debounce_seconds??30;
   if(provider==='feishu'){field('feishu_domain').value=value.feishu_domain||'feishu';field('app_id').value=value.app_id||'';field('app_secret').value='';field('app_secret').placeholder=value.app_secret_configured?'已保存，留空保留':'必填';}
   else $('account').textContent=value.bot_id||'';
   $('owner').textContent=value.owner_bound?'已绑定':'未绑定';$('reconnect').hidden=!saved;
   if($('wx-note'))$('wx-note').hidden=saved;
   scheduleStatus();
  }
  async function load(){if(loading||busy)return;loading=true;setBusy(true);$('retry').hidden=true;
   try{const data=await api();fill(data.connection,data.saved);message();}catch(error){message(error.message,true);$('retry').hidden=false;}finally{loading=false;setBusy(false);}}
  function scheduleStatus(){clearTimeout(statusTimer);if(!active()||document.hidden)return;statusTimer=setTimeout(async()=>{
   if(!busy)try{const data=await api('/check','POST');if(!active())return;$('status').textContent=({connected:'已连接',connecting:'正在连接',disabled:'已停用',error:'连接异常'})[data.status]||'未连接';$('status').dataset.state=data.status;if(data.error){statusMessage=data.error;message(data.error,true);}else if(statusMessage){if($('message').textContent===statusMessage)message();statusMessage='';}}catch(error){message(error.message,true);}
   scheduleStatus();},2500);}
  async function cancel(){generation++;clearTimeout(timer);const id=session;session=null;verifyCode='';$('setup-panel').hidden=true;$('verify-form').hidden=true;$('setup').hidden=false;
   if(id)try{await api('/setup/'+id,'DELETE');}catch{} }
  async function poll(current){if(!session||current!==generation||!active())return;
   try{const data=await api('/setup/'+session+'/check','POST',{verify_code:verifyCode});if(current!==generation||!active())return;
    if(data.status==='authorized'){session=null;generation++;$('setup-panel').hidden=true;$('setup').hidden=false;fill(data.connection);message('连接已保存');return;}
    if(data.image&&/^data:image\/png;base64,/.test(data.image)){ $('qr').src=data.image;$('qr').hidden=false;}
    if(data.code){$('code').textContent=data.code;$('pairing').hidden=false;}
    $('verify-form').hidden=data.status!=='need_verifycode';
    $('setup-status').textContent=({waiting:provider==='feishu'?'等待绑定消息':'等待扫码',scanned:'请在手机上确认',need_verifycode:'请输入手机上显示的验证码',expired:'已过期，请重新开始',failed:'连接失败，请重试'})[data.status]||'正在准备';
    if(['expired','failed'].includes(data.status)){ $('setup').hidden=false;return;}
    timer=setTimeout(()=>poll(current),1500);
   }catch(error){if(current===generation){message(error.message,true);$('setup').hidden=false;}}
  }
  form.onsubmit=async event=>{event.preventDefault();if(busy)return;setBusy(true);message();
   const data={enabled:field('enabled').checked,time_enabled:field('time_enabled').checked,debounce_seconds:Number(field('debounce_seconds').value)};
   if(provider==='feishu'){data.feishu_domain=field('feishu_domain').value;data.app_id=field('app_id').value.trim();data.app_secret=field('app_secret').value.trim();}
   try{const result=await api('','PUT',data);fill(result.connection);message('已保存');}catch(error){message(error.message,true);}finally{setBusy(false);}
  };
  $('setup').onclick=async()=>{if(busy)return;setBusy(true);await cancel();const current=generation;message();$('setup-panel').hidden=false;$('setup').hidden=true;$('qr').hidden=true;$('pairing').hidden=true;$('setup-status').textContent='正在准备…';
   try{const data=await api('/setup','POST',{});if(current!==generation||!active()){await api('/setup/'+data.id,'DELETE');return;}session=data.id;if(data.code){$('code').textContent=data.code;$('pairing').hidden=false;}timer=setTimeout(()=>poll(current),500);}
   catch(error){message(error.message,true);$('setup').hidden=false;$('setup-panel').hidden=true;}finally{setBusy(false);}
  };
  $('verify-form').onsubmit=event=>{event.preventDefault();verifyCode=$('verify-form').elements.verify_code.value.trim();$('setup-status').textContent='正在验证…';};
  $('cancel').onclick=()=>cancel();$('retry').onclick=load;
  $('reconnect').onclick=async()=>{if(busy)return;setBusy(true);try{await api('/reconnect','POST');field('enabled').checked=true;message('正在连接');scheduleStatus();}catch(error){message(error.message,true);}finally{setBusy(false);}};
  new MutationObserver(()=>{if(active())load();else{clearTimeout(statusTimer);void cancel();}}).observe(section,{attributes:true,attributeFilter:['class']});
  document.addEventListener('visibilitychange',()=>document.hidden?clearTimeout(statusTimer):scheduleStatus());
  if(active())load();
 }));
})();
