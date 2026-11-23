/* Run with PLAYWRIGHT_MODULE pointing to Playwright if it is not in node_modules.
 * ASH_PHONE_NAV_ONLY=1 runs navigation; ASH_PHONE_EXIT_ONLY=1 checks the exit regression.
 * ASH_PHONE_SKIP_NAV=1 runs the remaining integration checks.
 * All browser requests are intercepted; no live account, database or provider is used.
 */
const playwright = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const root = path.resolve(__dirname,'..');
const pages = JSON.parse(execFileSync(process.env.PYTHON || 'python3',['-c',`
import json,sys
from jinja2 import Environment,FileSystemLoader
e=Environment(loader=FileSystemLoader(sys.argv[1]+'/templates'))
v=dict(static_version='test',chat_version='test',csrf_token='test-csrf',initial_conversation_id=1,show_created_modal=False)
print(json.dumps({'dashboard':e.get_template('dashboard.html').render(**v),'prompt':e.get_template('prompt.html').render(**v,embedded='dashboard'),**{m:e.get_template('context.html').render(**dict(v,initial_conversation_id=i),embedded='list' if m=='list' else 'detail') for m,i in [('list',0),('detail',1),('history',2)]}}))
`,root],{encoding:'utf8'}));
const screenshotDir = process.env.ASH_SCREENSHOT_DIR || '/tmp/ash-phone-qa';
fs.mkdirSync(screenshotDir,{recursive:true});

