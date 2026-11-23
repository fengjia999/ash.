import test from 'node:test';
import assert from 'node:assert/strict';
import {FeishuDiagnostics} from './feishu-diagnostics.mjs';
import {Feishu} from './feishu.mjs';
import {defaultHttpInstance} from '@larksuiteoapi/node-sdk';

test('endpoint failures and handshake failures remain distinct without leaking SDK data',async()=>{
 const states=[],diagnostic=new FeishuDiagnostics((...state)=>states.push(state));
 await diagnostic.request({}, {request:async()=>({code:1000040343,msg:'secret-value'})});
 diagnostic.log(['[ws]','connect failed']);diagnostic.terminal();
 assert.equal(states.at(-1)[1],'feishu_endpoint_platform_1000040343');
 for(const [error,expected] of [[{code:'ENOTFOUND'},'dns'],[{code:'ECONNABORTED'},'timeout'],[{response:{status:403}},'http_403'],[{message:'secret-value'},'network']]){
  await assert.rejects(diagnostic.request({}, {request:async()=>{throw Object.assign(new Error('secret-value'),error);}}));
  assert.equal(states.at(-1)[1],'feishu_endpoint_'+expected);
 }
 await diagnostic.request({}, {request:async()=>({code:0,data:{URL:'wss://example.test/?ticket=secret-value'}})});
 diagnostic.log(['[ws]','ws connect failed']);
 assert.equal(states.at(-1)[1],'feishu_ws_handshake_failed');
 diagnostic.log(['[ws]','handshake timeout after 15000ms']);diagnostic.terminal();
 assert.equal(states.at(-1)[1],'feishu_ws_handshake_timeout');
 diagnostic.ready();assert.deepEqual(states.at(-1),['connected','']);
 assert(!JSON.stringify(states).includes('secret-value'));
});

test('actual SDK surfaces endpoint rejection through the adapter',async t=>{
 const states=[];
 t.mock.method(defaultHttpInstance,'request',async options=>{
  assert.match(options.url,/open\.larksuite\.com\/callback\/ws\/endpoint$/);
  assert.equal(options.data.AppSecret,'private-secret');
  return {code:4003,msg:'private-secret',data:{}};
 });
 const adapter=new Feishu({appId:'cli_0123456789abcdef',appSecret:'private-secret',feishuDomain:'lark'},()=>{},(...state)=>states.push(state));
 try{
  await adapter.start();
  for(let i=0;i<50&&adapter.connectionStatus()!=='error';i++)await new Promise(resolve=>setTimeout(resolve,10));
  assert.equal(adapter.connectionStatus(),'error');
  assert.equal(states.at(-1)[1],'feishu_endpoint_platform_4003');
  assert(!JSON.stringify(states).includes('private-secret'));
 }finally{await adapter.close();}
});
