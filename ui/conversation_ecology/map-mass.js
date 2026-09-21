"use strict";
const MASS_PROFILE=Object.freeze({version:'field-mass-size-1',min:1,max:3.2,gamma:1.05,zoomMax:4.375,ms:180});
function massValue(n){const m=n.mass;return m?.status==='available'&&Number.isFinite(m.value)&&m.value>=0&&m.value<=1&&m.B===1?m.value:null;}
function massDiameter(p,s){if(!Number.isFinite(p)||p<0||p>1||!Number.isFinite(s)||s<=0)return null;return Math.sqrt(MASS_PROFILE.min**2+(MASS_PROFILE.max**2-MASS_PROFILE.min**2)*p)*Math.min(MASS_PROFILE.zoomMax,s**MASS_PROFILE.gamma);}
function nodeDiameter(n,s,p=massValue(n)){return p===null?graphPixels(n.kind,s):massDiameter(p,s);}
class MassMotion {
  constructor(draw,env={}){this.draw=draw;this.now=env.now||(()=>performance.now());this.schedule=env.schedule||(f=>requestAnimationFrame(f));this.clear=env.clear||(id=>cancelAnimationFrame(id));this.pending=null;this.generation=0;this.frames=0;this.key=null;this.signature=null;this.values=new Map();this.targets=new Map();this.samples=[];this.maxPending=0;}
  cancel(){this.generation++;if(this.pending!==null)this.clear(this.pending);this.pending=null;}
  settle(){this.cancel();this.values=new Map(this.targets);}
  update(view,{immediate=false}={}){
    if(this.view===view&&!immediate)return;this.view=view;
    const key=JSON.stringify([view.session_id,view.epoch,view.mode,view.scope,view.provider]),signature=JSON.stringify(view.nodes.map(n=>[n.id,n.mass?.status,massValue(n),n.mass?.reference]));
    if(key===this.key&&signature===this.signature){if(immediate)this.settle();return;}
    const boundary=key!==this.key;this.cancel();const from=new Map(this.values);this.key=key;this.signature=signature;
    this.targets=new Map(view.nodes.map(n=>[n.id,massValue(n)]));this.values=new Map(this.targets);
    if(boundary||immediate)return;
    let changed=false;for(const [id,to]of this.targets){const prior=from.get(id);if(to!==null&&prior!==null&&prior!==undefined&&prior!==to){this.values.set(id,prior);changed=true;}}
    if(!changed)return;
    const generation=this.generation,start=this.now(),initial=new Map(this.values);
    const frame=()=>{if(generation!==this.generation)return;this.pending=null;const begin=this.now(),u=Math.min(1,(begin-start)/MASS_PROFILE.ms);
      for(const [id,to]of this.targets){const prior=initial.get(id);this.values.set(id,to===null||prior===null?to:prior+(to-prior)*u);}
      if(u<1){this.pending=this.schedule(frame);this.maxPending=1;}this.frames++;this.draw();this.samples.push(this.now()-begin);if(this.samples.length>240)this.samples.shift();
    };this.pending=this.schedule(frame);this.maxPending=1;
  }
  value(n){return this.values.has(n.id)?this.values.get(n.id):massValue(n);}
  dispose(){this.cancel();this.values.clear();this.targets.clear();this.key=null;this.signature=null;this.view=null;}
}
if(typeof module!=='undefined')module.exports={MASS_PROFILE,massValue,massDiameter,nodeDiameter,MassMotion};
