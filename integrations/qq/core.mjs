export function validateConfig(value) {
    if (!value || typeof value !== 'object' || Array.isArray(value) || typeof value.enabled !== 'boolean') throw new Error('invalid configuration');
    for (const key of ['appId','appSecret','gatewayUrl','gatewaySecret']) {
        if (typeof value[key] !== 'string' || value[key].length > 2000 || /[\x00-\x1f\x7f]/.test(value[key])) throw new Error('invalid configuration');
    }
    const url = new URL(value.gatewayUrl);
    if (url.protocol !== 'http:' || url.hostname !== '127.0.0.1' || url.username || url.password || url.search || url.hash) throw new Error('invalid gateway');
    if (!Array.isArray(value.allowedUsers) || value.allowedUsers.length > 50 || value.allowedUsers.some(v=>typeof v!=='string'||!v||v.length>200)) throw new Error('invalid allowlist');
    if (value.enabled && (!/^[0-9]{5,20}$/.test(value.appId) || !value.appSecret || !value.allowedUsers.length)) throw new Error('incomplete configuration');
    if (value.timeEnabled !== undefined && typeof value.timeEnabled !== 'boolean') throw new Error('invalid time setting');
    if (value.debounceSeconds !== undefined && (!Number.isInteger(value.debounceSeconds) || value.debounceSeconds < 0 || value.debounceSeconds > 300)) throw new Error('invalid wait setting');
    return structuredClone(value);
}

export function allowedMessage(message, config) {
    return !!(config.enabled && message.kind === 'c2c' && config.allowedUsers.includes(message.senderId)
        && message.replyTarget?.scope === 'c2c' && message.replyTarget.targetId === message.senderId);
}

const timeFormatter = new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',weekday:'long',hourCycle:'h23'});

export function gatewayContent(message, {timeEnabled=true, receivedAt=new Date(), prefixEnabled=true, platform='QQ'}={}) {
    const text = String(message.content || '').trim();
    const parts=Object.fromEntries(timeFormatter.formatToParts(receivedAt).map(({type,value})=>[type,value]));
    const time=`${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}:${parts.second} ${parts.weekday}`;
    const prefix = !prefixEnabled ? '' : timeEnabled ? `<conversation_path="${platform}" current_time="${time}" />\n` : `<conversation_path="${platform}" />\n`;
    const images = (message.attachments || []).filter(item=>/^image\//.test(item.content_type || '') && /^https:\/\//.test(item.url || '')).slice(0,4);
    if (!text && !images.length) return null;
    if (!images.length) return prefix + text;
    return [{type:'text',text:prefix + text},...images.map(item=>({type:'image_url',image_url:{url:item.url}}))];
}

export function gatewayBatchContent(items) {
    const blocks=[];
    for(const item of items){
        const content=gatewayContent(item.message,{timeEnabled:item.snapshot.timeEnabled!==false,receivedAt:item.receivedAt,prefixEnabled:blocks.length===0,platform:item.snapshot.platform||'QQ'});
        if(content!==null)blocks.push(...(typeof content==='string'?[{type:'text',text:content}]:content));
    }
    if(!blocks.length)return null;
    return blocks.every(block=>block.type==='text')?blocks.map(block=>block.text).join('\n'):blocks;
}
