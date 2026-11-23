import {gatewayBatchContent} from './core.mjs';
import {InboundBatcher} from '../photon/dist/inbound-batcher.js';
import {splitBubbles} from '../photon/dist/bubbles.js';
import {BubblePacer} from '../photon/dist/bubble-pacer.js';
import {readGatewayStream} from '../photon/dist/gateway-stream.js';

// QQ and iMessage share the same quiet-period collection and bubble rules.
export class QQTurns {
    constructor({fetchGateway=fetch,pacer=new BubblePacer(2000),onError=()=>{}}={}) {
        this.fetchGateway=fetchGateway;this.pacer=pacer;this.tail=Promise.resolve();
        this.batcher=new InboundBatcher(items=>{
            const turn=this.tail.then(()=>this.reply(items));
            this.tail=turn.catch(onError);
            return this.tail;
        },onError);
    }
    add(message,client,snapshot,receivedAt=new Date()) {
        this.batcher.add(message.senderId,{message,client,snapshot,receivedAt},(snapshot.debounceSeconds??30)*1000);
    }
    async reply(items) {
        const content=gatewayBatchContent(items);
        if(content===null)return;
        const {message,client,snapshot}=items.at(-1);
        const response=await this.fetchGateway(snapshot.gatewayUrl+'/v1/chat/completions',{
            method:'POST',headers:{Authorization:'Bearer '+snapshot.gatewaySecret,'Content-Type':'application/json'},
            body:JSON.stringify({stream:true,messages:[{role:'user',content}]}),signal:AbortSignal.timeout(300000),
        });
        if(!response.ok)throw new Error('gateway unavailable');
        const result=await readGatewayStream(response);
        if(result.assistant.tool_calls?.length)throw new Error('unexpected frontend tools');
        for(const bubble of splitBubbles(String(result.assistant.content||''))) {
            await this.pacer.send(message.senderId,()=>client.sendText(message.replyTarget,bubble));
        }
    }
    async close() {await this.batcher.close();await this.tail;}
    async notify(text,client,config) {
        if(!config.enabled || !config.allowedUsers?.length)throw new Error('disabled');
        if(typeof text!=='string'||!text.trim()||text.trim().length>12000)throw new Error('invalid text');
        const bubbles=splitBubbles(text);
        if(bubbles.length>20)throw new Error('too many bubbles');
        // No msgId: use the SDK's proactive send path, bound to the QR owner.
        // Do not queue behind the model turn: that turn may be calling this tool.
        const target={scope:'c2c',targetId:config.allowedUsers[0]};
        for(const bubble of bubbles)await this.pacer.send(target.targetId,()=>client.sendText(target,bubble));
        return bubbles.length;
    }
}
