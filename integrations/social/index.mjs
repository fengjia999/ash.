import {createServer} from 'node:http';
import {readFileSync} from 'node:fs';
import {timingSafeEqual} from 'node:crypto';
import {validateConfig} from './core.mjs';
import {Feishu} from './feishu.mjs';
import {Weixin} from './weixin.mjs';
import {QQTurns} from '../qq/turns.mjs';
const bootstrap=JSON.parse(readFileSync(0,'utf8'));
let config=validateConfig(bootstrap.connection);
const secret=bootstrap.managementToken;
if(typeof secret!=='string'||secret.length<32)throw new Error('invalid management token');
let adapter=null,turns=null,status='disabled',error='',closing=false,epoch=0,restarts=Promise.resolve();
const seen=new Set(),notifications=new Set();
function restart(){
 const current=++epoch;status=config.enabled||config.setupEnabled?'connecting':'disabled';error='';
 restarts=restarts.then(async()=>{
  if(current!==epoch||closing)return;
  await adapter?.close();await turns?.close();await Promise.allSettled([...notifications]);adapter=null;
  if(!config.enabled&&!config.setupEnabled)return;
  const snapshot={...config,platform:config.provider==='feishu'?'飞书':'微信'};
  turns=new QQTurns({onError:()=>{if(current===epoch)error='gateway_unavailable';}});
  const onMessage=message=>{
   const key=JSON.stringify([snapshot.appId,snapshot.botId,message.sender,message.id]);
   if(current!==epoch||closing||!snapshot.enabled||!snapshot.allowedUsers.includes(message.sender)||seen.has(key))return;
   if(!message.text&&!message.unsupported)return;
   seen.add(key);if(seen.size>2048)seen.delete(seen.values().next().value);
   const content=message.text+(message.unsupported?'\n[此连接暂未读取附件，请勿猜测附件内容。]':'');
   turns.add({messageId:message.id,senderId:message.sender,content,replyTarget:{scope:'c2c',targetId:message.sender,contextToken:message.context}},adapter,snapshot);
  };
  adapter=new (config.provider==='feishu'?Feishu:Weixin)(snapshot,onMessage,(next,detail)=>{if(current===epoch){status=next;error=detail;}});
  await adapter.start();
 }).catch(()=>{if(current===epoch){status='error';error='connection_failed';}});
}
function authorized(request){const got=Buffer.from(request.headers.authorization||''),want=Buffer.from('Bearer '+secret);return got.length===want.length&&timingSafeEqual(got,want);}
function json(response,code,data){response.writeHead(code,{'Content-Type':'application/json','Cache-Control':'no-store'});response.end(JSON.stringify(data));}
async function body(request){let size=0,chunks=[];for await(const chunk of request){size+=chunk.length;if(size>65536)throw new Error('too large');chunks.push(chunk);}return JSON.parse(Buffer.concat(chunks).toString()||'{}');}
const server=createServer(async(request,response)=>{
 if(!authorized(request)){json(response,401,{error:'unauthorized'});return;}
 try{
  if(request.url==='/api/connection'){
   if(request.method==='PUT'){const next=validateConfig(await body(request));if(next.provider!==config.provider)throw new Error('wrong provider');config=next;restart();}
   else if(request.method!=='GET'){json(response,405,{});return;}
   const actual=adapter?.connectionStatus?.();
   json(response,200,{status:status==='disabled'?'disabled':actual||status,error:error||(actual==='error'?'connection_failed':'')});return;
  }
  if(request.url==='/api/settings'){if(request.method==='PUT')await body(request);json(response,200,{});return;}
  if(request.url==='/setup'&&request.method==='POST'){
   await restarts;if(!adapter)throw new Error('not ready');json(response,200,await adapter.setup());return;
  }
  const match=/^\/setup\/([0-9a-f-]{36})$/.exec(request.url||'');
  if(match){
   if(request.method==='DELETE'){adapter?.cancel(match[1]);json(response,200,{});return;}
   if(request.method==='POST'){const data=await body(request);json(response,200,adapter?.read(match[1],data.verify_code)||{status:'expired'});return;}
  }
  if(request.url==='/notify'&&request.method==='POST'){
   if(closing||!config.enabled||!adapter||status!=='connected'){json(response,409,{error:'not_connected'});return;}
   const data=await body(request),pending=turns.notify(data.text,adapter,config);notifications.add(pending);
   try{json(response,200,{ok:true,bubbles:await pending});}finally{notifications.delete(pending);}return;
  }
  json(response,404,{});
 }catch{json(response,400,{error:'request_failed'});}
});
server.listen(0,'127.0.0.1',()=>console.log('[transport-ready]'+JSON.stringify({port:server.address().port})));
async function stop(){if(closing)return;closing=true;epoch++;server.close();await restarts;await turns?.close();await Promise.allSettled([...notifications]);await adapter?.close();process.exit(0);}
process.once('SIGTERM',()=>void stop());process.once('SIGINT',()=>void stop());
restart();
