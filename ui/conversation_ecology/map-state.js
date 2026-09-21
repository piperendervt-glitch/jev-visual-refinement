"use strict";
// Pure display reducer, also exercised by Node tests. No semantic mutation.
class MapState {
  constructor(){this.live=null;this.fixed=null;this.selected=null;this.seen=new Set();this.status='初期記録なし';}
  snapshot(view){
    const sameSource=this.live&&['session_id','epoch','mode','scope','provider'].every(k=>this.live[k]===view[k]);
    if(sameSource&&view.cursor<this.live.cursor)return 'old_snapshot';
    if(!sameSource){this.fixed=null;this.selected=null;this.seen.clear();}
    this.live=structuredClone(view);this.status='同期済み';
  }
  delta(d){
    if(!this.live||d.session_id!==this.live.session_id||d.epoch!==this.live.epoch)return 'wrong_session';
    if(this.seen.has(d.update_id)||d.cursor<=this.live.cursor)return 'duplicate_or_old';
    if(d.base!==this.live.cursor){this.status='欠番・同期中';return 'gap';}
    this.seen.add(d.update_id);this.live=structuredClone(d.snapshot);return 'applied';
  }
  freeze(){this.fixed=structuredClone(this.live);}
  latest(){this.fixed=null;}
  get view(){return this.fixed||this.live;}
  get incoming(){return this.fixed?Math.max(0,this.live.cursor-this.fixed.cursor):0;}
  edges(){const ids=new Set(this.view.nodes.map(n=>n.id));return this.view.edges.filter(e=>ids.has(e.source)&&ids.has(e.target));}
}
if(typeof module!=='undefined')module.exports={MapState};
