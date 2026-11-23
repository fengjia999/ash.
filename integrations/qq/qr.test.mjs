import test from 'node:test';
import assert from 'node:assert/strict';
import {QrSessions} from './qr.mjs';
test('QR progress is explicit; successful credentials stay in the private session',async()=>{
 let callbacks,disposed=0;
 const manager=new QrSessions((cb,options)=>{callbacks=cb;assert.equal(options.displayQrCodeToConsole,false);return ()=>disposed++;},async()=> 'data:image/png;base64,test');
 const {id}=manager.start();assert.equal(manager.read(id).status,'creating');
 callbacks.onQrDisplayed('https://q.qq.com/official-authorize');await new Promise(resolve=>setImmediate(resolve));
 assert.equal(manager.read(id).status,'waiting');assert(manager.read(id).image.startsWith('data:'));
 callbacks.onQrExpired();assert.equal(manager.read(id).image,'');assert.equal(manager.read(id).status,'creating');
 callbacks.onSuccess([{appId:'12345678',appSecret:'secret',userOpenid:'owner'}]);
 assert.equal(manager.read(id).status,'authorized');assert.equal(manager.read(id).credentials[0].appSecret,'secret');
 manager.cancel(id);assert.deepEqual(manager.read(id),{status:'expired'});assert.equal(disposed,1);
});
test('new QR sessions cancel earlier codes; expired sessions cannot return credentials',()=>{
 let time=0,disposed=0;
 const manager=new QrSessions(()=>()=>disposed++,()=>'',()=>time);
 const first=manager.start().id,second=manager.start().id;
 assert.equal(manager.read(first).status,'expired');assert.equal(disposed,1);
 time=600001;assert.equal(manager.read(second).status,'expired');assert.equal(disposed,2);
});