(async()=>{
 const browser=await playwright[process.env.ASH_BROWSER || 'chromium'].launch({headless:true,...(process.env.ASH_BROWSER==='webkit'?(process.env.PLAYWRIGHT_WEBKIT_EXECUTABLE_PATH?{executablePath:process.env.PLAYWRIGHT_WEBKIT_EXECUTABLE_PATH}:{}):{args:['--no-sandbox','--disable-gpu','--renderer-process-limit=1'],...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH?{executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH}:{})})});
 try {
 const context=await browser.newContext({viewport:{width:390,height:844},deviceScaleFactor:1,reducedMotion:'reduce',...(process.env.ASH_PHONE_MOBILE?{hasTouch:true,isMobile:true}:{})});
 const page=await context.newPage(), errors=[], writes=[];
 page.setDefaultTimeout(10000);
 page.setDefaultNavigationTimeout(60000);
 page.on('pageerror',e=>errors.push(e.message));
 let activeId=1, failChat=false, delayConversationReads=false;
 let countStatsGate=null;const countReads=[];
 let diarySaveError=false, keywordPreviewError=false, keywordPreviewGate=null;const editorDiaries=[];
 let exportStatus='running';const exportUrls=[];
 const diaryReads=[];
 const memoryEditorWrites=[];let memoryEditorSaveError=false;
 let botConnection=null, botApplyError=false, botCatalogError=false; const botWrites=[];
 const socialConnections={feishu:null,weixin:null};let socialOutcome='waiting',socialCancelled=0,socialConnectionError='';
 let qqConnection=null,qqOutcome='waiting',qqExpected='',qqCreateError=false,qqCancelled=0;
 const qqSession='12345678-1234-4234-8234-123456789abc';
 const qqImage=(process.env.ASH_PHONE_QQ_ONLY||process.env.ASH_PHONE_SOCIAL_ONLY)?await require(path.join(root,'integrations/qq/node_modules/qrcode')).toDataURL('https://q.qq.com/ash-ui-test'):'';
 const promptSections=[{key:'Identity',mode:'editable',priority:100,content:'Original identity prompt.'},{key:'Interaction',mode:'editable',priority:90,content:'Original interaction prompt.'}];
 let identityPresets={user_name:'我',assistant_name:'Ash'};
 let apiSettings={provider:'openai',model:'test-model',api_url:'https://example.test/v1',api_key:'current-secret'};
 let apiPresets=[];
 let wallNotes=[], noteFailure=false, nextNoteId=1;
 let meConfigError=false, meSaveError=false;
 const supplierProfiles=Object.fromEntries(['openai','anthropic'].map(route=>[route,[
  {id:1,name:'日常',api_url:'https://daily.test/v1',api_key:'keep-first-key',is_active:true},
  {id:2,name:'备用',api_url:'https://backup.test/v1',api_key:'keep-second-key',is_active:false},
  {id:3,name:'第三个供应商',api_url:'https://third.test/v1',api_key:'keep-third-key',is_active:false}
 ]]));
 const savedSuppliers={openai:{id:7,name:'已有 OpenAI 供应商',api_url:'https://saved-openai.test/v1',api_key:'openai-saved-secret'},anthropic:{id:7,name:'已有 Anthropic 供应商',api_url:'https://saved-anthropic.test/v1/messages',api_key:'anthropic-saved-secret'}};
 const draftKey=draft=>draft.api_key||(draft.source_provider_id?savedSuppliers[draft.source_provider_type]?.api_key:apiPresets.find(p=>p.id===draft.source_preset_id)?.api_key)||apiSettings.api_key;
 const conversationPrompts=new Map();
 let modelFetchResult={data:[{id:'preset-model'},{id:'second-model'}]}, modelFetchError='', modelFetchGate=null;
 const publicApi=config=>{const {api_key,...fields}=config;return {...fields,api_key_configured:!!api_key,api_key_hint:api_key?'••••'+api_key.slice(-4):''};};
 let modelSettings={title_model:'saved-title',title_provider_id:null,embedding_model:'saved-embedding',embedding_api_url:'https://example.test/embeddings',nocturne_recall_enabled:true,long_term_recall_limit:9};
 let ocrSettings={enabled:true,api_url:'https://ocr.test/v1',model:'ocr-model',api_key:'saved-ocr-key'};
 const convs=[{id:1,name:'十月的窗边与晚风',created_at:'2026-10-18T12:00:00Z',updated_at:'2026-10-19T10:00:00Z'},
 {id:2,name:'九月留下的第一句话',created_at:'2026-09-23T12:00:00Z',updated_at:'2026-09-24T10:00:00Z'}];
 const messages=new Map(convs.map(c=>[c.id,[{id:c.id*10+1,role:'user',content:'今天的风很舒服，想和你一起慢慢过。',created_at:c.created_at},
 {id:c.id*10+2,role:'assistant',content:'好呀。\n\n那就把今天留在这里，我们慢慢聊。',created_at:c.updated_at}]]));
 const routeHandler=async route=>{
  const request=route.request(),url=new URL(request.url()),p=url.pathname;
  if(process.env.ASH_PHONE_MESSAGE_ACTIONS_ONLY && /^\/api\/context-messages\/\d+\/recall/.test(p)){
   if(request.method()==='POST'){writes.push({path:p,data:request.postDataJSON()});return route.fulfill({json:{value:request.postDataJSON().value}});}
   return route.fulfill({json:{recorded:true,query:'海边',results:[{turn_id:3,conversation_id:2,messages:[{role:'user',date:'2020-01-01',text:'当时注入的原话 <script>不执行</script>'}]}]}});
  }
  if(process.env.ASH_PHONE_MEMORY_RETRIEVAL_ONLY && p.startsWith('/api/memories/retrieval')){
   const weights={keyword:.5,semantic:.5,recency:.05,diversity:.25,min_score:.18};
   if(p.endsWith('/feedback')){const input=request.postDataJSON();writes.push({path:p,data:input});return route.fulfill({json:{value:input.value,turn_id:input.turn_id}});}
   if(p.endsWith('/preview')){
    writes.push({path:p,data:request.postDataJSON()});
    return route.fulfill({json:{results:[{conversation_id:2,turn_id:10,score:.8,scores:{relevance:.8,rrf:.016},ranks:{keyword:1,semantic:2},mmr_score:.6,matches:[{message_id:10,role:'user',start:0,end:30,text:'我想和你去海边。<script>不执行</script>',created_at:'2025-08-10T10:00:00Z',included:true}]}],diagnostics:{warnings:[]},injection:'<system_info>历史原文</system_info>',used_chars:100,char_budget:2000,enabled:false}});
   }
   if(request.method()==='PUT')writes.push({path:p,data:request.postDataJSON()});
   return route.fulfill({json:{weights,semantic_configured:true,reranker_configured:false,enabled:false,char_budget:2000}});
  }
  if(process.env.ASH_PHONE_MONTHLY_ONLY && p.startsWith('/api/diary-months/')) return route.fulfill({json:{month:'2026-10',content:'十月，我记下了我们关于旅行的约定。\n'.repeat(120),status:'completed',error:''}});
  if(process.env.ASH_PHONE_ALBUM_ONLY && p==='/album-storage-seed')return route.fulfill({contentType:'text/html',body:'<!doctype html><title>Storage seed</title>'});
  if(url.hostname==='fonts.googleapis.com')return route.fulfill({contentType:'text/css',body:''});
  if(p==='/dashboard') return route.fulfill({contentType:'text/html',body:process.env.ASH_PHONE_OPENING_ONLY ? pages.dashboard : pages.dashboard.replace(/<dialog id="ash-opening"[\s\S]*?<\/dialog>/,'')});
  if(p==='/context')return route.fulfill({contentType:'text/html',body:pages[url.searchParams.get('embedded')==='list'?'list':url.searchParams.get('conversation_id')==='2'?'history':'detail']});
  if(process.env.ASH_PHONE_EXPORT_PROGRESS_ONLY && p==='/export/memories'){
   exportUrls.push(url);return route.fulfill({contentType:'application/json',headers:{'content-disposition':'attachment; filename="backup.json"'},body:'{}'});
  }
  if(p==='/prompt')return route.fulfill({contentType:'text/html',body:pages.prompt});
  if(p.startsWith('/static/')){
   const file=path.resolve(root,'.'+p);
   if(!file.startsWith(root+'/static/')||!fs.existsSync(file)) return route.fulfill({status:404,body:''});
   const types={'.css':'text/css','.js':'text/javascript','.png':'image/png','.webp':'image/webp','.svg':'image/svg+xml','.woff2':'font/woff2'};
   let body=fs.readFileSync(file);
   if((process.env.ASH_PHONE_PWA_ONLY || process.env.ASH_PHONE_PWA_GAP_ONLY || process.env.ASH_PHONE_MEMORY_EDITOR_ONLY || process.env.ASH_PHONE_FRAGMENT_LAYOUT_ONLY) && path.extname(file)==='.css'){
    // Exercise installed-mode CSS and iPhone insets; Chromium has no standalone
    // media emulation. This is a layout check, not a native installation test.
    body=body.toString().replaceAll('(display-mode: standalone)','(min-width: 0px)')
     .replace(/env\(safe-area-inset-bottom(?:,\s*0px)?\)/g,'var(--test-safe-bottom,34px)')
     .replace(/env\(safe-area-inset-top(?:,\s*0px)?\)/g,'47px');
    if(process.env.ASH_PHONE_PWA_GAP_ONLY) body=body.replaceAll('47px','62px').replaceAll('100dvh','calc(100lvh - 62px)');
   }
   return route.fulfill({contentType:types[path.extname(file)]||'application/octet-stream',body});
  }
  if(!p.startsWith('/api/'))throw Error('Unexpected network request: '+p);
  if(request.method()!=='GET') writes.push({path:p,method:request.method(),body:request.postData()});
  let data={}; const id=Number(p.match(/^\/api\/conversations\/(\d+)/)?.[1]);
  if((process.env.ASH_PHONE_BOTS_ONLY||process.env.ASH_PHONE_QQ_ONLY||process.env.ASH_PHONE_SOCIAL_ONLY) && p==='/api/bot-connections'){
   if(botCatalogError)return route.fulfill({status:503,json:{error:'暂时无法读取连接'}});
   return route.fulfill({json:{providers:[
    {id:'imessage',name:'iMessage',description:'Photon',symbol:'iM',available:true},
    {id:'qq',name:'QQ',symbol:'QQ',description:'官方 Bot',available:true},
    ...[['weixin','微信','微'],['feishu','飞书','飞']].map(([id,name,symbol])=>({id,name,description:'',symbol,available:!!process.env.ASH_PHONE_SOCIAL_ONLY}))
   ],connections:[...(botConnection?[{id:'imessage',provider:'imessage',name:'iMessage',account:botConnection.home_user,enabled:botConnection.enabled}]:[]),...(qqConnection?[{id:'qq',provider:'qq',name:'QQ',account:qqConnection.app_id,enabled:qqConnection.enabled}]:[])]}});
  }
  if(process.env.ASH_PHONE_SOCIAL_ONLY && /^\/api\/bot-connections\/(feishu|weixin)/.test(p)){
   const provider=p.split('/')[3],config=socialConnections[provider];
   if(p.endsWith('/setup')&&request.method()==='POST')return route.fulfill({json:{id:qqSession,status:'waiting',code:provider==='feishu'?'ASH-TESTCODE':''}});
   if(p.includes('/setup/')&&request.method()==='DELETE'){socialCancelled++;return route.fulfill({json:{status:'cancelled'}});}
   if(p.includes('/setup/')&&p.endsWith('/check')){
    if(socialOutcome==='authorized'){socialConnections[provider]={...config,enabled:true,owner_bound:true,time_enabled:true,debounce_seconds:30,...(provider==='weixin'?{bot_id:'test-weixin'}:{})};return route.fulfill({json:{status:'authorized',connection:socialConnections[provider]}});}
    return route.fulfill({json:{status:socialOutcome,image:provider==='weixin'?qqImage:'',code:provider==='feishu'?'ASH-TESTCODE':''}});
   }
   if(p.endsWith('/check'))return route.fulfill({json:{status:socialConnectionError?'connecting':config?.enabled?'connected':'disabled',error:socialConnectionError}});
   if(p.endsWith('/reconnect')){config.enabled=true;return route.fulfill({json:{status:'connecting'}});}
   if(request.method()==='PUT'){const data=request.postDataJSON();delete data.app_secret;socialConnections[provider]={...config,...data,app_secret_configured:provider==='feishu'};return route.fulfill({json:{connection:socialConnections[provider],saved:true}});}
   return route.fulfill({json:{connection:config||{enabled:false,time_enabled:true,debounce_seconds:30},saved:!!config}});
  }
  if(process.env.ASH_PHONE_QQ_ONLY && p.startsWith('/api/bot-connections/qq')){
   if(p.endsWith('/qr')&&request.method()==='POST'){
    if(qqCreateError)return route.fulfill({status:503,json:{error:'暂时无法生成二维码，请重试'}});
    qqExpected=request.postDataJSON().app_id;return route.fulfill({json:{id:qqSession,status:'creating'}});
   }
   if(p.includes('/qr/')&&request.method()==='DELETE'){qqCancelled++;return route.fulfill({json:{status:'cancelled'}});}
   if(p.includes('/qr/')&&p.endsWith('/check')){
    if(qqOutcome==='authorized'){qqConnection={app_id:qqExpected||'12345678',enabled:true,owner_bound:true,time_enabled:true,debounce_seconds:30};return route.fulfill({json:{status:'authorized',connection:qqConnection}});}
    return route.fulfill({json:{status:qqOutcome,image:qqOutcome==='waiting'?qqImage:'',...(qqOutcome==='mismatch'?{error:'扫码授权的 Bot 与填写的 AppID 不一致'}:{})}});
   }
   if(p.endsWith('/check'))return route.fulfill({json:{status:qqConnection?.enabled?'connected':'disabled',error:''}});
   if(p.endsWith('/reconnect')){qqConnection.enabled=true;return route.fulfill({json:{status:'connecting'}});}
   if(request.method()==='PUT'){Object.assign(qqConnection,request.postDataJSON());return route.fulfill({json:{connection:qqConnection,saved:true}});}
   return route.fulfill({json:{connection:qqConnection||{app_id:'',enabled:false,owner_bound:false},saved:!!qqConnection}});
  }
  if(process.env.ASH_PHONE_BOTS_ONLY && p.startsWith('/api/bot-connections/imessage')){
   const initial={enabled:false,project_id:'',home_user:'',allowed_users:[],
    project_secret_configured:false,time_enabled:true,debounce_seconds:30};
   if(p.endsWith('/check'))return route.fulfill({json:{status:'connected',error:''}});
   if(p.endsWith('/reconnect'))return route.fulfill({json:{status:botConnection?.enabled?'reconnecting':'disabled'}});
   if(request.method()==='PUT'){
    const body=request.postDataJSON();botWrites.push(body);
    if(botApplyError)return route.fulfill({status:503,json:{error:'配置保存失败，请重试'}});
    const {project_secret,...rest}=body;
    botConnection={...initial,...rest,project_secret_configured:true};
    return route.fulfill({json:{connection:botConnection,applied:!botApplyError,...(botApplyError?{error:'配置已保存，尚未应用：桥接暂时不可达'}:{})}});
   }
   return route.fulfill({json:{connection:botConnection||initial,saved:!!botConnection}});
  }
  if(process.env.ASH_PHONE_MEMORY_EDITOR_ONLY && p.startsWith('/api/standing-memory')){
   const block={id:9,status:'active',layer:'core',title:'长期记忆',content:Array.from({length:90},(_,i)=>`第${i+1}节：这是需要反复查看与修改的记忆正文。`).join('\n')};
   if(request.method()==='PUT'){
    memoryEditorWrites.push(request.postDataJSON());
    return route.fulfill(memoryEditorSaveError?{status:503,json:{error:'测试保存失败'}}:{json:{block:{...block,...request.postDataJSON()}}});
   }
   const shorter=Array.from({length:8},(_,i)=>({...block,id:i+10,content:'一段简短的记忆。'}));
   return route.fulfill({json:{blocks:[block,...shorter],overview:{}}});
  }

  if(p.startsWith('/api/noteboard')){
   if(noteFailure)return route.fulfill({status:503,json:{error:'便签暂时无法保存'}});
   const noteId=Number(p.split('/')[3]);
   if(request.method()==='GET')return route.fulfill({json:{notes:wallNotes}});
   if(request.method()==='DELETE'){wallNotes=wallNotes.filter(n=>n.id!==noteId);return route.fulfill({json:{deleted:true}});}
   const input=request.postDataJSON();let note;
   if(request.method()==='POST'){note={...input,id:nextNoteId++,author:'user',revision:1,created_at:'2026-10-26T12:00:00Z'};wallNotes.unshift(note);}
   else{note=wallNotes.find(n=>n.id===noteId);if(!note||note.revision!==input.revision)return route.fulfill({status:409,json:{error:'便签已更改或删除，请重新打开后编辑'}});Object.assign(note,input,{revision:note.revision+1});}
   return route.fulfill({json:{note}});
  }

  if(process.env.ASH_PHONE_EXPORT_PROGRESS_ONLY && p.startsWith('/api/export-progress/')){
   if(exportStatus==='unavailable')return route.fulfill({status:502,contentType:'text/html',body:'Bad Gateway'});
   return route.fulfill({json:{status:exportStatus,section:'context_messages',rows:128,bytes_sent:65536,elapsed_seconds:12,error:'QueryCanceledError'}});
  }
  if(p===`/api/conversations/${id}/extra-prompts`){
   const prompts=conversationPrompts.get(id)||[];
   if(request.method()==='POST'){
    const prompt={...request.postDataJSON(),id:prompts.length+1};
    prompts.push(prompt);conversationPrompts.set(id,prompts);data={prompt};
   }else data={sources:[],prompts,injections:[],capture_frontend_prompts:true,auto_inject_captured_prompts:true};
  }
  if(p===`/api/conversations/${id}/extra-prompt-settings`)data={status:'ok'};
  if(p==='/api/extra-prompt-presets')data={presets:[]};
  if(p==='/api/conversations'){
   if(request.method()==='POST'){
    const conv={id:3,name:'新的对话',created_at:'2026-10-19T12:00:00Z'};convs.push(conv);messages.set(3,[]);data={conversation:{...conv,is_active:false}};
   }else {if(delayConversationReads)await new Promise(resolve=>setTimeout(resolve,1500));data={conversations:convs.map(c=>({...c,is_active:c.id===activeId,message_count:messages.get(c.id).length}))};}
  }
  if(p.endsWith('/messages'))data={conversation:{...convs.find(c=>c.id===id),is_active:id===activeId},messages:messages.get(id)||[],pagination:{has_older:false},handoff_summary:'',handoff_draft:''};
  if(process.env.ASH_PHONE_MESSAGE_COUNT_ONLY && p.endsWith('/messages')){
   countReads.push(request.url());
   Object.assign(data.conversation,{message_count:messages.get(id)?.length||0,message_count_is_partial:id===1});
   if(id===1)data.pagination={has_older:true,next_before_id:messages.get(id)[0].id};
  }
  if(p.endsWith('/activate')){activeId=id;data={status:'ok'};}
  if(/^\/api\/conversations\/\d+$/.test(p)&&request.method()==='PUT') {Object.assign(convs.find(c=>c.id===id),request.postDataJSON());data={status:'ok'};}
  if(p.endsWith('/chat')){
   if(failChat)return route.fulfill({status:502,json:{error:'测试上游暂时不可用'}});
   const text=request.postDataJSON().messages[0].content;
   const thought=process.env.ASH_PHONE_REASONING_ONLY?'先整理问题，再回答。<script>window.reasoningInjected=true</script>':'';
   messages.get(id).push({id:50,role:'user',content:text},{id:51,role:'assistant',content:'我在这里，听你说。',reasoning_content:thought});
   return route.fulfill({contentType:'text/event-stream',body:(thought?'data: '+JSON.stringify({choices:[{delta:{reasoning_content:thought}}]})+'\n\n':'')+'data: {"choices":[{"delta":{"content":"我在这里，听你说。"}}]}\n\ndata: [DONE]\n\n'});
  }
  if(p.endsWith('/message-stats'))data={total_messages:messages.get(id)?.length||0};
  if(process.env.ASH_PHONE_MESSAGE_COUNT_ONLY && p.endsWith('/message-stats')){
   countReads.push(request.url());if(countStatsGate)await countStatsGate;
   data={total_messages:1200+(messages.get(id)?.length||0)-2};
  }
  if(p==='/api/chat/models')data={data:[{id:'test-model'}],default_model:'test-model'};
  if(p==='/api/conversation-model-settings'){if(request.method()==='PUT')Object.assign(modelSettings,request.postDataJSON());data={...modelSettings};}
  if(p==='/api/ocr-settings'){
   if(request.method()==='PUT'){const draft=request.postDataJSON();ocrSettings={...draft,api_key:draft.api_key||(draft.clear_api_key?'':ocrSettings.api_key)};}
   data=publicApi(ocrSettings);
  }
  if(p==='/api/route-settings'){
   if(meConfigError && request.method()==='GET')return route.fulfill({status:503,json:{error:'暂时无法读取配置'}});
   if(request.method()==='PUT'){
    if(meSaveError)return route.fulfill({status:503,json:{error:'暂时无法保存配置'}});
    const draft=request.postDataJSON();apiSettings={...draft,api_key:draftKey(draft)};
   }
   data={...publicApi(apiSettings),provider_name:'日常供应商'};
  }
  if(p==='/api/chat/config')data={model:apiSettings.model,provider:apiSettings.provider,ready:true};
  if(p==='/api/api-presets'){
   if(request.method()==='POST'){const draft=request.postDataJSON();const preset={...draft,id:apiPresets.find(p=>p.name===draft.name)?.id||apiPresets.length+1,api_key:draftKey(draft)};apiPresets=apiPresets.filter(p=>p.name!==preset.name);apiPresets.push(preset);data={preset:publicApi(preset)};}
   else data={presets:apiPresets.map(publicApi)};
  }
  if(p.startsWith('/api/api-presets/')&&request.method()==='DELETE'){apiPresets=apiPresets.filter(item=>item.id!==Number(p.split('/').at(-1)));data={status:'ok'};}
  if(p==='/api/api-presets/models'){
   const result=modelFetchResult,error=modelFetchError,gate=modelFetchGate;
   if(gate)await gate;
   if(error)return route.fulfill({status:502,json:{error}});
   data=result;
  }
  if(p.includes('providers'))data={profiles:[],effective:{name:'默认供应商'}};
  if(process.env.ASH_PHONE_SUPPLIER_REUSE_ONLY && /^\/api\/(openai|anthropic)-providers$/.test(p)){
   const supplier=savedSuppliers[p.includes('openai')?'openai':'anthropic'];
   data={profiles:[publicApi(supplier)],effective:publicApi(supplier)};
  }
  if(process.env.ASH_PHONE_PROVIDERS_ONLY && /^\/api\/(openai|anthropic)-providers/.test(p)){
   const match=p.match(/^\/api\/(openai|anthropic)-providers(?:\/(\d+))?(\/activate)?$/);
   const family=match[1],profileId=Number(match[2]),rows=supplierProfiles[family];
   if(request.method()==='GET')data={profiles:rows.map(publicApi),effective:publicApi(rows.find(item=>item.is_active)||rows[0])};
   else if(match[3]){rows.forEach(item=>item.is_active=item.id===profileId);data={status:'ok'};}
   else if(request.method()==='PUT'){
    const draft=request.postDataJSON(),row=rows.find(item=>item.id===profileId);
    Object.assign(row,{...draft,api_key:draft.api_key||row.api_key});data={profile:publicApi(row)};
   }else if(request.method()==='DELETE'){supplierProfiles[family]=rows.filter(item=>item.id!==profileId);data={status:'ok'};}
   else if(request.method()==='POST'){rows.push({...request.postDataJSON(),id:4});data={status:'ok'};}
  }
  if(p==='/api/identity-presets'){if(request.method()==='PUT')Object.assign(identityPresets,request.postDataJSON());data=identityPresets;}
  if(process.env.ASH_PHONE_STRUCTURE_ONLY || process.env.ASH_PHONE_MONTHLY_ONLY){
   if(p==='/api/standing-memory')data={blocks:[{id:9,title:'固定记忆',content:'仅属于记忆的数据',layer:'core',status:'active'}],overview:{diary_count:1}};
   const diary={id:8,title:'独立日记',diary_date:'2026-10-19',author_role:'user',keywords:['日常'],content:'这一页只属于日记。'};
   if(p==='/api/diaries')data={diaries:[diary,{...diary,id:9,title:'当天第二篇'}]};
   if(p==='/api/diaries/pending')data={pending:[]};
   if(p==='/api/diaries/8'){diaryReads.push(8);data=diary;}
   if(p==='/api/diaries/9'){diaryReads.push(9);data={...diary,id:9,title:'当天第二篇',content:'第二篇正文'};}
  }
  if(process.env.ASH_PHONE_DIARY_EDITOR_ONLY){
   if(p==='/api/diaries/keywords-preview'){
    const fail=keywordPreviewError,gate=keywordPreviewGate;
    if(gate)await gate;
    return route.fulfill(fail?{status:502,json:{error:'关键词模型暂时无法使用'}}:{json:{keywords:['雨天','窗边','散步']}});
   }
   if(p==='/api/diaries/pending')data={pending:[]};
   if(p==='/api/diaries'){
    if(request.method()==='POST'){
     if(diarySaveError)return route.fulfill({status:500,json:{error:'测试保存失败'}});
     const diary={...request.postDataJSON(),id:1};editorDiaries.push(diary);data={status:'ok',diary};
    }else data={diaries:editorDiaries};
   }
   if(p==='/api/diaries/1'){
    if(request.method()==='PUT'){Object.assign(editorDiaries[0],request.postDataJSON());data={status:'ok',diary:editorDiaries[0]};}
    else data=editorDiaries[0];
   }
  }
  if(p==='/api/prompt')data={sections:[],full_prompt_chars:0};
  if(process.env.ASH_PHONE_PROMPT_LAYOUT_ONLY){
   if(p==='/api/prompt')data={sections:promptSections,full_prompt_chars:promptSections.reduce((sum,item)=>sum+item.content.length,0)};
   if(p.startsWith('/api/prompt/')&&request.method()==='PUT'){
    const section=promptSections.find(item=>item.key===decodeURIComponent(p.split('/').at(-1)));
    section.content=request.postDataJSON().content;data={new_char_count:section.content.length};
   }
   if(p==='/api/prompt/splice-preview')data={content:promptSections.map(item=>item.content).join('\n')};
   if(p==='/api/prompt/log')data={logs:[]};
  }
  if(p==='/api/token-usage/summary')data={today:'2026-10-19',daily_usage:[{day:'2026-10-19',total_tokens:12480,request_count:18}],total_tokens:12480};
  if(p==='/api/token-usage/logs')data={logs:process.env.ASH_PHONE_USAGE_PAGES_ONLY?Array.from({length:40},(_,i)=>({id:40-i,created_at:'2026-11-01 12:30:00',model:'claude-sonnet-4-5',provider:'anthropic',total_tokens:12000,input_tokens:10000,output_tokens:2000})):[]};
  if(p==='/api/heartbeat-settings')data={enabled:true,ready:true,context_managed:true,route:'openai',route_name:'OpenAI',provider_name:'日常供应商',model:'test-model',interval_minutes:45,effective_interval_minutes:45};
  if(p==='/api/heartbeat-activities')data={activities:[{created_at:'2026-10-19 09:45',status:'idle',elapsed_minutes:45,provider:'OpenAI',model:'test-model',final_text:'今天的记忆都已经妥善收好。',tool_events:[]}]};
  return route.fulfill({json:data});
 };
 await context.route('**/*',routeHandler);
 const gotoHome=async()=>{await page.locator('#phone-home-button').click();await page.locator('#section-home.active').waitFor();};
 const shot=async name=>{await page.evaluate(()=>document.fonts.ready);await page.screenshot({path:path.join(screenshotDir,name+'.png'),animations:'disabled'});};
 const noOverflow=async()=>assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
 if(process.env.ASH_PHONE_ALBUM_ONLY){
  await page.goto('https://ash-phone.test/album-storage-seed');
  await page.evaluate(()=>new Promise((resolve,reject)=>{
   const request=indexedDB.open('ash-phone-local',1);
   request.onupgradeneeded=()=>request.result.createObjectStore('assets');
   request.onerror=()=>reject(request.error);
   request.onsuccess=()=>{const db=request.result,tx=db.transaction('assets','readwrite');
    tx.objectStore('assets').put(new Blob(['existing-image-bytes']),'previous-image');
    tx.oncomplete=()=>{db.close();resolve();};tx.onabort=()=>reject(tx.error);
   };
  }));
 }
 await page.goto('https://ash-phone.test/dashboard');
 await page.waitForFunction(()=>window.AshDesktop);
 await page.evaluate(()=>merlePhoneApps.whenReady());
 await page.locator('#section-home.active').waitFor();await noOverflow();
 if(process.env.ASH_PHONE_FRAGMENT_RECALL_ONLY){
  Object.assign(modelSettings,{search_enabled:true,embedding_api_key_configured:true});
  await page.evaluate(()=>switchSection('settings'));
  await page.waitForFunction(()=>document.getElementById('historyTitleModel').value==='saved-title');
  await page.locator('.other-model-task > summary').first().click();
  await page.locator('#historyTitleModel').fill('unsaved-title');
  await page.evaluate(()=>switchSection('recall'));
  const toggle=page.getByRole('switch',{name:'跨对话片段召回'});
  await toggle.waitFor();
  assert.equal(await page.locator('#section-recall input').count(),4);
  await page.getByRole('heading',{name:'日记语义搜索'}).waitFor();
  await page.waitForFunction(()=>document.getElementById('historyEmbeddingModel').value==='saved-embedding');
  assert.equal(await page.locator('#historyEmbeddingKey').inputValue(),'');
  assert.match(await page.locator('#historyEmbeddingKey').getAttribute('placeholder'),/已配置/);
  await page.locator('#historyEmbeddingUrl').fill('https://diary.test/v1');
  await page.locator('#historyEmbeddingModel').fill('diary-embedding');
  for(const width of [320,390])for(const theme of ['light','dark']){
   await page.setViewportSize({width,height:844});
   await page.evaluate(theme=>AshTheme.setTheme(theme),theme);
   await noOverflow();await shot('fragment-recall-'+width+'-'+theme);
  }
  for(const enabled of [true,false]){
   await toggle.setChecked(enabled);
   await page.locator('#section-recall').getByRole('button',{name:'保存',exact:true}).click();
   await page.locator('#recall-settings-msg').filter({hasText:'已保存'}).waitFor();
   const saved=JSON.parse(writes.filter(w=>w.path==='/api/conversation-model-settings').at(-1).body);
   assert.equal(saved.cross_conversation_recall_enabled,enabled);
   assert.equal(saved.title_model,'saved-title');
   assert.equal(saved.embedding_api_key,'');
   assert.equal(saved.embedding_model,'diary-embedding');
   assert.equal(saved.embedding_api_url,'https://diary.test/v1');
   assert.equal(modelSettings.embedding_model,'diary-embedding');
   assert.equal(await toggle.isChecked(),enabled);
  }
  await page.evaluate(()=>switchSection('settings'));
  await page.waitForFunction(()=>document.getElementById('historyTitleModel').value==='saved-title');
  await page.locator('#historyTitleModel').fill('new-title');
  await page.locator('.conversation-generation-panel').getByRole('button',{name:'保存',exact:true}).click();
  await page.locator('#conversation-model-settings-msg').filter({hasText:'已保存'}).waitFor();
  assert.equal(modelSettings.title_model,'new-title');
  assert.equal(modelSettings.embedding_model,'diary-embedding');
  const generationSave=JSON.parse(writes.filter(w=>w.path==='/api/conversation-model-settings').at(-1).body);
  assert.equal(Object.hasOwn(generationSave,'embedding_model'),false);
  assert.deepEqual(errors,[]);console.log('Passed fragment recall, diary vector configuration and settings isolation.');return;
 }
 if(process.env.ASH_PHONE_FRAGMENT_LAYOUT_ONLY){
  let rows=[];
  let pinWrites=0;
  await page.route('**/api/memories/*/pin',route=>{
   const row=rows.find(r=>r.id===Number(new URL(route.request().url()).pathname.split('/')[3]));
   const data=route.request().postDataJSON();
   assert.equal(data.original_content,row.content);
   assert.deepEqual(data.original_categories,row.tags);
   row.pinned=data.pinned;
   pinWrites++;
   return route.fulfill({json:{pinned:row.pinned,id:row.id}});
  });
  await page.route('**/api/memory-fragments?*',route=>{
   const params=new URL(route.request().url()).searchParams;
   const maxImportance=Number(params.get('max_importance')||Infinity);
   const found=rows.filter(row=>(!params.get('category') || row.tags.includes(params.get('category')))
    && row.content.includes(params.get('query') || '') && row.importance<=maxImportance
    && row.id<Number(params.get('before') || Infinity));
   return route.fulfill({json:found.slice(0,40)});
  });
  const blocks=Array.from({length:6},(_,i)=>({id:i+1,layer:i===5?'recent':'core',status:'active',
   content:'我记得她那天说过的话。',created_at:'2026-11-19',title:'那天的对话'}));
  blocks.push(
   {id:90,layer:'core',status:'pending',content:'她习惯在睡前聊聊当天发生的事。\n她希望重要的约定能一直被记住。',metadata:{pending_operation:'create'}},
   {id:91,layer:'core',status:'pending',content:'我记得她那天说过的话，也记得我们约好的下一次见面。',metadata:{pending_operation:'edit',target_block_id:1,source_diary_ids:[12,13]}},
   {id:92,layer:'core',status:'pending',content:blocks[1].content,metadata:{pending_operation:'delete',target_block_id:2}}
  );
  await page.route('**/api/standing-memory?*',route=>route.fulfill({json:{blocks,overview:{flow_window:{max_items:8,item_count:1}}}}));
  await page.evaluate(()=>switchSection('standing'));
  await page.locator('#fragment-empty').filter({hasText:'还没有片刻'}).waitFor();
  assert.equal(await page.locator('#phone-app-header').isVisible(),false);
  const main=page.locator('.main-content');
  for(const viewport of [{width:320,height:640},{width:402,height:874}]){
   await page.setViewportSize(viewport);
   for(const theme of ['light','dark']){
    await page.evaluate(theme=>AshTheme.setTheme(theme),theme);
    await noOverflow();
    const layout=await main.evaluate(el=>{
     const section=el.querySelector('#section-standing');
     const paper=section.querySelector('.fragment-page').getBoundingClientRect();
     return {width:paper.width,available:el.clientWidth,
      colors:[el.parentElement,el,section].map(node=>getComputedStyle(node).backgroundColor)};
    });
    assert.equal(await page.locator('#dande .sway').count(),26);
    assert.equal(layout.width,layout.available);
    assert.equal(new Set(layout.colors).size,1);
    await shot('memory-archive-'+viewport.width+'-'+theme);
   }
  }
  rows=Array.from({length:5},(_,i)=>({id:i+1,created_at:'2026-11-19',tags:['日常'],importance:i+1,content:'我记得那天下午的风。'}));
  await page.evaluate(()=>{AshTheme.setTheme('light');return loadFragmentPage();});
  await shot('memory-archive-pieces');
  rows=Array.from({length:42},(_,i)=>({id:42-i,created_at:'2026-11-19',tags:[i%2?'情绪':'日常'],importance:i%10+1,content:'我记得那天下午的风。'}));
  await page.evaluate(()=>loadFragmentPage());
  assert.equal(await page.locator('#dande .fill').count(),26);
  await page.locator('#fragment-more').click();
  await page.locator('#archive-fragment-count').filter({hasText:'42 条片刻'}).waitFor();
  await page.locator('#fragment-filters').getByText('情绪').click();
  await page.locator('#archive-fragment-count').filter({hasText:'21 条片刻'}).waitFor();
  await page.locator('#fragment-filters').getByText('全部').click();
  await page.locator('#archive-fragment-count').filter({hasText:'40+'}).waitFor();
  await page.locator('#fragment-query').fill('找不到');
  await page.locator('#fragment-empty').filter({hasText:'没有找到'}).waitFor();
  await page.locator('#fragment-query').fill('');
  await page.locator('#archive-fragment-count').filter({hasText:'40+'}).waitFor();
  await page.locator('#fragment-importance').selectOption('3');
  await page.locator('#archive-fragment-count').filter({hasText:'14 条片刻'}).waitFor();
  await page.locator('#fragment-importance').selectOption('');
  await page.locator('#archive-fragment-count').filter({hasText:'40+'}).waitFor();
  rows[0].content='这是一段需要保留的长记忆。'.repeat(30);
  await page.evaluate(()=>loadFragmentPage());
  const firstCard=page.locator('.archive-card').first(),body=firstCard.locator('p');
  assert.equal(await body.evaluate(el=>Math.round(el.clientHeight/parseFloat(getComputedStyle(el).lineHeight))),5);
  const pointer={pointerType:'touch',pointerId:3,isPrimary:true,clientX:200,clientY:100};
  await body.dispatchEvent('pointerdown',pointer);
  await body.dispatchEvent('pointerup',{...pointer,clientX:190,clientY:190});
  assert.equal(pinWrites,0);
  await body.dispatchEvent('pointerdown',pointer);
  await body.dispatchEvent('pointerup',{...pointer,clientX:100});
  const pin=firstCard.locator('.fragment-pin');
  await pin.filter({hasText:'已 Pin'}).waitFor();
  await page.evaluate(()=>loadFragmentPage());
  await firstCard.getByText('编辑',{exact:true}).click();
  const editor=page.locator('#fragment-editor');
  assert.equal(await editor.locator('textarea').inputValue(),rows[0].content);
  assert.equal(await editor.locator('textarea').isEditable(),true);
  assert.equal(await editor.locator('[name=importance]').isEditable(),true);
  assert.equal(await editor.locator('[name=category]').first().isEnabled(),true);
  assert.equal(await editor.locator('[type=submit]').isVisible(),true);
  assert.equal(await editor.locator('#fragment-delete').isVisible(),true);
  for(const width of [320,402])for(const theme of ['light','dark']){
   await page.setViewportSize({width,height:874});
   await page.evaluate(theme=>AshTheme.setTheme(theme),theme);
   const colors=await editor.evaluate(el=>{
    const color=node=>{const s=getComputedStyle(node);return {ink:s.color,paper:s.backgroundColor};};
    return {dialog:color(el),text:color(el.querySelector('textarea')),score:color(el.querySelector('[name=importance]'))};
   });
   const luminance=color=>{
    const channels=color.match(/[\d.]+/g).slice(0,3).map(Number);
    return channels.map(v=>{
     if(!color.startsWith('color(srgb'))v/=255;
     return v<=.04045?v/12.92:((v+.055)/1.055)**2.4;
    }).reduce((sum,v,i)=>sum+v*[.2126,.7152,.0722][i],0);
   };
   for(const item of Object.values(colors)){
    const ink=luminance(item.ink),paper=luminance(item.paper);
    assert.ok((Math.max(ink,paper)+.05)/(Math.min(ink,paper)+.05)>=4.5,'Readable fragment editor '+JSON.stringify(item));
    assert.equal(ink>paper,theme==='dark');
   }
   await noOverflow();await shot('fragment-editor-'+width+'-'+theme);
  }
  await page.evaluate(()=>AshTheme.setTheme('light'));
  await editor.getByText('取消').click();
  await page.locator('#dande .fill .hit').first().dispatchEvent('click');
  assert.equal(await page.locator('.archive-card.on').count(),1);
  await page.locator('.archive-card.on .edit').click();
  assert.equal(await page.locator('#fragment-editor textarea').inputValue(),await page.locator('.archive-card.on p').textContent());
  await editor.getByText('取消').click();
  await firstCard.getByText('编辑',{exact:true}).click();
  const id=rows[0].id;
  assert.equal(rows.find(row=>row.id===id).pinned,true);
  await page.route('**/api/memory-fragments/'+id,route=>{
   const row=rows.find(row=>row.id===id);
   assert.equal(row.pinned,true);
   if(route.request().method()==='DELETE'){
    rows=rows.filter(row=>row.id!==id);
    return route.fulfill({json:{id}});
   }
   const data=route.request().postDataJSON();
   assert.equal(data.importance,9);
   assert.equal(data.content,'我亲手修改了这条已 Pin 的记忆。');
   assert.deepEqual(data.categories,['计划']);
   Object.assign(row,{importance:data.importance,content:data.content,tags:data.categories});
   return route.fulfill({json:{id}});
  });
  await editor.locator('textarea').fill('我亲手修改了这条已 Pin 的记忆。');
  for(const box of await editor.locator('[name=category]').all()) await box.uncheck();
  await editor.locator('[name=category][value="计划"]').check();
  await editor.locator('[name=importance]').fill('9');
  await editor.getByRole('button',{name:'保存'}).click();
  await editor.waitFor({state:'hidden'});
  await page.waitForFunction(()=>!document.querySelector('.archive-card.on'));
  await page.locator('.archive-card[data-id="'+id+'"] .edit').click();
  assert.equal(await editor.locator('[name=importance]').inputValue(),'9');
  assert.equal(await editor.locator('textarea').inputValue(),'我亲手修改了这条已 Pin 的记忆。');
  assert.equal(rows.find(row=>row.id===id).pinned,true);
  await page.locator('#fragment-editor').getByText('取消').click();
  await pin.click();
  await pin.filter({hasText:/^Pin$/}).waitFor();
  assert.equal(pinWrites,2);
  await pin.click();
  await pin.filter({hasText:'已 Pin'}).waitFor();
  await firstCard.getByText('编辑',{exact:true}).click();
  page.once('dialog',dialog=>dialog.accept());
  await editor.locator('#fragment-delete').click();
  await editor.waitFor({state:'hidden'});
  await page.locator('.archive-card[data-id="'+id+'"]').waitFor({state:'detached'});
  await page.locator('#fragment-compose').click();
  assert.equal(await page.locator('#fragment-editor textarea').inputValue(),'');
  await page.locator('#fragment-editor').getByText('取消').click();
  await page.locator('#archive-tab-fixed').click();
  await page.locator('#archive-fixed .ghost').waitFor();
  assert.equal(await page.locator('#archive-fixed .stand').count(),3);
  await page.locator('#archive-expand').click();
  assert.equal(await page.locator('#archive-fixed .stand').count(),5);
  await page.locator('#archive-expand').click();
  await shot('memory-archive-fixed');
  const pending=page.locator('#standing-pending-section');
  assert.equal(await pending.locator('.standing-pending-card').count(),3);
  assert.equal(await pending.getByRole('button',{name:'通过',exact:true}).count(),3);
  assert.equal(await pending.getByRole('button',{name:'拒绝',exact:true}).count(),3);
  assert.equal(await pending.locator('.is-new').count(),2);
  assert.equal(await pending.locator('.is-old').count(),2);
  for(const width of [320,402])for(const theme of ['light','dark']){
   await page.setViewportSize({width,height:874});
   await page.evaluate(theme=>AshTheme.setTheme(theme),theme);
   await pending.scrollIntoViewIfNeeded();
   await noOverflow();
   const styles=await pending.locator('.standing-pending-card').first().evaluate(el=>{
    const style=getComputedStyle(el),button=el.querySelector('.btn-primary'),mark=el.querySelector('mark');
    return {background:style.backgroundColor,radius:style.borderRadius,shadow:style.boxShadow,
     button:getComputedStyle(button).color,accent:getComputedStyle(el).getPropertyValue('--blue').trim(),
     mark:getComputedStyle(mark).backgroundColor,markColor:getComputedStyle(mark).color,
     text:getComputedStyle(el.querySelector('.pending-diff-line')).color};
   });
   assert.equal(styles.background,'rgba(0, 0, 0, 0)');
   assert.equal(styles.radius,'0px');
   assert.equal(styles.shadow,'none');
   assert.equal(styles.button,theme==='dark'?'rgb(156, 178, 255)':'rgb(24, 52, 212)');
   assert.equal(styles.markColor,styles.text);
   assert.notEqual(styles.mark,'rgba(0, 0, 0, 0)');
   await shot('memory-pending-'+width+'-'+theme);
  }
  await page.evaluate(()=>AshTheme.setTheme('light'));
  await page.locator('#archive-tab-flow').click();
  await page.locator('#archive-flow .river').waitFor();
  assert.equal(await page.locator('#flowMemoryMaxItems').inputValue(),'8');
  await page.locator('#archive-flow-list [data-promote-id]').waitFor();
  await shot('memory-archive-flow');
  await page.locator('#archive-tab-fragments').click();
  await main.evaluate(el=>el.scrollTo({top:el.scrollHeight,behavior:'instant'}));
  const gap=await main.evaluate(el=>el.getBoundingClientRect().bottom-el.querySelector('.foot').getBoundingClientRect().bottom);
  assert.ok(gap>=0 && gap<=35,'Footer bottom gap '+gap);
  await page.locator('.memory-back').click();
  await page.locator('#section-home.active').waitFor();
  assert.deepEqual(errors,[]);console.log('Passed memory archive edges, long-list scroll and back navigation.');return;
 }
 if(process.env.ASH_PHONE_THINKING_ONLY){
  await page.evaluate(()=>switchSection('supplier-route'));
  await page.locator('#routeModel').filter({visible:true}).waitFor();
  await page.waitForFunction(()=>document.getElementById('routeModel').value==='test-model');
  await page.locator('#routeThinking').fill('2');
  assert.equal(await page.locator('#route-thinking-value').innerText(),'Medium');
  await page.locator('#api-configuration-form [type=submit]').click();
  await page.locator('#route-settings-msg').filter({hasText:'设置已保存'}).waitFor();
  assert.equal(apiSettings.thinking_effort,'medium');
  await page.evaluate(()=>loadRouteSettings());
  assert.equal(await page.locator('#routeThinking').inputValue(),'2');
  for(const width of [320,390])for(const theme of ['light','dark']){
   await page.setViewportSize({width,height:844});await page.evaluate(theme=>AshTheme.setTheme(theme),theme);
   await noOverflow();await shot('chat-thinking-'+theme+'-'+width);
  }
  assert.deepEqual(errors,[]);console.log('Passed thinking slider draft, saved effort, reload and phone layouts.');return;
 }
 if(process.env.ASH_PHONE_DEFAULT_LAYOUT_ONLY){
  const layout=await page.evaluate(()=>AshDesktop.get());
  assert.deepEqual(layout.dock,['bots','preferences','theme',null]);
  assert.deepEqual(layout.positions['widget-ash-note'],{row:2,col:0});
  assert.deepEqual(layout.positions.chat,{row:2,col:2});
  assert.deepEqual(layout.positions.diary,{row:3,col:3});
  for(const width of [320,390])for(const theme of ['light','dark']){
   await page.setViewportSize({width,height:844});await page.evaluate(theme=>AshTheme.setTheme(theme),theme);
   await noOverflow();await shot('default-home-'+theme+'-'+width);
  }
  const custom={...layout,positions:{...layout.positions,chat:{row:3,col:3},diary:{row:2,col:2}}};
  await page.evaluate(data=>AshDesktop.restore(data),custom);await page.reload();await page.waitForFunction(()=>window.AshDesktop);
  assert.deepEqual(await page.evaluate(()=>AshDesktop.get().positions.chat),{row:3,col:3});
  assert.deepEqual(errors,[]);console.log('Passed paired default home, three dock apps, narrow light/dark layout and preserved customized positions.');return;
 }
 if(process.env.ASH_PHONE_SOCIAL_ONLY){
  await page.getByRole('button',{name:'打开Bot',exact:true}).click();
  await page.getByRole('button',{name:'＋ 添加连接',exact:true}).click();
  await page.locator('#bot-provider-list [data-phone-app="bot-feishu"]').click();
  const feishu=page.locator('#section-bot-feishu');await feishu.locator('input[name=app_id]:enabled').waitFor();
  assert.equal(await page.locator('#phone-app-title').innerText(),'飞书');
  assert.equal(await feishu.locator('select[name=feishu_domain]').inputValue(),'feishu');
  await feishu.locator('select[name=feishu_domain]').selectOption('lark');
  await feishu.locator('input[name=app_id]').fill('cli_0123456789abcdef');await feishu.locator('input[name=app_secret]').fill('private-secret');
  await feishu.getByRole('button',{name:'保存连接',exact:true}).click();await feishu.locator('[data-social=message]').filter({hasText:'已保存'}).waitFor();
  assert.equal(await feishu.locator('input[name=app_secret]').inputValue(),'');
  assert.equal(socialConnections.feishu.feishu_domain,'lark');
  await page.locator('#phone-back').click();await page.locator('#bot-provider-list [data-phone-app="bot-feishu"]').click();
  await feishu.locator('select[name=feishu_domain]:enabled').waitFor();
  assert.equal(await feishu.locator('select[name=feishu_domain]').inputValue(),'lark');
  socialConnectionError='已获取连接地址，但 WebSocket 握手失败';
  await feishu.locator('[data-social=message]').filter({hasText:socialConnectionError}).waitFor();
  socialConnectionError='';
  await page.waitForFunction(()=>document.querySelector('#section-bot-feishu [data-social=message]').textContent==='');
  await feishu.locator('[data-social=setup]').click();await feishu.locator('[data-social=code]').filter({hasText:'ASH-TESTCODE'}).waitFor();
  await shot('feishu-pairing');socialOutcome='authorized';await feishu.locator('[data-social=owner]').filter({hasText:'已绑定'}).waitFor();
  await feishu.locator('input[name=debounce_seconds]').fill('12');await feishu.getByRole('button',{name:'保存连接',exact:true}).click();
  await feishu.locator('[data-social=message]').filter({hasText:'已保存'}).waitFor();assert.equal(socialConnections.feishu.debounce_seconds,12);
  for(const width of [320,390])for(const theme of ['light','dark']){await page.setViewportSize({width,height:844});await page.evaluate(theme=>AshTheme.setTheme(theme),theme);await noOverflow();await shot('feishu-'+theme+'-'+width);}
  await page.locator('#phone-back').click();
  await page.locator('#bot-provider-list [data-phone-app="bot-weixin"]').click();const wx=page.locator('#section-bot-weixin');
  await wx.locator('[data-social=setup]:enabled').waitFor();assert.equal(await wx.locator('[data-social=form]').isVisible(),false);
  socialOutcome='waiting';await wx.locator('[data-social=setup]').click();await wx.locator('[data-social=qr]').waitFor();await shot('weixin-qr');
  socialOutcome='need_verifycode';await wx.locator('[data-social=verify-form]').waitFor();await wx.locator('input[name=verify_code]').fill('123456');await wx.getByRole('button',{name:'提交验证码'}).click();
  socialOutcome='authorized';await wx.locator('[data-social=owner]').filter({hasText:'已绑定'}).waitFor();
  assert.equal(await wx.locator('[data-social=account]').innerText(),'test-weixin');
  await wx.locator('input[name=enabled]').uncheck();await wx.getByRole('button',{name:'保存连接',exact:true}).click();await wx.locator('[data-social=message]').filter({hasText:'已保存'}).waitFor();assert.equal(socialConnections.weixin.enabled,false);
  for(const width of [320,390])for(const theme of ['light','dark']){await page.setViewportSize({width,height:844});await page.evaluate(theme=>AshTheme.setTheme(theme),theme);await noOverflow();await shot('weixin-'+theme+'-'+width);}
  socialOutcome='waiting';await wx.locator('[data-social=setup]').click();await wx.locator('[data-social=qr]').waitFor();await page.locator('#phone-back').click();await page.waitForTimeout(150);assert(socialCancelled>0);
  assert(!(await page.evaluate(()=>JSON.stringify({...localStorage}))).includes('private-secret'));assert.deepEqual(errors,[]);
  console.log('Passed Feishu setup and pairing, Weixin QR/verification, settings, cancellation and responsive themes.');return;
 }
 if(process.env.ASH_PHONE_QQ_ONLY){
  await page.getByRole('button',{name:'打开Bot',exact:true}).click();
  await page.getByRole('button',{name:'＋ 添加连接',exact:true}).click();
  await page.locator('#bot-provider-list [data-phone-app="bot-qq"]').click();
  await page.locator('#qq-choices').waitFor();
  assert.equal(await page.locator('#phone-app-title').textContent(),'QQ');
  assert.equal(await page.locator('#qq-existing-form').isVisible(),false);
  await shot('qq-connect-methods');
  await page.locator('#qq-existing').click();await page.locator('#qq-existing-id').fill('12345678');
  assert.equal(await page.locator('#section-bot-qq input[type=password]').count(),0,'existing bot requires no manual secret');
  await page.locator('#qq-existing-continue').click();
  await page.locator('#qq-qr-image').waitFor({state:'visible'});
  assert.equal(qqExpected,'12345678');
  assert.ok((await page.locator('#qq-expected-id').textContent()).includes('12345678'));
  await shot('qq-existing-authorize');
  qqOutcome='mismatch';await page.locator('#qq-message.is-error').filter({hasText:'不一致'}).waitFor();
  assert.equal(await page.locator('#qq-summary').isVisible(),false,'wrong bot never appears as connected');
  await page.locator('#qq-setup-back').click();await page.locator('#qq-choices').waitFor();
  qqCreateError=true;await page.locator('#qq-scan').click();await page.locator('#qq-message.is-error').filter({hasText:'无法生成'}).waitFor();
  qqCreateError=false;qqOutcome='waiting';await page.locator('#qq-refresh-qr').click();
  await page.locator('#qq-qr-image').waitFor({state:'visible'});
  assert.equal(qqExpected,'');
  qqOutcome='authorized';await page.locator('#qq-summary').waitFor();
  assert.equal(await page.locator('#qq-app-id').textContent(),'12345678');
  await page.locator('#qq-status').filter({hasText:'已连接'}).waitFor();
  assert.equal(await page.locator('#qq-debounce-seconds').inputValue(),'30');
  await page.locator('#qq-time-enabled').uncheck();await page.locator('#qq-debounce-seconds').fill('12');
  await page.locator('#qq-save-settings').click();await page.locator('#qq-message').filter({hasText:'设置已保存'}).waitFor();
  assert.equal(qqConnection.enabled,true);assert.equal(qqConnection.time_enabled,false);assert.equal(qqConnection.debounce_seconds,12);
  await page.reload();await page.locator('#qq-summary').waitFor();
  assert.equal(await page.locator('#qq-time-enabled').isChecked(),false);
  assert.equal(await page.locator('#qq-debounce-seconds').inputValue(),'12');
  await page.locator('#qq-enabled').uncheck();await page.locator('#qq-status').filter({hasText:'已停用'}).waitFor();
  await page.locator('#qq-reconnect').click();await page.locator('#qq-status').filter({hasText:'已连接'}).waitFor();
  for(const width of [320,390,768])for(const theme of ['light','dark']){
   await page.setViewportSize({width,height:844});await page.evaluate(value=>AshTheme.setTheme(value),theme);
   await noOverflow();await shot('qq-connected-'+theme+'-'+width);
  }
  await page.locator('#qq-reauthorize').click();await page.locator('#qq-choices').waitFor();
  qqOutcome='waiting';await page.locator('#qq-scan').click();await page.locator('#qq-qr-image').waitFor({state:'visible'});
  const before=qqCancelled;await page.locator('#phone-back').click();
  await page.waitForFunction(()=>document.getElementById('section-bot-add').classList.contains('active'));
  await page.waitForTimeout(100);assert(qqCancelled>before,'leaving cancels the unfinished QR');
  await page.locator('#phone-back').click();await page.locator('#section-bots.active').waitFor();
  await page.locator('#bot-connections-list [data-phone-app="bot-qq"]').waitFor();
  assert.deepEqual(errors,[]);console.log('Passed QQ authorization, reply settings persistence, enable/disable, reconnect and cancellation.');return;
 }
 if(process.env.ASH_PHONE_BOTS_ONLY){
  identityPresets={user_name:'预设用户',assistant_name:'预设助手'};
  await page.evaluate(()=>AshLocal.update(state=>{state.names.assistant='桌面昵称';}));
  await page.getByRole('button',{name:'打开Bot',exact:true}).click();
  await page.locator('#section-bots.active').waitFor();
  await page.locator('#bot-connections-list .bot-empty').waitFor();
  assert.equal(await page.locator('#phone-app-title').textContent(),'Bot 连接');
  await page.locator('#section-bots h2').filter({hasText:'狡兔三窟'}).waitFor();
  assert.equal(await page.evaluate(()=>AshLocal.get().names.assistant),'桌面昵称','preset names do not replace desktop nicknames');
  await page.evaluate(async()=>{
   document.getElementById('identityUserName').value='预设用户';
   document.getElementById('identityAssistantName').value='修改后的预设助手';
   await saveIdentityPresets();
  });
  await page.locator('#section-bots h2').filter({hasText:'修改后的预设助手'}).waitFor();
  await page.evaluate(()=>AshLocal.update(state=>{state.names.assistant='另一个桌面昵称';}));
  assert.ok((await page.locator('#section-bots h2').textContent()).includes('修改后的预设助手'));
  assert.equal(await page.locator('#bot-connection-form').isVisible(),false,'Bot home is a connection list, not an iMessage form');
  await shot('bot-connections-empty');
  await page.getByRole('button',{name:'＋ 添加连接',exact:true}).click();
  await page.locator('#section-bot-add.active').waitFor();
  await page.locator('#bot-provider-list .bot-provider-option').first().waitFor();
  assert.equal(await page.locator('#bot-provider-list button:disabled').count(),2,'future platforms have explicit unavailable slots');
  for(const label of ['微信','飞书'])assert.equal(await page.locator('#bot-provider-list').getByRole('button',{name:new RegExp(label)}).isDisabled(),true);
  await shot('bot-connection-providers');
  await page.locator('#bot-provider-list [data-phone-app="bot-imessage"]').click();
  await page.locator('#section-bot-imessage.active').waitFor();
  await page.locator('#bot-message').filter({hasText:'填写连接信息'}).waitFor();
  assert.equal(await page.locator('#phone-app-title').textContent(),'iMessage');
  await page.locator('#bot-enabled').check();
  await page.locator('#bot-project_id').fill('photon-project');
  await page.locator('#bot-project_secret').fill('project-secret');
  await page.locator('#bot-home_user').fill('+8613800000000');
  await page.locator('#bot-allowed_users').fill('+8613800000000\nuser@example.test');
  await page.locator('#bot-debounce_seconds').fill('10');
  await page.locator('#bot-save').click();
  await page.locator('#bot-message').filter({hasText:'已保存，正在连接'}).waitFor();
  assert.equal(botWrites.length,1);
  assert.deepEqual(botWrites[0].allowed_users,['+8613800000000','user@example.test']);
  assert.equal(botWrites[0].debounce_seconds,10);
  assert.equal(await page.locator('#bot-project_secret').inputValue(),'');
  assert.equal(await page.locator('#bot-project_secret').getAttribute('placeholder'),'已保存，留空保留');
  await page.locator('#bot-check').click();
  await page.locator('#bot-status').filter({hasText:'已连接'}).waitFor();
  for(const width of [320,390,768])for(const theme of ['light','dark']){
   await page.setViewportSize({width,height:844});
   await page.evaluate(value=>AshTheme.setTheme(value),theme);
   await noOverflow();await shot('bot-connections-'+theme+'-'+width);
  }
  await page.locator('#bot-reconnect').click();await page.locator('#bot-status').filter({hasText:'正在重连'}).waitFor();
  botApplyError=true;
  await page.locator('#bot-debounce_seconds').fill('12');await page.locator('#bot-save').click();
  await page.locator('#bot-message.is-error').filter({hasText:'配置保存失败'}).waitFor();
  assert.equal(await page.locator('#bot-debounce_seconds').inputValue(),'12');
  botApplyError=false;
  await page.locator('#bot-enabled').uncheck();await page.locator('#bot-save').click();
  await page.locator('#bot-status').filter({hasText:'已停用'}).waitFor();
  await page.locator('#phone-home-button').click();await page.locator('#section-home.active').waitFor();
  await page.getByRole('button',{name:'打开Bot',exact:true}).click();
  await page.locator('#bot-connections-list .bot-connection-row').waitFor();
  assert.equal(await page.locator('#bot-connections-list .bot-connection-row').count(),1);
  assert.ok((await page.locator('#bot-connections-list').textContent()).includes('+8613800000000'));
  assert.ok((await page.locator('#bot-connections-list').textContent()).includes('已停用'));
  await shot('bot-connection-list');
  await page.locator('#bot-connections-list .bot-connection-row').click();
  await page.locator('#section-bot-imessage.active').waitFor();
  await page.locator('#phone-back').click();await page.locator('#section-bots.active').waitFor();
  botCatalogError=true;
  await page.getByRole('button',{name:'＋ 添加连接',exact:true}).click();
  await page.locator('#bot-provider-message').filter({hasText:'暂时无法读取连接'}).waitFor();
  botCatalogError=false;await page.locator('#bot-provider-retry').click();
  await page.locator('#bot-provider-retry').waitFor({state:'hidden'});
  assert.ok((await page.locator('#bot-provider-list').textContent()).includes('管理已有连接'));
  await page.locator('#phone-back').click();await page.locator('#section-bots.active').waitFor();
  const storage=await page.evaluate(()=>JSON.stringify({...localStorage}));
  assert(!storage.includes('management-secret')&&!storage.includes('project-secret'),'credentials never enter local storage');
  await page.locator('#phone-home-button').click();await page.locator('#section-home.active').waitFor();
  assert.deepEqual(errors,[]);console.log('Passed Bot desktop entry, connection setup, masked secrets, status, reconnect, failed apply, disable and responsive themes.');return;
 }
 if(process.env.ASH_PHONE_MEMORY_EDITOR_ONLY){
  await page.evaluate(()=>switchSection('standing'));
  await page.waitForFunction(()=>standingBlocks.some(b=>b.id===9));
  await page.locator('#archive-tab-fixed').click();
  await page.evaluate(()=>{
   fixedMemoryStackExpanded=true;renderStandingLists();
   const list=document.querySelector('.main-content');
   list.scrollTo({top:180,behavior:'instant'});
  });
  const backgroundList=page.locator('.main-content');
  const entry=page.locator('#archive-fixed [data-standing-block-id="9"] .read');
  await entry.scrollIntoViewIfNeeded();
  const preview=entry.locator('p');
  const fullText=await preview.textContent();
  assert.equal(await preview.evaluate(el=>Math.round(el.clientHeight/parseFloat(getComputedStyle(el).lineHeight))),2);
  assert.ok(await preview.evaluate(el=>el.scrollHeight>el.clientHeight));
  const backgroundPosition=await backgroundList.evaluate(el=>el.scrollTop);
  assert(backgroundPosition>0,'exercise a scrollable background list');
  await entry.click();
  const modal=page.locator('#memory-editor-modal'),text=page.locator('#memory-editor-content');
  const close=modal.locator('.memory-editor-close'),save=page.locator('#memory-editor-save');
  await modal.waitFor({state:'visible'});
  assert.equal(await text.inputValue(),fullText);
  await page.waitForFunction(()=>document.activeElement===document.getElementById("memory-editor-content"));
  assert.equal(await modal.getByRole('button').count(),4,'original editor controls remain');
  assert.equal(await modal.locator('h3').count(),1,'original heading remains');
  assert.equal(await modal.locator('.memory-editor-dialog').evaluate(el=>el.querySelector('.memory-typewriter-sheet').getAnimations().length),0,'reduced motion skips the paper entrance');
  const appearance=()=>modal.evaluate(el=>Object.fromEntries(['.memory-typewriter-dialog','.memory-typewriter-sheet','.memory-typewriter-machine','.textarea'].map(selector=>{
   const node=el.querySelector(selector),r=node.getBoundingClientRect(),s=getComputedStyle(node);
   return [selector,{width:r.width,height:r.height,x:r.x,y:r.y,background:s.background,color:s.color,font:s.font,padding:s.padding}];
  })));
  for(const theme of ['dark','light']){
   await page.evaluate(theme=>AshTheme.setTheme(theme),theme);
   const palette=await modal.evaluate(el=>{
    const archive=document.querySelector('.fragment-page');
    return {ink:getComputedStyle(archive).color,text:getComputedStyle(el.querySelector('textarea')).color,
     accent:getComputedStyle(archive.querySelector('.tab-ink')).backgroundColor,
     save:getComputedStyle(el.querySelector('#memory-editor-save')).backgroundColor};
   });
   assert.equal(palette.text,palette.ink);
   assert.equal(palette.save,palette.accent);
   await shot('memory-typewriter-'+theme);
  }
  const original=await appearance();
  assert.equal(await backgroundList.evaluate(el=>getComputedStyle(el).overflowY),'hidden');
  const checkScrollIsolation=async()=>{
   for(const direction of [-1,1]){
    await text.evaluate((el,d)=>{el.scrollTop=d<0?0:el.scrollHeight;},direction);
    await text.hover();await page.mouse.wheel(0,direction*2000);await page.waitForTimeout(100);
    assert.equal(await backgroundList.evaluate(el=>el.scrollTop),backgroundPosition,'textarea boundaries do not scroll the background');
   }
   await modal.locator('.memory-typewriter-machine').hover();
   await page.mouse.wheel(0,2000);await page.waitForTimeout(100);
   assert.equal(await backgroundList.evaluate(el=>el.scrollTop),backgroundPosition,'scrolling the carriage does not scroll the list');
  };
  await checkScrollIsolation();
  await shot('memory-original-before-keyboard');
  await text.click();
  await page.evaluate(()=>{window.memoryTestViewport={height:420,offsetTop:40};Object.defineProperty(window,'visualViewport',{configurable:true,value:memoryTestViewport});AshPhoneViewport.refresh();scheduleMemoryCaret();});
  await page.waitForFunction(()=>document.body.classList.contains('phone-viewport-active'));
  const bounded=async()=>{
   const area=await text.boundingBox(),paper=await modal.locator('.memory-editor-dialog').boundingBox();
   const shell=await page.locator('.dashboard').boundingBox();
   assert(area.y>=shell.y&&area.y+area.height<=shell.y+shell.height,'whole textarea is visible above keyboard');
   assert(area.height>60,'several lines remain editable');
   const x=await close.boundingBox(),s=await save.boundingBox();
   assert(x.y>=shell.y&&x.y+x.height<=area.y);
   assert(s.y>=area.y+area.height&&s.y+s.height<=shell.y+shell.height);

  };
  for(const width of [320,402]){
   await page.setViewportSize({width,height:844});await page.evaluate(()=>AshPhoneViewport.refresh());
   await page.waitForTimeout(80);await bounded();
  }
  await text.evaluate(el=>{el.setSelectionRange(el.value.length,el.value.length);scheduleMemoryCaret();});
  await page.keyboard.type(' 编辑末节');
  await page.waitForFunction(()=>{const el=document.getElementById('memory-editor-content');return el.scrollTop>el.scrollHeight-el.clientHeight-70;});
  await shot('memory-typewriter-restored-keyboard');
  await text.hover();await page.mouse.wheel(0,-10000);
  await page.waitForFunction(()=>document.getElementById('memory-editor-content').scrollTop===0);
  await page.waitForTimeout(100);assert.equal(await text.evaluate(el=>el.scrollTop),0);
  await text.evaluate(el=>{el.setSelectionRange(0,0);el.focus({preventScroll:true});});
  await page.keyboard.type('编辑首节 ');
  const draft=await text.inputValue();
  assert(draft.startsWith('编辑首节 ')&&draft.endsWith(' 编辑末节'));
  await page.setViewportSize({width:390,height:844});
  await page.evaluate(()=>{memoryTestViewport.height=844;memoryTestViewport.offsetTop=0;AshPhoneViewport.refresh();});
  await page.waitForFunction(()=>!document.body.classList.contains('phone-viewport-active'));
  assert.deepEqual(await appearance(),original,'closing keyboard restores the exact original appearance');
  await text.focus();
  await page.evaluate(()=>{memoryTestViewport.height=420;memoryTestViewport.offsetTop=40;AshPhoneViewport.refresh();});
  await page.waitForFunction(()=>document.body.classList.contains("phone-viewport-active"));
  memoryEditorSaveError=true;await save.click();
  await page.locator('#memory-editor-msg').filter({hasText:'测试保存失败'}).waitFor();
  assert.equal(await text.inputValue(),draft);
  memoryEditorSaveError=false;await save.click();await modal.waitFor({state:'hidden'});
  assert.equal(await backgroundList.evaluate(el=>getComputedStyle(el).overflowY),'auto','closing restores background scrolling');
  assert.equal(memoryEditorWrites.length,2);assert.equal(memoryEditorWrites[1].content,draft);
  for(const exit of ['close','cancel','backdrop','escape']){
   await page.evaluate(()=>openStandingMemoryEditor(9));await text.click();
   await page.evaluate(()=>{memoryTestViewport.height=420;memoryTestViewport.offsetTop=40;AshPhoneViewport.refresh();});
   await page.waitForFunction(()=>document.body.classList.contains('phone-viewport-active'));
   if(exit==='close')await close.click();
   else if(exit==='cancel')await modal.getByRole('button',{name:'取消',exact:true}).click();
   else if(exit==='backdrop')await modal.locator('.memory-editor-backdrop').click({position:{x:5,y:100}});
   else await page.keyboard.press('Escape');
   await modal.waitFor({state:'hidden'});
   assert.equal(await text.evaluate(el=>document.activeElement===el),false);
  }
  assert.equal(memoryEditorWrites.length,2,'closing never saves');
  assert.deepEqual(errors,[]);console.log('Passed keyboard text visibility, unchanged original appearance, scrolling, save and all original exits.');return;
 }
 if(process.env.ASH_PHONE_OPENING_ONLY){
  const opening=page.locator('#ash-opening'),canvas=opening.locator('canvas');
  const color=async(x,y)=>canvas.evaluate((el,p)=>{const r=el.getBoundingClientRect();return [...el.getContext('2d').getImageData(p.x/r.width*el.width,p.y/r.height*el.height,1,1).data];},{x,y});
  const drag=async(x1,y1,x2,y2,steps=12)=>{await page.mouse.move(x1,y1);await page.mouse.down();await page.mouse.move(x2,y2,{steps});await page.mouse.up();};
  assert.equal(await opening.evaluate(el=>el.matches(':modal')),true);
  await shot('opening-frost');
  const before=await color(90,220);
  await drag(50,220,140,220);const after=await color(90,220);
  assert(before.slice(0,3).some((v,i)=>Math.abs(v-after[i])>12),'wiping visibly clears the frosted surface');
  for(let n=0;n<24;n++)await drag(50,100+n*2,170,100+n*2,2);
  assert.equal(await opening.isVisible(),true,'unlimited unrelated strokes do not complete the letters');
  await drag(65,450,125,530);assert.equal(await opening.isVisible(),true,'one letter is insufficient');
  await shot('opening-wiped');
  await page.setViewportSize({width:402,height:874});
  assert.equal((await opening.boundingBox()).height,874);
  await page.emulateMedia({reducedMotion:'no-preference'});
  const still=await canvas.evaluate(el=>el.toDataURL());
  await page.waitForFunction(previous=>document.querySelector('#ash-opening canvas').toDataURL()!==previous,still,{polling:250,timeout:6000});
  assert.equal(await opening.isVisible(),true,'natural rain moves without a gesture and never unlocks the screen');
  await page.waitForTimeout(10000);
  await shot('opening-rain');
  await page.emulateMedia({reducedMotion:'reduce'});
  await page.waitForTimeout(100);
  const paused=await canvas.evaluate(el=>el.toDataURL());
  await page.waitForTimeout(350);
  assert.equal(await canvas.evaluate(el=>el.toDataURL()),paused,'reduced motion stops ambient rain');
  await page.emulateMedia({reducedMotion:'no-preference'});
  await drag(70,260,300,310,20);await page.waitForTimeout(400);await shot('opening-water');
  // Real touch input on a new opening, including a cancelled gesture.
  await opening.locator('button').click();await opening.waitFor({state:'detached'});
  assert.equal(await page.locator('body').getAttribute('data-phone-view'),'home');
  await page.emulateMedia({reducedMotion:'reduce'});
  await page.locator('#phone-pages [data-phone-app=chat]').click();
  await page.reload();await opening.waitFor({state:'visible'});
  if(process.env.ASH_BROWSER==='webkit'){
   await page.mouse.move(65,200);await page.mouse.down();await page.mouse.move(170,230);
   await canvas.dispatchEvent('pointercancel',{pointerId:1});await page.mouse.up();
  }else{
   const client=await context.newCDPSession(page);
   await client.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:65,y:200}]});
   await client.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:170,y:230}]});
   await client.send('Input.dispatchTouchEvent',{type:'touchCancel',touchPoints:[]});
   await client.detach();
  }
  // Wipe all three letters, checking completion through the UI, not test hooks.
  for(let y=430;y<=600 && await opening.count();y+=25)await drag(35,y,365,y,15);
  await opening.waitFor({state:'detached'});
  assert.equal(await page.locator('.dashboard').evaluate(el=>el.inert),false);
  await page.reload();await opening.waitFor({state:'visible'});
  await page.keyboard.press('Escape');await opening.waitFor({state:'detached'});
  await page.addInitScript(()=>{const getContext=HTMLCanvasElement.prototype.getContext;HTMLCanvasElement.prototype.getContext=function(...args){return this.closest('#ash-opening')?null:getContext.apply(this,args);};});
  await page.reload();await page.waitForFunction(()=>window.AshDesktop);await opening.waitFor({state:'detached'});
  await page.locator('#phone-pages [data-phone-app=chat]').click();
  assert.deepEqual(errors,[]);assert.equal(writes.length,0);
  console.log('Passed fog clearing, ambient rain, unrestricted strokes, per-letter completion, resize, touch cancellation, reduced motion, skip, Escape and canvas failure fallback.');return;
 }
 assert.equal(await page.locator('.sidebar.page-index').count(),0,'old dashboard sidebar is removed');
 assert.equal(await page.locator('#conversation-list-frame').count(),0,'native Chat owns the only conversation list');
 assert.equal(await page.locator('.phone-tile').count(),0,'only the native Merle desktop is mounted');
 assert.equal(await page.locator('.phone-desktop-item').count(),9);
 assert.equal(await page.locator('.phone-statusbar').count(),0,'applications do not add another phone status bar');
 assert.equal(await page.locator('[data-phone-app=usage],[data-phone-launch=usage]').count(),0);
 assert.equal(await page.evaluate(()=>Object.hasOwn(AshDesktopConfig.apps,'usage')),false);
 const checkPair=async()=>{
  const geometry=await page.locator('.phone-pair').first().evaluate(el=>{
   const [a,b]=[...el.querySelectorAll('.phone-avatar')].map(n=>n.getBoundingClientRect());
   return {overlap:a.right-b.left,raised:el.parentElement.getBoundingClientRect().top-a.top};
  });assert.ok(geometry.overlap>=8&&geometry.overlap<=14);assert.ok(geometry.raised>=35);
 };
 await checkPair();await shot('merle-home-390');
 if(process.env.ASH_PHONE_THEME_ONLY){
  const theme=async expected=>{
   await page.waitForFunction(expected=>document.documentElement.dataset.theme===expected,expected);
   assert.equal(await page.locator('#phone-home').getAttribute('data-mode'),expected);
  };
  assert.equal(await page.evaluate(()=>AshTheme.getPreference()),'auto');
  await page.emulateMedia({colorScheme:'dark'});await theme('dark');
  await page.evaluate(()=>AshDesktop.customize('wallpaper'));
  const option=value=>page.locator(`[data-appearance-setting=mode][data-value=${value}]`);
  assert.equal(await option('auto').textContent(),'跟随系统');
  await option('light').click();await theme('light');
  await page.emulateMedia({colorScheme:'light'});await page.emulateMedia({colorScheme:'dark'});await theme('light');
  await option('dark').click();await theme('dark');
  await page.locator('[data-appearance-setting=ink][data-value=light]').click();
  assert.equal(await page.locator('#phone-home').getAttribute('data-ink'),'light');await theme('dark');
  for(const width of [320,390]){
   await page.setViewportSize({width,height:844});await noOverflow();
   const fits=await option('auto').evaluate(el=>el.getBoundingClientRect().right<=el.closest('.phone-appearance-row').getBoundingClientRect().right);
   assert(fits);await shot('global-appearance-'+width);
  }
  await option('auto').click();assert.equal(await option('auto').getAttribute('aria-pressed'),'true');
  const backup=await page.evaluate(()=>AshDesktop.export());assert.equal(backup.mode,'auto');
  assert.equal(await page.evaluate(()=>JSON.parse(localStorage.getItem('ash.phone.desktop.v2')).mode),undefined,'no second stored theme');
  await page.reload();await page.waitForFunction(()=>window.AshDesktop);await theme('dark');
  assert.equal(await page.evaluate(()=>AshTheme.getPreference()),'auto');
  await page.evaluate(()=>switchSection('preferences'));await theme('dark');
  await page.emulateMedia({colorScheme:'light'});await theme('light');
  await page.evaluate(()=>switchSection('chat'));await page.locator('#phone-open-chat').click();
  const frame=page.frameLocator('#conversation-detail-frame');await frame.locator('#sendBtn:not([disabled])').waitFor();
  assert.equal(await frame.locator('html').getAttribute('data-theme'),'light');
  await page.emulateMedia({colorScheme:'dark'});await theme('dark');
  await frame.locator('html[data-theme=dark]').waitFor({state:'attached'});
  assert.equal(await frame.locator('body').evaluate(()=>AshTheme.getPreference()),'auto');
  const darkPaper=await frame.locator('.app').evaluate(el=>getComputedStyle(el).backgroundColor);
  await page.emulateMedia({colorScheme:'light'});await theme('light');
  await frame.locator('html[data-theme=light]').waitFor({state:'attached'});
  assert.notEqual(await frame.locator('.app').evaluate(el=>getComputedStyle(el).backgroundColor),darkPaper);
  await page.evaluate(()=>switchSection('home'));
  await page.evaluate(backup=>AshDesktop.restore({...backup,mode:'dark'}),backup);await theme('dark');
  await page.evaluate(backup=>AshDesktop.restore(backup),backup);await theme('light');
  await page.evaluate(()=>AshTheme.setTheme('dark'));
  const oldBackup={...backup};delete oldBackup.mode;
  await page.evaluate(backup=>AshDesktop.restore(backup),oldBackup);await theme('dark');
  assert.equal(writes.length,0);assert.deepEqual(errors,[]);
  console.log('Passed system appearance, manual overrides, desktop text isolation, reload, settings/chat sync and backup compatibility.');return;
 }
 if(process.env.ASH_PHONE_ME_ONLY){
  apiPresets=[{id:1,name:'夜晚',provider:'anthropic',api_url:'https://night.test/v1',model:'night-model',api_key:'night-secret'}];
  await page.locator('#phone-pages [data-phone-app=chat]').click();
  await page.locator('[data-chat-tab=me]').click();
  await page.locator('#phone-me-model').filter({hasText:'test-model'}).waitFor();
  assert.equal(await page.locator('#phone-me-supplier').innerText(),'日常供应商');
  assert.equal(await page.locator('#phone-me-route').innerText(),'OpenAI 兼容');
  assert.equal(writes.length,0,'viewing Me does not change configuration');
  await shot('me-profile-light');
  assert.equal(await page.locator('#phone-me-preset-form').count(),0);
  await page.locator('#phone-me-favorites').click();
  await page.locator('#section-favorites.active').waitFor();
  await page.locator('#phone-back').click();
  await page.locator('[data-chat-panel=me]').waitFor({state:'visible'});
  await page.locator('#phone-me-config').click();
  await page.locator('#section-supplier-route.active').waitFor();
  assert.equal(await page.locator('#phone-back').getAttribute('aria-label'),'返回Me');
  await page.waitForFunction(()=>document.getElementById('routeModel').value==='test-model');
  await page.locator('#routeModel').fill('edited-model');
  await page.locator('#api-configuration-form [type=submit]').click();
  await page.locator('#route-settings-msg').filter({hasText:'设置已保存'}).waitFor();
  await page.locator('#phone-back').click();
  await page.locator('#phone-me-model').filter({hasText:'edited-model'}).waitFor();
  meConfigError=true;
  await page.locator('[data-chat-tab=chat]').click();await page.locator('[data-chat-tab=me]').click();
  await page.locator('#phone-me-status').filter({hasText:'加载失败'}).waitFor();
  meConfigError=false;apiPresets=[];
  await page.locator('#phone-me-retry').click();
  await page.locator('#phone-me-model').filter({hasText:'edited-model'}).waitFor();
  for(const theme of ['light','dark'])for(const width of [320,390]){
   await page.setViewportSize({width,height:844});
   await page.evaluate(theme=>document.documentElement.dataset.theme=theme,theme);
   await noOverflow();await shot('me-profile-'+theme+'-'+width);
  }
  assert.deepEqual(errors,[]);
  console.log('Passed Me configuration, favorites navigation, save, refresh and retry.');return;
 }
 if(process.env.ASH_PHONE_ALBUM_ONLY){
  assert.equal(await page.evaluate(async()=>await (await AshLocal.asset('previous-image')).text()),'existing-image-bytes','storage upgrade retains existing image data');
  await page.locator('#phone-pages [data-phone-app=chat]').click();
  await page.locator('[data-chat-tab=me]').click();await page.locator('#phone-me-favorites').click();
  await page.locator('#phone-favorites-status').filter({hasText:'暂无收藏'}).waitFor();
  await shot('favorites-empty');await page.locator('#phone-back').click();
  await page.locator('[data-chat-tab=chat]').click();await page.locator('#phone-open-chat').click();
  const frame=page.frameLocator('#conversation-detail-frame');
  await frame.locator('#sendBtn:not([disabled])').waitFor();
  const user=frame.locator('.msg.user').first();await user.locator('.phone-message-bubble').click();
  await frame.locator('body').evaluate(()=>{window.realSaveKeepsake=AshLocal.saveKeepsake;AshLocal.saveKeepsake=async()=>{throw new Error('存储空间不足');};});
  await user.getByRole('button',{name:'收藏',exact:true}).click();
  await frame.locator('#phone-chat-notice-text').filter({hasText:'收藏失败'}).waitFor();
  assert.equal((await page.evaluate(()=>AshLocal.keepsakes())).length,0);
  await frame.locator('body').evaluate(()=>{AshLocal.saveKeepsake=window.realSaveKeepsake;});
  await user.getByRole('button',{name:'收藏',exact:true}).click();
  await user.getByRole('button',{name:'已收藏',exact:true}).waitFor();
  const assistant=frame.locator('.msg.assistant').first();await assistant.locator('.phone-message-bubble').click();
  await assistant.getByRole('button',{name:'收藏',exact:true}).click();
  await assistant.getByRole('button',{name:'已收藏',exact:true}).waitFor();
  const original=await page.evaluate(()=>AshLocal.keepsakes());assert.equal(original.length,2);
  assert.equal(original[0].role,'assistant');assert.equal(original[0].content,messages.get(1)[1].content);
  await page.evaluate(async item=>{await Promise.all([AshLocal.saveKeepsake(item),AshLocal.saveKeepsake({...item,content:'duplicate must not overwrite'})]);},original[0]);
  assert.deepEqual(await page.evaluate(()=>AshLocal.keepsakes()),original);
  await frame.locator('.topbar-left .menu-btn').click();await page.locator('[data-chat-tab=me]').click();await page.locator('#phone-me-favorites').click();
  await page.waitForFunction(()=>document.querySelectorAll('.phone-favorite').length===2);
  await page.locator('.phone-favorite').first().click();
  assert.equal(await page.locator('.phone-favorite-reading').innerText(),original[0].content);
  await page.locator('#phone-favorite-open-source').click();await frame.locator('#msgInput').waitFor();
  assert.equal(await page.locator('#phone-back').getAttribute('aria-label'),'返回收藏');
  await frame.locator('.topbar-left .menu-btn').click();await page.locator('#section-favorites.active').waitFor();
  messages.get(1)[1].content='后来编辑过的回复';
  await page.reload();await page.locator('#section-favorites.active').waitFor();
  await page.waitForFunction(()=>document.querySelectorAll('.phone-favorite').length===2);
  for(const width of [320,390,768])for(const theme of ['light','dark']){
   await page.setViewportSize({width,height:844});await page.evaluate(theme=>AshTheme.setTheme(theme),theme);
   await page.locator('.phone-favorite').last().scrollIntoViewIfNeeded();
   const bounds=await page.locator('.phone-favorite').evaluateAll(notes=>notes.map(n=>{
    const a=n.getBoundingClientRect(),b=n.closest('.main-content').getBoundingClientRect();
    return a.left>=b.left&&a.right<=b.right;
   }));assert.ok(bounds.every(Boolean),'favorites stay inside the screen');
   await page.locator('.main-content').evaluate(el=>{el.scrollTop=0;});await shot('favorites-'+theme+'-'+width);
  }
  await page.setViewportSize({width:390,height:844});await page.evaluate(()=>AshTheme.setTheme('light'));
  await page.evaluate(()=>AshLocal.asset('album-cover',new Blob([Uint8Array.from(atob('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aXioAAAAASUVORK5CYII='),c=>c.charCodeAt(0))],{type:'image/png'})));
  await page.evaluate(()=>AshPhone.navigate('phone-transfer'));
  const downloadPromise=page.waitForEvent('download');await page.locator('#phone-export-local').click();
  const download=await downloadPromise, backupFile=path.join(screenshotDir,'album-backup.json');await download.saveAs(backupFile);
  const backup=JSON.parse(fs.readFileSync(backupFile,'utf8'));
  assert.equal(backup.version,3);assert.equal(backup.keepsakes.length,2);assert.ok(backup.assets['album-cover']);
  await page.evaluate(async()=>{await AshLocal.replaceKeepsakes([]);await AshLocal.asset('album-cover',null);});
  await page.locator('#phone-local-backup').setInputFiles(backupFile);
  await page.locator('#phone-toast').filter({hasText:'本机桌面已恢复'}).waitFor();
  assert.deepEqual(await page.evaluate(()=>AshLocal.keepsakes()),original);
  assert.equal(await page.evaluate(async()=>Boolean(await AshLocal.asset('album-cover'))),true);
  const oldBackup={...backup,version:2};delete oldBackup.keepsakes;delete oldBackup.assets['album-cover'];
  await page.locator('#phone-local-backup').setInputFiles({name:'old.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(oldBackup))});
  await page.waitForTimeout(200);assert.deepEqual(await page.evaluate(()=>AshLocal.keepsakes()),original);
  await gotoHome();await page.locator('#phone-pages [data-phone-app=chat]').click();await page.locator('[data-chat-tab=me]').click();await page.locator('#phone-me-favorites').click();
  await page.locator('.phone-favorite').first().click();
  page.once('dialog',dialog=>dialog.accept());await page.locator('#phone-favorite-remove').click();
  await page.waitForFunction(()=>document.querySelectorAll('.phone-favorite').length===1);
  assert.equal(messages.get(1).length,2,'removing a keepsake preserves original chat');
  assert.equal(writes.length,0,'collecting, reading and restoring never call server write or model endpoints');
  assert.deepEqual(errors,[]);console.log('Passed favorites migration, local collection, snapshot persistence, source navigation, backup compatibility and removal.');return;
 }
 if(process.env.ASH_PHONE_NOTES_ONLY){
  await page.locator('#phone-pages [data-phone-app=chat]').click();await page.locator('[data-chat-tab=cover]').click();
  await page.locator('#phone-note-empty:not([hidden])').waitFor();
  await page.locator('#phone-note-add').click();await page.locator('#phone-note-content').fill('今天的风很好。\n等你回来的时候，一起去散步。');
  await page.locator('#phone-note-title').fill('留在门口');noteFailure=true;await page.locator('#phone-note-save').click();
  await page.locator('#phone-note-error').filter({hasText:'暂时无法保存'}).waitFor();
  assert.equal(wallNotes.length,0);assert.match(await page.locator('#phone-note-content').inputValue(),/今天的风/);
  noteFailure=false;await page.locator('#phone-note-save').click();await page.locator('.phone-wall-note').waitFor();
  const firstId=wallNotes[0].id;
  await page.locator('.phone-wall-note').click();await page.locator('#phone-note-content').fill('今天的风很好。\n我们慢慢走。');await page.locator('#phone-note-save').click();
  await page.locator('.phone-wall-copy').filter({hasText:'我们慢慢走'}).waitFor();assert.equal(wallNotes[0].revision,2);
  // A note written from another frontend joins the same wall on reopening.
  wallNotes.push({id:nextNoteId++,title:'别忘了',content:'窗台上的花开了。',author:'assistant',revision:1,created_at:'2026-10-25T09:00:00Z'});
  wallNotes.push({id:nextNoteId++,title:'周末',content:'去旧书店看看。',author:'user',revision:1,created_at:'2026-10-24T09:00:00Z'});
  await page.locator('[data-chat-tab=me]').click();await page.locator('[data-chat-tab=cover]').click();await page.waitForFunction(()=>document.querySelectorAll('.phone-wall-note').length===3);
  await page.locator('#phone-note-arrange').click();
  const card=page.locator(`[data-note-id="${firstId}"]`),box=await card.boundingBox();
  await page.mouse.move(box.x+40,box.y+60);await page.mouse.down();await page.mouse.move(box.x+80,box.y+110,{steps:8});await page.mouse.up();
  assert.equal(await page.locator('#phone-personalize').evaluate(el=>el.open),false,'drag never opens editor');
  const placement=await page.evaluate(id=>AshLocal.get().noteLayout[id],firstId);
  assert.ok(placement.x>0.02);await page.reload();await page.locator('.phone-wall-note').first().waitFor();
  assert.deepEqual(await page.evaluate(id=>AshLocal.get().noteLayout[id],firstId),placement);
  // Desktop backups carry placements keyed by the IDs retained in server backups.
  await page.evaluate(()=>AshPhone.navigate('phone-transfer'));
  const noteDownloadPromise=page.waitForEvent('download');await page.locator('#phone-export-local').click();
  const noteDownload=await noteDownloadPromise;
  const noteBackup=JSON.parse(fs.readFileSync(await noteDownload.path(),'utf8'));
  assert.deepEqual(noteBackup.state.noteLayout[firstId],placement);
  await page.evaluate(()=>AshLocal.update(state=>{state.noteLayout={};}));
  assert.deepEqual(await page.evaluate(()=>AshLocal.get().noteLayout),{});
  await page.locator('#phone-local-backup').setInputFiles({name:'notes-desktop.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(noteBackup))});
  await page.locator('#phone-toast').filter({hasText:'本机桌面已恢复'}).waitFor();
  await page.waitForFunction(({id,placement})=>JSON.stringify(AshLocal.get().noteLayout[id])===JSON.stringify(placement),{id:firstId,placement});
  await page.evaluate(()=>AshPhone.navigate('chat'));
  await page.locator('[data-chat-tab=cover]').click();await card.waitFor();
  for(const width of [320,390,768])for(const theme of ['light','dark']){
   await page.setViewportSize({width,height:844});await page.evaluate(theme=>AshTheme.setTheme(theme),theme);await page.waitForTimeout(50);
   const fits=await page.locator('.phone-wall-note').evaluateAll(cards=>cards.every(card=>{const a=card.getBoundingClientRect(),b=card.closest('#phone-note-surface').getBoundingClientRect();return a.left>=b.left&&a.right<=b.right;}));
   assert.ok(fits,'paper fits narrow screens');await noOverflow();await shot('notes-'+theme+'-'+width);
  }
  await page.setViewportSize({width:390,height:844});await page.evaluate(()=>AshTheme.setTheme('light'));
  await card.click();wallNotes.find(n=>n.id===firstId).revision++;await page.locator('#phone-note-save').click();
  await page.locator('#phone-note-error').filter({hasText:'便签已更改'}).waitFor();
  await page.locator('#phone-personalize .phone-sheet-heading button').click();
  await page.locator('[data-chat-tab=me]').click();await page.locator('[data-chat-tab=cover]').click();await page.waitForTimeout(100);
  await card.click();page.once('dialog',dialog=>dialog.accept());await page.locator('#phone-note-delete').click();
  await page.waitForFunction(()=>document.querySelectorAll('.phone-wall-note').length===2);assert.equal(wallNotes.some(n=>n.id===firstId),false);
  assert.ok(writes.every(w=>w.path.startsWith('/api/noteboard')),'no model, memory or configuration writes');
  assert.deepEqual(errors,[]);console.log('Passed note creation, failure recovery, editing, remote refresh, drag persistence, layout, stale edit protection and deletion.');return;
 }
 if(process.env.ASH_PHONE_PWA_GAP_ONLY){
  // Reproduce the reported CSS and fixed-containing-block disagreement;
  // this does not emulate iOS's native compositor or its screen hit testing.
  await page.setViewportSize({width:402,height:874});
  await page.evaluate(()=>{
   const host=document.createElement('div');host.id='test-short-fixed-viewport';
   Object.assign(host.style,{position:'absolute',inset:'0 0 auto',height:'812px',transform:'translateZ(0)'});
   document.body.append(host);host.append(document.querySelector('.dashboard'));
   Object.defineProperty(window,'innerHeight',{configurable:true,value:812});
   Object.defineProperty(window,'visualViewport',{configurable:true,value:{height:812,offsetTop:0}});
   dispatchEvent(new Event('orientationchange'));
  });
  await page.waitForTimeout(350);
  const canvas=async()=>{
   const result=await page.evaluate(()=>{
    const r=document.querySelector('.dashboard').getBoundingClientRect();
    return {top:r.top,bottom:r.bottom,root:document.documentElement.getBoundingClientRect().height,
     bottomHit:!!document.elementFromPoint(201,873)?.closest('.dashboard'),scrollY};
   });assert.deepEqual(result,{top:0,bottom:874,root:874,bottomHit:true,scrollY:0});
  };
  await canvas();assert.equal((await page.locator('#phone-wallpaper').boundingBox()).height,874);
  const dock=await page.locator('.phone-dock').boundingBox();assert.equal(dock.y+dock.height,828);
  await page.evaluate(()=>switchSection('settings'));await canvas();
  assert.equal((await page.locator('#phone-app-header').boundingBox()).y,62);
  const main=await page.locator('.main-content').boundingBox();assert.equal(main.y+main.height,874);
  // A full-height shell alone used to pass while every application stopped
  // 34px above it. Check the actual page/bar at the physical bottom edge.
  for(const theme of ['light','dark']){
   await page.evaluate(theme=>AshTheme.setTheme(theme),theme);
   for(const view of ['preferences','settings','diary','standing','presets','heartbeats','recall','suppliers','supplier-route','import','export']){
    await page.evaluate(view=>switchSection(view),view);await canvas();
    assert.equal(await page.locator('.main-content').evaluate(el=>el.getBoundingClientRect().bottom),874,view+' reaches the screen bottom');
    assert.equal(await page.evaluate(()=>!!document.elementFromPoint(201,873)?.closest('.main-content')),true,view+' has no shell strip');
   }
   await page.evaluate(()=>switchSection('chat'));
   for(const tab of ['chat','conversations','cover','me']){
    await page.locator(`[data-chat-tab=${tab}]`).click();
    assert.equal(await page.evaluate(()=>!!document.elementFromPoint(201,873)?.closest('.phone-chat-tabs')),true,tab+' tab bar paints the bottom edge');
    const buttons=await page.locator('.phone-chat-tabs button').evaluateAll(els=>els.map(el=>el.getBoundingClientRect().bottom));
    assert(buttons.every(bottom=>bottom<=840),'tab controls stay above the home indicator');
   }
  }
  await page.evaluate(()=>AshTheme.setTheme('light'));
  await page.evaluate(()=>switchSection('chat'));await page.locator('[data-chat-tab=conversations]').click();
  await page.locator('.phone-conversation-entry .phone-icon-button').first().click();
  await page.locator('#phone-rename-conversation').click();
  const sheet=await page.locator('#phone-personalize').boundingBox();assert.equal(sheet.y+sheet.height,874);
  const save=page.locator('#phone-conversation-form button[type=submit]'),button=await save.boundingBox();
  assert(button.y+button.height>812);await shot('pwa-874-sheet');
  await save.click({position:{x:10,y:button.height-2}});
  await page.locator('#phone-personalize').waitFor({state:'hidden'});
  await page.evaluate(()=>switchSection('chat'));await page.locator('[data-chat-tab=chat]').click();await canvas();
  const tabs=await page.locator('.phone-chat-tabs').boundingBox();assert.equal(tabs.y+tabs.height,874);
  await page.locator('#phone-open-chat').click();
  const frame=page.frameLocator('#conversation-detail-frame');await frame.locator('#sendBtn:not([disabled])').waitFor();
  const composerBottom=async()=>{const r=await frame.locator('#composer').boundingBox();return r.y+r.height;};
  assert.equal(await composerBottom(),874);await canvas();await shot('pwa-874-chat');
  assert.equal(await frame.locator('body').evaluate(()=>!!document.elementFromPoint(innerWidth/2,innerHeight-1)?.closest('#composer')),true);
  const send=await frame.locator('#sendBtn').boundingBox();assert(send.y+send.height<=840);
  await frame.locator('#msgInput').focus();await page.evaluate(()=>AshPhoneViewport.refresh());
  await page.waitForTimeout(80);await canvas();
  await page.evaluate(()=>{visualViewport.height=460;AshPhoneViewport.refresh();});
  await page.locator('body.phone-chat-keyboard-open').waitFor();await frame.locator('body.phone-chat-keyboard-open').waitFor();
  assert.equal(await composerBottom(),460);
  await page.evaluate(()=>{visualViewport.height=812;AshPhoneViewport.refresh();});
  await page.waitForFunction(()=>!document.body.classList.contains('phone-viewport-active'));
  await frame.locator('body.phone-chat-keyboard-open').waitFor({state:'hidden'});
  assert.equal(await composerBottom(),874);await canvas();
  assert.deepEqual(errors,[]);console.log('Passed 874/812 PWA mismatch, safe areas, bottom-sheet click, iframe composer and keyboard recovery.');return;
 }
 if(process.env.ASH_PHONE_PWA_ONLY){
  assert.match(await page.locator('meta[name="viewport"]').getAttribute('content'),/viewport-fit=cover/);
  assert.equal(await page.locator('meta[name="apple-mobile-web-app-status-bar-style"]').getAttribute('content'),'black-translucent');
  async function checkShell(safeBottom){
   const bounds=await page.evaluate(expected=>{
    const shell=document.querySelector('.dashboard'),r=shell.getBoundingClientRect();
    return {x:r.x,y:r.y,width:r.width,bottom:r.bottom,padding:parseFloat(getComputedStyle(shell).paddingBottom),
     widthExpected:expected.width,heightExpected:expected.height,scroll:document.documentElement.scrollHeight,
     rootPosition:getComputedStyle(document.documentElement).position,bodyPosition:getComputedStyle(document.body).position,
     bottomElement:!!document.elementFromPoint(expected.width/2,expected.height-1)?.closest('.dashboard')};
   },page.viewportSize());
   assert.equal(bounds.x,0);assert.equal(bounds.y,0);assert.equal(bounds.width,bounds.widthExpected);
   assert(Math.abs(bounds.bottom-bounds.heightExpected)<0.5);assert.equal(bounds.padding,safeBottom);
   assert.notEqual(bounds.rootPosition,'fixed');assert.notEqual(bounds.bodyPosition,'fixed');assert.equal(bounds.bottomElement,true);
   assert(bounds.scroll<=bounds.heightExpected);assert.equal(await page.locator('.phone-home-indicator').isVisible(),false);
  }
  async function checkHome(){
   await checkShell(0);
   const wallpaper=await page.locator('#phone-wallpaper').boundingBox();
   assert.equal(wallpaper.y,0);assert.equal(wallpaper.height,page.viewportSize().height,'wallpaper covers both system safe areas');
   assert.equal(await page.locator('.phone-home-content').evaluate(el=>getComputedStyle(el).paddingTop),'47px');
   const dock=await page.locator('.phone-dock').boundingBox();
   assert.equal(Math.round(page.viewportSize().height-dock.y-dock.height),46,'Dock reserves the bottom inset once');
  }
  for(const width of [390,768]){
   await page.setViewportSize({width,height:844});await checkHome();
   await page.evaluate(()=>switchSection('preferences'));await checkShell(0);
   assert.equal(await page.locator('.phone-app-header').evaluate(el=>el.getBoundingClientRect().top),47);
   await page.evaluate(()=>switchSection('home'));await checkHome();
  }
  await page.setViewportSize({width:390,height:844});
  await page.evaluate(()=>merlePhoneApps.customize('wallpaper'));
  const studio=await page.locator('.phone-customize-sheet').boundingBox();
  assert.equal(studio.y,0);assert.equal(studio.height,844,'absolute appearance panel fills its parent');
  assert.equal(await page.locator('#phone-customize-content').evaluate(el=>getComputedStyle(el).paddingBottom),'34px');
  await shot('pwa-appearance-full-height');await page.locator('#btn-phone-customize-close').click();
  await shot('pwa-home-edge-to-edge');
  // Both JS APIs can exclude the status bar. Taking their maximum must not
  // shrink the CSS app viewport, even while a field is focused without a keyboard.
  await page.evaluate(()=>{
   window.testInnerHeightDescriptor=Object.getOwnPropertyDescriptor(window,'innerHeight');
   Object.defineProperty(window,'innerHeight',{configurable:true,value:784});
   Object.defineProperty(window,'visualViewport',{configurable:true,value:{height:784,offsetTop:0}});
   dispatchEvent(new Event('orientationchange'));
  });
  await page.waitForTimeout(350);
  await checkShell(0);
  await page.evaluate(()=>switchSection('preferences'));await checkShell(0);await shot('pwa-settings-full-height');
  await page.evaluate(()=>switchSection('home'));await checkShell(0);
  await page.locator('#phone-pages [data-phone-app=chat]').click();await checkShell(0);
  await page.locator('#phone-open-chat').click();
  const frame=page.frameLocator('#conversation-detail-frame');await frame.locator('#sendBtn:not([disabled])').waitFor();
  await checkShell(0);
  await frame.locator('#msgInput').focus();await page.evaluate(()=>AshPhoneViewport.refresh());
  await page.waitForTimeout(50);await checkShell(0);
  const input=await frame.locator('#composer').boundingBox();assert(Math.abs(input.y+input.height-844)<2);
  assert.equal(await frame.locator('body').evaluate(el=>getComputedStyle(el).getPropertyValue('--safe-bottom').trim()),'34px','iframe composer owns the bottom inset');
  assert.equal(await frame.locator('.phone-input-bar').evaluate(el=>getComputedStyle(el).paddingBottom),'42px','input bar protects controls with one 34px inset');
  assert.equal(await frame.locator('body').evaluate(()=>!!document.elementFromPoint(innerWidth/2,innerHeight-1)?.closest('#composer')),true,'the composer itself paints the bottom edge');
  await shot('pwa-chat-safe-area');
  await page.evaluate(()=>{document.documentElement.style.setProperty('--test-safe-bottom','0px');});await checkShell(0);
  await page.evaluate(()=>{document.documentElement.style.removeProperty('--test-safe-bottom');Object.defineProperty(window,'visualViewport',{configurable:true,value:{height:460,offsetTop:0}});});
  await frame.locator('#msgInput').focus();await page.evaluate(()=>AshPhoneViewport.refresh());
  await page.locator('body.phone-chat-keyboard-open').waitFor();await frame.locator('body.phone-chat-keyboard-open').waitFor();
  const keyboardInput=await frame.locator('#composer').boundingBox();assert(Math.abs(keyboardInput.y+keyboardInput.height-460)<2);
  assert.equal(await page.locator('.dashboard').evaluate(el=>getComputedStyle(el).paddingBottom),'0px');
  await page.evaluate(()=>{Object.defineProperty(window,'visualViewport',{configurable:true,value:{height:784,offsetTop:0}});AshPhoneViewport.refresh();});
  await page.waitForFunction(()=>!document.body.classList.contains('phone-viewport-active'));
  await checkShell(0);
  await frame.locator('#msgInput').blur();await checkShell(0);
  assert.deepEqual(errors,[]);console.log('Passed single fixed shell, both JS viewport heights under-reporting, focus without keyboard, keyboard dismissal and safe area.');return;
 }
 if(process.env.ASH_PHONE_PROMPTS_ONLY){
  await page.locator('#phone-pages [data-phone-app=chat]').click();
  await page.locator('[data-chat-tab=conversations]').click();
  await page.locator('.phone-conversation-entry').nth(1).locator('.phone-icon-button').click();
  await page.locator('#phone-extra-prompts').click();
  await page.locator('#extraPromptsModal[open]').waitFor();
  assert.equal(await page.locator('#phone-personalize').evaluate(el=>el.open),false);
  await page.waitForFunction(()=>!document.getElementById('captureFrontendPrompts').disabled);
  await page.locator('#extraPromptEditor summary').click();
  await page.locator('#extraPromptTitle').fill('只属于九月');
  await page.locator('#extraPromptContent').fill('这段额外提示词只用于所选会话。');
  await page.locator('#saveExtraPromptBtn').click();
  await page.waitForFunction(()=>document.getElementById('extraPromptStatus').textContent.includes('已保存'));
  assert.equal(conversationPrompts.get(2)?.[0].title,'只属于九月');
  assert.equal(conversationPrompts.has(1),false);
  assert.equal(writes.find(w=>w.path==='/api/conversations/2/extra-prompts')?.method,'POST');
  assert.equal(await page.locator('#extraPromptBlocks').getByText('只属于九月',{exact:false}).count()>0,true);
  await noOverflow();await shot('conversation-prompts-light');
  await page.evaluate(()=>AshTheme.setTheme('dark'));await shot('conversation-prompts-dark');
  await page.locator('#extraPromptsModal .extra-prompts-footer button').click();
  await page.locator('.phone-conversation-entry').first().locator('.phone-icon-button').click();
  await page.locator('#phone-extra-prompts').click();
  await page.waitForFunction(()=>!document.getElementById('captureFrontendPrompts').disabled);
  assert.equal(await page.locator('#extraPromptConversationSection').isVisible(),false);
  await page.locator('#extraPromptsModal .extra-prompts-footer button').click();
  await page.locator('.phone-conversation-row').first().click();
  const chat=page.frameLocator('#conversation-detail-frame');
  await chat.locator('#sendBtn').waitFor();
  assert.equal(await chat.locator('#promptBtn,#extraPromptsModal').count(),0);
  assert.deepEqual(errors,[]);
  console.log('Passed conversation management prompt editing, target isolation, chat cleanup and light/dark layouts.');return;
 }
 if(process.env.ASH_PHONE_EXPORT_PROGRESS_ONLY){
  await page.evaluate(()=>switchSection('export'));
  const button=page.locator('#export-download'),status=page.locator('#export-progress');
  await button.click();await status.filter({hasText:'读取聊天消息'}).waitFor();
  assert.equal(await button.isDisabled(),true);assert.equal(exportUrls.length,1);
  assert.equal(exportUrls[0].searchParams.get('include_messages'),'false');
  assert.match(exportUrls[0].searchParams.get('export_id'),/^[a-f0-9]{32}$/);
  assert.match(await status.innerText(),/128 条.*0.06 MB/);await shot('export-running');
  exportStatus='failed';await status.filter({hasText:'QueryCanceledError'}).waitFor();assert.equal(await button.isEnabled(),true);
  await page.locator('#export-history-messages').check();exportStatus='running';await button.click();
  await status.filter({hasText:'读取聊天消息'}).waitFor();assert.equal(exportUrls.length,2);
  assert.equal(exportUrls[1].searchParams.get('include_messages'),'true');
  assert.notEqual(exportUrls[0].searchParams.get('export_id'),exportUrls[1].searchParams.get('export_id'));
  exportStatus='completed';await status.filter({hasText:'发送完成'}).waitFor();assert.equal(await button.isEnabled(),true);
  exportStatus='running';await button.click();await status.filter({hasText:'读取聊天消息'}).waitFor();
  exportStatus='interrupted';await status.filter({hasText:'导出中断'}).waitFor();assert.equal(await button.isEnabled(),true);
  exportStatus='running';await button.click();await status.filter({hasText:'读取聊天消息'}).waitFor();
  exportStatus='unavailable';await status.filter({hasText:'无法确认导出结果（HTTP 502）'}).waitFor();
  assert.match(await status.innerText(),/最后进度：读取聊天消息.*128 条/);
  assert.equal(await button.isEnabled(),true);
  assert.match(page.url(),/\/dashboard/);assert.deepEqual(errors,[]);
  console.log('Passed visible export stage/rows/bytes, failed/interrupted/completed states, retry identifiers and native background download.');return;
 }
 if(process.env.ASH_PHONE_DIARY_EDITOR_ONLY){
  await page.locator('#phone-pages [data-phone-app=diary]').click();
  await page.getByRole('button',{name:'写日记',exact:true}).click();
  const modal=page.locator('#long-term-memory-editor-modal'),save=page.locator('#long-term-memory-editor-save');await modal.waitFor();
  const bounded=async()=>{
   const bounds=await page.locator('.dashboard').boundingBox(),dialog=await modal.locator('.memory-editor-dialog').boundingBox(),button=await save.boundingBox();
   assert(dialog.x>=bounds.x-1&&dialog.x+dialog.width<=bounds.x+bounds.width+1);
   assert(dialog.y>=bounds.y-1&&dialog.y+dialog.height<=bounds.y+bounds.height+1);
   assert(button.y>=dialog.y&&button.y+button.height<=dialog.y+dialog.height,'save remains inside visible dialog');
   assert.equal(await modal.locator('.memory-editor-actions').evaluate(el=>el.parentElement.classList.contains('memory-editor-dialog')),true);
  };
  for(const width of [320,390,768])for(const theme of ['light','dark']){
   await page.setViewportSize({width,height:844});await page.evaluate(theme=>AshTheme.setTheme(theme),theme);await bounded();
   assert.equal(await modal.evaluate(el=>el.classList.contains('phone-paper-app')),false);
   await shot(`diary-editor-${theme}-${width}`);
  }
  await page.setViewportSize({width:390,height:844});
  await page.locator('#long-term-memory-title').fill('雨后的窗边');await page.locator('#long-term-memory-content').fill('这是新日记正文。');
  await modal.getByRole('button',{name:'关键词',exact:true}).click();
  const keywords=page.locator('#long-term-summary-modal');await keywords.waitFor();
  assert.equal(await page.locator('[id^=temporary-diary-trial]').count(),0,'retired migration UI is removed');
  await page.locator('#long-term-summary-content').fill('手写关键词');keywordPreviewError=true;
  await page.locator('#long-term-summary-generate').click();await page.locator('#long-term-summary-msg').filter({hasText:'暂时无法使用'}).waitFor();
  assert.equal(await page.locator('#long-term-summary-content').inputValue(),'手写关键词');
  keywordPreviewError=false;await page.locator('#long-term-summary-generate').click();
  await page.waitForFunction(()=>document.getElementById('long-term-summary-content').value.split(String.fromCharCode(10)).join('|')==='雨天|窗边|散步');
  assert.equal(editorDiaries.length,0,'generation previews an unsaved diary without saving it');
  const generated=JSON.parse(writes.filter(w=>w.path==='/api/diaries/keywords-preview').at(-1).body);
  assert.equal(generated.content,'这是新日记正文。');assert.equal(generated.author_role,'user');
  // Closing a pending request must not replace a newly opened keyword draft.
  let finishPreview;keywordPreviewGate=new Promise(resolve=>{finishPreview=resolve;});
  await page.locator('#long-term-summary-generate').click();await page.locator('#long-term-summary-generate:disabled').waitFor();
  await keywords.locator('.memory-editor-close').click();await modal.getByRole('button',{name:'关键词',exact:true}).click();
  await page.locator('#long-term-summary-content').fill('新的草稿');finishPreview();keywordPreviewGate=null;
  await page.waitForTimeout(100);assert.equal(await page.locator('#long-term-summary-content').inputValue(),'新的草稿');
  await page.locator('#long-term-summary-content').fill('雨天\n窗边');
  await keywords.getByRole('button',{name:'保存',exact:true}).click();await keywords.waitFor({state:'hidden'});
  assert.equal(await page.locator('#long-term-memory-summary-preview').innerText(),'#雨天 #窗边');
  await page.locator('#long-term-memory-title').focus();
  await page.evaluate(()=>{window.diaryTestViewport={height:420,offsetTop:40};Object.defineProperty(window,'visualViewport',{configurable:true,value:diaryTestViewport});AshPhoneViewport.refresh();});
  await page.locator('body.phone-viewport-active').waitFor();await bounded();await shot('diary-editor-keyboard');
  diarySaveError=true;await save.click();await page.locator('#long-term-memory-editor-msg').filter({hasText:'测试保存失败'}).waitFor();
  assert.equal(await page.locator('#long-term-memory-content').inputValue(),'这是新日记正文。');assert.equal(await modal.isVisible(),true);
  diarySaveError=false;await save.click();await modal.waitFor({state:'hidden'});
  assert.equal(editorDiaries[0].title,'雨后的窗边');assert.deepEqual(editorDiaries[0].keywords,['雨天','窗边']);assert.equal(editorDiaries[0].author_role,'user');
  await page.evaluate(()=>{diaryTestViewport.height=844;diaryTestViewport.offsetTop=0;AshPhoneViewport.refresh();});
  await page.waitForFunction(()=>!document.body.classList.contains('phone-viewport-active'));
  await page.evaluate(()=>openLongTermMemoryEditor(1));await modal.waitFor();assert.equal(await page.locator('#long-term-memory-content').inputValue(),'这是新日记正文。');
  await page.locator('#long-term-memory-content').fill('修改后的正文。');await save.click();await modal.waitFor({state:'hidden'});
  assert.equal(editorDiaries[0].content,'修改后的正文。');
  await page.getByRole('button',{name:'写日记',exact:true}).click();await save.click();
  await page.locator('#long-term-memory-editor-msg').filter({hasText:'不能为空'}).waitFor();
  await modal.getByRole('button',{name:'取消',exact:true}).click();await modal.waitFor({state:'hidden'});
  assert.deepEqual(errors,[]);console.log('Passed bounded monochrome diary editors, visible footer, keyboard/panning, keyword draft, save failure retention, create/edit and validation.');return;
 }
 if(process.env.ASH_PHONE_MESSAGE_COUNT_ONLY){
  let release;countStatsGate=new Promise(resolve=>{release=resolve;});
  await page.locator('#phone-pages [data-phone-app=chat]').click();await page.locator('#phone-open-chat').click();
  const frame=page.frameLocator('#conversation-detail-frame'),counter=frame.locator('#phone-chat-message-count');
  await frame.locator('.msg.assistant .msg-body').waitFor();assert.equal(await counter.textContent(),' · 2+ 条消息');
  assert.equal(await counter.isVisible(),false,'count is hidden until details are expanded');
  assert.equal(await frame.locator('.phone-chat-person #phone-chat-message-count').count(),0);
  await frame.locator('#phone-chat-more').click();await counter.waitFor();
  assert.match(await counter.getAttribute('title'),/统计中/);
  assert.equal(countReads.filter(url=>new URL(url).pathname.endsWith('/messages')).length,1,'only the initial message page is fetched');
  assert.equal(new URL(countReads[0]).searchParams.get('limit'),'20');
  release();countStatsGate=null;await counter.filter({hasText:'1200 条消息'}).waitFor();
  assert.equal(countReads.length,2,'reuse existing background statistics without extra requests');
  for(const width of [320,390,768])for(const theme of ['light','dark']){
   await page.setViewportSize({width,height:844});await page.evaluate(theme=>AshTheme.setTheme(theme),theme);
   const box=await counter.boundingBox();assert(box.x>=0&&box.x+box.width<=width);await shot(`message-count-${theme}-${width}`);
  }
  await frame.locator('#phone-chat-more').click();assert.equal(await counter.isVisible(),false);
  await frame.locator('#msgInput').fill('更新消息条数');await frame.locator('#sendBtn').click();
  await counter.filter({hasText:'1202 条消息'}).waitFor({state:'attached'});
  await gotoHome();messages.set(2,[]);
  await page.locator('#phone-pages [data-phone-app=chat]').click();await page.locator('[data-chat-tab=conversations]').click();await page.locator('[data-conversation-id="2"]').click();
  await counter.filter({hasText:'0 条消息'}).waitFor({state:'attached'});
  assert.equal(await counter.isVisible(),false);
  await frame.locator('#phone-chat-more').click();await counter.waitFor();
  assert.equal(await frame.locator('.composer-hint').innerText(),'正在浏览历史上下文；激活此会话后可继续聊天 · 0 条消息');
  assert.equal(countReads.filter(url=>new URL(url).pathname.includes('/2/message-stats')).length,0,'empty conversations need no statistics request');
  assert.deepEqual(errors,[]);console.log('Passed nonblocking first page, deferred exact total, fixed request count, send refresh, empty history and responsive message count.');return;
 }
 if(process.env.ASH_PHONE_PAIR_ONLY){
  const image={name:'avatar.png',mimeType:'image/png',buffer:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jN1EAAAAASUVORK5CYII=','base64')};
  const pair=page.locator('#phone-pages .phone-pair'),menu=page.locator('#phone-avatar-menu');
  for(const [role,name] of [['user','小满'],['assistant','雾']]){
   await pair.locator(`[data-phone-name="${role}"]`).click();
   const input=pair.locator(`[data-phone-name-editor="${role}"]`);await input.fill(name);
   await input.press(role==='user'?'Enter':'Tab');
   await pair.locator(`[data-local-name="${role}"]`).filter({hasText:name}).waitFor();
   assert.equal(await page.evaluate(role=>AshLocal.get().names[role],role),name);
   await pair.locator(`[data-phone-profile="${role}"]`).click();await menu.waitFor({state:'visible'});
   assert.deepEqual(await menu.locator('button').allTextContents(),['恢复','图片']);
   assert.equal(await page.locator('#phone-personalize').isVisible(),false);
   await menu.getByRole('button',{name:'图片',exact:true}).click();await page.locator('#phone-local-image').setInputFiles(image);
   await pair.locator(`[data-local-avatar="${role}"] img`).waitFor();
  }
  await page.reload();await pair.locator('[data-local-name=user]').filter({hasText:'小满'}).waitFor();
  assert.equal(await pair.locator('[data-local-avatar] img').count(),2);
  await pair.locator('[data-phone-name=user]').click();await pair.locator('input').fill('');await pair.locator('input').press('Enter');
  assert.equal(await page.evaluate(()=>AshLocal.get().names.user),'小满');
  await pair.locator('[data-phone-name=user]').click();await pair.locator('input').fill('不保存');await pair.locator('input').press('Escape');
  assert.equal(await page.evaluate(()=>AshLocal.get().names.user),'小满');
  await pair.locator('[data-phone-name=user]').click();await pair.locator('input').fill('中文输入');
  await pair.locator('input').dispatchEvent('keydown',{key:'Enter',isComposing:true});assert.equal(await pair.locator('input').count(),1);
  await pair.locator('input').press('Escape');
  for(const width of [320,390,768])for(const theme of ['light','dark']){
   await page.setViewportSize({width,height:844});await page.evaluate(theme=>{AshTheme.setTheme(theme);const layout=AshDesktop.get();layout.mode=theme;return AshDesktop.restore(layout);},theme);
   await pair.locator('[data-phone-profile=user]').click();await menu.waitFor({state:'visible'});
   const box=await menu.boundingBox();assert(box.x>=0&&box.y>=0&&box.x+box.width<=width);
   const avatars=await pair.locator('.phone-pair-avatar').evaluateAll(nodes=>nodes.map(el=>{const b=el.getBoundingClientRect();return {left:b.left,right:b.right};}));
   assert(avatars[1].left<avatars[0].right,'avatars still overlap');
   await shot(`pair-menu-${theme}-${width}`);await page.keyboard.press('Escape');
  }
  for(const role of ['user','assistant']){
   await pair.locator(`[data-phone-profile="${role}"]`).click();await menu.getByRole('button',{name:'恢复',exact:true}).click();
   await pair.locator(`[data-local-avatar="${role}"] img`).waitFor({state:'detached'});
  }
  await page.reload();assert.equal(await pair.locator('[data-local-avatar] img').count(),0);
  assert.equal(await pair.locator('[data-phone-profile=user]').getAttribute('aria-label'),'你的头像');
  const together=page.locator('#phone-pages .phone-widget-together').first(),body=await together.locator('.phone-together-widget').boundingBox();
  await together.locator('.phone-together-widget').click({position:{x:10,y:body.height-10}});await together.locator('[data-widget-edit]').click();
  const editor=page.locator('#phone-customize');
  await editor.locator('[data-phone-name=user]').click();await editor.locator('input[data-phone-name-editor]').fill('编辑中');await editor.locator('input[data-phone-name-editor]').press('Enter');
  await editor.locator('[data-phone-profile=user]').click();await menu.waitFor({state:'visible'});await page.keyboard.press('Escape');
  assert.equal(await editor.isVisible(),true);await page.locator('#btn-phone-customize-close').click();
  assert.equal(await page.evaluate(()=>AshLocal.get().names.user),'编辑中');
  const hold=await together.locator('.phone-together-widget').boundingBox(),cdp=await context.newCDPSession(page);
  await cdp.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:hold.x+10,y:hold.y+hold.height-10}]});
  await page.locator('#phone-home.is-editing').waitFor();await cdp.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});
  assert.equal(writes.length,0);assert.deepEqual(errors,[]);
  console.log('Passed direct name autosave, IME/blank/cancel, avatar image/reset, persistence, overlapping layout, bounded menus and zero server writes.');return;
 }
 if(process.env.ASH_PHONE_CONFIG_ENTRY_ONLY){
  await page.locator('#phone-pages [data-phone-app=chat]').click();await page.locator('#phone-open-chat').click();
  const frame=page.frameLocator('#conversation-detail-frame');await frame.locator('#sendBtn:not([disabled])').waitFor();
  await frame.locator('#phone-chat-more').click();
  assert.equal(await frame.locator('#phone-chat-more').getAttribute('aria-expanded'),'true');
  assert.equal(await frame.locator('#chatOpenConfiguration,.chat-toolbar,#chat-config-description,#activateChat').count(),0,'legacy configuration toolbar removed');
  await frame.locator('#conversationSettingsBtn').waitFor({state:'visible'});
  assert.equal(await page.locator('body').getAttribute('data-phone-view'),'detail');
  const entry=frame.getByRole('button',{name:'聊天配置',exact:true});assert.equal(await entry.count(),1);
  assert.equal(await entry.innerText(),'test-model');await entry.click();
  await page.waitForFunction(()=>document.body.dataset.phoneView==='supplier-route');
  await page.locator('#routeModel').waitFor();await page.waitForFunction(()=>document.getElementById('routeModel').value==='test-model');
  assert.equal(writes.length,0,'opening configuration never changes saved settings');
  assert.deepEqual(errors,[]);console.log('Passed chat-only plus menu, single header configuration button, route navigation and unchanged saved configuration.');return;
 }
 if(process.env.ASH_PHONE_CHAT_BOTTOM_ONLY){
  await page.locator('#phone-pages [data-phone-app=chat]').click();await page.locator('#phone-open-chat').click();
  const frame=page.frameLocator('#conversation-detail-frame');await frame.locator('#sendBtn:not([disabled])').waitFor();
  for(const width of [320,390,768])for(const theme of ['light','dark']){
   await page.setViewportSize({width,height:844});await page.evaluate(theme=>AshTheme.setTheme(theme),theme);
   await frame.locator('body').evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
   const chatBackground=await frame.locator('.app').evaluate(el=>getComputedStyle(el).backgroundColor);
   assert.equal(await page.locator('.dashboard').evaluate(el=>getComputedStyle(el).backgroundColor),chatBackground,'home indicator backing matches the chat');
   assert.equal(await page.locator('.phone-home-indicator').evaluate(el=>getComputedStyle(el).backgroundColor),'rgba(0, 0, 0, 0)');
   const input=await frame.locator('#composer').boundingBox(),indicator=await page.locator('.phone-home-indicator').boundingBox();
   assert(Math.abs(input.y+input.height-indicator.y)<2,'input meets the home indicator without a gap');
   await shot(`chat-bottom-${theme}-${width}`);
  }
  await page.setViewportSize({width:390,height:844});
  await page.locator('.phone-home-indicator').evaluate(el=>{el.style.height='34px';el.style.flexBasis='34px';});
  await shot('chat-bottom-safe-area');
  await page.evaluate(()=>{window.phoneTestViewport={height:460,offsetTop:0};Object.defineProperty(window,'visualViewport',{configurable:true,value:phoneTestViewport});});
  await frame.locator('#msgInput').focus();await page.evaluate(()=>AshPhoneViewport.refresh());
  await page.locator('body.phone-chat-keyboard-open').waitFor();await frame.locator('body.phone-chat-keyboard-open').waitFor();
  assert.equal(await page.locator('.phone-home-indicator').isVisible(),false);
  const keyboardInput=await frame.locator('#composer').boundingBox();assert(Math.abs(keyboardInput.y+keyboardInput.height-460)<2);
  await frame.locator('#msgInput').blur();await page.evaluate(()=>{phoneTestViewport.height=844;AshPhoneViewport.refresh();});
  await page.waitForFunction(()=>!document.body.classList.contains('phone-chat-keyboard-open'));
  assert.equal(await page.locator('.dashboard').evaluate(el=>getComputedStyle(el).backgroundColor),await frame.locator('.app').evaluate(el=>getComputedStyle(el).backgroundColor));
  await page.locator('#phone-home-button').click();await page.waitForFunction(()=>document.body.dataset.phoneView==='home');
  assert.equal(await page.locator('.dashboard').evaluate(el=>getComputedStyle(el).backgroundColor),await page.locator('body').evaluate(el=>getComputedStyle(el).getPropertyValue('--phone-bg').trim()==='#202122'?'rgb(32, 33, 34)':'rgb(248, 248, 246)'));
  assert.deepEqual(errors,[]);console.log('Passed continuous chat/home-indicator backgrounds, no input gap, light/dark narrow/wide layouts, safe area and returning home.');return;
 }
 if(process.env.ASH_PHONE_NOTICE_ONLY){
  await page.locator('#phone-pages [data-phone-app=chat]').click();await page.locator('[data-chat-tab=conversations]').click();await page.locator('[data-conversation-id="2"]').click();
  const frame=page.frameLocator('#conversation-detail-frame');await frame.locator('#phone-chat-continue').waitFor();
  for(const width of [320,390])for(const theme of ['light','dark']){
   await page.setViewportSize({width,height:844});await page.evaluate(theme=>AshTheme.setTheme(theme),theme);
   for(const keyboard of [false,true]){
    await frame.locator('body').evaluate((el,open)=>el.classList.toggle('phone-chat-keyboard-open',open),keyboard);
    await frame.locator('body').evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
    const notice=frame.locator('#phone-chat-notice'),header=frame.locator('.app > .topbar');
    assert.equal(await notice.evaluate(el=>el.parentElement.classList.contains('topbar')),true);
    const n=await notice.boundingBox(),h=await header.boundingBox();
    assert(n.x>=0&&n.x+n.width<=width&&n.y+n.height<=h.y+h.height+1,'notice stays within header');
    const padding=await frame.locator('#msgArea').evaluate(el=>parseFloat(getComputedStyle(el).paddingTop));
    assert(padding>=h.height+11,'messages reserve actual header height');
   }
   await shot(`history-notice-${theme}-${width}`);
  }
  await frame.locator('body').evaluate(el=>el.classList.remove('phone-chat-keyboard-open'));
  await frame.locator('#phone-chat-more').click();
  const notice=await frame.locator('#phone-chat-notice').boundingBox(),options=await frame.locator('.topbar-actions').boundingBox();
  assert(options.y>=notice.y+notice.height,'options sit below the notice');
  await frame.locator('#phone-chat-more').click();await frame.locator('#phone-chat-continue').click();
  await frame.locator('#sendBtn:not([disabled])').waitFor();assert.equal(activeId,2);
  await frame.locator('#phone-chat-notice').waitFor({state:'hidden'});
  await frame.locator('#msgInput').fill('测试失败提示');failChat=true;await frame.locator('#sendBtn').click();
  await frame.locator('#phone-chat-notice').filter({hasText:'测试上游暂时不可用'}).waitFor();
  assert.deepEqual(errors,[]);console.log('Passed history notice header placement, reserved message space, keyboard/narrow/light/dark layouts, options, activation and errors.');return;
 }
 if(process.env.ASH_PHONE_MESSAGE_ACTIONS_ONLY){
  await page.locator('#phone-pages [data-phone-app=chat]').click();await page.locator('#phone-open-chat').click();
  const frame=page.frameLocator('#conversation-detail-frame');await frame.locator('#sendBtn:not([disabled])').waitFor();
  for(const width of [320,390])for(const theme of ['light','dark']){
   await page.setViewportSize({width,height:844});await page.evaluate(theme=>AshTheme.setTheme(theme),theme);
   for(const role of ['assistant','user']){
    const message=frame.locator('.msg.'+role).first(),bubble=message.locator('.phone-message-bubble'),actions=message.locator('.msg-actions');
    await frame.locator('#msgInput').focus();assert.equal(await actions.isVisible(),false);
    const box=await bubble.boundingBox();
    await bubble.dispatchEvent('pointerdown',{pointerId:1,pointerType:'touch',isPrimary:true,button:0,clientX:box.x+10,clientY:box.y+10});
    await actions.waitFor({state:'visible'});await bubble.dispatchEvent('pointerup',{pointerId:1,pointerType:'touch'});
    const anchor=await bubble.boundingBox(),bar=await actions.boundingBox();
    assert(bar.y>=anchor.y+anchor.height,'actions sit below their own bubble');
    assert(bar.x>=0&&bar.x+bar.width<=width,'actions fit inside the screen');
    assert.equal(await actions.evaluate(el=>getComputedStyle(el).position),'static');
    assert.equal(await actions.evaluate(el=>getComputedStyle(el).boxShadow),'none');
    assert.equal(await actions.getByRole('button',{name:'编辑消息',exact:true}).locator('svg').count(),1);
    const remove=actions.getByRole('button',{name:'删除消息',exact:true});
    assert.equal(await remove.locator('svg').count(),1);
    const color=await remove.evaluate(el=>getComputedStyle(el).color.match(/\d+/g).map(Number));assert(color[0]>color[1]&&color[0]>color[2]);
    await shot(`message-actions-${role}-${theme}-${width}`);
    await actions.getByRole('button',{name:'查看本轮召回',exact:true}).click();
    await frame.locator('.phone-recall-card').waitFor();
    assert.match(await frame.locator('.phone-recall-card').innerText(),/当时注入的原话/);
    assert.equal(await frame.locator('.phone-recall-card script').count(),0);
    await frame.locator('.phone-recall-feedback [data-feedback=useful]').click();
    await frame.locator('.phone-recall-feedback [data-feedback=useful][aria-pressed=true]').waitFor();
    assert.equal(writes.at(-1).data.turn_id,3);
    await frame.getByRole('button',{name:'关闭召回',exact:true}).click();
   }
  }
  const editBubble=frame.locator('.msg.user').first().locator('.phone-message-bubble');
  const editBox=await editBubble.boundingBox();
  await editBubble.dispatchEvent('pointerdown',{pointerId:1,pointerType:'touch',isPrimary:true,button:0,clientX:editBox.x+10,clientY:editBox.y+10});
  await frame.locator('.msg.user').first().locator('.msg-actions').waitFor({state:'visible'});
  await editBubble.dispatchEvent('pointerup',{pointerId:1,pointerType:'touch'});
  await frame.getByRole('button',{name:'编辑消息',exact:true}).first().click();await frame.locator('#editMsgModal.show').waitFor();
  assert.deepEqual(errors,[]);console.log('Passed inline message actions, long press, user/assistant alignment, monochrome icons, red delete, edit and light/dark narrow layouts.');return;
 }
 if(process.env.ASH_PHONE_REASONING_ONLY){
  await page.locator('#phone-pages [data-phone-app=chat]').click();await page.locator('#phone-open-chat').click();
  let frame=page.frameLocator('#conversation-detail-frame');await frame.locator('#sendBtn:not([disabled])').waitFor();
  const datedMessage=frame.locator('.msg.assistant').first(), timestamp=datedMessage.locator('.phone-message-time');
  assert.equal(await timestamp.evaluate(el=>getComputedStyle(el).opacity),'0');
  if(await frame.locator('body').evaluate(()=>matchMedia('(hover:hover)').matches)) {
   await datedMessage.hover();assert.equal(await timestamp.evaluate(el=>getComputedStyle(el).opacity),'1');
   await frame.locator('#phone-chat-identity').hover();assert.equal(await timestamp.evaluate(el=>getComputedStyle(el).opacity),'0');
  } else {
   const bubble=await datedMessage.locator('.phone-message-bubble').boundingBox(), cdp=await context.newCDPSession(page);
   await cdp.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:bubble.x+20,y:bubble.y+12}]});
   await frame.locator('.msg.assistant.phone-message-actions-open').first().waitFor();
   await cdp.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});
   assert.equal(await timestamp.evaluate(el=>getComputedStyle(el).opacity),'1');
  }
  await frame.locator('.phone-message-reasoning').waitFor({state:'hidden'});
  await frame.locator('#msgInput').fill('带思考的回复');await frame.locator('#sendBtn').click();
  await frame.locator('#sendBtn:not([disabled])').waitFor();await frame.locator('.phone-message-reasoning').click();
  await frame.locator('.phone-reasoning-dialog[open]').waitFor();
  assert.equal(await frame.locator('body').evaluate(()=>document.activeElement.id),'phone-reasoning-title');
  assert.equal(await frame.getByRole('button',{name:'关闭思考',exact:true}).evaluate(el=>el.matches(':focus-visible')),false);
  assert.match(await frame.locator('.phone-reasoning-content').innerText(),/先整理问题/);
  assert.equal(await frame.locator('body').evaluate(()=>window.reasoningInjected),undefined);
  const dot=await frame.locator('.phone-message-reasoning').boundingBox(),bubble=await frame.locator('.msg.assistant').last().locator('.phone-message-bubble').boundingBox();
  assert.ok(dot.y>=bubble.y+bubble.height,'thought control belongs to the reply');
  await frame.locator('#phone-chat-identity').evaluate(el=>el.hidden=true);
  await frame.getByRole('button',{name:'关闭思考',exact:true}).click();
  await frame.locator('.phone-message-reasoning').click();
  assert.match(await frame.locator('.phone-reasoning-content').innerText(),/先整理问题/);
  await shot('chat-reasoning');
  await frame.getByRole('button',{name:'关闭思考',exact:true}).click();
  await page.reload();await page.locator('#phone-open-chat').click();frame=page.frameLocator('#conversation-detail-frame');
  await frame.locator('.phone-message-reasoning').click();await frame.locator('.phone-reasoning-dialog[open]').waitFor();
  assert.match(await frame.locator('.phone-reasoning-content').innerText(),/先整理问题/);
  await frame.getByRole('button',{name:'关闭思考',exact:true}).click();
  await gotoHome();await page.locator('#phone-pages [data-phone-app=chat]').click();await page.locator('[data-chat-tab=conversations]').click();await page.locator('[data-conversation-id="2"]').click();
  await frame.locator('#msgInput').waitFor();await frame.locator('.phone-message-reasoning').waitFor({state:'hidden'});
  await frame.locator('body').evaluate(()=>{
   const area=document.getElementById('msgArea');
   area.append(createMessageElement({id:901,role:'assistant',content:'第一条',reasoning_content:'只属于第一条的思考'}),
    createMessageElement({id:902,role:'assistant',content:'第二条',reasoning_content:'只属于第二条的思考'}),
    createMessageElement({id:903,role:'assistant',content:'没有思考'}));
  });
  assert.equal(await frame.locator('.phone-message-reasoning').count(),2);
  for(const [id,text] of [[901,'只属于第一条的思考'],[902,'只属于第二条的思考']]) {
   await frame.locator(`[data-message-id="${id}"] .phone-message-reasoning`).click();
   assert.equal(await frame.locator('.phone-reasoning-content').innerText(),text);
   await frame.getByRole('button',{name:'关闭思考',exact:true}).click();
  }
  await frame.locator('body').evaluate(()=>{
   const message=createMessageElement({id:904,role:'assistant',content:'流式回复'});
   document.getElementById('msgArea').appendChild(message);
   AshChatUI.startReasoning(message);AshChatUI.appendReasoning('正在思考');
  });
  await frame.locator('[data-message-id="904"] .phone-message-reasoning').click();
  assert.equal(await frame.locator('.phone-reasoning-content').innerText(),'正在思考');
  await frame.locator('body').evaluate(()=>AshChatUI.appendReasoning('，继续检查'));
  assert.equal(await frame.locator('.phone-reasoning-content').innerText(),'正在思考，继续检查');
  await frame.getByRole('button',{name:'关闭思考',exact:true}).click();
  assert.deepEqual(errors,[]);console.log('Passed per-message reasoning, hidden avatars, live updates, popup, safe text, refresh persistence and conversation isolation.');return;
 }
 if(process.env.ASH_PHONE_USAGE_PAGES_ONLY){
  await page.evaluate(()=>openUsageBoard());
  await page.locator('#usage-overview strong').first().waitFor();
  const close=page.locator('.usage-board-close');
  await close.focus();
  const closeStyle=await close.evaluate(el=>{const s=getComputedStyle(el);return {outline:s.outlineStyle,radius:s.borderRadius,border:s.borderTopWidth,width:el.offsetWidth,height:el.offsetHeight};});
  assert.equal(closeStyle.outline,'none');assert.equal(closeStyle.radius,'50%');assert.equal(closeStyle.border,'0px');assert.equal(closeStyle.width,closeStyle.height);
  const pages=page.locator('#usage-pages');
  assert.equal(await pages.locator(':scope > section').count(),3);
  for(const theme of ['light','dark']){
   await page.evaluate(theme=>document.documentElement.dataset.theme=theme,theme);
   for(let i=0;i<3;i++){
    await page.locator(`[data-usage-page="${i}"]`).click();
    await page.waitForFunction(i=>document.querySelector(`[data-usage-page="${i}"]`).hasAttribute('aria-current'),i);
    assert.ok(await page.locator('.usage-board').evaluate(el=>el.scrollHeight<=el.clientHeight+1));
    await shot('usage-pages-'+theme+'-'+i);
   }
  }
  assert.equal(await page.locator('.usage-log-entry').count(),40);
  assert.ok(await page.locator('.usage-log-entry > summary').first().evaluate(el=>el.offsetHeight<=48));
  await page.locator('.usage-log-entry > summary').first().click();
  assert.equal(await page.locator('.usage-log-entry[open]').count(),1);
  await page.locator('[data-usage-page="0"]').click();await page.waitForTimeout(200);
  await pages.hover();await page.mouse.wheel(390,0);
  await page.waitForFunction(()=>document.querySelector('[data-usage-page="1"]').hasAttribute('aria-current'));
  await page.keyboard.press('Escape');assert.equal(await page.locator('#usage-board-overlay').isVisible(),false);
  assert.deepEqual(errors,[]);console.log('Passed usage pages, horizontal scroll, light/dark and fixed board height.');return;
 }
 if(process.env.ASH_PHONE_MEMORY_RETRIEVAL_ONLY){
  await page.evaluate(()=>switchSection('recall'));
  await page.locator('#memory-weight-keyword').waitFor({state:'attached'});
  assert.equal(await page.locator('#section-standing #memory-retrieval').count(),0);
  assert.equal(await page.locator('#section-recall #memory-retrieval').count(),1);
  await page.locator('#memory-query').fill('海边');await page.locator('#memory-search-button').click();
  await page.locator('.memory-search-result').waitFor();
  assert.equal(await page.locator('.memory-search-result script').count(),0);
  assert.match(await page.locator('.memory-search-result').innerText(),/<script>不执行<\/script>/);
  await page.locator('#memory-injection-preview button').click();
  await page.locator('#recall-detail-dialog').waitFor();
  assert.match(await page.locator('.recall-dialog-content').innerText(),/<system_info>/);
  await page.locator('#recall-detail-dialog button[aria-label=关闭]').click();
  assert.equal(await page.locator('#section-recall details').count(),0);
  await page.locator('.memory-detail-button').click();
  await page.locator('#recall-detail-dialog').waitFor();
  const rankingBox=await page.locator('#recall-detail-dialog').boundingBox();
  const rankingViewport=page.viewportSize();
  assert.ok(Math.abs(rankingBox.y+rankingBox.height/2-rankingViewport.height/2)<2,'ranking dialog centers vertically');
  assert.ok(Math.abs(rankingBox.x+rankingBox.width/2-rankingViewport.width/2)<2,'ranking dialog centers horizontally');
  await page.locator('#recall-detail-dialog button[aria-label=关闭]').click();
  const useless=page.locator('.memory-feedback [data-feedback=useless]');
  await useless.click();await page.locator('.memory-feedback [data-feedback=useless][aria-pressed=true]').waitFor();
  assert.equal(await useless.getAttribute('aria-pressed'),'true');
  assert.equal(writes.find(w=>w.path.endsWith('/feedback')).data.query,'海边');
  await useless.click();await page.locator('.memory-feedback span').filter({hasText:'已撤销'}).waitFor();
  assert.equal(await useless.getAttribute('aria-pressed'),'false');
  assert.equal(writes.filter(w=>w.path.endsWith('/feedback')).at(-1).data.value,'reset');
  await page.evaluate(()=>showRecallPanel('weights'));
  await page.locator('#memory-weight-keyword').fill('0.8');
  await page.evaluate(()=>showRecallPanel('search'));
  await page.locator('#memory-search-button').click();
  await page.locator('.memory-search-result').waitFor();
  assert.equal(writes.filter(w=>w.path.endsWith('/preview')).at(-1).data.weights.keyword,.8);
  assert.equal(writes.filter(w=>w.path==='/api/memories/retrieval').length,0);
  await page.evaluate(()=>showRecallPanel('weights'));
  await page.locator('#memory-weights-save').click();
  await page.evaluate(()=>showRecallPanel('search'));
  await page.locator('#memory-search-status').filter({hasText:'权重已保存'}).waitFor();
  assert.equal(writes.find(w=>w.path==='/api/memories/retrieval').data.weights.keyword,.8);
  await page.evaluate(()=>showRecallPanel('search'));
  for(const width of [320,390])for(const theme of ['light','dark']){
   await page.setViewportSize({width,height:844});await page.evaluate(theme=>AshTheme.setTheme(theme),theme);
   await noOverflow();await shot('memory-retrieval-'+theme+'-'+width);
  }
  assert.deepEqual(errors,[]);console.log('Passed memories search, escaped originals, draft/save weights and narrow light/dark layout.');return;
 }
 if(process.env.ASH_PHONE_MONTHLY_ONLY){
  await page.locator('#phone-pages [data-phone-app=diary]').click();
  await page.locator('.diary-entry').nth(1).waitFor();
  const card=page.locator('#diary-calendar-flipper');
  // The center remains scrollable; only edge grips own vertical gestures.
  assert.equal(await card.evaluate(el=>getComputedStyle(el).touchAction),'pan-y');
  assert.equal(await page.locator('.diary-card-grip-left').evaluate(el=>getComputedStyle(el).touchAction),'none');
  const edgeBox=await page.locator('.diary-card-grip-left').boundingBox();
  assert(edgeBox.width<=18,'edge grip must not cover the scrollable middle');
  for(const [dx,dy] of [[0,150],[0,-150],[110,110]]){
   const r=await card.boundingBox(),sx=r.x+7,sy=r.y+r.height*.5;
   await page.mouse.move(sx,sy);await page.mouse.down();
   await page.mouse.move(sx+dx,sy+dy,{steps:8});
   assert.match(await card.evaluate(el=>el.style.transform),/rotateX/,'edge drag tilts both axes');
   await page.mouse.up();
   assert.equal(await page.evaluate(()=>diaryMonthFlipped),true,'edge flick flips in any direction');
   await page.evaluate(()=>flipDiaryMonth(false,0));await page.waitForTimeout(350);
  }
  const box=await card.boundingBox();
  const x=box.x+box.width*.8,y=box.y+box.height*.55;
  const original=await page.evaluate(()=>diaryNotebookDay);
  await page.mouse.move(x,y);await page.mouse.down();await page.mouse.move(x-box.width*.12,y,{steps:4});
  const partial=await card.evaluate(el=>el.style.transform);
  assert.ok(partial.includes('rotateY('),'drag continuously rotates card');
  await page.mouse.move(x-box.width*.65,y,{steps:6});await page.mouse.up();
  await page.locator('#diary-month-content').filter({hasText:'十月，我记下了'}).waitFor();
  assert.equal(await page.evaluate(()=>diaryMonthFlipped),true);
  assert.equal(await page.evaluate(()=>diaryNotebookDay),original,'drag must not select a date');
  await page.waitForTimeout(350);
  assert.ok(await page.locator('#diary-month-content').evaluate(el=>el.scrollHeight>el.clientHeight),'long summary scrolls within its face');
  await shot('diary-monthly-back');
  await card.focus();await page.keyboard.press('Enter');await page.waitForTimeout(350);
  assert.equal(await page.evaluate(()=>diaryMonthFlipped),false);
  assert.ok(Math.abs((await card.boundingBox()).height-box.height)<2,'calendar returns to original height after long summary');
  await shot('diary-monthly-front-restored');
  if(process.env.ASH_BROWSER!=='webkit'){
  const touch=await context.newCDPSession(page);
  await touch.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x,y}]});
  for(let step=1;step<=8;step++)await touch.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:x-box.width*.65*step/8,y}]});
  await touch.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});
  assert.equal(await page.evaluate(()=>diaryMonthFlipped),true,'finger drag flips card');
  await page.waitForTimeout(350);
  await card.focus();await page.keyboard.press('Enter');await page.waitForTimeout(350);
  }
  await card.evaluate(el=>el.blur());
  for(const width of [320,390])for(const theme of ['light','dark']){
   await page.setViewportSize({width,height:844});
   await page.evaluate(theme=>AshTheme.setTheme(theme),theme);
   await noOverflow();await shot('diary-paper-'+theme+'-'+width);
  }
  await page.evaluate(()=>AshTheme.setTheme('light'));
  await page.locator('#diary-notebook-manage-toggle').click();
  await page.locator('#long-term-select-toggle').click();
  assert.equal(await page.locator('.long-term-memory-checkbox').count(),0);
  const row=page.locator('.long-term-memory-card').first();
  await row.locator('.long-term-memory-main').click();
  assert.equal(await row.locator('.long-term-memory-main').getAttribute('aria-pressed'),'true');
  assert.ok((await row.getAttribute('class')).includes('is-selected'));
  await shot('diary-selection-shade');
  assert.deepEqual(errors,[]);console.log('Passed monthly card drag, no accidental date click, keyboard flip, saved summary and shade selection.');return;
 }
 if(process.env.ASH_PHONE_STRUCTURE_ONLY){
  const view=name=>page.waitForFunction(name=>document.body.dataset.phoneView===name,name);
  assert.equal(await page.locator('#phone-home [data-phone-app=presets],[data-phone-launch=presets]').count(),0);
  assert.equal(await page.evaluate(()=>Object.hasOwn(AshDesktopConfig.apps,'presets')),false);
  await page.locator('#phone-pages [data-phone-app=standing]').click();await view('standing');
  await page.locator('#archive-tab-fixed').click();
  await page.locator('#standing-active-list .stand').first().waitFor();
  assert.equal(await page.locator('#section-standing #diary-notebook,.diary-stack-trigger').count(),0);
  await gotoHome();await page.locator('#phone-pages [data-phone-app=diary]').click();await view('diary');
  await page.locator('.diary-entry').nth(1).waitFor();
  assert.equal(await page.locator('.diary-entry[open]').count(),0);
  assert.deepEqual(diaryReads,[],'folded diaries do not fetch full text');
  await shot('diary-title-cards');
  await page.locator('.diary-entry > summary').first().click();
  await page.locator('.diary-reading-content').filter({hasText:'这一页只属于日记。'}).waitFor();
  assert.deepEqual(diaryReads,[8]);
  await page.locator('.diary-entry > summary').first().click();
  await page.locator('.diary-entry > summary').first().click();
  assert.deepEqual(diaryReads,[8],'reopening a loaded card reuses its text');
  await page.locator('.diary-entry > summary').nth(1).click();
  await page.locator('.diary-reading-content').filter({hasText:'第二篇正文'}).waitFor();
  assert.deepEqual(diaryReads,[8,9]);
  assert.equal(await page.locator('.diary-notebook-backdrop,.diary-notebook-modal').count(),0);
  assert.equal(await page.locator('.diary-notebook-content').getAttribute('role'),'region');
  for(const width of [320,390,768])for(const theme of ['light','dark']){
   await page.setViewportSize({width,height:844});await page.evaluate(theme=>AshTheme.setTheme(theme),theme);
   assert.equal(await page.locator('.diary-calendar-day.has-diary').count(),1);
   assert.equal(await page.locator('.diary-calendar-keywords').count(),0);
   const colors=await page.locator('.diary-entry').first().evaluate(el=>{
    const style=getComputedStyle(el);return {paper:style.backgroundColor,text:getComputedStyle(el.querySelector('.diary-reading-content')).color};
   });
   for(const color of Object.values(colors)){const rgb=color.match(/[\d.]+/g).slice(0,3).map(Number);assert.ok(Math.max(...rgb)-Math.min(...rgb)<=2,'neutral notebook surfaces: '+color);}
   await shot('diary-'+theme+'-'+width);await noOverflow();
  }
  await page.setViewportSize({width:390,height:844});await page.evaluate(()=>AshTheme.setTheme('light'));
  assert.equal(await page.getByRole('button',{name:/上个月|下个月/}).count(),0);
  await page.locator('#diary-calendar-month-picker').fill('2026-11');
  await page.locator('#diary-calendar-month-picker').dispatchEvent('change');
  assert.equal(await page.locator('.diary-empty').innerText(),'暂无日记');
  await page.locator('#diary-calendar-month-picker').fill('2026-10');
  await page.locator('#diary-calendar-month-picker').dispatchEvent('change');
  assert.equal(await page.locator('.diary-entry[open]').count(),0);
  await page.locator('.diary-entry > summary').first().click();
  await page.locator('.diary-reading-content').filter({hasText:'这一页只属于日记。'}).waitFor();
  await page.getByRole('button',{name:'写日记',exact:true}).first().click();await page.locator('#long-term-memory-editor-modal.open').waitFor();
  await page.locator('#long-term-memory-editor-modal').getByRole('button',{name:'取消',exact:true}).click();
  assert.equal(await page.locator('#section-diary.active').count(),1);
  await page.locator('#diary-notebook-manage-toggle').click();await page.locator('#standing-view-long-term:not([hidden])').waitFor();
  await page.locator('#long-term-list').filter({hasText:'独立日记'}).waitFor();
  await page.locator('#phone-back').click();await view('home');
  await page.locator('.phone-dock [data-phone-launch=preferences]').click();await view('preferences');
  await page.locator('#section-preferences [data-phone-app=presets]').click();await view('presets');
  await page.locator('#phone-back').click();await view('preferences');await gotoHome();
  const old=await page.evaluate(()=>AshDesktop.get());
  old.pages=old.pages.map(items=>items.map(id=>id==='diary'?'presets':id));old.positions.presets=old.positions.diary;delete old.positions.diary;
  old.icons.presets='data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jN1EAAAAASUVORK5CYII=';
  await page.evaluate(value=>AshDesktop.restore(value),old);
  const migrated=await page.evaluate(()=>AshDesktop.get());
  assert.deepEqual(migrated.positions.diary,old.positions.presets);
  assert.equal(migrated.pages.flat().includes('presets'),false);assert.equal(migrated.pages.flat().includes('diary'),true);
  assert.ok(migrated.icons.diary);assert.deepEqual(migrated.positions.standing,old.positions.standing);
  await page.reload();await page.evaluate(()=>merlePhoneApps.whenReady());
  assert.equal(await page.locator('#phone-pages [data-phone-app=diary]').count(),1);
  assert.equal(writes.length,0,'navigation and desktop migration never rewrite memory, diaries or provider data');
  assert.deepEqual(errors,[]);console.log('Passed separate diary/memory apps, settings-only prompts, diary reading/editing/management and preserving desktop positions/images.');return;
 }
 if(process.env.ASH_PHONE_EDGE_ONLY){
  const cdp=await context.newCDPSession(page);
  const touch=(type,x,y)=>cdp.send('Input.dispatchTouchEvent',{type,touchPoints:type==='touchEnd'||type==='touchCancel'?[]:[{x,y}]});
  const drag=async(x,y,endX,endY)=>{
   await touch('touchStart',x,y);
   for(let i=1;i<=6;i++)await touch('touchMove',x+(endX-x)*i/6,y+(endY-y)*i/6);
   await touch('touchEnd');
  };
  const homeHistory=await page.evaluate(()=>JSON.stringify(history.state));
  await page.evaluate(()=>{window.edgeStarts=[];document.addEventListener('touchstart',e=>edgeStarts.push({x:e.touches[0]?.clientX,prevented:e.defaultPrevented}),{passive:true});});
  const pagesBox=await page.locator('#phone-pages').boundingBox(),y=pagesBox.y+pagesBox.height*.6;
  await drag(389,y,160,y);await page.locator('#phone-page-dots [data-page="1"][aria-current=page]').waitFor();
  await drag(1,y,230,y);await page.locator('#phone-page-dots [data-page="0"][aria-current=page]').waitFor();
  assert.equal(await page.evaluate(()=>JSON.stringify(history.state)),homeHistory,'edge paging never traverses app history');
  const initial=await page.evaluate(()=>AshDesktop.get()),tall=structuredClone(initial);tall.positions.diary={row:12,col:3};
  await page.evaluate(value=>AshDesktop.restore(value),tall);
  const desktop=page.locator('.phone-desktop-page').first();
  await drag(1,y,1,y-170);assert.ok(await desktop.evaluate(el=>el.scrollTop)>60,'edge vertical drag still scrolls the desktop');
  await drag(389,y,389,y-100);assert.ok(await desktop.evaluate(el=>el.scrollTop)>150);
  await page.evaluate(value=>AshDesktop.restore(value),initial);
  await page.locator('.phone-dock [data-phone-launch=preferences]').click();
  const settingsHistory=await page.evaluate(()=>JSON.stringify(history.state));
  await drag(1,240,150,240);await drag(389,240,240,240);
  assert.equal(await page.evaluate(()=>JSON.stringify(history.state)),settingsHistory,'edge swipes do not reveal the previous app');
  assert.equal(await page.locator('#section-preferences.active').count(),1);
  const backBox=await page.locator('#phone-back').boundingBox();
  await touch('touchStart',18,backBox.y+backBox.height/2);await touch('touchEnd');await page.locator('#section-home.active').waitFor();
  await page.locator('.phone-dock [data-phone-launch=preferences]').click();await page.locator('[data-phone-app=settings]').click();
  const content=page.locator('.main-content'),headerY=(await page.locator('#phone-app-header').boundingBox()).y;
  await drag(1,650,1,340);assert.ok(await content.evaluate(el=>el.scrollTop)>60,'edge drag scrolls the app form');
  assert.equal((await page.locator('#phone-app-header').boundingBox()).y,headerY);
  await gotoHome();
  messages.set(1,Array.from({length:35},(_,i)=>({id:100+i,role:i%2?'assistant':'user',content:'边缘手势回归 '+i+'：只滚动当前聊天，保留当前页面。\n\n第二段。'})));
  await page.locator('#phone-pages [data-phone-app=chat]').click();await page.locator('#phone-open-chat').click();
  const detail=page.frameLocator('#conversation-detail-frame');await detail.locator('#sendBtn:not([disabled])').waitFor();
  await detail.locator('body').evaluate(()=>{window.edgeStarts=[];document.addEventListener('touchstart',e=>edgeStarts.push({x:e.touches[0]?.clientX,prevented:e.defaultPrevented}),{passive:true});});
  const area=detail.locator('#msgArea');await area.evaluate(el=>el.scrollTop=0);
  const box=await area.boundingBox(),chatHistory=await page.evaluate(()=>JSON.stringify(history.state));
  const composerBox=await detail.locator('#composer').boundingBox();
  await drag(1,composerBox.y-30,1,box.y+180);
  assert.ok(await area.evaluate(el=>el.scrollTop)>80,'edge scroll works inside the conversation iframe: '+JSON.stringify(await area.evaluate(el=>({top:el.scrollTop,height:el.clientHeight,total:el.scrollHeight,overflow:getComputedStyle(el).overflowY,box:el.getBoundingClientRect().toJSON(),starts:edgeStarts}))));
  await drag(389,box.y+120,220,box.y+120);
  assert.equal(await page.evaluate(()=>JSON.stringify(history.state)),chatHistory);
  await touch('touchStart',195,box.y+100);await touch('touchEnd');
  const starts=await detail.locator('body').evaluate(()=>edgeStarts);
  assert.equal(starts.find(e=>e.x<=20)?.prevented,false);assert.equal(starts.find(e=>e.x>=370)?.prevented,false);
  assert.equal(starts.at(-1).prevented,false,'center touches retain native behavior');
  const parentStarts=await page.evaluate(()=>edgeStarts);
  assert.equal(parentStarts.find(e=>e.x<=20)?.prevented,false);assert.equal(parentStarts.find(e=>e.x>=370)?.prevented,false);
  assert.equal(await page.evaluate(()=>scrollY),0);assert.deepEqual(errors,[]);
  console.log('Passed native edge touches, desktop paging, native scrolling, edge taps, chat scrolling and unchanged app history.');return;
 }
 if(process.env.ASH_PHONE_APPEARANCE_ONLY||process.env.ASH_PHONE_PAPER_ONLY){
  const original=await page.evaluate(()=>AshDesktop.get());
  const independent=async()=>{
   const result=await page.evaluate(()=>{
    const links=[...document.querySelectorAll('link[rel=stylesheet]')].filter(el=>/\/(dashboard|night|memory-letter|memory-notebook|presets-paper|heartbeat-coffee|transfer-paper|usage-paper)\.css/.test(el.href));
    const nodes=[...document.querySelectorAll('body,.dashboard,.main-content,.phone-app-header,.phone-home,.phone-primary-button,.phone-settings-page .btn,.phone-settings-page .control-input,.phone-sheet')].filter(el=>!el.closest('.phone-paper-app'));
    const props=['color','backgroundColor','backgroundImage','fontFamily','fontSize','borderRadius','boxShadow','transform','padding','margin','position','display'];
    const snapshot=()=>nodes.map(el=>{const s=getComputedStyle(el);return props.map(prop=>s[prop]);});
    const before=snapshot();links.forEach(el=>el.disabled=true);const withoutPaper=snapshot();links.forEach(el=>el.disabled=false);
    return {before,withoutPaper,paperToken:getComputedStyle(document.body).getPropertyValue('--paper-base')};
   });
   assert.deepEqual(result.before,result.withoutPaper,'phone components render identically with every old paper stylesheet disabled');
   assert.equal(result.paperToken.trim(),'','paper tokens never reach the phone shell');
  };
  const readable=async(button,backgroundSelector=null)=>{
   await button.waitFor({state:'visible'});
   const colors=await button.evaluate((el,backgroundSelector)=>{const s=getComputedStyle(el);return {bg:getComputedStyle(backgroundSelector?el.closest(backgroundSelector):el).backgroundColor,ink:s.color,opacity:s.opacity};},backgroundSelector);
   const rgba=value=>value.match(/[\d.]+/g).map(Number);
   const bg=rgba(colors.bg),ink=rgba(colors.ink);
   assert.ok(bg.length<4||bg[3]>.95,'save button has a solid background: '+JSON.stringify(colors));
   const luminance=rgb=>rgb.slice(0,3).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4;}).reduce((sum,v,i)=>sum+v*[.2126,.7152,.0722][i],0);
   const a=luminance(bg),b=luminance(ink);
   assert.ok((Math.max(a,b)+.05)/(Math.min(a,b)+.05)>=4.5,'save button text is readable: '+JSON.stringify(colors));
  };
  for(const width of process.env.ASH_PHONE_PAPER_ONLY?[]:[320,390,768])for(const theme of ['light','dark']){
   await page.setViewportSize({width,height:844});
   await page.evaluate(theme=>AshTheme.setTheme(theme),theme);
   await page.evaluate(()=>AshDesktop.customize('presets'));
   assert.equal(await page.locator('[data-phone-tab=presets],#phone-theme-dialog,[data-theme-save]').count(),0);
   assert.equal(await page.locator('[data-phone-tab=wallpaper]').getAttribute('aria-current'),'page','removed theme deep links open wallpaper');
   await page.locator('[data-phone-tab=widgets]').click();await page.locator('[data-widget-type=note] > summary').click();await page.locator('[data-add-widget=note]').click();
   await readable(page.locator('#phone-widget-form [type=submit]'));
   await independent();
   await page.locator('#phone-widget-form [name=text]').fill('保存按钮清晰可见');
   if(width===390)await shot('widget-save-'+theme);
   await page.locator('#phone-widget-form [type=submit]').click();
   await page.locator('#phone-customize').waitFor({state:'hidden'});
   assert.ok(await page.evaluate(()=>Object.values(AshDesktop.get().widgets).some(w=>w.text==='保存按钮清晰可见')));
   await page.locator('.phone-pair [data-phone-profile=user]').click();
   await page.locator('#phone-avatar-menu:popover-open').waitFor();
   assert.equal(await page.locator('#phone-profile-form').count(),0);
   await independent();
   const bounds=await page.locator('#phone-avatar-menu').boundingBox();
   assert.ok(bounds.x>=0&&bounds.x+bounds.width<=width,'avatar menu fits the screen');
   await noOverflow();if(width===390)await shot('avatar-menu-'+theme);
   await page.keyboard.press('Escape');
   await page.evaluate(value=>AshDesktop.restore(value),original);
   await page.locator('.phone-dock [data-phone-launch=preferences]').click();
   await page.locator('#phone-supplier-settings').click();await page.locator('[data-phone-app=supplier-route]').click();
   await readable(page.locator('#api-configuration-form [type=submit]'));
   await readable(page.locator('#api-preset-form [type=submit]'));
   await independent();
   if(width===390)await shot('settings-save-'+theme);
   for(const name of ['supplier-openai','supplier-anthropic','recall','settings']){
    await page.evaluate(name=>switchSection(name),name);
    await page.locator('#section-'+name+'.active').waitFor();
    if(name.startsWith('supplier-')&&!await page.locator('#section-'+name+' .provider-create-form').isVisible())await page.locator('#phone-supplier-add').click();
    await independent();await noOverflow();
    const save=page.locator('#section-'+name+' .btn-primary').last();
    if(await save.count())await readable(save);
   }
   await gotoHome();
  }
  await page.setViewportSize({width:390,height:844});
  for(const theme of ['light','dark']){
   await page.evaluate(theme=>AshTheme.setTheme(theme),theme);
   for(const name of ['standing','heartbeats','presets','import','export']){
    await page.evaluate(name=>switchSection(name),name);await page.locator('#section-'+name+'.active').waitFor();
    assert.equal(await page.locator('.memory-editor-modal:not(.open)').first().isVisible(),false,'closed paper editors stay hidden outside the memory page');
    await independent();await noOverflow();await shot('scoped-'+name+'-'+theme);
    if(name==='standing'){
     await page.evaluate(()=>openStandingMemoryEditor());await page.locator('#memory-editor-modal.open').waitFor({state:'visible'});
     await page.locator('#memory-editor-save').waitFor({state:'visible'});await shot('scoped-memory-editor-'+theme);
     await page.evaluate(()=>closeStandingMemoryEditor());
    }
    if(name==='heartbeats')await readable(page.locator('.coffee-recipe h2'),'.coffee-recipe');
   }
   await page.evaluate(()=>openUsageBoard());await page.locator('#usage-board-overlay:not([hidden])').waitFor({state:'visible'});
   assert.equal(await page.locator('#usage-board-overlay').evaluate(el=>el.classList.contains('phone-paper-app')),true);
   await noOverflow();await shot('scoped-usage-'+theme);await page.locator('.usage-board-close').click();
  }
  assert.deepEqual(errors,[]);console.log('Passed removed theme page, widget saving, readable save buttons and centered dialogs at 320/390/768px in light/dark modes.');return;
 }
 if(process.env.ASH_PHONE_SHOWCASE_ONLY){
  await page.locator('#phone-pages [data-phone-app=chat]').click();await page.locator('#phone-open-chat').click();
  await page.frameLocator('#conversation-detail-frame').locator('#sendBtn:not([disabled])').waitFor();await shot('merle-chat-390');
  assert.deepEqual(errors,[]);console.log('Native Merle desktop and Ash chat rendered.');return;
 }
 if(process.env.ASH_PHONE_OTHER_SETTINGS_ONLY){
  Object.assign(modelSettings,{handoff_model:'compact-model',temporary_summary_model:'temporary-model',diary_keyword_model:'keyword-model',diary_merge_model:'merge-model'});
  await page.evaluate(()=>switchSection('settings'));
  await page.waitForFunction(()=>document.getElementById('historyTitleModel').value==='saved-title');
  assert.equal(await page.locator('#phone-app-title').innerText(),'其它');
  assert.equal(await page.locator('.other-model-task').count(),5);
  assert.equal(await page.locator('.other-model-task[open]').count(),0);
  for(const width of [320,390,768])for(const theme of ['light','dark']){
   await page.setViewportSize({width,height:844});await page.evaluate(theme=>AshTheme.setTheme(theme),theme);
   await noOverflow();await shot('other-settings-'+theme+'-'+width);
  }
  await page.locator('.other-model-task > summary').first().click();
  await page.locator('#historyTitleModel').fill('new-title');
  await page.locator('.conversation-generation-panel').getByRole('button',{name:'保存',exact:true}).click();
  await page.locator('#conversation-model-settings-msg').filter({hasText:'已保存'}).waitFor();
  assert.equal(modelSettings.title_model,'new-title');assert.equal(modelSettings.diary_merge_model,'merge-model');
  assert.equal(modelSettings.embedding_model,'saved-embedding');
  await page.locator('.other-model-task > summary').nth(3).click();
  await page.locator('#diaryKeywordModel').fill('new-keywords');
  await page.locator('.conversation-generation-panel').getByRole('button',{name:'保存',exact:true}).click();
  await page.locator('#conversation-model-settings-msg').filter({hasText:'已保存'}).waitFor();
  assert.equal(modelSettings.diary_keyword_model,'new-keywords');assert.equal(modelSettings.handoff_model,'compact-model');
  await page.locator('.other-ocr-settings').getByRole('button',{name:'保存',exact:true}).click();
  await page.locator('#ocr-settings-msg').filter({hasText:'已保存'}).waitFor();
  assert.equal(ocrSettings.api_key,'saved-ocr-key');
  await page.locator('#ocrClearKey').click();
  await page.locator('.other-ocr-settings').getByRole('button',{name:'保存',exact:true}).click();
  await page.locator('#ocr-settings-msg').filter({hasText:'已保存'}).waitFor();
  assert.equal(ocrSettings.api_key,'');assert.equal(ocrSettings.model,'ocr-model');
  assert.deepEqual(errors,[]);console.log('Passed grouped other settings, preserved model configuration, recall isolation, OCR credential retention/clearing and responsive light/dark layouts.');return;
 }
 if(process.env.ASH_PHONE_GALLERY_ONLY){
  const upload=async color=>{
   const encoded=await page.evaluate(color=>{const canvas=document.createElement('canvas');canvas.width=160;canvas.height=240;const ctx=canvas.getContext('2d');ctx.fillStyle=color;ctx.fillRect(0,0,160,240);return canvas.toDataURL('image/png').split(',')[1];},color);
   await page.locator('[data-upload=wallpaper]').setInputFiles({name:'wallpaper.png',mimeType:'image/png',buffer:Buffer.from(encoded,'base64')});
  };
  await page.evaluate(()=>AshDesktop.customize('wallpaper'));
  await upload('#b5aaa0');await page.waitForFunction(()=>AshDesktop.get().wallpapers.length===1);
  const first=await page.evaluate(()=>AshDesktop.get().wallpaperImage);
  await upload('#8498a5');await page.waitForFunction(()=>AshDesktop.get().wallpapers.length===2);
  const second=await page.evaluate(()=>AshDesktop.get().wallpaperImage);
  assert.notEqual(first,second);
  assert.deepEqual(await page.evaluate(()=>[...merlePhoneMedia.references(AshDesktop.get())]),[second,first]);
  await page.locator('[data-wallpaper-image="0"]').click();
  assert.equal(await page.evaluate(()=>AshDesktop.get().wallpaperImage),first);
  await page.locator('[data-appearance-setting=ink][data-value=dark]').click();
  await page.locator('[data-appearance-setting=mode][data-value=light]').click();
  assert.equal(await page.evaluate(()=>AshDesktop.get().ink),'dark');
  await page.locator('#btn-phone-customize-preview').click();
  assert.equal(await page.locator('#phone-customize').evaluate(el=>el.classList.contains('is-previewing')),true);
  await page.locator('#btn-phone-customize-preview').click();
  for(const width of [320,390,768])for(const theme of ['light','dark']){
   await page.setViewportSize({width,height:844});await page.evaluate(theme=>AshTheme.setTheme(theme),theme);
   await noOverflow();await shot('wallpaper-gallery-'+theme+'-'+width);
  }
  const backup=await page.evaluate(()=>AshDesktop.export());
  assert.equal(backup.wallpapers.length,2);assert.ok(backup.wallpapers.every(image=>image.startsWith('data:image/')));
  await page.reload();await page.waitForFunction(()=>window.AshDesktop);await page.evaluate(()=>merlePhoneApps.whenReady());
  assert.equal(await page.evaluate(()=>AshDesktop.get().wallpapers.length),2);
  await page.evaluate(()=>AshDesktop.customize('wallpaper'));
  assert.equal(await page.locator('.phone-wallpaper-select img').evaluateAll(images=>images.every(image=>image.complete&&image.naturalWidth>0)),true);
  await page.locator('[data-delete-wallpaper="1"]').click();
  assert.equal(await page.evaluate(()=>AshDesktop.get().wallpaperImage),first,'removing another wallpaper preserves the active one');
  await page.locator('[data-delete-wallpaper="0"]').click();
  assert.equal(await page.evaluate(()=>AshDesktop.get().wallpaperImage),'');
  const legacyWallpaper=structuredClone(backup);delete legacyWallpaper.wallpapers;
  await page.evaluate(backup=>AshDesktop.restore(backup),legacyWallpaper);
  assert.equal(await page.evaluate(()=>AshDesktop.get().wallpapers.length),1,'older backups keep their selected wallpaper in the new library');
  await page.evaluate(backup=>AshDesktop.restore(backup),backup);await page.evaluate(()=>AshDesktop.customize('wallpaper'));
  assert.equal(await page.locator('.phone-wallpaper-card').count(),2);
  await page.locator('[data-delete-wallpaper="0"]').click();
  assert.equal(await page.evaluate(()=>AshDesktop.get().wallpaperImage),second,'removing the active wallpaper selects the remaining one');
  await page.locator('[data-phone-tab=widgets]').click();
  assert.equal(await page.locator('.phone-widget-choice').count(),6);
  assert.equal(await page.locator('.phone-widget-choice[open]').count(),0);
  assert.equal(await page.locator('.phone-widget-list').count(),0);
  await page.locator('[data-widget-type=photo] > summary').click();
  await page.locator('[data-widget-type=photo] [data-widget-size=square]').click();
  for(const width of [320,390,768])for(const theme of ['light','dark']){
   await page.setViewportSize({width,height:844});await page.evaluate(theme=>AshTheme.setTheme(theme),theme);
   await noOverflow();await shot('widget-catalog-'+theme+'-'+width);
  }
  await page.locator('[data-add-widget=photo]').click();
  assert.equal(await page.locator('#phone-widget-form [name=size]').inputValue(),'square');
  await page.locator('#phone-widget-form [name=title]').fill('方形照片');
  await page.locator('#phone-widget-form [type=submit]').click();await page.locator('#phone-customize').waitFor({state:'hidden'});
  const added=await page.evaluate(()=>Object.entries(AshDesktop.get().widgets).find(([,w])=>w.title==='方形照片'));
  assert.equal(added[1].size,'square');
  await page.evaluate(()=>AshDesktop.customize('widgets'));
  assert.equal(await page.locator('.phone-widget-list').count(),0);
  assert.equal(await page.locator('#phone-customize-content').getByText('已添加',{exact:true}).count(),0);
  assert.deepEqual(errors,[]);console.log('Passed local wallpaper library persistence, switching, removal, backup/restore, desktop preview and widget size selection without an added-widget list.');return;
 }
 if(process.env.ASH_PHONE_PROMPT_LAYOUT_ONLY){
  await page.evaluate(()=>switchSection('presets'));
  const editor=page.frameLocator('#prompt-console-frame');
  await editor.locator('.section-card').nth(1).waitFor();
  assert.deepEqual(await editor.locator('.section-key').allTextContents(),['Identity','Interaction']);
  assert.equal(await page.locator('.identity-explanation').count(),0);
  assert.equal(await editor.locator('.section-body.open').count(),0);
  await page.locator('#identityUserName').fill('用户名字');await page.locator('#identityAssistantName').fill('助手名字');
  await page.getByRole('button',{name:'保存预设',exact:true}).click();
  await page.locator('#identity-presets-msg').filter({hasText:'人物预设已保存'}).waitFor();
  assert.equal(identityPresets.assistant_name,'助手名字');
  for(const width of [320,390,768])for(const theme of ['light','dark']){
   await page.setViewportSize({width,height:844});await page.evaluate(theme=>AshTheme.setTheme(theme),theme);
   await editor.locator('html').evaluate((el,theme)=>{el.dataset.theme=theme;},theme);
   await noOverflow();assert.equal(await editor.locator('html').evaluate(el=>el.scrollWidth<=innerWidth+1),true);
   await shot('prompt-layout-'+theme+'-'+width);
  }
  await editor.getByRole('button',{name:'Edit Identity',exact:true}).click();
  await editor.locator('#textarea-Identity').fill('Updated original English block.');
  await editor.getByRole('button',{name:'Save',exact:true}).click();
  await editor.locator('#save-status-Identity').filter({hasText:'已保存'}).waitFor();
  assert.equal(promptSections[0].content,'Updated original English block.');
  assert.match(await editor.locator('.section-card').first().locator('.section-meta').innerText(),/P100/);
  await editor.getByRole('button',{name:'完整预览',exact:true}).click();
  await editor.locator('#preview-content').filter({hasText:'Updated original English block.'}).waitFor();
  await editor.getByRole('button',{name:'修改日志',exact:true}).click();await editor.locator('#logs-list .empty').waitFor();
  assert.deepEqual(errors,[]);console.log('Passed grouped name presets, original English block names, direct editing/saving, preview/logs and responsive light/dark layouts.');return;
 }
 if(process.env.ASH_PHONE_PROVIDERS_ONLY){
  for(const family of ['openai','anthropic']){
   await page.evaluate(family=>switchSection('supplier-'+family),family);
   const list=page.locator('#'+family+'-provider-list');
   await list.locator('details').nth(2).waitFor();
   assert.equal(await list.locator('details[open]').count(),0);
   assert.equal(await page.locator('#section-supplier-'+family+' .heartbeat-settings-head').count(),0);
   const entry=list.locator('details').nth(1);
   await entry.locator('summary').click();
   assert.equal(await entry.locator('.provider-editor').isVisible(),false);
   await entry.getByRole('button',{name:'编辑',exact:true}).click();
   await page.locator('#'+family+'ProviderName-2').fill('修改后的备用');
   await entry.getByRole('button',{name:'保存',exact:true}).click();
   await list.locator('summary').filter({hasText:'修改后的备用'}).waitFor();
   assert.equal(supplierProfiles[family][1].api_key,'keep-second-key');
   await entry.locator('summary').click();
   await entry.getByRole('button',{name:'设为活跃',exact:true}).click();
   await entry.locator('.provider-active-mark').waitFor();
   assert.equal(supplierProfiles[family].find(item=>item.is_active).id,2);
   assert.equal(supplierProfiles[family][1].api_key,'keep-second-key');
   await list.locator('details').nth(2).locator('summary').click();
   for(const width of [320,390,768])for(const theme of ['light','dark']){
    await page.setViewportSize({width,height:844});await page.evaluate(theme=>AshTheme.setTheme(theme),theme);
    await noOverflow();await shot('supplier-'+family+'-'+theme+'-'+width);
   }
   await page.setViewportSize({width:390,height:844});
   await page.locator('#phone-supplier-add').click();
   await page.locator('#'+family+'-provider-create:not([hidden])').waitFor();
   await page.locator('#'+family+'ProviderName').fill('新增');
   await page.locator('#'+family+'ProviderUrl').fill('https://new.test/v1');
   await page.locator('#'+family+'ProviderKey').fill('new-key');
   await page.locator('#'+family+'-provider-create').getByRole('button',{name:'添加',exact:true}).click();
   await list.locator('details').nth(3).waitFor();
   assert.equal(supplierProfiles[family][3].name,'新增');
  }
  assert.deepEqual(errors,[]);console.log('Passed supplier disclosure cards, separate editing, preserved keys, activation, header creation and responsive light/dark layouts.');return;
 }
 if(process.env.ASH_PHONE_SUPPLIER_REUSE_ONLY){
  const current=structuredClone(apiSettings);
  await page.evaluate(()=>switchSection('supplier-route'));
  await page.locator('#routeSupplier option[value="anthropic:7"]').waitFor({state:'attached'});
  await page.locator('#routeSupplier').selectOption('anthropic:7');
  assert.equal(await page.locator('#routeApiUrl').inputValue(),savedSuppliers.anthropic.api_url);
  assert.equal(await page.locator('#routeApiKey').inputValue(),'');
  assert.match(await page.locator('#routeApiKey').getAttribute('placeholder'),/已保存/);
  assert.equal(await page.locator('.route-config-group').count(),3);
  assert.equal(await page.locator('#api-configuration-form > .phone-local-note').last().innerText(),'心跳复用最后一次请求配置');
  await page.getByRole('button',{name:'修改密钥',exact:true}).click();
  assert.equal(await page.locator('#routeApiKey').evaluate(el=>el===document.activeElement),true);
  await page.locator('#phone-app-title').click();
  for(const width of [320,390,768])for(const theme of ['light','dark']){
   await page.setViewportSize({width,height:844});await page.evaluate(theme=>AshTheme.setTheme(theme),theme);
   await noOverflow();await shot('chat-configuration-'+theme+'-'+width);
  }
  await page.setViewportSize({width:390,height:844});await page.evaluate(()=>AshTheme.setTheme('light'));
  await page.locator('#route-fetch-models').click();
  await page.locator('#routeModels option[value=preset-model]').waitFor({state:'attached'});
  const discovery=JSON.parse(writes.find(w=>w.path==='/api/api-presets/models').body);
  assert.equal(discovery.source_provider_type,'anthropic');assert.equal(discovery.source_provider_id,7);
  assert.equal(discovery.api_key,'');
  await page.locator('#routeModels').selectOption('preset-model');
  await page.locator('#routeProvider').selectOption('auto');
  await page.locator('#api-preset-name').fill('已有供应商的模型');
  await page.locator('#api-preset-form [type=submit]').click();
  await page.locator('#route-settings-msg').filter({hasText:'预设已保存'}).waitFor();
  assert.equal(apiPresets[0].api_key,savedSuppliers.anthropic.api_key);
  assert.equal(apiPresets[0].provider,'auto');assert.equal(apiPresets[0].model,'preset-model');
  assert.deepEqual(apiSettings,current);
  await page.locator('#api-configuration-form [type=submit]').click();
  await page.locator('#route-settings-msg').filter({hasText:'设置已保存'}).waitFor();
  assert.equal(apiSettings.api_key,savedSuppliers.anthropic.api_key);assert.equal(apiSettings.provider,'auto');
  assert.equal(writes.some(w=>w.path.includes('-providers')),false);
  assert.deepEqual(errors,[]);console.log('Passed saved supplier URL/key reuse for model discovery, model preset saving and applying with the selected route.');return;
 }
 if(process.env.ASH_PHONE_API_ONLY){
  const view=async name=>page.waitForFunction(name=>document.body.dataset.phoneView===name,name);
  const current=structuredClone(apiSettings);
  await page.locator('.phone-dock [data-phone-launch=preferences]').click();await page.locator('#phone-supplier-settings').click();
  await page.locator('[data-phone-app=supplier-route]').click();await view('supplier-route');
  await page.locator('#routeModel').waitFor();
  await page.waitForFunction(()=>document.getElementById('routeModel').value==='test-model');
  assert.equal(writes.length,0);assert.equal(await page.locator('#routeProvider').inputValue(),'openai');
  await page.locator('#routeProvider').selectOption('anthropic');await page.locator('#routeApiUrl').fill('https://night.test/v1');
  await page.locator('#routeApiKey').fill('night-secret');await page.locator('#routeModel').fill('night-model');
  await page.locator('#api-preset-name').fill('夜晚');await page.locator('#api-preset-form [type=submit]').click();
  await page.locator('#route-settings-msg').filter({hasText:'预设已保存'}).waitFor();assert.deepEqual(apiSettings,current);await shot('api-configuration-presets');
  assert.equal(writes.filter(w=>w.path==='/api/route-settings').length,0,'saving a preset never applies it');
  await page.locator('#phone-back').click();await view('suppliers');await page.locator('[data-phone-app=supplier-route]').click();
  await page.waitForFunction(()=>document.getElementById('routeModel').value==='test-model');
  await page.getByRole('button',{name:'填入预设 夜晚'}).click();
  assert.equal(await page.locator('#routeProvider').inputValue(),'anthropic');assert.equal(await page.locator('#routeModel').inputValue(),'night-model');
  assert.equal(await page.locator('#routeApiUrl').inputValue(),'https://night.test/v1');assert.equal(await page.locator('#routeApiKey').inputValue(),'');
  assert.deepEqual(apiSettings,current);assert.equal(writes.filter(w=>w.path==='/api/route-settings').length,0,'loading a preset only fills the form');
  await page.locator('#route-fetch-models').click();await page.locator('#routeModels').waitFor({state:'visible'});
  assert.equal(await page.locator('#routeModels option').count(),3,'all fetched models are selectable despite a different prefilled ID');
  assert.equal(await page.locator('#routeModel').inputValue(),'night-model','fetching does not silently replace the draft model');
  assert.match(await page.locator('#route-models-msg').innerText(),/2 个模型/);
  await shot('api-model-picker');await noOverflow();
  await page.locator('#routeModels').selectOption('second-model');
  assert.equal(await page.locator('#routeModel').inputValue(),'second-model');
  modelFetchError='模型列表接口返回 HTTP 401，请检查 API Key';
  await page.locator('#route-fetch-models').click();await page.locator('#route-models-msg').filter({hasText:'HTTP 401'}).waitFor();
  assert.equal(await page.locator('#routeModels').isVisible(),false,'failed fetch removes stale model choices');
  modelFetchError='';modelFetchResult={data:[]};
  await page.locator('#route-fetch-models').click();await page.locator('#route-models-msg').filter({hasText:'空模型列表'}).waitFor();
  assert.equal(await page.locator('#routeModels').isVisible(),false);
  let releaseModelFetch;modelFetchResult={data:[{id:'stale-model'}]};modelFetchGate=new Promise(resolve=>{releaseModelFetch=resolve;});
  const pendingFetch=page.waitForRequest(request=>request.url().endsWith('/api/api-presets/models'));
  await page.locator('#route-fetch-models').click();await pendingFetch;
  await page.locator('#route-models-msg').filter({hasText:'正在拉取'}).waitFor();
  await page.locator('#routeApiUrl').fill('https://another.test/v1');
  modelFetchGate=null;modelFetchResult={data:[]};
  await page.locator('#route-fetch-models').click();await page.locator('#route-models-msg').filter({hasText:'空模型列表'}).waitFor();
  const oldResponse=page.waitForResponse(response=>response.url().endsWith('/api/api-presets/models'));
  releaseModelFetch();await oldResponse;await page.waitForTimeout(100);
  assert.match(await page.locator('#route-models-msg').innerText(),/空模型列表/,'a late response from the old API cannot overwrite the new result');
  assert.equal(await page.locator('#routeModels').isVisible(),false);
  await page.locator('#routeApiUrl').fill('https://night.test/v1');
  await page.locator('#routeModel').fill('night-model');
  await page.locator('#api-configuration-form [type=submit]').click();await page.locator('#route-settings-msg').filter({hasText:'设置已保存'}).waitFor();
  assert.equal(apiSettings.provider,'anthropic');assert.equal(apiSettings.model,'night-model');assert.equal(apiSettings.api_key,'night-secret');
  assert.equal(writes.some(w=>/providers/.test(w.path)),false,'existing supplier records are not edited');
  await page.getByRole('button',{name:'删除预设 夜晚'}).click();await page.waitForFunction(()=>!document.querySelector('.api-preset-row'));
  assert.equal(apiSettings.model,'night-model','deleting a snapshot does not undo the saved configuration');
  await gotoHome();await page.locator('#phone-pages [data-phone-app=chat]').click();await page.locator('#phone-open-chat').click();
  const detail=page.frameLocator('#conversation-detail-frame');await detail.locator('#sendBtn:not([disabled])').waitFor();
  assert.equal(await detail.locator('#chatModel,#chatRoute,#chatProvider').count(),0,'chat has no model or route selectors');
  assert.equal(await detail.locator('#phone-chat-model').innerText(),'night-model');
  await detail.getByRole('button',{name:'聊天配置',exact:true}).click();await view('supplier-route');
  assert.equal(await page.locator('#phone-back').getAttribute('aria-label'),'返回对话');
  await page.locator('#phone-back').click();await view('detail');await detail.locator('#msgInput').waitFor({state:'visible'});
  assert.deepEqual(errors,[]);await shot('chat-fixed-model');console.log('Passed preset save/fill/apply/delete, route and key snapshots, supplier preservation and simplified chat.');return;
 }
 if(process.env.ASH_PHONE_EXIT_ONLY){
  const waitView=async name=>page.waitForFunction(name=>document.body.dataset.phoneView===name,name,{timeout:1500});
  await page.locator('#phone-pages [data-phone-app=chat]').click();await waitView('chat');
  await page.locator('[data-chat-tab=conversations]').click();await page.locator('[data-conversation-id="2"]').waitFor();
  const parentHistory=await page.evaluate(()=>history.length);
  for(const id of [2,1,2]){
   await page.locator(`[data-conversation-id="${id}"]`).click();
   const frame=page.frameLocator('#conversation-detail-frame');await frame.locator('#msgInput').waitFor();
   assert.equal(await page.evaluate(()=>history.length),parentHistory,'opening conversations never adds browser history');
   delayConversationReads=true;
   await page.evaluate(()=>{
    window.phoneExitBlankFrames=0;window.phoneExitRecording=true;
    const observe=()=>{if(!phoneExitRecording)return;const active=document.querySelector('.main-content > .section.active');
     if(!active || (active.id==='section-conversations' && !document.getElementById('conversation-detail-layer').classList.contains('open')))phoneExitBlankFrames++;
     requestAnimationFrame(observe);};requestAnimationFrame(observe);
   });
   await frame.getByRole('button',{name:'返回Conversation',exact:true}).click();await waitView('chat');
   assert.equal(await page.locator('[data-chat-tab=conversations]').getAttribute('aria-current'),'page');
   assert.equal(await page.locator('#phone-conversation-list [data-conversation-id]').count(),2,'previous list stays visible while refresh is slow');
   assert.equal(await page.evaluate(()=>{phoneExitRecording=false;return phoneExitBlankFrames;}),0,'exit never exposes an empty detail section');
   assert.ok(await page.evaluate(()=>Boolean(document.getElementById('conversation-detail-frame').dataset.contextSrc)),'exiting retains the loaded conversation');
   assert.equal(await frame.locator('#msgInput').count(),1,'back traversal does not replace the cached iframe with about:blank');
   delayConversationReads=false;
  }
  await page.locator('[data-chat-tab=chat]').click();await page.locator('#phone-open-chat').click();
  await page.frameLocator('#conversation-detail-frame').locator('#msgInput').waitFor();
  await page.frameLocator('#conversation-detail-frame').getByRole('button',{name:'返回Chat',exact:true}).click();await waitView('chat');
  assert.equal(await page.locator('[data-chat-tab=chat]').getAttribute('aria-current'),'page');
  await page.locator('#phone-open-chat').click();await page.frameLocator('#conversation-detail-frame').locator('#msgInput').waitFor({state:'visible'});
  await page.frameLocator('#conversation-detail-frame').getByRole('button',{name:'返回Chat',exact:true}).click();await waitView('chat');
  assert.deepEqual(errors,[]);console.log('Passed immediate conversation exit, zero blank frames, retained list on slow refresh, repeated switches and both return tabs.');return;
 }
 if(!process.env.ASH_PHONE_SKIP_NAV){
 // Follow the same paths as the user, checking every destination in both directions.
 const waitView=async name=>page.waitForFunction(name=>document.body.dataset.phoneView===name,name);
 const backTo=async(name,label)=>{if(label)assert.equal(await page.locator('#phone-back').getAttribute('aria-label'),'返回'+label);await page.locator('#phone-back').click();await waitView(name);};
 await page.locator('#phone-pages [data-phone-app=diary]').click();await waitView('diary');await backTo('home','主屏幕');
 await page.locator('.phone-dock [data-phone-launch=preferences]').click();await waitView('preferences');await shot('settings-home');
 await page.locator('#phone-supplier-settings').click();await waitView('suppliers');await shot('suppliers');
 for(const kind of ['route','openai','anthropic']){
  await page.locator(`[data-phone-app=supplier-${kind}]`).click();await waitView('supplier-'+kind);
  assert.equal(await page.locator('#section-recall').isVisible(),false);assert.equal(await page.locator('#section-settings').isVisible(),false);
  await backTo('suppliers','模型供应商');
 }
 const appHistoryLength=await page.evaluate(()=>history.length);
 await page.locator('[data-phone-app=supplier-openai]').click();await waitView('supplier-openai');
 assert.equal(await page.evaluate(()=>history.length),appHistoryLength,'app navigation never adds browser history');
 await backTo('suppliers','模型供应商');await page.locator('[data-phone-app=supplier-openai]').click();await waitView('supplier-openai');
 await page.reload();await waitView('supplier-openai');await backTo('suppliers','模型供应商');await backTo('preferences','设置');
 await page.locator('[data-phone-app=settings]').click();await waitView('settings');
 await page.locator('#section-settings summary').filter({hasText:'自动标题'}).click();
 await page.locator('#historyTitleModel').fill('unsaved-title');
 await backTo('preferences','设置');await page.locator('#phone-recall-settings').click();await waitView('recall');
 assert.equal(await page.locator('#section-suppliers').isVisible(),false);assert.equal(await page.locator('#section-settings').isVisible(),false);await shot('recall');
 await page.locator('#crossConversationRecallEnabled').check();
 await page.locator('#historyEmbeddingModel').fill('new-embedding');
 await page.locator('#section-recall').getByRole('button',{name:'保存',exact:true}).click();
 await page.locator('#recall-settings-msg').filter({hasText:'已保存'}).waitFor();
 let saved=JSON.parse(writes.filter(w=>w.path==='/api/conversation-model-settings').at(-1).body);
 assert.equal(saved.title_model,'saved-title','saving recall does not save the other page draft');assert.equal(saved.long_term_recall_limit,9);
 assert.equal(saved.cross_conversation_recall_enabled,true);assert.equal(saved.embedding_model,'new-embedding');assert.equal(Object.hasOwn(saved,'diary_summary_model'),false);
 await backTo('preferences','设置');await page.locator('[data-phone-app=settings]').click();await waitView('settings');
 await shot('other-settings');await page.locator('#historyTitleModel').fill('new-title');
 await page.locator('#section-settings .conversation-generation-panel').getByRole('button',{name:'保存',exact:true}).click();
 await page.locator('#conversation-model-settings-msg').filter({hasText:'已保存'}).waitFor();
 saved=JSON.parse(writes.filter(w=>w.path==='/api/conversation-model-settings').at(-1).body);
 assert.equal(saved.title_model,'new-title');assert.equal(Object.hasOwn(saved,'embedding_api_url'),false);assert.equal(modelSettings.embedding_model,'new-embedding');
 await backTo('preferences','设置');await page.locator('#phone-backup-settings').click();await waitView('phone-transfer');
 for(const tool of ['export','import']){await page.locator(`#section-phone-transfer [data-phone-app=${tool}]`).click();await waitView(tool);await backTo('phone-transfer','备份与导入');}
 await backTo('preferences','设置');await backTo('home','主屏幕');
 await page.locator('#phone-pages [data-phone-app=chat]').click();await waitView('chat');
 await page.locator('[data-chat-tab=conversations]').click();
 await page.locator('.phone-conversation-group').first().waitFor();
 assert.equal(await page.locator('.phone-conversation-group').count(),2);
 assert.match(await page.locator('.phone-month-title').first().innerText(),/年\d+月/);
 assert.equal(await page.locator('#phone-printer-name').innerText(),convs[0].name);
 await page.locator('#phone-printer-feed').click();
 assert.equal(await page.locator('#phone-conversation-list').isVisible(),false);
 assert.equal(await page.locator('#phone-printer-feed').getAttribute('aria-expanded'),'false');
 await page.locator('#phone-printer-feed').click();
 assert.equal(await page.locator('#phone-conversation-list').isVisible(),true);
 assert.equal(await page.locator('.phone-conversation-group').count(),2,'feeding preserves the loaded directory');
 assert.equal(await page.locator('#phone-conversation-list').evaluate(el=>getComputedStyle(el).animationName),'none','reduced motion skips paper animation');
 await page.emulateMedia({reducedMotion:'no-preference'});
 await page.locator('#phone-printer-feed').click();await page.locator('#phone-printer-feed').click();
 assert.equal(await page.locator('#phone-conversation-list').evaluate(el=>getComputedStyle(el).animationName),'phone-receipt-feed');
 await page.emulateMedia({reducedMotion:'reduce'});
 const listDate=page.locator('.phone-conversation-date').first();
 await page.locator('#phone-app-title').hover();assert.equal(await listDate.isVisible(),false);
 await page.locator('.phone-conversation-entry').first().hover();assert.equal(await listDate.isVisible(),true);
 await page.locator('#phone-app-title').hover();assert.equal(await listDate.isVisible(),false);
 for(const width of [320,390,768]) {
  await page.setViewportSize({width,height:844});
  for(const theme of ['light','dark']) {
   await page.evaluate(theme=>AshTheme.setTheme(theme),theme);await noOverflow();
   assert.equal(await page.locator('.phone-conversation-row strong').first().evaluate(el=>getComputedStyle(el).fontSize),'17px');
   await shot(`grouped-conversations-${theme}-${width}`);
  }
 }
 await page.setViewportSize({width:390,height:844});await page.evaluate(()=>AshTheme.setTheme('light'));
 await page.locator('[data-conversation-id="2"]').click();await waitView('detail');
 await page.frameLocator('#conversation-detail-frame').getByRole('button',{name:'返回Conversation',exact:true}).click();await waitView('chat');
 await page.locator('#phone-printer-current').click();await waitView('detail');
 await page.frameLocator('#conversation-detail-frame').locator('#topTitle').filter({hasText:convs[0].name}).waitFor({state:'attached'});
 await page.frameLocator('#conversation-detail-frame').getByRole('button',{name:'返回Conversation',exact:true}).click();await waitView('chat');
 assert.equal(await page.locator('[data-chat-tab=conversations]').getAttribute('aria-current'),'page');await backTo('home','主屏幕');
 await page.locator('#phone-pages [data-phone-app=chat]').click();await waitView('chat');await page.locator('[data-chat-tab=chat]').click();
 const usageHash=await page.evaluate(()=>location.hash);await page.locator('#phone-chat-usage').click();await page.locator('.usage-board-close').click();
 assert.equal(await page.evaluate(()=>location.hash),usageHash);await backTo('home','主屏幕');
 // A fresh deep link builds the same explicit parent path, without unrelated pages.
 const deep=await context.newPage();deep.on('pageerror',e=>errors.push(e.message));
 await deep.goto('https://ash-phone.test/dashboard#supplier-anthropic');await deep.locator('#section-supplier-anthropic.active').waitFor();
 for(const name of ['suppliers','preferences','home']){await deep.locator('#phone-back').click();await deep.waitForFunction(name=>document.body.dataset.phoneView===name,name);}
 await deep.close();
 // Back restores the settings screen at the same scroll position.
 await page.setViewportSize({width:390,height:500});
 await page.locator('.phone-dock [data-phone-launch=preferences]').click();await waitView('preferences');
 await page.locator('.main-content').evaluate(el=>{el.scrollTop=100;});await page.waitForTimeout(60);
 const originScroll=await page.locator('.main-content').evaluate(el=>el.scrollTop);
 await page.locator('#phone-recall-settings').click();await waitView('recall');await backTo('preferences','设置');await page.waitForTimeout(80);
 assert.equal(await page.locator('.main-content').evaluate(el=>el.scrollTop),originScroll);
 await backTo('home','主屏幕');await page.setViewportSize({width:390,height:844});
 // Existing v2 layouts and imported backups also drop the retired Usage app.
 const originalDesktop=await page.evaluate(()=>AshDesktop.get());
 await page.evaluate(async()=>{const stale=AshDesktop.get();stale.pages[1].push('usage');stale.hidden.push('usage');stale.icons.usage='data:image/png;base64,invalid';await AshDesktop.restore(stale);});
 assert.equal(await page.evaluate(()=>AshDesktop.get().pages.flat().includes('usage')),false);
 assert.equal(await page.evaluate(()=>AshDesktop.get().hidden.includes('usage')),false);
 await page.evaluate(value=>AshDesktop.restore(value),originalDesktop);
 writes.length=0;
 for(const theme of ['dark','light']){
  await page.evaluate(theme=>AshTheme.setTheme(theme),theme);
  await page.locator('.phone-dock [data-phone-launch=preferences]').click();await waitView('preferences');
  for(const name of ['suppliers','recall','settings']){
   await page.locator(`[data-phone-app=${name}]`).click();await waitView(name);await noOverflow();
   await shot(`${name}-${theme}`);await backTo('preferences','设置');
  }
  await backTo('home','主屏幕');
 }
 console.log('Independent settings, isolated saves, internal back stack, stable browser history, deep links and Chat tab returns passed.');
 if(process.env.ASH_PHONE_NAV_ONLY){assert.deepEqual(errors,[]);return;}
 }
 const cdp=await context.newCDPSession(page);
 const touch=async(type,x,y)=>cdp.send('Input.dispatchTouchEvent',{type,touchPoints:type==='touchEnd'||type==='touchCancel'?[]:[{x,y}]});
 const layout=()=>page.evaluate(()=>AshDesktop.get());
 const initialLayout=await layout();
 const shellState=()=>page.evaluate(()=>({y:scrollY,root:document.scrollingElement.scrollTop,body:document.body.scrollTop,
  main:document.querySelector('.main-content').scrollTop,top:document.querySelector('.dashboard').getBoundingClientRect().top,
  home:document.getElementById('phone-home-button').getBoundingClientRect().top}));
 const swipe=async(x,from,to)=>{
  await touch('touchStart',x,from);
  for(let i=1;i<=6;i++) await touch('touchMove',x,from+(to-from)*i/6);
  await touch('touchEnd');await page.waitForTimeout(120);
 };
 const fixedShell=async(before,mainMayScroll=false)=>{
  const after=await shellState();assert.equal(after.y,0);assert.equal(after.root,0);assert.equal(after.body,0);
  assert.ok(Math.abs(after.top-before.top)<1);assert.ok(Math.abs(after.home-before.home)<1);
  if(!mainMayScroll)assert.equal(after.main,0);
 };
 const openStudio=async(tab='wallpaper')=>page.evaluate(tab=>merlePhoneApps.customize(tab),tab);
 const closeStudio=async()=>page.locator('#btn-phone-customize-close').click();
 const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jN1EAAAAASUVORK5CYII=','base64');
 const image={name:'local.png',mimeType:'image/png',buffer:png};
 let shellBefore;
 if(!process.env.ASH_PHONE_CHAT_ONLY){
 // Scrolling a long desktop and continuing at its boundary must never move the shell or Dock.
 const tall=structuredClone(initialLayout);tall.positions.diary={row:12,col:3};await page.evaluate(value=>AshDesktop.restore(value),tall);
 const desktop=page.locator('.phone-desktop-page').first(),desktopBox=await desktop.boundingBox();
 shellBefore=await shellState();const dockTop=(await page.locator('.phone-dock').boundingBox()).y;
 const dragStart=await page.locator('#phone-pages [data-item=chat]').boundingBox();
 await swipe(dragStart.x+25,dragStart.y+30,dragStart.y-100);
 assert.ok(await desktop.evaluate(el=>el.scrollTop)>50,'desktop content scrolls inside its own page');await fixedShell(shellBefore);
 await desktop.evaluate(el=>{el.scrollTop=el.scrollHeight;});
 await swipe(desktopBox.x+desktopBox.width-4,desktopBox.y+desktopBox.height-40,desktopBox.y+desktopBox.height-170);
 await fixedShell(shellBefore);assert.ok(Math.abs((await page.locator('.phone-dock').boundingBox()).y-dockTop)<1);
 await desktop.evaluate(el=>{el.scrollTop=0;});await swipe(desktopBox.x+desktopBox.width-4,desktopBox.y+30,desktopBox.y+160);await fixedShell(shellBefore);
 await page.evaluate(value=>AshDesktop.restore(value),initialLayout);

 const exitEdit=async()=>page.evaluate(()=>AshDesktop.edit(false));
 let tile=await page.locator('#phone-pages [data-item=chat]').boundingBox();
 // Original Merle capture/snap logic distinguishes an app tap from a swipe.
 await touch('touchStart',tile.x+25,tile.y+25);await touch('touchMove',tile.x-90,tile.y+25);await touch('touchEnd');
 await page.locator('#phone-page-dots [data-page="1"][aria-current=page]').waitFor();
 assert.equal(await page.locator('#section-home.active').count(),1);
 assert.equal(await page.locator('#phone-home.is-editing').count(),0);
 await page.locator('#phone-page-dots [data-page="0"]').click();
 await page.waitForFunction(()=>document.getElementById('phone-pages').scrollLeft<1);
 const beforeCancel=await layout();
 tile=await page.locator('#phone-pages [data-item=chat]').boundingBox();
 await touch('touchStart',tile.x+25,tile.y+25);await page.locator('.phone-drag-preview').waitFor();
 await touch('touchMove',tile.x+50,tile.y+90);await touch('touchCancel');
 assert.deepEqual(await layout(),beforeCancel,'native cancelled drag restores coordinates');
 assert.equal(await page.locator('.phone-drag-preview').count(),0);await exitEdit();
 // Native grid, Dock placement and page controls remain the original module.
 tile=await page.locator('#phone-pages [data-item=chat]').boundingBox();
 const target=await page.locator('#phone-pages [data-item=standing]').boundingBox();
 await touch('touchStart',tile.x+25,tile.y+25);await page.locator('.phone-drag-preview').waitFor();
 await touch('touchMove',target.x+25,target.y+25);await touch('touchEnd');
 assert.notDeepEqual((await layout()).positions.chat,initialLayout.positions.chat);
 await page.locator('#phone-pages [data-item=chat] .phone-app').click();
 await page.locator('#phone-move-page').selectOption('dock');await page.locator('#phone-move-item').click();
 assert.ok((await layout()).dock.includes('chat'),'original Dock supports moving apps');
 await page.locator('#phone-add-page').click();assert.equal((await layout()).pages.length,3);
 await page.locator('.phone-dock [data-item=chat] .phone-app').click();await page.locator('#phone-move-page').selectOption('2');await page.locator('#phone-move-item').click();
 assert.ok((await layout()).pages[2].includes('chat'));await exitEdit();
 await page.evaluate(value=>AshDesktop.restore(value),initialLayout);
 // Native customization: wallpaper, individual icons and photo widgets.
 await openStudio();
 await page.locator('[data-upload=wallpaper]').setInputFiles(image);
 await page.waitForFunction(()=>AshDesktop.get().wallpaperImage.startsWith('phone-image:'));
 await page.locator('[data-phone-tab=icons]').click();await page.locator('[data-icon-style=glass]').click();
 await page.locator('[data-upload=icon][data-id=chat]').setInputFiles(image);
 await page.waitForFunction(()=>!!AshDesktop.get().icons.chat);
 await page.locator('#phone-icon-opacity-range').fill('55');await page.locator('#phone-icon-opacity-range').dispatchEvent('change');
 assert.equal((await layout()).iconOpacity,55);
 await page.locator('[data-phone-tab=widgets]').click();await page.locator('[data-widget-type=photo] > summary').click();await page.locator('[data-add-widget=photo]').click();
 await page.locator('#phone-widget-form [name=title]').fill('一起留下的照片');
 await page.locator('[data-upload=widget]').setInputFiles(image);
 await page.locator('#phone-widget-form button[type=submit]').click();
 await page.locator('#phone-customize').waitFor({state:'hidden'});
 assert.ok(Object.values((await layout()).widgets).some(w=>w.type==='photo'&&w.image.startsWith('phone-image:')));
 await openStudio();assert.equal(await page.locator('[data-phone-tab=presets]').count(),0);await closeStudio();
 await page.reload();await page.evaluate(()=>merlePhoneApps.whenReady());
 assert.equal((await layout()).wallpaper,initialLayout.wallpaper);assert.equal((await layout()).iconOpacity,55);
 assert.equal(await page.locator('#phone-pages [data-phone-app=chat] img').count(),1);
 // Profile state is independent and never writes server identity APIs.
 await page.locator('#phone-pages [data-phone-name=user]').click();await page.locator('[data-phone-name-editor=user]').fill('小满');
 await page.locator('[data-phone-name-editor=user]').press('Enter');
 await page.locator('#phone-pages [data-phone-profile=assistant]').click();await page.locator('#phone-avatar-menu [data-avatar-action=image]').click();await page.locator('#phone-local-image').setInputFiles(image);
 await page.locator('#phone-pages [data-local-avatar=assistant] img').waitFor();
 assert.equal(writes.length,0);
 await page.reload();await page.locator('.phone-pair [data-local-name=user]').filter({hasText:'小满'}).waitFor();
 assert.equal(await page.locator('.phone-pair [data-local-avatar=assistant] img').count(),1);
 console.log('Native desktop, gestures, Dock, widgets, customization and profile persistence passed.');
 }else await page.evaluate(()=>AshLocal.update(state=>{state.names.user='小满';}));
 // Ash chat bindings: history is read-only until explicit activation; drafts stay per conversation.
 await page.evaluate(()=>switchSection('chat'));await page.locator('[data-chat-tab=me]').click();await page.locator('#phone-me-favorites').click();await page.locator('[data-chat-panel=cover]:not([hidden])').waitFor();
 await page.locator('[data-chat-tab=me]').click();await page.locator('[data-chat-panel=me] [data-local-name=user]').filter({hasText:'小满'}).waitFor();
 await page.locator('[data-chat-tab=conversations]').click();await page.locator('[data-conversation-id="2"]').click();
 let frame=page.frameLocator('#conversation-detail-frame');await frame.locator('#phone-chat-continue:not([hidden])').waitFor();assert.equal(activeId,1);
 await frame.locator('#msgInput').fill('九月的独立草稿');await gotoHome();await page.evaluate(()=>switchSection('chat'));await page.locator('[data-chat-tab=chat]').click();await page.locator('#phone-open-chat').click();
 frame=page.frameLocator('#conversation-detail-frame');await frame.locator('#sendBtn:not([disabled])').waitFor();
 assert.equal(await frame.locator('#msgInput').inputValue(),'');assert.equal(await page.evaluate(()=>AshLocal.readDraft(2)),'九月的独立草稿');
 await frame.locator('#msgInput').fill('刷新后还要在的草稿');await page.reload();await page.locator('#phone-open-chat').click();
 frame=page.frameLocator('#conversation-detail-frame');await frame.locator('#sendBtn:not([disabled])').waitFor();assert.equal(await frame.locator('#msgInput').inputValue(),'刷新后还要在的草稿');
 assert.equal(await frame.locator('link[href*="conversation-paper.css"]').count(),0,'chat no longer loads the old paper skin');
 assert.equal(await frame.locator('.msg.user .phone-message-bubble').evaluate(el=>getComputedStyle(el).backgroundColor),'rgb(102, 102, 99)');
 await shot('merle-chat-390');
 let bubble=await frame.locator('.msg.assistant .phone-message-bubble').boundingBox();
 await touch('touchStart',bubble.x+20,bubble.y+15);await touch('touchEnd');assert.equal(await frame.locator('.phone-message-actions-open').count(),0);
 await touch('touchStart',bubble.x+20,bubble.y+15);await frame.locator('.msg.assistant.phone-message-actions-open').waitFor();await touch('touchEnd');
 await frame.locator('.phone-copy-message').last().waitFor({state:'visible'});
 await page.evaluate(()=>{window.phoneTestViewport={height:844,offsetTop:0};Object.defineProperty(window,'visualViewport',{configurable:true,value:phoneTestViewport});});
 for(const [height,top] of [[460,0],[420,55]]){
  await frame.locator('#msgInput').focus();assert.equal(await frame.locator('.phone-message-actions-open').count(),0);
  await page.evaluate(([height,top])=>{Object.assign(phoneTestViewport,{height,offsetTop:top});AshPhoneViewport.refresh();},[height,top]);
  await frame.locator('body.phone-chat-keyboard-open').waitFor();await page.waitForTimeout(100);
  const composer=await frame.locator('#composer').boundingBox();assert.ok(Math.abs(composer.y+composer.height-(height+top))<3);
  await frame.locator('#msgInput').blur();await page.evaluate(()=>{Object.assign(phoneTestViewport,{height:844,offsetTop:0});AshPhoneViewport.refresh();});
  await page.waitForFunction(()=>!document.body.classList.contains('phone-chat-keyboard-open'));
 }
 await page.reload();await page.locator('#phone-open-chat').click();frame=page.frameLocator('#conversation-detail-frame');await frame.locator('#sendBtn:not([disabled])').waitFor();
 failChat=true;await frame.locator('#sendBtn').click();await frame.locator('#phone-chat-notice').filter({hasText:'测试上游暂时不可用'}).waitFor();assert.equal(await frame.locator('#msgInput').inputValue(),'刷新后还要在的草稿');
 failChat=false;await frame.locator('#sendBtn:not([disabled])').click();await frame.locator('.msg-body').filter({hasText:'我在这里，听你说。'}).waitFor();await frame.locator('#sendBtn:not([disabled])').waitFor();assert.equal(await page.evaluate(()=>AshLocal.readDraft(1)),'');
 await frame.locator('#phone-chat-more').click();await frame.locator('#conversationSettingsBtn').click();await frame.locator('#editConvModal.show').waitFor();await frame.locator('#editConvModal').getByRole('button',{name:'取消',exact:true}).click();
 // Load a real long fixture transcript, then drag at both scroll boundaries.
 await frame.locator('#phone-chat-more').click();
 const originalMessages=messages.get(1);
 messages.set(1,Array.from({length:40},(_,i)=>({id:100+i,role:i%2?'assistant':'user',content:'滚动测试消息 '+i+'：只滚动聊天记录，标题与输入栏留在原处。\n\n这是第二段内容。'})));
 await gotoHome();await page.evaluate(()=>switchSection('chat'));await page.locator('#phone-open-chat').click();
 frame=page.frameLocator('#conversation-detail-frame');await frame.locator('body').evaluate(()=>loadMessages(currentConvId));
 assert.equal(await frame.locator('.msg').count(),40);
 const chatArea=frame.locator('#msgArea');await chatArea.evaluate(el=>{el.scrollTop=0;});
 const chatBox=await chatArea.boundingBox(),headerTop=(await frame.locator('.topbar').boundingBox()).y,composeTop=(await frame.locator('#composer').boundingBox()).y;
 const chatBottom=composeTop-25;
 shellBefore=await shellState();await swipe(chatBox.x+20,chatBottom,chatBottom-140);
 assert.ok(await chatArea.evaluate(el=>el.scrollTop)>30,'only transcript scrolls: '+JSON.stringify(await chatArea.evaluate(el=>({top:el.scrollTop,height:el.clientHeight,total:el.scrollHeight,box:el.getBoundingClientRect().toJSON(),target:document.elementFromPoint(20,el.getBoundingClientRect().bottom-40)?.outerHTML.slice(0,300)}))));await fixedShell(shellBefore);
 await chatArea.evaluate(el=>{el.scrollTop=el.scrollHeight;});await swipe(chatBox.x+20,chatBottom,chatBottom-140);await fixedShell(shellBefore);
 await chatArea.evaluate(el=>{el.scrollTop=0;});await swipe(chatBox.x+20,headerTop+120,headerTop+240);await fixedShell(shellBefore);
 assert.ok(Math.abs((await frame.locator('.topbar').boundingBox()).y-headerTop)<1);assert.ok(Math.abs((await frame.locator('#composer').boundingBox()).y-composeTop)<1);
 assert.equal(await frame.locator('html').evaluate(()=>document.scrollingElement.scrollTop),0);messages.set(1,originalMessages);
 console.log('Chat history, drafts, touch menu, keyboard, streaming and fixed shell scrolling passed.');
 if(process.env.ASH_PHONE_CHAT_ONLY){assert.deepEqual(errors,[]);return;}
 await gotoHome();await page.evaluate(()=>switchSection('preferences'));await page.locator('#phone-supplier-settings').click();await page.locator('[data-phone-app=supplier-openai]').click();await page.locator('#section-supplier-openai.active').waitFor();await page.locator('#phone-back').click();await page.locator('#section-suppliers.active').waitFor();
 await gotoHome();await page.evaluate(()=>switchSection('heartbeats'));await page.locator('#heartbeatInterval:not([disabled])').waitFor();
 assert.equal(await page.locator('.main-content').evaluate(el=>getComputedStyle(el).backgroundImage),'none');
 await page.evaluate(()=>switchSection('presets'));assert.equal(await page.locator('.main-content').evaluate(el=>getComputedStyle(el).backgroundImage),'none');
 // Backup v2 includes native widget/theme images, never message data. v1 stays importable.
 // A tool page on a compact screen scrolls inside main; header/home remain fixed.
 await page.setViewportSize({width:390,height:500});
 await gotoHome();await page.evaluate(()=>switchSection('presets'));
 const content=page.locator('.main-content'),contentBox=await content.boundingBox();
 await page.frameLocator('#prompt-console-frame').locator('body').waitFor();
 shellBefore=await shellState();
 const settingsHeader=(await page.locator('#phone-app-header').boundingBox()).y;
 await swipe(contentBox.x+5,contentBox.y+contentBox.height-30,contentBox.y+contentBox.height-170);
 assert.ok(await content.evaluate(el=>el.scrollTop)>20,'tool content retains native scrolling: '+JSON.stringify(await content.evaluate(el=>({top:el.scrollTop,height:el.clientHeight,total:el.scrollHeight,overflow:getComputedStyle(el).overflowY,box:el.getBoundingClientRect().toJSON()}))));await fixedShell(shellBefore,true);
 await content.evaluate(el=>{el.scrollTop=el.scrollHeight;});await swipe(contentBox.x+5,contentBox.y+contentBox.height-30,contentBox.y+contentBox.height-170);await fixedShell(shellBefore,true);
 await content.evaluate(el=>{el.scrollTop=0;});await swipe(contentBox.x+5,contentBox.y+30,contentBox.y+160);await fixedShell(shellBefore,true);
 assert.ok(Math.abs((await page.locator('#phone-app-header').boundingBox()).y-settingsHeader)<1);
 await page.setViewportSize({width:390,height:844});
 if(process.env.ASH_PHONE_SCROLL_ONLY){assert.deepEqual(errors,[]);console.log('Passed desktop/transcript/tool scrolling and boundaries with fixed shell, headers, Dock and composer.');return;}
 await gotoHome();await page.evaluate(()=>switchSection('phone-transfer'));
 const downloadEvent=page.waitForEvent('download');await page.locator('#phone-export-local').click();const download=await downloadEvent;
 const backupFile=path.join(screenshotDir,'desktop-backup.json');await download.saveAs(backupFile);const backup=JSON.parse(fs.readFileSync(backupFile));
 assert.equal(backup.version,2);assert.ok(backup.desktop.wallpaperImage.startsWith('data:image/'));assert.ok(backup.assets['avatar-assistant'].startsWith('data:image/'));
 await page.locator('#phone-import-local').click();await page.locator('#phone-local-backup').setInputFiles(backupFile);await page.locator('#phone-toast').filter({hasText:'本机桌面已恢复'}).waitFor();
 assert.equal(await page.evaluate(()=>AshLocal.get().names.user),'小满');assert.ok((await layout()).wallpaperImage.startsWith('phone-image:'));
 assert.equal(writes.some(w=>w.path.includes('/identity-presets')),false);
 await page.evaluate(()=>switchSection('chat'));await page.locator('#phone-header-action').click();await page.frameLocator('#conversation-detail-frame').locator('#msgInput').waitFor({state:'visible'});assert.equal(activeId,3);
 const createdModal=page.frameLocator('#conversation-detail-frame').locator('#createdConvModal');if(await createdModal.isVisible())await createdModal.getByRole('button',{name:'开始对话'}).click();await gotoHome();
 for(const width of [320,390,768,1365]){
  await page.setViewportSize({width,height:844});await noOverflow();await checkPair();
  for(const theme of ['light','dark']){
   await page.evaluate(theme=>AshTheme.setTheme(theme),theme);await shot(`home-${theme}-${width}`);
   await page.evaluate(()=>switchSection('chat'));await page.locator('#phone-open-chat').click();const detail=page.frameLocator('#conversation-detail-frame');await detail.locator('#msgInput').waitFor({state:'visible'});
   assert.equal(await detail.locator('.app').evaluate(el=>el.scrollWidth<=el.clientWidth+1),true);await gotoHome();
  }
 }
 await page.evaluate(value=>AshDesktop.restore(value),initialLayout);await openStudio('icons');
 const stored=await page.evaluate(()=>localStorage.getItem('ash.phone.desktop.v2'));
 await page.evaluate(()=>{Storage.prototype.setItem=()=>{throw new DOMException('Quota exceeded','QuotaExceededError');};});
 await page.locator('[data-icon-style=round]').click();await page.locator('#phone-toast').filter({hasText:'未保存'}).waitFor();assert.equal(await page.evaluate(()=>localStorage.getItem('ash.phone.desktop.v2')),stored);
 // A separate browser starts with the previous Ash desktop, including its IndexedDB wallpaper.
 const legacyContext=await browser.newContext({viewport:{width:390,height:844},reducedMotion:'reduce',hasTouch:true});
 await legacyContext.route('**/*',routeHandler);
 const legacyPage=await legacyContext.newPage();legacyPage.on('pageerror',e=>errors.push(e.message));
 await legacyPage.goto('https://ash-phone.test/dashboard');await legacyPage.waitForFunction(()=>window.AshDesktop);
 await legacyPage.evaluate(async base64=>{
  const blob=new Blob([Uint8Array.from(atob(base64),c=>c.charCodeAt(0))],{type:'image/png'});
  await AshLocal.asset('wallpaper',blob);await AshLocal.asset('avatar-user',blob);
  localStorage.setItem('ash.phone.v1',JSON.stringify({version:1,names:{user:'迁移前的昵称',assistant:'原来的助手'},
   pages:[['together','note','chat','heartbeats','standing','presets'],['usage','settings']],
   positions:{together:{row:0,col:0},note:{row:2,col:0}},wallpaper:'photo',iconStyle:'round',iconOpacity:73,note:'迁移前的便签'}));
  localStorage.removeItem('ash.phone.desktop.v2');
 },png.toString('base64'));
 await legacyPage.reload();await legacyPage.evaluate(()=>merlePhoneApps.whenReady());
 await legacyPage.locator('.phone-pair [data-local-name=user]').filter({hasText:'迁移前的昵称'}).waitFor();
 const migrated=await legacyPage.evaluate(()=>AshDesktop.get());
 assert.equal(migrated.widgets['widget-ash-note'].text,'迁移前的便签');assert.equal(migrated.iconStyle,'round');assert.equal(migrated.iconOpacity,73);
 assert.ok(migrated.wallpaperImage.startsWith('phone-image:'));assert.ok(migrated.pages[1].includes('preferences'));assert.equal(migrated.pages.flat().includes('usage'),false);
 assert.deepEqual(migrated.positions['widget-ash-note'],{row:2,col:0});
 await legacyPage.locator('.phone-pair [data-local-avatar=user] img').waitFor();
 // The v1 backup boundary migrates the layout and images into the same native engine.
 await legacyPage.evaluate(()=>switchSection('phone-transfer'));
 const oldBackup={format:'ash-phone-desktop',version:1,state:{version:1,names:{user:'旧备份昵称',assistant:'Ash'},pages:[['together','note','chat']],note:'旧备份便签',wallpaper:'paper'},assets:{}};
 await legacyPage.locator('#phone-import-local').click();await legacyPage.locator('#phone-local-backup').setInputFiles({name:'v1.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(oldBackup))});
 await legacyPage.locator('#phone-toast').filter({hasText:'本机桌面已恢复'}).waitFor();
 assert.equal(await legacyPage.evaluate(()=>AshLocal.get().names.user),'旧备份昵称');assert.equal(await legacyPage.evaluate(()=>AshDesktop.get().widgets['widget-ash-note'].text),'旧备份便签');
 await legacyContext.close();
 assert.deepEqual(errors,[]);console.log('Passed native Merle desktop, local customization/media, Ash chat/settings/backup, mobile keyboard and 320/390/768/1365px.');
 await context.close();
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
