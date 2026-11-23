// Return only fixed diagnostic codes; SDK errors can contain credentials or WS tickets.
export class FeishuDiagnostics {
 constructor(onState){this.onState=onState;this.lastError='';this.stage='endpoint';}
 fail(code){this.lastError=code;this.onState('error',code);}
 ready(){this.lastError='';this.onState('connected','');}
 reconnect(){this.onState('connecting',this.lastError);}
 terminal(){this.fail(this.lastError||(this.stage==='endpoint'?'feishu_endpoint_failed':'feishu_ws_handshake_failed'));}
 async request(options,transport){
  this.stage='endpoint';
  try{
   const result=await transport.request(options);
   if(Number.isSafeInteger(result?.code)&&result.code!==0){this.fail('feishu_endpoint_platform_'+result.code);}
   else if(result?.code!==0||typeof result?.data?.URL!=='string'||!result.data.URL.startsWith('wss://')){this.fail('feishu_endpoint_invalid');}
   else{this.stage='handshake';this.lastError='';this.onState('connecting','');}
   return result;
  }catch(error){
   const status=error?.response?.status;
   if(Number.isInteger(status)&&status>=100&&status<=599)this.fail('feishu_endpoint_http_'+status);
   else if(['ENOTFOUND','EAI_AGAIN'].includes(error?.code))this.fail('feishu_endpoint_dns');
   else if(['ETIMEDOUT','ECONNABORTED'].includes(error?.code))this.fail('feishu_endpoint_timeout');
   else this.fail('feishu_endpoint_network');
   throw error;
  }
 }
 log(...values){
  const parts=values.flat(2).filter(value=>typeof value==='string');
  if(!parts.includes('[ws]'))return;
  if(parts.includes('handshake timeout after 15000ms'))this.fail('feishu_ws_handshake_timeout');
  else if(parts.some(value=>['connect failed','new WebSocket error','ws connect failed'].includes(value))&&!this.lastError)this.fail(this.stage==='handshake'?'feishu_ws_handshake_failed':'feishu_endpoint_failed');
 }
}
