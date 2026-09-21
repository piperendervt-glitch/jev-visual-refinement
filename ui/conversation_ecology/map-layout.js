"use strict";
// Display-only state. No projection object is mutated or retained as a mutable point.
const LAYOUT_PROFILE=Object.freeze({version:'dyn-1',seed:1701,steps:24,milliseconds:800,fps:30,chunkSteps:2,chunkMs:4,maxMove:3,epsilon:.12,stableSteps:3,cell:48});
const LAYOUT_REGIONS={person:[250,145],place:[750,145],conversation:[500,365]};
function layoutHash(text){let h=LAYOUT_PROFILE.seed;for(const c of text)h=Math.imul(h^c.charCodeAt(0),16777619);return h>>>0;}
function layoutKey(v){return JSON.stringify([v.session_id,v.epoch,v.mode,v.scope??v.nodes[0]?.scope??null,v.provider??null]);}
function structureKey(v){return JSON.stringify([v.nodes.map(n=>[n.id,n.region]).sort(),v.edges.map(e=>[e.id,e.source,e.target]).sort()]);}
class LayoutState {
  constructor(){this.points=new Map();this.generation=0;this.key='';this.structure='';this.status='idle';this.ticks=0;this.rejected=0;this.metrics=[];}
  cancel(reason='cancelled'){this.generation++;this.status=reason;}
  sync(view,force=false){
    const key=layoutKey(view),structure=structureKey(view);
    if(key!==this.key){this.points.clear();this.key=key;this.structure='';this.cancel('session_changed');}
    if(!force&&structure===this.structure)return false;
    this.structure=structure;this.generation++;this.iteration=0;this.stable=0;this.status='running';let invalid=false;
    const ids=new Set(view.nodes.map(n=>n.id));for(const id of this.points.keys())if(!ids.has(id))this.points.delete(id);
    const first=this.points.size===0,counts={};
    for(const n of view.nodes){
      const index=counts[n.region]=(counts[n.region]??-1)+1;
      if(!this.points.has(n.id)){
        const region=LAYOUT_REGIONS[n.region]||LAYOUT_REGIONS.conversation;
        let pos;
        if(first){const a=index*2.399963,r=index===0?0:Math.min(180,76+Math.sqrt(index)*20);pos={x:region[0]+Math.cos(a)*r,y:region[1]+Math.sin(a)*r*.65};}
        else{
          const edge=view.edges.find(e=>(e.source===n.id&&this.points.has(e.target))||(e.target===n.id&&this.points.has(e.source)));
          const related=edge&&this.points.get(edge.source===n.id?edge.target:edge.source),anchor=related||{x:region[0],y:region[1]};
          let best=-Infinity;const seed=layoutHash(n.id)/4294967296*Math.PI*2;
          for(let k=0;k<48;k++){const a=seed+k*2.399963,r=42+Math.sqrt(k)*20,candidate={x:anchor.x+Math.cos(a)*r,y:anchor.y+Math.sin(a)*r};let distance=160;
            for(const p of this.points.values())distance=Math.min(distance,Math.hypot(p.x-candidate.x,p.y-candidate.y));
            const score=distance-r*.08;if(score>best){best=score;pos=candidate;}}
        }
        this.points.set(n.id,{...pos,vx:0,vy:0,region:n.region});
      }
      const p=this.points.get(n.id);if(!Number.isFinite(p.x)||!Number.isFinite(p.y)){p.x=(LAYOUT_REGIONS[n.region]||[500,250])[0];p.y=(LAYOUT_REGIONS[n.region]||[500,250])[1];invalid=true;}
      p.ax=p.x;p.ay=p.y;p.vx=0;p.vy=0;p.region=n.region;
    }
    this.edges=view.edges.filter(e=>ids.has(e.source)&&ids.has(e.target)).map(e=>({source:e.source,target:e.target}));
    this.degree=new Map();for(const e of this.edges)for(const id of [e.source,e.target])this.degree.set(id,(this.degree.get(id)||0)+1);
    this.status=invalid?'invalid_coordinates':'running';return true;
  }
  ticket(){return {key:this.key,structure:this.structure,generation:this.generation};}
  accepts(t){return t.key===this.key&&t.structure===this.structure&&t.generation===this.generation&&this.status==='running';}
  step(ticket=this.ticket()){
    if(!this.accepts(ticket)){this.rejected++;return false;}
    const cells=new Map(),wide=new Map(),forces=new Map();
    for(const [id,p]of this.points){const cell=`${Math.floor(p.x/48)},${Math.floor(p.y/48)}`;if(!cells.has(cell))cells.set(cell,[]);cells.get(cell).push([id,p]);
      const key=`${Math.floor(p.x/192)},${Math.floor(p.y/192)}`;if(!wide.has(key))wide.set(key,{x:0,y:0,n:0});const c=wide.get(key);c.x+=p.x;c.y+=p.y;c.n++;}
    for(const [id,p]of this.points){
      const r=LAYOUT_REGIONS[p.region]||LAYOUT_REGIONS.conversation;let fx=(p.ax-p.x)*.035+(r[0]-p.x)*.0008,fy=(p.ay-p.y)*.035+(r[1]-p.y)*.0008;
      const cx=Math.floor(p.x/48),cy=Math.floor(p.y/48);let examined=0;
      neighbors:for(let dx=-1;dx<=1;dx++)for(let dy=-1;dy<=1;dy++)for(const [other,q]of cells.get(`${cx+dx},${cy+dy}`)||[]){
        if(examined>=64)break neighbors;if(other===id)continue;examined++;let x=p.x-q.x,y=p.y-q.y,d=Math.hypot(x,y);
        if(d<.001){const angle=layoutHash(id+'|'+other)/4294967296*Math.PI*2;x=Math.cos(angle);y=Math.sin(angle);d=1;}
        if(d<44){fx+=x/d*(44-d)*.20;fy+=y/d*(44-d)*.20;}
      }
      // At most 8 x 7 coarse cells in the bounded world, rather than unbounded all-pairs.
      for(const c of wide.values()){const x=p.x-c.x/c.n,y=p.y-c.y/c.n,d2=x*x+y*y;if(d2>2304){const f=Math.min(.16,c.n*9/(d2+2304));fx+=x/Math.sqrt(d2)*f;fy+=y/Math.sqrt(d2)*f;}}
      forces.set(id,{x:fx,y:fy});
    }
    for(const e of this.edges){const a=this.points.get(e.source),b=this.points.get(e.target),x=b.x-a.x,y=b.y-a.y,d=Math.hypot(x,y)||1;
      const f=Math.max(-.3,Math.min(.3,(d-90)*.003))/Math.sqrt(Math.max(this.degree.get(e.source),this.degree.get(e.target)));
      forces.get(e.source).x+=x/d*f;forces.get(e.source).y+=y/d*f;forces.get(e.target).x-=x/d*f;forces.get(e.target).y-=y/d*f;
    }
    let max=0;for(const [id,p]of this.points){const f=forces.get(id);p.vx=(p.vx+f.x)*.65;p.vy=(p.vy+f.y)*.65;const speed=Math.hypot(p.vx,p.vy),scale=Math.min(1,3/(speed||1));p.vx*=scale;p.vy*=scale;
      p.x=Math.max(-250,Math.min(1250,p.x+p.vx));p.y=Math.max(-200,Math.min(800,p.y+p.vy));max=Math.max(max,Math.hypot(p.vx,p.vy));}
    this.ticks++;this.iteration++;this.stable=max<=LAYOUT_PROFILE.epsilon?this.stable+1:0;
    if(this.stable>=LAYOUT_PROFILE.stableSteps)this.status='settled';else if(this.iteration>=LAYOUT_PROFILE.steps)this.status='budget_exhausted';
    return true;
  }
}
class LayoutRunner {
  constructor(layout,draw,env={}){this.layout=layout;this.draw=draw;this.now=env.now||(()=>performance.now());this.schedule=env.schedule||(f=>{const handle={timer:null,frame:null};handle.timer=setTimeout(()=>{handle.timer=null;handle.frame=requestAnimationFrame(f);},1000/LAYOUT_PROFILE.fps);return handle;});this.clear=env.clear||(h=>{if(h.timer!==null)clearTimeout(h.timer);if(h.frame!==null)cancelAnimationFrame(h.frame);});this.pending=null;this.samples=[];this.lastFrame=null;this.paused=false;}
  stop(reason){if(this.pending!==null)this.clear(this.pending);this.pending=null;if(reason)this.layout.cancel(reason);}
  start(){this.stop();if(this.layout.status!=='running')return;const ticket=this.layout.ticket(),start=this.now();this.lastFrame=null;
    const frame=()=>{this.pending=null;if(!this.layout.accepts(ticket))return;
      const begin=this.now();
      if(begin-start>=LAYOUT_PROFILE.milliseconds){this.layout.status='budget_exhausted';this.draw();return;}
      if(this.paused){this.pending=this.schedule(frame);return;}
      for(let i=0;i<LAYOUT_PROFILE.chunkSteps&&this.layout.status==='running';i++){this.layout.step(ticket);if(this.now()-begin>=LAYOUT_PROFILE.chunkMs)break;}
      if(this.layout.status==='running')this.pending=this.schedule(frame);
      const compute=this.now()-begin;this.draw();const end=this.now();this.samples.push({compute,dom:end-begin-compute,interval:this.lastFrame===null?null:begin-this.lastFrame});if(this.samples.length>600)this.samples.shift();this.lastFrame=begin;this.onSample?.();
    };this.pending=this.schedule(frame);
  }
}
function semanticLevel(level,zoom){const thresholds=[1.25,2,3.1];while(level<3&&zoom>thresholds[level]+.1)level++;while(level>0&&zoom<thresholds[level-1]-.1)level--;return level;}
function labelPixels(zoom){return Math.max(12,Math.min(18,12+Math.log2(Math.max(.65,zoom))*3));}
class NodeGesture {
  begin(id,key,x,y){this.active={id,key,x,y,moved:false};}
  move(x,y){if(this.active&&Math.hypot(x-this.active.x,y-this.active.y)>5)this.active.moved=true;}
  end(key,ids){const a=this.active;this.active=null;return a&&!a.moved&&a.key===key&&ids.has(a.id)?a.id:null;}
  cancel(){this.active=null;}
}
function aggregateLocations(aggregateNodes,positions,aggregatePlacement){const all=new Map(positions);
  for(const n of aggregateNodes){let p=aggregatePlacement.get(n.id);if(!p){const region=LAYOUT_REGIONS[n.region],occupied=[...positions.values(),...aggregatePlacement.values()];let best=-Infinity;
      for(let i=0;i<64;i++){const angle=layoutHash(n.id)/4294967296*Math.PI*2+i*2.399963,r=75+Math.sqrt(i)*24,candidate={x:region[0]+Math.cos(angle)*r,y:region[1]+Math.sin(angle)*r};if(candidate.x<40||candidate.x>960||candidate.y<40||candidate.y>460)continue;let gap=200;for(const q of occupied)gap=Math.min(gap,Math.hypot(q.x-candidate.x,q.y-candidate.y));const score=gap-r*.04;if(score>best){best=score;p=candidate;}}
      aggregatePlacement.set(n.id,p);}all.set(n.id,p);}return all;}

if(typeof module!=='undefined')module.exports={aggregateLocations,LayoutState,LayoutRunner,LAYOUT_PROFILE,layoutKey,structureKey,semanticLevel,labelPixels,NodeGesture};
