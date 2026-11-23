import {randomUUID} from 'node:crypto';

export class QrSessions {
    constructor(startConnect, encodeImage, now=Date.now) { this.startConnect=startConnect;this.encodeImage=encodeImage;this.now=now;this.sessions=new Map(); }
    start(expectedAppId='') {
        this.close();
        const id=randomUUID(), session={id,status:'creating',image:'',credentials:[],created:this.now(),version:0,dispose:()=>{}};
        this.sessions.set(id,session);
        session.dispose=this.startConnect({
            onQrDisplayed:url=>{
                const version=++session.version;
                session.status='creating';session.image='';
                Promise.resolve(this.encodeImage(url)).then(image=>{
                    if(this.sessions.get(id)===session&&version===session.version){session.image=image;session.status='waiting';}
                }).catch(()=>{session.status='failed';});
            },
            onQrExpired:()=>{session.version++;session.image='';session.status='creating';},
            onSuccess:credentials=>{
                session.version++;session.status='authorized';session.image='';
                session.credentials=Array.isArray(credentials)?credentials:[];
            },
            onFailure:()=>{session.version++;session.status='failed';session.image='';session.credentials=[];},
        },{displayQrCodeToConsole:false,source:'ash'});
        return {id,status:session.status};
    }
    read(id) {
        const session=this.sessions.get(id);
        if(!session)return {status:'expired'};
        if(this.now()-session.created>600000){this.cancel(id);return {status:'expired'};}
        return {status:session.status,image:session.image,...(session.status==='authorized'?{credentials:structuredClone(session.credentials)}:{})};
    }
    cancel(id) {const session=this.sessions.get(id);this.sessions.delete(id);session?.dispose();}
    close(){for(const id of this.sessions.keys())this.cancel(id);}
}
