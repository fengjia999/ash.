export const WEIXIN_BASE='https://ilinkai.weixin.qq.com';
export function trustedWeixinBase(value){
 const url=new URL(value);
 if(url.protocol!=='https:'||!(url.hostname==='ilinkai.weixin.qq.com'||url.hostname.endsWith('.ilinkai.weixin.qq.com'))||url.username||url.password||url.port||url.pathname!=='/'||url.search||url.hash)throw new Error('untrusted base');
 return url.origin;
}
export function validateConfig(value){
 if(!value||!['feishu','weixin'].includes(value.provider)||typeof value.enabled!=='boolean'||typeof value.setupEnabled!=='boolean')throw new Error('invalid configuration');
 if(value.feishuDomain!==undefined&&!['feishu','lark'].includes(value.feishuDomain))throw new Error('invalid platform');
 for(const key of ['appId','appSecret','botToken','botId','gatewayUrl','gatewaySecret','stateFile'])if(typeof value[key]!=='string'||value[key].length>4096||/[\x00-\x1f\x7f]/.test(value[key]))throw new Error('invalid configuration');
 const url=new URL(value.gatewayUrl);
 if(url.protocol!=='http:'||url.hostname!=='127.0.0.1'||url.username||url.password||url.search||url.hash||url.pathname!=='/')throw new Error('invalid gateway');
 trustedWeixinBase(value.baseUrl);
 if(!Array.isArray(value.allowedUsers)||value.allowedUsers.length>1||value.allowedUsers.some(x=>typeof x!=='string'||!x||x.length>256))throw new Error('invalid owner');
 if(typeof value.timeEnabled!=='boolean'||!Number.isInteger(value.debounceSeconds)||value.debounceSeconds<0||value.debounceSeconds>300)throw new Error('invalid settings');
 return structuredClone(value);
}
export function feishuMessage(event){
 const message=event?.message, sender=event?.sender;
 if(message?.chat_type!=='p2p'||sender?.sender_type!=='user'||!sender.sender_id?.open_id||!message.message_id)return null;
 let content;try{content=JSON.parse(message.content);}catch{return null;}
 return {id:message.message_id,sender:sender.sender_id.open_id,text:message.message_type==='text'?String(content.text||''):'',unsupported:message.message_type!=='text'};
}
export function weixinMessage(message){
 if(message?.message_type!==1||message.group_id||!message.from_user_id||message.message_id===undefined)return null;
 const parts=Array.isArray(message.item_list)?message.item_list:[];
 return {id:String(message.message_id),sender:message.from_user_id,context:message.context_token,
  text:parts.filter(x=>x.type===1).map(x=>x.text_item?.text||'').join('\n'),unsupported:parts.some(x=>x.type!==1)};
}
