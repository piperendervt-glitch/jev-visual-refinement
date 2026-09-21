"use strict";
const PIPE_PROFILE=Object.freeze({version:'pipeline-v1',active:24,queue:128,windowMs:250,durationMs:450,ttlMs:900,fps:30,dotPx:5,records:512});
function pipelineC0(state,expires){
  if(!state)return [];
  const ns=JSON.stringify(['C0',null,state.session_id,'response']),out=[],commits=new Map(),deliveries=new Map();
  for(const e of state.events||[]){const p=e.payload||{};let stage,status,parent,refs=[];
    if(e.kind==='commit'){stage='output';status='committed';refs=[p.snapshot_id,p.evaluation_id].filter(Boolean);}
    else if(['delivery','resend','ack'].includes(e.kind)){
      stage=e.kind==='ack'?'ack':'delivery';status=e.kind==='ack'?p.kind:e.kind==='resend'?(p.result==='no_commits'?'no_commits':'resend_prepared'):'prepared';
      parent=(stage==='ack'?deliveries:commits).get(p.commit_id||((p.commit_ids||[]).length===1?p.commit_ids[0]:null));refs=parent?.refs||[];
    }else continue;
    const r={id:ns+':'+e.cursor+':'+stage,namespace:ns,source_event_id:e.id,source_cursor:e.cursor,stage,status,refs,
      parent:parent?.id,source_stage:parent?.stage,commit_id:p.id||p.commit_id,commit_ids:p.commit_ids,result:p.result,
      parent_ids:e.kind==='resend'?(p.commit_ids||[]).map(id=>commits.get(id)?.id).filter(Boolean):undefined,
      origin:'FIXTURE',clock:'fixture_monotonic_ms',fixture_monotonic_ms:e.fixture_monotonic_ms,expires_at:expires,
      started_at:null,completed_at:null,human_read_proof:false};out.push(r);
    if(e.kind==='commit')commits.set(p.id,r);if(e.kind==='delivery')deliveries.set(p.commit_id,r);
  }return out;
}
class PipelineMotion {
  constructor(draw,env={}){this.draw=draw;this.now=env.now||(()=>performance.now());this.wall=env.wall||(()=>Date.now()/1000);
    this.schedule=env.schedule||(f=>{const h={timer:null,frame:null};h.timer=setTimeout(()=>{h.timer=null;h.frame=requestAnimationFrame(f);},1000/PIPE_PROFILE.fps);return h;});
    this.clear=env.clear||(h=>{if(h.timer!==null)clearTimeout(h.timer);if(h.frame!==null)cancelAnimationFrame(h.frame);});
    this.pending=null;this.generation=0;this.frames=0;this.queue=[];this.dots=[];this.samples=[];this.omitted=0;this.aggregated=0;this.queueMax=0;this.activeMax=0;this.suppressed=0;}
  cancel(reason='cancelled'){this.generation++;if(this.pending!==null)this.clear(this.pending);this.pending=null;this.queue=[];this.dots=[];this.reason=reason;this.draw([]);}
  enqueue(rows){const now=this.now();for(const r of rows){if(!r.source_stage||!r.parent||r.source_stage===r.stage)continue;
      if(['failed','stale','unavailable','unknown','cancel_requested','cancelled','disabled','not_run'].includes(r.status))continue;
      if(r.expires_at&&r.expires_at<=this.wall())continue;
      const key=JSON.stringify([r.namespace,r.media_epoch,r.source_stage,r.stage,r.status]);
      const same=this.queue.find(d=>d.key===key&&now-d.enqueued<=PIPE_PROFILE.windowMs);
      if(same){same.count++;if(same.ids.length<24)same.ids.push(r.id);this.aggregated++;continue;}
      if(this.queue.length>=PIPE_PROFILE.queue){this.omitted++;continue;}
      this.queue.push({key,record:r,ids:[r.id],count:1,enqueued:now});
    }this.queueMax=Math.max(this.queueMax,this.queue.length);this.start();}
  start(){if(this.pending!==null||!this.queue.length&&!this.dots.length)return;const generation=this.generation;
    this.pending=this.schedule(()=>{if(generation!==this.generation)return;this.pending=null;const begin=this.now();
      this.dots=this.dots.filter(d=>begin-d.started<PIPE_PROFILE.durationMs&&(!d.record.expires_at||d.record.expires_at>this.wall()));
      while(this.dots.length<PIPE_PROFILE.active&&this.queue.length){const d=this.queue.shift();if(begin-d.enqueued>PIPE_PROFILE.ttlMs||d.record.expires_at&&d.record.expires_at<=this.wall()){this.omitted+=d.count;continue;}d.started=begin;this.dots.push(d);}
      this.activeMax=Math.max(this.activeMax,this.dots.length);this.frames++;
      this.draw(this.dots.map(d=>({...d,progress:Math.min(1,(begin-d.started)/PIPE_PROFILE.durationMs)})));
      this.samples.push(this.now()-begin);if(this.samples.length>300)this.samples.shift();this.start();if(this.onSample)this.onSample();
    });}
}
class PipelineState {
  constructor(motion){this.motion=motion;this.key=null;this.watermarks=new Map();this.records=[];this.mode='LIVE';this.paused=false;this.replayGeneration=0;this.reason='initial';}
  update(snapshot,options={}){
    const key=JSON.stringify([snapshot.namespace,snapshot.epoch,snapshot.media_epoch,options.c0Session]),
      paused=!!(options.frozen||options.hidden||options.off||options.collapsed||options.reduced||options.stopped);
    const rows=(snapshot.records||[]).filter(r=>!r.expires_at||r.expires_at>this.motion.wall()).slice(-PIPE_PROFILE.records);
    const signature=JSON.stringify(rows.map(r=>[r.id,r.status,r.expires_at]));
    if(this.mode==='Replay'&&key===this.key&&paused===this.paused&&!options.resync&&signature===this.signature)return this.records;
    const boundary=key!==this.key||paused!==this.paused||options.resync||this.mode==='Replay';
    if(boundary){this.motion.cancel(key!==this.key?'session/epoch':'display_boundary');if(key!==this.key)this.watermarks.clear();}
    this.mode=options.frozen?'固定':options.liveFixed?'LIVE（固定mapとは別時点）':'LIVE';this.key=key;this.paused=paused;
    this.records=rows;this.snapshot=snapshot;this.signature=signature;
    const fresh=rows.filter(r=>r.source_cursor>(this.watermarks.get(r.namespace)??-1));
    for(const r of rows)this.watermarks.set(r.namespace,Math.max(r.source_cursor,this.watermarks.get(r.namespace)??-1));
    if(!boundary&&!paused)this.motion.enqueue(fresh);else this.motion.suppressed+=fresh.length;
    // Deleted/expired references must also disappear from queued display data.
    const allowed=new Set(rows.filter(r=>r.status!=='unavailable').map(r=>r.id));
    if([...this.motion.dots,...this.motion.queue].some(d=>!allowed.has(d.record.id)))this.motion.cancel('reference_unavailable');
    return rows;
  }
  replay(){this.motion.cancel('explicit_replay');this.replayGeneration++;this.mode='Replay';if(!this.paused)this.motion.enqueue(this.records);}
  dispose(){this.motion.cancel('disposed');this.records=[];this.watermarks.clear();this.snapshot=null;}
}
if(typeof module!=='undefined')module.exports={PIPE_PROFILE,PipelineMotion,PipelineState,pipelineC0};
