import assert from 'node:assert/strict';
import test from 'node:test';
import {validateConnection} from './connection.js';
const valid={enabled:true,projectId:'project',projectSecret:'secret',homeUser:'user@example.test',allowedUsers:['user@example.test'],gatewayUrl:'http://127.0.0.1:8080',gatewaySecret:'ash_bot_token'};
test('accepts supervisor configuration and normalizes the sender allowlist',()=>{
 assert.deepEqual(validateConnection(valid),valid);
 assert.deepEqual(validateConnection({...valid,allowedUsers:[' USER@example.test ','user@example.test']}).allowedUsers,['user@example.test']);
 assert.equal(validateConnection({...valid,enabled:false,projectSecret:''}).enabled,false);
});
test('rejects incomplete, unsafe and unexpected supervisor configuration',()=>{
 for(const value of [{...valid,projectSecret:''},{...valid,allowedUsers:[]},{...valid,allowedUsers:['x\ny']},{...valid,gatewayUrl:'file:///tmp/key'},
  {...valid,gatewayUrl:'https://key@host.test'},{...valid,gatewaySecret:'x\ny'},{...valid,unexpected:true}])assert.throws(()=>validateConnection(value));
});
