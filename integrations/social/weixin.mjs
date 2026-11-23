import {randomBytes,randomUUID} from 'node:crypto';
import {readFileSync,writeFileSync,renameSync} from 'node:fs';
import QRCode from 'qrcode';
import {WEIXIN_BASE,trustedWeixinBase,weixinMessage} from './core.mjs';
const version='2.4.8';
export async function weixinRequest(base,path,{token='',body,signal,fetcher=fetch}={}){
 const headers={'iLink-App-Id':'bot','iLink-App-ClientVersion':String(0x020408)};
 if(body!==undefined){headers['Content-Type']='application/json';headers.AuthorizationType='ilink_bot_token';headers['X-WECHAT-UIN']=Buffer.from(String(randomBytes(4).readUInt32BE())).toString('base64');}
 if(token)headers.Authorization='Bearer '+token;
 const response=await fetcher(trustedWeixinBase(base)+path,{method:body===undefined?'GET':'POST',headers,body:body===undefined?undefined:JSON.stringify(token?{...body,base_info:{channel_version:version,bot_agent:'Ash/1.0'}}:body),signal:signal||AbortSignal.timeout(45000),redirect:'error'});
 if(!response.ok)throw new Error('platform unavailable');
 const data=await response.json();
 if(data.ret||data.errcode){const error=new Error('platform rejected');error.expired=data.ret===-14||data.errcode===-14;throw error;}
 return data;
}
export class Weixin {
 constructor(config,onMessage,onState){this.config=config;this.onMessage=onMessage;this.onState=onState;this.controller=new AbortController();this.session=null;this.state={botId:config.botId,cursor:'',context:{}};
  try{const saved=JSON.parse(readFileSync(config.stateFile,'utf8'));if(saved.botId===config.botId&&typeof saved.cursor==='string'&&saved.context&&typeof saved.context==='object')this.state=saved;}catch{}
 }
 save(){const file=this.config.stateFile;writeFileSync(file+'.tmp',JSON.stringify(this.state),{mode:0o600});renameSync(file+'.tmp',file);}
 async start(){if(this.config.enabled&&this.config.botToken)this.loop();}
 async loop(){
  const signal=this.controller.signal;
  while(!signal.aborted){
   try{
    const data=await weixinRequest(this.config.baseUrl,'/ilink/bot/getupdates',{token:this.config.botToken,body:{get_updates_buf:this.state.cursor},signal:AbortSignal.any([signal,AbortSignal.timeout(45000)])});
    if(signal.aborted)return;
    this.onState('connected','');
    for(const raw of data.msgs||[]){const msg=weixinMessage(raw);if(!msg||!this.config.allowedUsers.includes(msg.sender))continue;
     if(typeof msg.context==='string'&&msg.context)this.state.context[msg.sender]=msg.context;
     this.onMessage(msg);
    }
    if(typeof data.get_updates_buf==='string'&&data.get_updates_buf)this.state.cursor=data.get_updates_buf;
    this.save();
   }catch(error){if(signal.aborted)return;this.onState('error',error.expired?'session_expired':'connection_failed');if(error.expired)return;await new Promise(resolve=>{const timer=setTimeout(done,5000);function done(){clearTimeout(timer);signal.removeEventListener('abort',done);resolve();}signal.addEventListener('abort',done,{once:true});});}
  }
 }
 async sendText(target,text){
  const context=target.contextToken||this.state.context[target.targetId];
  if(!context)throw new Error('send a message in Weixin first');
  await weixinRequest(this.config.baseUrl,'/ilink/bot/sendmessage',{token:this.config.botToken,body:{msg:{from_user_id:'',to_user_id:target.targetId,client_id:randomUUID(),message_type:2,message_state:2,context_token:context,item_list:[{type:1,text_item:{text}}]}}});
 }
 async setup(){
  this.cancel();const session={id:randomUUID(),status:'creating',until:Date.now()+600000,controller:new AbortController(),base:WEIXIN_BASE,verify:''};this.session=session;
  this.login(session).catch(()=>{if(!session.controller.signal.aborted)session.status='failed';});
  return {id:session.id,status:session.status};
 }
 async login(session){
  const data=await weixinRequest(WEIXIN_BASE,'/ilink/bot/get_bot_qrcode?bot_type=3',{body:{local_token_list:[]},signal:AbortSignal.any([session.controller.signal,AbortSignal.timeout(15000)])});
  if(typeof data.qrcode!=='string'||typeof data.qrcode_img_content!=='string'||data.qrcode_img_content.length>8192)throw new Error('invalid QR');
  session.image=await QRCode.toDataURL(data.qrcode_img_content,{width:280,margin:2});session.status='waiting';
  while(!session.controller.signal.aborted&&Date.now()<session.until){
   const query=new URLSearchParams({qrcode:data.qrcode});if(session.verify)query.set('verify_code',session.verify);
   let result;
   try{result=await weixinRequest(session.base,'/ilink/bot/get_qrcode_status?'+query,{signal:AbortSignal.any([session.controller.signal,AbortSignal.timeout(40000)])});}
   catch(error){if(error.name==='TimeoutError'&&!session.controller.signal.aborted)continue;throw error;}
   if(result.status==='confirmed'){
    session.status='authorized';session.owner=result.ilink_user_id;session.bot_token=result.bot_token;session.bot_id=result.ilink_bot_id;session.base_url=trustedWeixinBase(result.baseurl||session.base);return;
   }
   if(result.status==='scaned_but_redirect'&&result.redirect_host){session.base=trustedWeixinBase('https://'+result.redirect_host);}
   else if(result.status==='expired'||result.status==='verify_code_blocked'){session.status='expired';return;}
   else session.status=result.status==='need_verifycode'?'need_verifycode':result.status==='scaned'?'scanned':'waiting';
   await new Promise(resolve=>setTimeout(resolve,1000));
  }
  session.status='expired';
 }
 read(id,code){const s=this.session;if(!s||s.id!==id||Date.now()>s.until)return {status:'expired'};if(code)s.verify=code;const {controller,base,verify,...value}=s;return value;}
 cancel(id){if(this.session&&(!id||id===this.session.id)){this.session.controller.abort();this.session=null;}}
 async close(){this.controller.abort();this.cancel();}
}
