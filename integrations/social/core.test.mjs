import test from 'node:test';
import assert from 'node:assert/strict';
import {trustedWeixinBase,feishuMessage,weixinMessage,validateConfig} from './core.mjs';
import {gatewayBatchContent} from '../qq/core.mjs';
const event={sender:{sender_type:'user',sender_id:{open_id:'owner'}},message:{chat_type:'p2p',message_id:'m1',message_type:'text',content:'{"text":"hello"}'}};
test('only private human messages are normalized',()=>{
 assert.equal(feishuMessage(event).text,'hello');
 assert.equal(feishuMessage({...event,message:{...event.message,chat_type:'group'}}),null);
 assert.equal(feishuMessage({...event,sender:{...event.sender,sender_type:'app'}}),null);
 const wx={message_type:1,message_id:1,from_user_id:'owner',context_token:'context',item_list:[{type:1,text_item:{text:'hello'}}]};
 assert.equal(weixinMessage(wx).context,'context');assert.equal(weixinMessage({...wx,group_id:'group'}),null);assert.equal(weixinMessage({...wx,message_type:2}),null);
 assert.equal(weixinMessage({...wx,item_list:[{type:2}]}).unsupported,true);
});
test('redirect and credential bases are confined to the official HTTPS service',()=>{
 assert.equal(trustedWeixinBase('https://ilinkai.weixin.qq.com'),'https://ilinkai.weixin.qq.com');
 for(const url of ['http://ilinkai.weixin.qq.com','https://evil.test','https://ilinkai.weixin.qq.com.evil.test','https://user:pass@ilinkai.weixin.qq.com','https://ilinkai.weixin.qq.com:1234','https://ilinkai.weixin.qq.com/other'])assert.throws(()=>trustedWeixinBase(url));
});
test('social messages retain first timestamp and platform without numbering',()=>{
 for(const platform of ['飞书','微信']){
  const items=['one','two'].map(content=>({message:{content},receivedAt:new Date('2026-10-31T04:00:00Z'),snapshot:{timeEnabled:true,platform}}));
  const body=gatewayBatchContent(items);assert.match(body,new RegExp('conversation_path="'+platform+'"'));assert.equal(body.match(/current_time/g).length,1);assert.ok(body.endsWith('one\ntwo'));
 }
});
