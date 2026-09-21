"use strict";
// Stable-ID SVG records. Coordinate ticks only touch transforms/endpoints.
class MapRenderer {
  constructor(nodes,edges,create,select){this.nodes=nodes;this.edges=edges;this.create=create;this.select=select;this.nodeCache=new Map();this.edgeCache=new Map();}
  attr(e,key,value){value=String(value);if(e.getAttribute(key)!==value)e.setAttribute(key,value);}
  text(e,value){if(e.textContent!==value)e.textContent=value;}
  geometry(r,options){const n=r.node,size=options.sizes?options.sizes(n):({Entity:16,Claim:9,Evidence:4,OpenIssue:12,Aggregate:18}[n.kind]||7);
    r.offset=size+3/(options.scale||1);this.attr(r.hit,'r',options.hit?options.hit(n):20);
    const disk=options.mass?.(n);this.attr(r.shape,'d',n.kind==='OpenIssue'&&!disk?`M0 ${-size}L${size} 0L0 ${size}L${-size} 0Z`:`M${-size} 0a${size} ${size} 0 1 0 ${size*2} 0a${size} ${size} 0 1 0 ${-size*2} 0`);
    this.attr(r.label,'x',r.left?-r.offset:r.offset);
  }
  resize(options){for(const r of this.nodeCache.values())this.geometry(r,options);}
  clear(){for(const r of this.nodeCache.values()){r.group.remove();r.hit.onkeydown=null;r.hit.onclick=null;}for(const r of this.edgeCache.values())r.group.remove();this.nodeCache.clear();this.edgeCache.clear();}
  sync(nodes,edges,options){
    const ids=new Set(nodes.map(n=>n.id));for(const [id,r]of this.nodeCache)if(!ids.has(id)){r.hit.onkeydown=null;r.hit.onclick=null;r.group.remove();this.nodeCache.delete(id);}
    let labels=0;for(const n of nodes){let r=this.nodeCache.get(n.id);
      if(!r){const group=this.create('g',{'data-node-id':n.id}),hit=this.create('circle',{r:20,fill:'transparent',stroke:'none',tabindex:0,role:'button'}),shape=this.create('path',{'pointer-events':'none'}),label=this.create('text',{'pointer-events':'none'}),title=this.create('title',{});
        group.append(hit,shape,label,title);this.nodes.append(group);r={group,hit,shape,label,title,node:n};this.nodeCache.set(n.id,r);
        hit.onkeydown=e=>{if(e.key==='Enter')this.select(n.id);};hit.onclick=e=>{if(e.detail===0)this.select(n.id);};
      }r.node=n;this.attr(r.group,'class','node'+(n.id===options.selected?' selected':''));this.attr(r.hit,'aria-label',`${n.kind} ${n.label}`);
      this.geometry(r,options);
      this.attr(r.shape,'vector-effect','non-scaling-stroke');this.attr(r.label,'vector-effect','non-scaling-stroke');
      this.attr(r.shape,'fill',options.color(n));this.attr(r.shape,'stroke',options.color(n));this.attr(r.shape,'opacity',['superseded','history_only'].includes(n.state)?.4:1);
      this.attr(r.shape,'stroke-dasharray',n.kind==='Unknown'||['not_evaluated','pending_evaluation'].includes(n.state)?'1 1':'');this.attr(r.group,'data-state',n.state||'unknown');this.attr(r.group,'data-mass-state',n.mass?.status||'not_provided');
      this.text(r.title,n.label);const show=options.label(n);this.attr(r.label,'display',show?'inline':'none');if(show)labels++;
      this.text(r.label,options.text(n));this.attr(r.label,'font-size',options.font);r.label.style.fontSize=options.font+'px';
    }
    const edgeIds=new Set();for(const e of edges){if(!ids.has(e.source)||!ids.has(e.target))continue;edgeIds.add(e.id);let r=this.edgeCache.get(e.id);
      if(!r){const group=this.create('g',{'data-edge-id':e.id}),line=this.create('line',{}),label=this.create('text',{class:'edge-label','pointer-events':'none'});group.append(line,label);this.edges.append(group);r={group,line,label};this.edgeCache.set(e.id,r);}r.edge=e;
      const active=[e.source,e.target].includes(options.selected);this.attr(r.line,'class','edge'+(active?' selected':''));this.attr(r.line,'vector-effect','non-scaling-stroke');this.attr(r.label,'vector-effect','non-scaling-stroke');this.attr(r.line,'marker-end',active?'url(#arrow)':'');this.attr(r.label,'display',active&&options.level>=2?'inline':'none');this.text(r.label,'→ '+e.relation);r.label.style.fontSize=options.font+'px';
    }
    for(const [id,r]of this.edgeCache)if(!edgeIds.has(id)){r.group.remove();this.edgeCache.delete(id);}return labels;
  }
  coordinates(points){for(const [id,r]of this.nodeCache){const p=points.get(id);if(!p)continue;this.attr(r.group,'transform',`translate(${p.x} ${p.y})`);const left=r.left=p.x>650;this.attr(r.label,'x',left?-r.offset:r.offset);this.attr(r.label,'y',0);this.attr(r.label,'dominant-baseline','middle');this.attr(r.label,'text-anchor',left?'end':'start');}
    for(const r of this.edgeCache.values()){const a=points.get(r.edge.source),b=points.get(r.edge.target);if(!a||!b)continue;for(const [key,value]of Object.entries({x1:a.x,y1:a.y,x2:b.x,y2:b.y}))this.attr(r.line,key,value);this.attr(r.label,'x',(a.x+b.x)/2);this.attr(r.label,'y',(a.y+b.y)/2);}
  }
}
if(typeof module!=='undefined')module.exports={MapRenderer};
