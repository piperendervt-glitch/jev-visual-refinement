"use strict";
// One display profile; CSS sizes are converted to world units exactly once.
const GRAPH_PROFILE=Object.freeze({version:'graph-2d-1',exponent:1.05,label:[4,14],region:[5,20],
  diameters:{Evidence:[1.3,5.5],Claim:[2,9],Entity:[3.2,14],OpenIssue:[3.5,15],Aggregate:[4,16]},
  colors:{person:'#46d9e8',place:'#f4b45b',conversation:'#d77ce8'},hit:6,cameraMs:160,minZoom:.5,maxZoom:8});
function graphPixels(kind,s){const range=GRAPH_PROFILE.diameters[kind]||GRAPH_PROFILE[kind]||[2,9];return Math.min(range[1],range[0]*Math.pow(Math.max(.01,s),GRAPH_PROFILE.exponent));}
function graphFit(points,minimum=[900,440],limit=1){
  const ps=[...points].filter(p=>Number.isFinite(p.x)&&Number.isFinite(p.y));
  if(!ps.length)return {zoom:1,x:0,y:0};
  const xs=ps.map(p=>p.x),ys=ps.map(p=>p.y),cx=(Math.min(...xs)+Math.max(...xs))/2,cy=(Math.min(...ys)+Math.max(...ys))/2;
  const w=Math.max(minimum[0],Math.max(...xs)-Math.min(...xs)+80),h=Math.max(minimum[1],Math.max(...ys)-Math.min(...ys)+80);
  const zoom=Math.min(limit,1000/w,500/h);return {zoom,x:500-cx*zoom,y:250-cy*zoom};
}
function graphZoom(camera,factor,x,y,k0=1){const zoom=Math.max(k0*GRAPH_PROFILE.minZoom,Math.min(k0*GRAPH_PROFILE.maxZoom,camera.zoom*factor));
  return {zoom,x:x-(x-camera.x)*zoom/camera.zoom,y:y-(y-camera.y)*zoom/camera.zoom};}
function graphHit(nodes,points,x,y,scale,s,diameter=n=>graphPixels(n.kind,s)){let best=null,distance=Infinity;
  for(const n of nodes){const p=points.get(n.id);if(!p)continue;const d=Math.hypot(p.x-x,p.y-y)*scale,limit=Math.max(GRAPH_PROFILE.hit,diameter(n)/2+2);
    if(d<=limit&&(d<distance-1e-9||Math.abs(d-distance)<1e-9&&n.id<best)){best=n.id;distance=d;}}
  return best;
}
class CameraMotion {
  constructor(draw,env={}){this.draw=draw;this.now=env.now||(()=>performance.now());this.schedule=env.schedule||(f=>requestAnimationFrame(f));this.clear=env.clear||(id=>cancelAnimationFrame(id));this.pending=null;this.generation=0;this.frames=0;this.samples=[];this.target=null;}
  cancel(){this.generation++;if(this.pending!==null)this.clear(this.pending);this.pending=null;this.target=null;}
  move(from,to,immediate=false){this.cancel();this.target={...to};const generation=this.generation,start=this.now();let last=null;
    if(immediate){this.target=null;this.draw(to);return;}
    const frame=()=>{if(generation!==this.generation)return;this.pending=null;const begin=this.now(),t=Math.min(1,(begin-start)/GRAPH_PROFILE.cameraMs),u=1-Math.pow(1-t,3);
      if(t<1)this.pending=this.schedule(frame);else this.target=null;
      this.frames++;this.draw({zoom:from.zoom+(to.zoom-from.zoom)*u,x:from.x+(to.x-from.x)*u,y:from.y+(to.y-from.y)*u});
      this.samples.push({dom:this.now()-begin,interval:last===null?null:begin-last});if(this.samples.length>240)this.samples.shift();last=begin;if(this.onSample)this.onSample();
    };this.pending=this.schedule(frame);
  }
}
if(typeof module!=='undefined')module.exports={GRAPH_PROFILE,graphPixels,graphFit,graphZoom,graphHit,CameraMotion};
