import test from 'node:test';
import assert from 'node:assert/strict';
import {setImmediate as tick} from 'node:timers/promises';
import {Feishu,feishuOptions} from './feishu.mjs';
import {Domain} from '@larksuiteoapi/node-sdk';
import {Weixin,weixinRequest} from './weixin.mjs';
const event=(sender,text)=>({sender:{sender_type:'user',sender_id:{open_id:sender}},message:{chat_type:'p2p',message_id:'m1',message_type:'text',content:JSON.stringify({text})}});
test('Feishu and Lark use their own SDK domains; existing settings retain Feishu',()=>{
 assert.equal(feishuOptions({}).domain,Domain.Feishu);
 assert.equal(feishuOptions({feishuDomain:'feishu'}).domain,Domain.Feishu);
 assert.equal(feishuOptions({feishuDomain:'lark'}).domain,Domain.Lark);
 assert.throws(()=>feishuOptions({feishuDomain:'https://other.test'}));
});
test('Feishu pairing requires the exact one-time code, then only accepts the bound user',async()=>{
 const received=[],adapter=new Feishu({enabled:true,allowedUsers:['owner']},message=>received.push(message),()=>{});
 const session=await adapter.setup();adapter.receive(event('other','hello'));assert.equal(received.length,0);assert.equal(adapter.read(session.id).status,'waiting');
 adapter.receive(event('owner',session.code));assert.equal(adapter.read(session.id).owner,'owner');assert.equal(received.length,0);
 adapter.receive(event('other','hello'));adapter.receive(event('owner','hello'));assert.equal(received.length,1);
 adapter.cancel(session.id);assert.equal(adapter.read(session.id).status,'expired');await adapter.close();
});
test('Feishu checks platform errors and targets the bound user by open_id',async()=>{
 const adapter=new Feishu({},()=>{},()=>{});let args;
 adapter.client={im:{message:{create:async value=>{args=value;return {code:0};}}}};
 await adapter.sendText({targetId:'owner'},'hello');assert.equal(args.params.receive_id_type,'open_id');assert.equal(args.data.receive_id,'owner');
 adapter.client.im.message.create=async()=>({code:999});await assert.rejects(adapter.sendText({targetId:'owner'},'hello'));
});
test('Weixin QR authorizes without exposing a token until confirmation; cancel removes the session',async t=>{
 let calls=0;
 t.mock.method(globalThis,'fetch',async(url,options)=>{
  calls++;
  if(url.includes('get_bot_qrcode')){assert.equal(options.method,'POST');assert.equal(options.headers.Authorization,undefined);return Response.json({qrcode:'qr-id',qrcode_img_content:'https://weixin.qq.com/test'});}
  assert.equal(options.method,'GET');if(calls===2)throw new DOMException('long poll timeout','TimeoutError');return Response.json({status:'confirmed',bot_token:'private-token',ilink_bot_id:'bot',ilink_user_id:'owner',baseurl:'https://ilinkai.weixin.qq.com'});
 });
 const adapter=new Weixin({stateFile:'/nonexistent/ash-unit-test',botId:''},()=>{},()=>{});
 const first=await adapter.setup();assert.equal(first.bot_token,undefined);
 for(let i=0;i<100&&adapter.read(first.id).status!=='authorized';i++)await new Promise(resolve=>setTimeout(resolve,10));
 const result=adapter.read(first.id);assert.equal(result.status,'authorized');assert.equal(result.owner,'owner');assert.ok(result.image.startsWith('data:image/png;base64,'));assert.equal(calls,3);
 adapter.cancel(first.id);assert.equal(adapter.read(first.id).status,'expired');await adapter.close();
});
test('Weixin sends context back, detects expired sessions, and never sends without context',async t=>{
 let payload;
 t.mock.method(globalThis,'fetch',async(url,options)=>{payload=JSON.parse(options.body);assert.equal(options.headers.Authorization,'Bearer secret');return Response.json({ret:0});});
 const adapter=new Weixin({stateFile:'/nonexistent/ash-unit-test',botId:'bot',baseUrl:'https://ilinkai.weixin.qq.com',botToken:'secret'},()=>{},()=>{});
 await assert.rejects(adapter.sendText({targetId:'owner'},'hello'));
 await adapter.sendText({targetId:'owner',contextToken:'context'},'hello');assert.equal(payload.msg.context_token,'context');assert.equal(payload.msg.to_user_id,'owner');assert.equal(payload.msg.item_list[0].text_item.text,'hello');
 await assert.rejects(weixinRequest('https://ilinkai.weixin.qq.com','/test',{body:{},fetcher:async()=>Response.json({ret:-14})}),error=>error.expired);
 await adapter.close();
});
