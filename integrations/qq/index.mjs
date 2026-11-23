import {createServer} from 'node:http';
import {readFileSync} from 'node:fs';
import {timingSafeEqual} from 'node:crypto';
import {QQBot} from '@tencent-connect/qqbot-nodejs';
import {startQrConnect} from '@tencent-connect/qqbot-connector';
import QRCode from 'qrcode';
import {validateConfig,allowedMessage} from './core.mjs';
import {QrSessions} from './qr.mjs';
import {QQTurns} from './turns.mjs';

const bootstrap=JSON.parse(readFileSync(0,'utf8'));
let config=validateConfig(bootstrap.connection);
const managementToken=bootstrap.managementToken;
if(typeof managementToken!=='string'||managementToken.length<32)throw new Error('invalid supervisor token');
const qr=new QrSessions(startQrConnect,url=>QRCode.toDataURL(url,{width:280,margin:2,errorCorrectionLevel:'M'}));
let bot=null,status=config.enabled?'connecting':'disabled',error='',accepting=false,epoch=0,closing=false;
const createTurns=()=>new QQTurns({onError:()=>{error='gateway_unavailable';}});
let turns=createTurns(),restarts=Promise.resolve();
const seen=new Set();
const notifications=new Set();
const quiet={info(){},warn(){},error(){},debug(){}};

function restart(){
    const current=++epoch;accepting=false;status=config.enabled?'connecting':'disabled';error='';
    restarts=restarts.then(async()=>{
        if(current!==epoch||closing)return;
        await turns.close();turns=createTurns();
        await Promise.allSettled([...notifications]);
        if(bot)bot.stop();bot=null;
        if(!config.enabled)return;
        const snapshot=structuredClone(config);
        const client=new QQBot({appId:snapshot.appId,appSecret:snapshot.appSecret,logger:quiet,tokenPrefetch:'sync'});
        bot=client;
        client.on('ready',()=>{if(current===epoch){status='connected';error='';accepting=true;}});
        client.on('resumed',()=>{if(current===epoch){status='connected';error='';accepting=true;}});
        client.on('error',()=>{if(current===epoch){status='error';error='connection_failed';}});
        client.on('message',(_context,message)=>{
            if(!accepting||current!==epoch||!allowedMessage(message,snapshot)||seen.has(message.messageId))return;
            seen.add(message.messageId);
            if(seen.size>2048)seen.delete(seen.values().next().value);
            turns.add(message,client,snapshot);
        });
        void client.start().catch(()=>{if(current===epoch){status='error';error='connection_failed';accepting=false;}});
    }).catch(()=>{status='error';error='connection_failed';accepting=false;});
}
function authorized(request){
    const actual=Buffer.from(request.headers.authorization||''),expected=Buffer.from('Bearer '+managementToken);
    return actual.length===expected.length&&timingSafeEqual(actual,expected);
}
function json(response,code,data){response.writeHead(code,{'Content-Type':'application/json','Cache-Control':'no-store'});response.end(JSON.stringify(data));}
async function body(request){let size=0,chunks=[];for await(const chunk of request){size+=chunk.length;if(size>65536)throw new Error('body too large');chunks.push(chunk);}return JSON.parse(Buffer.concat(chunks).toString()||'{}');}
const server=createServer(async(request,response)=>{
    if(!authorized(request)){json(response,401,{error:'unauthorized'});return;}
    try{
        if(request.url==='/notify'&&request.method==='POST'){
            if(closing||!accepting||!config.enabled||!bot){json(response,409,{error:'connection_unavailable'});return;}
            const data=await body(request);
            const pending=turns.notify(data.text,bot,structuredClone(config));
            notifications.add(pending);
            try{const bubbles=await pending;json(response,200,{ok:true,bubbles});}
            finally{notifications.delete(pending);}
            return;
        }
        if(request.url==='/api/connection'){
            if(request.method==='PUT'){config=validateConfig(await body(request));restart();}
            else if(request.method!=='GET'){json(response,405,{error:'method_not_allowed'});return;}
            json(response,200,{status,error});return;
        }
        if(request.url==='/api/settings'){
            if(request.method==='PUT'){
                const settings=await body(request);
                config=validateConfig({...config,timeEnabled:settings.timeEnabled,debounceSeconds:settings.debounceSeconds});
            }else if(request.method!=='GET'){json(response,405,{error:'method_not_allowed'});return;}
            json(response,200,{timeEnabled:config.timeEnabled!==false,debounceSeconds:config.debounceSeconds??30});return;
        }
        if(request.url==='/qr'&&request.method==='POST'){
            const data=await body(request);json(response,200,qr.start(data.expectedAppId||''));return;
        }
        const match=/^\/qr\/([0-9a-f-]{36})$/.exec(request.url||'');
        if(match&&request.method==='GET'){json(response,200,qr.read(match[1]));return;}
        if(match&&request.method==='DELETE'){qr.cancel(match[1]);json(response,200,{status:'cancelled'});return;}
        json(response,404,{error:'not_found'});
    }catch{json(response,400,{error:'request_failed'});}
});
server.listen(0,'127.0.0.1',()=>{const address=server.address();console.log('[transport-ready]'+JSON.stringify({port:address.port}));});
async function stop(){if(closing)return;closing=true;accepting=false;qr.close();server.close();await restarts;await turns.close();await Promise.allSettled([...notifications]);if(bot)bot.stop();process.exit(0);}
process.once('SIGTERM',()=>void stop());process.once('SIGINT',()=>void stop());
if(config.enabled)restart();
