import * as lark from '@larksuiteoapi/node-sdk';
import {randomBytes,randomUUID} from 'node:crypto';
import {feishuMessage} from './core.mjs';
import {FeishuDiagnostics} from './feishu-diagnostics.mjs';
const logger={debug(){},info(){},warn(){},error(){},trace(){}};
export function feishuOptions(config){
 if(config.feishuDomain!==undefined&&!['feishu','lark'].includes(config.feishuDomain))throw new Error('invalid platform');
 return {appId:config.appId,appSecret:config.appSecret,domain:config.feishuDomain==='lark'?lark.Domain.Lark:lark.Domain.Feishu,logger};
}
export class Feishu {
 constructor(config,onMessage,onState){this.config=config;this.onMessage=onMessage;this.onState=onState;this.session=null;}
 async start(){
  if(!this.config.appId||!this.config.appSecret)return;
  const options=feishuOptions(this.config);
  const diagnostic=new FeishuDiagnostics(this.onState);
  this.client=new lark.Client(options);
  this.ws=new lark.WSClient({...options,handshakeTimeoutMs:15000,
   httpInstance:{request:request=>diagnostic.request(request,lark.defaultHttpInstance)},
   logger:{...logger,error:(...args)=>diagnostic.log(...args)},
   onReady:()=>diagnostic.ready(),onReconnected:()=>diagnostic.ready(),
   onReconnecting:()=>diagnostic.reconnect(),onError:()=>diagnostic.terminal()});
  await this.ws.start({eventDispatcher:new lark.EventDispatcher({logger}).register({'im.message.receive_v1':event=>this.receive(event)})});
 }
 receive(event){
  const message=feishuMessage(event);if(!message)return;
  const session=this.session;
  if(session&&Date.now()<session.until&&session.status==='waiting'&&message.text.trim()===session.code){session.owner=message.sender;session.status='authorized';return;}
  if(this.config.enabled&&this.config.allowedUsers.includes(message.sender))this.onMessage(message);
 }

 connectionStatus(){const state=this.ws?.getConnectionStatus().state;return state==='connected'?'connected':state==='failed'?'error':'connecting';}
 async sendText(target,text){
  const result=await this.client.im.message.create({params:{receive_id_type:'open_id'},data:{receive_id:target.targetId,msg_type:'text',content:JSON.stringify({text}),uuid:randomUUID()}});
  if(result.code!==0)throw new Error('platform rejected');
 }
 async setup(){this.session={id:randomUUID(),status:'waiting',code:'ASH-'+randomBytes(5).toString('hex').toUpperCase(),until:Date.now()+600000};return this.session;}
 read(id){const s=this.session;return s&&s.id===id&&Date.now()<s.until?s:{status:'expired'};}
 cancel(id){if(this.session&&(!id||id===this.session.id))this.session=null;}
 async close(){this.ws?.close({force:true});this.cancel();}
}
