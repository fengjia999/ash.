/* One canvas scene; no image downloads, persistent state or background timer. */
(() => {
    'use strict';
    const dialog = document.getElementById('ash-opening');
    if (!dialog) return;
    const canvas = dialog.querySelector('canvas'), ctx = canvas.getContext('2d');
    const reduced = matchMedia('(prefers-reduced-motion: reduce)');
    const layer = () => document.createElement('canvas');
    const clean = layer(), fog = layer(), moisture = layer(), grain = layer(), wiped = layer(), lens = layer();
    lens.width=lens.height=40;
    const lensContext=lens.getContext('2d');
    const lensPixels=lensContext?.createImageData(40,40);
    let scenePixels=null;
    wiped.width=256;wiped.height=512;
    const wipeMask = wiped.getContext('2d');
    const base = clean.getContext('2d'), mist = fog.getContext('2d'), wet = moisture.getContext('2d');
    let width = 0, height = 0, ratio = 1, fontSize = 0, letterY = 0, frame = 0, last = 0;
    let pointer = null, samples = [], drops = [], beads = [], trails = [], leaving = false, disposed = false;
    let water = 0, releaseVolume = 0, lastRelease = -Infinity, rainIn = 1;
    const random = (min,max) => min + Math.random() * (max-min);
    const brush = () => Math.max(25,Math.min(42,width*.075));
    const abort = new AbortController(), options = {signal:abort.signal};
    function cleanup() {
        if (disposed) return;
        disposed = true; cancelAnimationFrame(frame); observer.disconnect(); abort.abort();
        for (const surface of [canvas,clean,fog,moisture,grain,wiped,lens]) surface.width = surface.height = 0;
        drops = []; beads = []; trails = []; samples = []; scenePixels=null; dialog.remove();
    }
    function enter() {
        if (leaving) return;
        leaving = true; pointer = null; cancelAnimationFrame(frame);
        window.AshPhone?.navigate('home');
        dialog.classList.add('is-leaving');
        if (reduced.matches) { dialog.close(); cleanup(); }
        else { dialog.addEventListener('transitionend', cleanup, {once:true}); setTimeout(cleanup,750); }
    }
    const observer = new ResizeObserver(() => {
        if (!leaving && (dialog.clientWidth !== width || dialog.clientHeight !== height)) build();
    });
    function erase(a,b,r,target=mist,remove=true) {
        target.save(); target.globalCompositeOperation = remove ? 'destination-out' : 'source-over';
        // Soft outer moisture, with a clear finger-width centre.
        const distance = Math.hypot(b.x-a.x,b.y-a.y), steps = Math.max(1,Math.ceil(distance/(r*.32)));
        for (let i=0;i<=steps;i++) {
            const x=a.x+(b.x-a.x)*i/steps,y=a.y+(b.y-a.y)*i/steps;
            const edge=target.createRadialGradient(x,y,r*.68,x,y,r);
            edge.addColorStop(0,'rgba(0,0,0,1)');edge.addColorStop(.55,'rgba(0,0,0,.7)');edge.addColorStop(1,'rgba(0,0,0,0)');
            target.fillStyle=edge;target.beginPath();target.arc(x,y,r,0,Math.PI*2);target.fill();
        }
        target.restore();
    }
    function distanceToStroke(point,a,b) {
        const dx=b.x-a.x,dy=b.y-a.y,length=dx*dx+dy*dy;
        const t=length ? Math.max(0,Math.min(1,((point.x-a.x)*dx+(point.y-a.y)*dy)/length)) : 0;
        return (point.x-a.x-t*dx)**2+(point.y-a.y-t*dy)**2;
    }
    function mark(a,b) {
        const radius=brush()*.76;
        for(const point of samples)if(!point.clear && distanceToStroke(point,a,b)<radius*radius)point.clear=true;
    }
    function paintFrost() {
        // Blur pixels once at low resolution. Canvas filter is not reliable on
        // all installed Safari versions; never let sharp letter ink leak out.
        const small=layer(),scale=Math.min(128/width,256/height);
        small.width=Math.max(1,Math.round(width*scale));small.height=Math.max(1,Math.round(height*scale));
        const context=small.getContext('2d'),w=small.width,h=small.height;
        context.drawImage(clean,0,0,w,h);
        const image=context.getImageData(0,0,w,h),radius=Math.max(2,Math.round(Math.max(8,width*.023)*scale));
        let input=image.data,output=new Uint8ClampedArray(input.length);
        // Three separable box passes approximate a soft Gaussian frost.
        for(let pass=0;pass<3;pass++)for(const horizontal of [true,false]) {
            const length=horizontal?w:h,lines=horizontal?h:w,stride=horizontal?4:w*4;
            for(let line=0;line<lines;line++)for(let channel=0;channel<4;channel++) {
                const origin=(horizontal?line*w*4:line*4)+channel;let sum=0;
                for(let n=-radius;n<=radius;n++)sum+=input[origin+Math.max(0,Math.min(length-1,n))*stride];
                for(let n=0;n<length;n++) {
                    output[origin+n*stride]=sum/(radius*2+1);
                    sum+=input[origin+Math.min(length-1,n+radius+1)*stride]-input[origin+Math.max(0,n-radius)*stride];
                }
            }
            [input,output]=[output,input];
        }
        image.data.set(input);context.putImageData(image,0,0);
        mist.drawImage(small,0,0,width,height);small.width=small.height=0;
    }
    function build() {
        width=dialog.clientWidth;height=dialog.clientHeight;
        if(!width || !height)return;
        // Cap backing pixels on large screens and high-DPR phones.
        ratio=Math.min(devicePixelRatio || 1,2,Math.sqrt(1500000/(width*height)));
        for(const surface of [canvas,clean,fog,moisture]){surface.width=Math.round(width*ratio);surface.height=Math.round(height*ratio);surface.getContext('2d').setTransform(ratio,0,0,ratio,0,0);}
        wipeMask.setTransform(wiped.width/width,0,0,wiped.height/height,0,0);
        const shade=base.createLinearGradient(0,0,width,height);
        shade.addColorStop(0,'#59605e');shade.addColorStop(.43,'#959c98');shade.addColorStop(1,'#c1c4bd');
        base.fillStyle=shade;base.fillRect(0,0,width,height);
        const glow=base.createRadialGradient(width*.77,height*.19,0,width*.7,height*.25,height*.8);
        glow.addColorStop(0,'rgba(241,244,230,.65)');glow.addColorStop(1,'rgba(180,190,175,0)');
        base.fillStyle=glow;base.fillRect(0,0,width,height);
        fontSize=Math.min(width*.43,220);letterY=height*.59;
        base.font=`500 ${fontSize}px Georgia, 'Times New Roman', serif`;base.textAlign='center';base.textBaseline='middle';
        base.fillStyle='rgba(23,35,31,.78)';base.fillText('Ash',width/2,letterY);
        // Read the sharp scene once per resize, never once per animation frame.
        scenePixels=base.getImageData(0,0,clean.width,clean.height).data;
        // Sample only letter ink: wiping unrelated glass cannot unlock the page.
        const glyph=layer();glyph.width=Math.ceil(width);glyph.height=Math.ceil(fontSize*1.4);
        const ink=glyph.getContext('2d');ink.font=base.font;ink.textAlign='center';ink.textBaseline='middle';ink.fillText('Ash',width/2,glyph.height/2);
        const pixels=ink.getImageData(0,0,glyph.width,glyph.height).data;
        const wordWidth=ink.measureText('Ash').width,wordStart=(width-wordWidth)/2;
        const boundaries=[wordStart+ink.measureText('A').width,wordStart+ink.measureText('As').width];
        samples=[];
        for(let y=0;y<glyph.height;y+=4)for(let x=0;x<glyph.width;x+=4)if(pixels[(y*glyph.width+x)*4+3]>180)samples.push({x,y:y+letterY-glyph.height/2,letter:x<boundaries[0]?0:x<boundaries[1]?1:2,clear:false});
        glyph.width=glyph.height=0;
        paintFrost();
        const haze=mist.createLinearGradient(0,0,width,height);
        haze.addColorStop(0,'rgba(190,195,192,.84)');haze.addColorStop(.55,'rgba(196,200,197,.54)');haze.addColorStop(1,'rgba(159,167,162,.78)');
        mist.fillStyle=haze;mist.fillRect(0,0,width,height);
        grain.width=grain.height=160;
        const noise=grain.getContext('2d'),data=noise.createImageData(160,160);
        for(let i=0;i<data.data.length;i+=4){const v=Math.random()>.5?255:45;data.data[i]=data.data[i+1]=data.data[i+2]=v;data.data[i+3]=Math.random()*8;}
        noise.putImageData(data,0,0);mist.fillStyle=mist.createPattern(grain,'repeat');mist.fillRect(0,0,width,height);
        // Dense condensation, with fine droplets between the larger lenses.
        // No prepainted trails: a stationary bead has never travelled anywhere.
        beads=Array.from({length:Math.min(480,Math.round(width*height/1300))},()=>{
            const size=Math.random();
            return {x:random(4,width-4),y:random(4,height-58),r:size<.08?random(3.5,5.8):size<.42?random(1.4,2.8):random(.45,1.3),stretch:random(.95,1.5),lean:random(-.3,.3),shape:random(0,Math.PI*2),used:false};
        });
        for(const bead of beads)paintDrop(wet,bead);
        drops=[];trails=[];water=0;rainIn=random(.8,1.6);
        // A fixed-size mask preserves drawings on rotation without retaining
        // an ever-growing pointer history. Any number of strokes costs the same.
        for(const surface of [mist,wet]){surface.save();surface.globalCompositeOperation='destination-out';surface.drawImage(wiped,0,0,width,height);surface.restore();}
        const mask=wipeMask.getImageData(0,0,wiped.width,wiped.height).data;
        for(const p of samples)p.clear=mask[(Math.floor(p.y/height*wiped.height)*wiped.width+Math.floor(p.x/width*wiped.width))*4+3]>230;
        for(const bead of beads)bead.used=mask[(Math.floor(bead.y/height*wiped.height)*wiped.width+Math.floor(bead.x/width*wiped.width))*4+3]>230;
        draw();start();
    }
    function paintDrop(context,drop) {
        // Curved-normal refraction of the sharp scene over the blurred glass.
        // Same optical principle as Codrops RainEffect; only small 40px lenses
        // are sampled here, with at most four moving drops, so no 3D runtime.
        // https://tympanus.net/codrops/2015/11/04/rain-water-effect-experiments/
        const {x,y,r}=drop,shape=drop.shape || 0,output=lensPixels.data;
        output.fill(0);
        for(let py=0;py<40;py++)for(let px=0;px<40;px++) {
            const u=((px+.5)/40-.5)*2.6,v=((py+.5)/40-.5)*2.6;
            const angle=Math.atan2(v,u);
            const contour=(.88+.065*Math.sin(angle*3+shape)+.035*Math.cos(angle*5-shape))*(1+Math.min(v,0)*.12);
            const nx=u/contour,ny=v/contour,d=Math.hypot(nx,ny);
            if(d>=1)continue;
            const z=Math.sqrt(1-d*d),curvature=.45+.55*z;
            // Normal-directed sampling flips and bends the scene within a bead.
            const sx=Math.max(0,Math.min(clean.width-2,(x-nx*(12+r*4)*curvature)*ratio));
            const sy=Math.max(0,Math.min(clean.height-2,(y-ny*(18+r*5)*curvature)*ratio));
            const ix=Math.floor(sx),iy=Math.floor(sy),fx=sx-ix,fy=sy-iy;
            const source=(iy*clean.width+ix)*4,next=source+clean.width*4,index=(py*40+px)*4;
            const rim=(1-z)**1.8;
            const light=Math.max(0,-nx*.36-ny*.64+z*.68);
            const highlight=Math.min(.92,light**28*.7+rim*Math.max(0,-ny*.85-nx*.5)*.9);
            const shade=.96-.18*Math.max(0,ny)-rim*Math.max(0,ny)*.55;
            for(let c=0;c<3;c++) {
                const upper=scenePixels[source+c]*(1-fx)+scenePixels[source+4+c]*fx;
                const lower=scenePixels[next+c]*(1-fx)+scenePixels[next+4+c]*fx;
                const color=(upper*(1-fy)+lower*fy)*shade;
                output[index+c]=color*(1-highlight)+250*highlight;
            }
            output[index+3]=Math.min(1,(1-d)*15)*255;
        }
        lensContext.putImageData(lensPixels,0,0);
        context.save();context.translate(x,y);context.transform(1,0,drop.lean || 0,drop.stretch || 1.2,0,0);
        context.drawImage(lens,-r*1.3,-r*1.3,r*2.6,r*2.6);context.restore();
    }
    function fallingDrop(x,y,r,shape=random(0,Math.PI*2)) {
        const trace=[];trails.push(trace);if(trails.length>12)trails.shift();
        return {x,y,r,shape,trace,speed:random(5,12),lean:random(-.3,.3),drift:random(-3,3),targetDrift:random(-9,9),turnIn:random(.7,2),pause:0,film:random(.6,1.1)};
    }
    function paintTrails(time) {
        trails=trails.filter(trace=>!trace.length || time-trace[trace.length-1].time<6000);
        ctx.save();ctx.lineCap='round';ctx.lineJoin='round';
        for(const trace of trails)for(let i=1;i<trace.length;i++) {
            const a=trace[i-1],b=trace[i];
            if(a.cleared || b.cleared)continue;
            const fade=Math.max(0,1-(time-b.time)/6000)**2;
            if(!fade)continue;
            // A faint wet film, never a second finger-width clearing of fog.
            ctx.lineWidth=b.width;ctx.strokeStyle=`rgba(12,24,29,${fade*.13})`;
            ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);ctx.stroke();
            ctx.lineWidth=Math.max(.3,b.width*.45);ctx.strokeStyle=`rgba(216,232,236,${fade*.19})`;
            ctx.beginPath();ctx.moveTo(a.x-.4,a.y);ctx.lineTo(b.x-.4,b.y);ctx.stroke();
        }
        ctx.restore();
    }
    function rain(dt) {
        rainIn-=dt;
        if(rainIn>0 || drops.length>=4)return;
        rainIn=random(1.4,3);
        const candidates=beads.filter(bead=>!bead.used && bead.r>3.5 && bead.y<height*.7);
        if(candidates.length && Math.random()<.65) {
            const bead=candidates[Math.floor(Math.random()*candidates.length)];
            bead.used=true;erase(bead,bead,bead.r*2.6,wet);
            drops.push(fallingDrop(bead.x,bead.y,bead.r,bead.shape));
        } else drops.push(fallingDrop(random(8,width-8),-12,random(3.3,5.5)));
    }
    function draw() {
        ctx.clearRect(0,0,width,height);ctx.drawImage(clean,0,0,width,height);ctx.drawImage(fog,0,0,width,height);paintTrails(performance.now());ctx.drawImage(moisture,0,0,width,height);
        for(const drop of drops)paintDrop(ctx,drop);
    }
    function animate(time) {
        frame=0;if(disposed || leaving || document.hidden || reduced.matches)return;
        if(time-last<40){frame=requestAnimationFrame(animate);return;}
        const dt=Math.min((time-last)/1000,.06);last=time;rain(dt);
        const moving=drops.length>0 || trails.length>0;
        for(const drop of drops){
            if(drop.merged)continue;
            const previous={x:drop.x,y:drop.y};
            drop.turnIn-=dt;drop.pause=Math.max(0,drop.pause-dt);
            if(drop.turnIn<=0){
                drop.targetDrift=random(-11,11);drop.turnIn=random(.8,2.6);
                if(Math.random()<.18){drop.pause=random(.15,.55);drop.speed*=.35;}
            }
            if(drop.pause>0)continue;
            drop.speed=Math.min(85,drop.speed+dt*(14+drop.r*2));drop.y+=drop.speed*dt;
            drop.drift+=(drop.targetDrift-drop.drift)*Math.min(1,dt*2);
            drop.x=Math.max(2,Math.min(width-2,drop.x+drop.drift*dt));
            drop.lean=drop.drift*.018;drop.stretch=1.15+drop.speed/170;
            // A held finger also catches drops that flow into its contact area.
            if(pointer && distanceToStroke(pointer,previous,drop)<(brush()*.76+drop.r)**2){drop.wiped=true;continue;}
            // Gather stationary beads in the path, removing their old images.
            for(const bead of beads)if(!bead.used && distanceToStroke(bead,previous,drop)<((drop.r+bead.r)*.8)**2){
                bead.used=true;drop.r=Math.min(7.5,Math.cbrt(drop.r**3+bead.r**3));
                erase(bead,bead,bead.r*2.6,wet);
            }
            for(const other of drops)if(other!==drop && !other.merged && !other.wiped && Math.hypot(drop.x-other.x,drop.y-other.y)<(drop.r+other.r)*.8){
                const volume=drop.r**3+other.r**3;
                drop.x=(drop.x*drop.r**3+other.x*other.r**3)/volume;
                drop.y=Math.max(drop.y,other.y);drop.r=Math.min(7.5,Math.cbrt(volume));other.merged=true;
            }
            // Follow the drop's real, gently wandering path. Film thickness
            // changes smoothly; no on/off dash pattern and no permanent cuts.
            erase(previous,drop,drop.r*.85,wet);
            const tip=drop.trace[drop.trace.length-1];
            if(!tip || Math.hypot(tip.x-drop.x,tip.y-drop.y)>2.5){
                drop.film+=(random(.45,1.2)-drop.film)*.12;
                drop.trace.push({x:drop.x,y:drop.y,time,width:Math.max(.5,drop.r*.22*drop.film)});
                if(drop.trace.length>96)drop.trace.shift();
            }

        }
        drops=drops.filter(drop=>!drop.merged && !drop.wiped && drop.y<height+12);if(moving)draw();
        frame=requestAnimationFrame(animate);
    }
    function start(){if(!frame && !document.hidden && !reduced.matches && !leaving){last=performance.now();frame=requestAnimationFrame(animate);}}
    function wipe(a,b) {
        erase(a,b,brush());erase(a,b,brush(),wet);mark(a,b);
        erase(a,b,brush(),wipeMask,false);
        // Moving water belongs to the glass too: wipe it away on contact.
        drops=drops.filter(drop=>distanceToStroke(drop,a,b)>=(brush()*.76+drop.r)**2);
        // Keep gaps in a trace; filtering points would reconnect across the wipe.
        for(const trace of trails)for(const point of trace)if(distanceToStroke(point,a,b)<(brush()*.9)**2)point.cleared=true;
        // Only existing water swept up by this gesture can form a falling drop.
        // Repeated passes over dry glass never manufacture more water.
        for(const bead of beads)if(!bead.used && distanceToStroke(bead,a,b)<(brush()*.76)**2){bead.used=true;water+=(bead.r*.25)**2;}
        if(!reduced.matches && water>=releaseVolume && drops.length<4 && performance.now()-lastRelease>1800){
            const radius=Math.min(4.5,Math.sqrt(water));
            drops.push(fallingDrop(b.x,b.y+brush()+radius+2,radius));
            water=0;lastRelease=performance.now();
        }
        draw();start();
        if(samples.length && [0,1,2].every(letter=>{const group=samples.filter(p=>p.letter===letter);return group.length && group.filter(p=>p.clear).length/group.length>=.9;}))enter();
    }
    function point(event){const bounds=canvas.getBoundingClientRect();return {x:event.clientX-bounds.left,y:event.clientY-bounds.top};}
    try {
        if(!ctx || !base || !mist || !wet || !wipeMask || !lensContext)throw new Error('Canvas unavailable');
        dialog.removeAttribute('open');dialog.showModal();dialog.focus({preventScroll:true});observer.observe(dialog);build();
        canvas.addEventListener('pointerdown',event=>{
            if(leaving || pointer || (event.pointerType==='mouse' && event.button!==0))return;
            event.preventDefault();canvas.setPointerCapture(event.pointerId);water=0;releaseVolume=random(7,11);pointer={id:event.pointerId,...point(event)};wipe(pointer,pointer);
        },options);
        canvas.addEventListener('pointermove',event=>{
            if(!pointer || pointer.id!==event.pointerId || leaving)return;
            event.preventDefault();const next=point(event);wipe(pointer,next);pointer={id:event.pointerId,...next};
        },options);
        for(const name of ['pointerup','pointercancel','lostpointercapture'])canvas.addEventListener(name,event=>{if(pointer?.id===event.pointerId)pointer=null;},options);
        dialog.querySelector('form').addEventListener('submit',event=>{event.preventDefault();enter();},options);
        dialog.addEventListener('cancel',event=>{event.preventDefault();enter();},options);
        dialog.addEventListener('close',cleanup,options);
        document.addEventListener('visibilitychange',()=>{if(document.hidden){cancelAnimationFrame(frame);frame=0;pointer=null;}else start();},options);
        reduced.addEventListener('change',()=>{cancelAnimationFrame(frame);frame=0;if(reduced.matches){drops=[];trails=[];draw();}else start();},options);
        addEventListener('pagehide',cleanup,{...options,once:true});
    } catch (error) { console.warn('Ash opening unavailable:',error); cleanup(); }
})();
