import test from 'node:test';
import assert from 'node:assert/strict';
import {allowedMessage,gatewayContent,gatewayBatchContent,validateConfig} from './core.mjs';
const config={enabled:true,appId:'12345678',appSecret:'secret',allowedUsers:['owner'],gatewayUrl:'http://127.0.0.1:8080',gatewaySecret:'ash_bot_qq:secret'};
test('only the QR owner private chat is accepted',()=>{
 const msg={kind:'c2c',senderId:'owner',replyTarget:{scope:'c2c',targetId:'owner'}};
 assert.equal(allowedMessage(msg,config),true);
 assert.equal(allowedMessage({...msg,senderId:'stranger'},config),false);
 assert.equal(allowedMessage({...msg,kind:'group'},config),false);
 assert.equal(allowedMessage({...msg,replyTarget:{scope:'c2c',targetId:'stranger'}},config),false);
 assert.equal(allowedMessage(msg,{...config,enabled:false}),false);
});
test('validates supervisor configuration and sends a single message to shared Ash',()=>{
 assert.deepEqual(validateConfig(config),config);
 for(const invalid of [{...config,appSecret:''},{...config,gatewayUrl:'https://attacker.test'},
 {...config,allowedUsers:[]},{...config,appSecret:'a\nb'}])assert.throws(()=>validateConfig(invalid));
 assert.equal(gatewayContent({content:'hello'},{timeEnabled:false}),'<conversation_path="QQ" />\nhello');
 assert.equal(gatewayContent({content:''}),null);
 const content=gatewayContent({content:'看看',attachments:[{content_type:'image/png',url:'https://qq.test/image.png'}]});
 assert.equal(content[1].image_url.url,'https://qq.test/image.png');
});
test('batch has one Shanghai timestamp, natural text order and preserves images',()=>{
 const receivedAt=new Date('2026-10-31T04:00:00Z'),snapshot={timeEnabled:true};
 const content=gatewayBatchContent([
  {message:{content:'第一行\n第二行'},snapshot,receivedAt},
  {message:{content:'还有这张',attachments:[{content_type:'image/png',url:'https://qq.test/1.png'}]},snapshot,receivedAt:new Date('2026-10-31T04:00:10Z')},
 ]);
 assert.equal(content[0].text,'<conversation_path="QQ" current_time="2026-10-31 12:00:00 星期六" />\n第一行\n第二行');
 assert.equal(content[1].text,'还有这张');
 assert.equal(content[2].type,'image_url');
 assert.equal(JSON.stringify(content).match(/current_time/g).length,1);
 assert.equal(gatewayBatchContent([{message:{content:''},snapshot,receivedAt},{message:{content:'hi'},snapshot:{timeEnabled:false},receivedAt}]),'<conversation_path="QQ" />\nhi');
 for(const value of [{...config,timeEnabled:1},{...config,debounceSeconds:-1},{...config,debounceSeconds:301},{...config,debounceSeconds:1.2}])assert.throws(()=>validateConfig(value));
});
