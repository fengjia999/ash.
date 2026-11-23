import test from 'node:test';
import assert from 'node:assert/strict';
import {setImmediate as tick} from 'node:timers/promises';
import {QQTurns} from './turns.mjs';

const snapshot={gatewayUrl:'http://127.0.0.1:8080',gatewaySecret:'secret',debounceSeconds:30,timeEnabled:true};
const message=(text,id)=>({content:text,messageId:id,senderId:'owner',replyTarget:{scope:'c2c',targetId:'owner',msgId:id}});
const answer=text=>new Response('data: '+JSON.stringify({choices:[{delta:{content:text}}]})+'\n\ndata: [DONE]\n\n',{headers:{'content-type':'text/event-stream'}});

test('QQ waits after the last input then replies in paced bubbles to the latest message',async t=>{
 t.mock.timers.enable({apis:['setTimeout']});
 const requests=[],sent=[],paces=[];
 const client={async sendText(target,text){sent.push({target,text});}};
 const turns=new QQTurns({fetchGateway:async(url,options)=>{requests.push(JSON.parse(options.body));return answer('你好\n\n第二段👀');},
  pacer:{async send(key,send){paces.push(key);await send();}},onError:error=>assert.fail(String(error))});
 turns.add(message('一','1'),client,snapshot,new Date('2026-10-31T04:00:00Z'));
 t.mock.timers.tick(20_000);await tick();assert.equal(requests.length,0);
 turns.add(message('二','2'),client,snapshot,new Date('2026-10-31T04:00:20Z'));
 t.mock.timers.tick(29_999);await tick();assert.equal(requests.length,0);
 t.mock.timers.tick(1);await turns.close();
 assert.equal(requests.length,1);
 assert.match(requests[0].messages[0].content,/12:00:00 星期六" \/>\n一\n二$/);
 assert.deepEqual(sent.map(item=>item.text),['你好','第二段👀']);
 assert.ok(sent.every(item=>item.target.msgId==='2'));assert.deepEqual(paces,['owner','owner']);
});

test('zero wait stays separate, later input queues during generation and failure does not block it',async()=>{
 const requests=[],sent=[],errors=[];let release;
 const gate=new Promise(resolve=>{release=resolve;});
 const client={async sendText(target,text){sent.push(text);}};
 const turns=new QQTurns({fetchGateway:async(url,options)=>{
  requests.push(JSON.parse(options.body));
  if(requests.length===1){await gate;throw new Error('failed');}
  return answer('好了');
 },pacer:{async send(key,send){await send();}},onError:error=>errors.push(error)});
 turns.add(message('first','1'),client,{...snapshot,debounceSeconds:0});await tick();
 turns.add(message('second','2'),client,{...snapshot,debounceSeconds:0});await tick();
 assert.equal(requests.length,1);release();await turns.close();
 assert.equal(requests.length,2);assert.equal(errors.length,1);assert.deepEqual(sent,['好了']);
});

test('notifications target only the bound owner and propagate partial-send failure',async()=>{
 const sent=[];
 const turns=new QQTurns({pacer:{async send(key,send){await send();}}});
 const config={enabled:true,allowedUsers:['owner']};
 const client={async sendText(target,text){sent.push({target,text});}};
 assert.equal(await turns.notify('one\ntwo',client,config),2);
 assert.deepEqual(sent,[{target:{scope:'c2c',targetId:'owner'},text:'one'},{target:{scope:'c2c',targetId:'owner'},text:'two'}]);
 await assert.rejects(turns.notify('hello',client,{...config,enabled:false}));
 await assert.rejects(turns.notify('x\n'.repeat(21),client,config));
 assert.equal(sent.length,2);
 let count=0;
 await assert.rejects(turns.notify('one\ntwo',{async sendText(){if(++count===2)throw new Error('rejected');}},config));
 assert.equal(count,2);
 await turns.close();
});
