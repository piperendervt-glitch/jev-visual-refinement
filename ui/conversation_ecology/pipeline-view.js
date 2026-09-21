"use strict";
const PIPE_STAGES={llm:'LLM',vision:'Vision',audio:'Audio',program:'Program',rule:'Rule',sensor:'Sensor',input:'入力受付',decode:'Frame / PCM',analyze:'観測候補',record:'SQLite保存',evaluate:'意味・関連付け・重要度',validate:'採用・保留・更新検証',person:'人物レイヤー',place:'場所レイヤー',conversation:'会話レイヤー',project:'投影',display:'全体文脈マップへ統合・更新',output:'C0・質問 commit',delivery:'配送準備／再送',ack:'DOM ack'};
// Geometry is shared by the solid arrow and its moving dot; no DOM reads in a frame.
function pipeRoute(a,b,bypass=false){
  if(a.x===b.x&&a.y===b.y){const x=a.x+a.width+6,y=a.y+a.height+6;return [{x:a.x+a.width/2,y:a.y+a.height},{x:a.x+a.width/2,y},{x,y},{x,y:a.y+a.height/2},{x:a.x+a.width,y:a.y+a.height/2}];}
  if(bypass==='source-wrap'){const x=4,y=a.y+a.height+6;return [{x:a.x+a.width/2,y:a.y+a.height},{x:a.x+a.width/2,y},{x,y},{x,y:b.y-6},{x:b.x+b.width/2,y:b.y-6},{x:b.x+b.width/2,y:b.y}];}
  if(bypass){const x=4;return [{x:a.x+a.width/2,y:a.y+a.height},{x:a.x+a.width/2,y:a.y+a.height+9},{x,y:a.y+a.height+9},{x,y:b.y+b.height/2},{x:b.x,y:b.y+b.height/2}];}
  if(Math.abs(a.y-b.y)<Math.min(a.height,b.height)/2){const right=b.x>a.x;
    if(Math.abs(b.x-a.x)>Math.max(a.width,b.width)*1.5){const y=Math.max(a.y+a.height,b.y+b.height)+8;return [{x:a.x+a.width/2,y:a.y+a.height},{x:a.x+a.width/2,y},{x:b.x+b.width/2,y},{x:b.x+b.width/2,y:b.y+b.height}];}
    return [{x:a.x+(right?a.width:0),y:a.y+a.height/2},{x:b.x+(right?0:b.width),y:b.y+b.height/2}];}
  const down=b.y>a.y,p={x:a.x+a.width/2,y:a.y+(down?a.height:0)},q={x:b.x+b.width/2,y:b.y+(down?0:b.height)},mid=(p.y+q.y)/2;
  return [p,{x:p.x,y:mid},{x:q.x,y:mid},q];
}
function pipePoint(route,progress){const lengths=route.slice(1).map((p,i)=>Math.hypot(p.x-route[i].x,p.y-route[i].y));let left=lengths.reduce((a,b)=>a+b,0)*Math.max(0,Math.min(1,progress));for(let i=0;i<lengths.length;i++){if(left<=lengths[i]||i===lengths.length-1){const t=lengths[i]?left/lengths[i]:0;return{x:route[i].x+(route[i+1].x-route[i].x)*t,y:route[i].y+(route[i+1].y-route[i].y)*t};}left-=lengths[i];}return route[0];}
class PipelineView {
  constructor(root,pick){this.root=root;this.pick=pick;this.boxes=new Map();this.paths=new Map();this.points=new Map();this.dots=[];this.applied=null;
    const make=(tag,text,cls)=>{const e=document.createElement(tag);if(text)e.textContent=text;if(cls)e.className=cls;return e;};this.make=make;
    const title=(text,cls)=>{const e=make('h3',text,cls);root.append(e);return e;};
    title('① 入力ソース','pipe-heading');const sources=make('div',null,'pipe-sources');root.append(sources);
    const box=(id,parent)=>{const b=make('button',null,'pipe-box pipe-'+id);b.type='button';b.dataset.stage=id;
      const label=make('b',PIPE_STAGES[id]),connection=make('span',null,'pipe-connection'),status=make('span','unknown','pipe-state'),counts=make('small','記録なし');b.append(label,connection,status,counts);parent.append(b);
      b.onclick=()=>this.pickStage(id);this.boxes.set(id,{b,status,counts,connection});return b;};
    for(const id of ['llm','vision','audio','program','rule','sensor'])box(id,sources);
    this.grid=make('div',null,'pipe-grid');root.append(this.grid);
    this.observations=make('section',null,'pipe-observations');this.grid.append(this.observations);this.observations.append(make('h3','未評価の記録経路 → 左の迂回線で投影へ'));
    const intake=make('div',null,'pipe-intake');this.observations.append(intake);for(const id of ['input','decode','analyze','record'])box(id,intake);
    this.meaning=make('section',null,'pipe-meaning');this.grid.append(this.meaning);this.meaning.append(make('h3','② Jev評価役 · 実Jev NOT_CONNECTED'));
    const reasoning=make('div',null,'pipe-reasoning');this.meaning.append(reasoning);box('evaluate',reasoning);box('validate',reasoning);
    const fieldSection=make('section',null,'pipe-field-section');this.grid.append(fieldSection);fieldSection.append(make('h3','③ 文脈の割当て・更新 · 実観測未接続'));
    const fields=make('div',null,'pipe-fields');fieldSection.append(fields);for(const id of ['person','place','conversation'])box(id,fields);
    const result=make('section',null,'pipe-result');this.grid.append(result);result.append(make('h3','④ マップへの統合'));
    const results=make('div',null,'pipe-results');result.append(results);box('project',results);box('display',results);
    this.output=make('details',null,'pipe-output');this.output.append(make('summary','別枝：C0・質問 → commit → 配送準備 → DOM ack'));
    for(const id of ['output','delivery','ack'])box(id,this.output);this.output.ontoggle=()=>this.measure();
    this.legend=make('p','矢印＝構成（未接続も含む）。光る点＝記録された遷移のみ。成功・既読の証明ではありません。','pipe-legend');root.append(this.legend);
    this.recordsPanel=make('details',null,'pipe-records');this.recordsPanel.append(make('summary','遷移記録・応答枝・図の状態'),this.output);root.append(this.recordsPanel);
    this.info=make('p',null,'pipe-info');this.recordsPanel.append(this.info);this.recent=make('div',null,'pipe-recent');this.recordsPanel.append(this.recent);this.recordsPanel.ontoggle=()=>this.measure();
    this.overlay=document.createElementNS('http://www.w3.org/2000/svg','svg');this.overlay.setAttribute('class','pipe-lines');this.overlay.setAttribute('aria-hidden','true');root.append(this.overlay);
    const defs=document.createElementNS('http://www.w3.org/2000/svg','defs'),marker=document.createElementNS('http://www.w3.org/2000/svg','marker'),tip=document.createElementNS('http://www.w3.org/2000/svg','path');
    for(const [k,v]of Object.entries({id:'pipeline-arrow',viewBox:'0 0 10 10',refX:9,refY:5,markerWidth:5,markerHeight:5,orient:'auto'}))marker.setAttribute(k,v);
    tip.setAttribute('d','M 0 0 L 10 5 L 0 10 z');tip.setAttribute('fill','#6adfeb');marker.append(tip);defs.append(marker);
    const mutedMarker=document.createElementNS('http://www.w3.org/2000/svg','marker'),mutedTip=document.createElementNS('http://www.w3.org/2000/svg','path');
    for(const [k,v]of Object.entries({id:'pipeline-arrow-planned',viewBox:'0 0 10 10',refX:9,refY:5,markerWidth:5,markerHeight:5,orient:'auto'}))mutedMarker.setAttribute(k,v);
    mutedTip.setAttribute('d','M 0 0 L 10 5 L 0 10 z');mutedTip.setAttribute('fill','#7b9cae');mutedMarker.append(mutedTip);defs.append(mutedMarker);this.overlay.append(defs);this.routes=new Map();
    for(let i=0;i<PIPE_PROFILE.active;i++){const d=make('i',null,'pipe-dot');d.hidden=true;d.setAttribute('aria-hidden','true');root.append(d);this.dots.push(d);}
    this.motion=new PipelineMotion(ds=>this.draw(ds));this.state=new PipelineState(this.motion);this.motion.onSample=()=>this.metrics();
    this.abort=new AbortController();window.addEventListener('resize',()=>this.measure(),{signal:this.abort.signal});
    if(typeof ResizeObserver!=='undefined'){this.resize=new ResizeObserver(()=>this.measure());this.resize.observe(root);}
  }
  update(view,c0,options={}){
    const original=view.pipeline||{namespace:view.session_id,epoch:view.epoch,cursor:view.cursor,mode:view.mode,records:[],telemetry_gap:true};
    const p={...original,records:[...original.records,...pipelineC0(c0,original.expires_at)]};
    // This is a local DOM-application observation, never an output acknowledgement.
    for(const r of original.records)if(!options.liveFixed&&r.stage==='project'&&r.status==='projected')p.records.push({...r,id:r.id+':dom',stage:'display',source_stage:'project',parent:r.id,status:'DOM_applied_not_paint_or_ack'});
    const before=this.state.key;this.state.update(p,{...options,c0Session:c0?.session_id});this.options=options;this.view=view;this.c0=c0;
    const records=this.state.records;
    for(const [id,{b,status,counts,connection}]of this.boxes){const rs=records.filter(r=>r.stage===id),last=rs.at(-1);let text='not_connected';
      if(['program','rule'].includes(id))text='FIXTURE専用／実推論なし';
      if(['vision','audio'].includes(id)){const m=p.source_status?.models?.[id==='vision'?'image':'asr'];text=m?('保存動画 · '+(m.state||'unknown')):'このrunでは無効';}
      if(['input','decode','analyze','record','project'].includes(id))text=view.mode.includes('OBSERVATION')?'接続済み・記録なし':view.mode==='CONTEXT_FIXTURE'?'FIXTURE接続':'記録なし';
      if(id==='evaluate'&&view.mode==='CONTEXT_FIXTURE')text='合成評価専用 · 実Jev未接続';
      if(['person','place','conversation'].includes(id))text='実観測の意味採用 NOT_CONNECTED';
      if(last)text=last.status+(last.started_at==null&&['completed','APPLIED','projected'].includes(last.status)?' · 開始時刻なし':'');
      if(id==='analyze'&&view.mode.includes('OBSERVATION'))text+=` · ${options.frozen?'固定時点':'現在'}queue ${p.source_status?.queued??'不明'} / running ${p.source_status?.active===true?1:p.source_status?.active===false?0:'不明'}`;
      if(['audio','vision'].includes(id)&&p.source_status?.lanes){const l=p.source_status.lanes[id==='audio'?'asr':'image'];text=`待${l.queued} / 動${l.active} / 済${l.completed}`;b.title=`${l.state} · 最古 ${l.oldest_media??'なし'} · 遅延 ${l.last_latency??'未取得'} · 非受付 ${l.rejected} · 取消 ${l.cancelled}`;}
      if(id==='record'&&p.source_status?.observation_error)text='NOT_RECORDED · '+p.source_status.observation_error;
      if(id==='display')text=options.liveFixed?'LIVE図のみ／固定mapには未反映':view.retention==='expired'?'期限切れ・参照不可':view.mode==='CONTEXT_FIXTURE'?'合成文脈のDOM適用':view.mode.includes('OBSERVATION')?'観測記録のDOM適用／未評価':'DEMO／表示のみ';
      b.dataset.running=String(id==='analyze'&&p.source_status?.active===true&&this.state.mode!=='Replay');
      if(['audio','vision'].includes(id)&&p.source_status?.lanes)b.dataset.running=String(p.source_status.lanes[id==='audio'?'asr':'image'].active>0&&this.state.mode!=='Replay');
      let connected='NOT_CONNECTED';
      if(['program','rule'].includes(id)||['evaluate','validate'].includes(id)&&view.mode==='CONTEXT_FIXTURE')connected='FIXTURE_ONLY';
      if(['vision','audio'].includes(id)){const m=p.source_status?.models?.[id==='vision'?'image':'asr'];connected=!m?'DISABLED':/SYNTHETIC|synthetic|FAKE/.test(m.state)?'FIXTURE_ONLY':/ready|available/i.test(m.state)?'CONNECTED':'DISABLED';}
      if(['input','decode','analyze','record','project','display'].includes(id))connected=view.mode.includes('OBSERVATION')?'CONNECTED':view.mode==='CONTEXT_FIXTURE'?'FIXTURE_ONLY':'DISPLAY_ONLY';
      if(['output','delivery','ack'].includes(id))connected='FIXTURE_ONLY';
      b.dataset.connection=connected;connection.textContent=({NOT_CONNECTED:'未接続',DISABLED:'無効',FIXTURE_ONLY:'合成専用',CONNECTED:'接続済',DISPLAY_ONLY:'表示のみ'})[connected];
      const states={};for(const r of rs)states[r.status]=(states[r.status]||0)+1;
      const execution=id==='analyze'&&p.source_status?.active===true&&this.state.mode!=='Replay'?'processing':last?.status||'idle';
      status.textContent=(this.state.mode==='Replay'?'Replay: ':'')+(id==='record'&&p.source_status?.observation_error?'NOT_RECORDED':id==='display'&&options.liveFixed?'固定map未反映':execution);
      counts.textContent=rs.length?`記録 ${rs.length}`:'記録なし';b.title=`${PIPE_STAGES[id]} · ${connected}\n${text}\n${Object.entries(states).map(([k,n])=>`${k} ${n}`).join(' / ')||'記録なし'}`;
      const lane=['audio','vision'].includes(id)&&p.source_status?.lanes?.[id==='audio'?'asr':'image'];
      if(lane){status.textContent=`${this.state.mode==='Replay'?'Replay: ':''}待 ${lane.queued} / 動 ${lane.active}`;counts.textContent=`待 ${lane.queued} · 動 ${lane.active} · 完 ${lane.completed}`;
        b.title+=`\n${lane.state} · 最古 ${lane.oldest_media??'なし'} · 遅延 ${lane.last_latency??'未取得'} · 非受付 ${lane.rejected} · 取消 ${lane.cancelled}`;}
      b.dataset.state=last?.status||text;b.classList.toggle('pipe-muted',!!options.selected&&!options.whole&&!rs.some(r=>r.refs.includes(options.selected)));
      b.classList.toggle('pipe-warning',rs.some(r=>['failed','cancel_requested','unavailable','STORAGE_FAILED'].includes(r.status)));
    }
    this.recent.replaceChildren();for(const r of records.slice(-8).reverse()){const b=this.make('button',`${r.stage} · ${r.status} · #${r.source_cursor}`);b.type='button';b.onclick=()=>this.pick(r);this.recent.append(b);}
    this.updateInfo();if(before!==this.state.key||this.applied!==p.cursor){this.measure();this.applied=p.cursor;}this.metrics();
  }
  updateInfo(){const p=this.state.snapshot||{};this.info.textContent=`${p.mode||'記録なし'} · ${this.state.mode} · cursor ${p.cursor??'不明'} · 図世代 ${this.motion.generation} · 元記録省略 ${p.omitted_records||0} · telemetry ${p.telemetry_gap?'gap／部分履歴':'受領範囲'} · 演出省略 ${this.motion.omitted} · 演出集約 ${this.motion.aggregated}`;}
  pickStage(id){const r=this.state.records.filter(r=>r.stage===id).at(-1);this.pick(r||{stage:id,status:'not_connected_or_no_record',refs:[],namespace:this.state.snapshot?.namespace,source_cursor:this.state.snapshot?.cursor});}
  measure(){if(!this.root.isConnected||this.root.hidden)return;const origin=this.root.getBoundingClientRect();this.points.clear();this.routes.clear();for(const line of this.paths.values())line.setAttribute('visibility','hidden');
    for(const [id,{b}]of this.boxes){if(['output','delivery','ack'].includes(id)&&!this.output.open)continue;const r=b.getBoundingClientRect();if(r.width&&r.height)this.points.set(id,{x:r.x-origin.x,y:r.y-origin.y,width:r.width,height:r.height});}
    this.overlay.setAttribute('width',origin.width);this.overlay.setAttribute('height',origin.height);
    const edges=new Set(['llm|input','vision|input','audio|input','program|input','rule|input','sensor|input','input|decode','decode|analyze','analyze|record','decode|evaluate','evaluate|validate','validate|person','validate|place','validate|conversation','person|display','place|display','conversation|display','record|project','validate|project','project|display','output|delivery','delivery|ack']);
    for(const r of this.state?.records||[])if(r.source_stage&&r.parent)edges.add(r.source_stage+'|'+r.stage);
    for(const edge of edges){const [a,b]=edge.split('|'),p=this.points.get(a),q=this.points.get(b);let line=this.paths.get(edge);
      if(!line){line=document.createElementNS('http://www.w3.org/2000/svg','path');line.setAttribute('fill','none');line.setAttribute('marker-end','url(#pipeline-arrow)');this.overlay.append(line);this.paths.set(edge,line);}
      line.setAttribute('visibility',p&&q?'visible':'hidden');if(p&&q){const wrapped=b==='input'&&['llm','vision','audio','program','rule','sensor'].some(id=>(this.points.get(id)?.y??p.y)>p.y);const route=pipeRoute(p,q,wrapped?'source-wrap':['record|project','validate|project'].includes(edge));this.routes.set(edge,route);line.setAttribute('d',route.map((v,i)=>`${i?'L':'M'} ${v.x} ${v.y}`).join(' '));line.setAttribute('data-edge',edge);
        const planned=[a,b].some(id=>['NOT_CONNECTED','DISABLED','DISPLAY_ONLY'].includes(this.boxes.get(id)?.b.dataset.connection));line.setAttribute('data-planned',String(planned));line.setAttribute('marker-end',planned?'url(#pipeline-arrow-planned)':'url(#pipeline-arrow)');}
    }
  }
  draw(rows){for(let i=0;i<this.dots.length;i++){const d=this.dots[i],row=rows[i],route=row&&this.routes.get(row.record.source_stage+'|'+row.record.stage);d.hidden=!route;
      if(route){const p=pipePoint(route,row.progress);d.style.transform=`translate(${p.x-2.5}px,${p.y-2.5}px)`;d.title=`この区間の遷移 ${row.count}件`;}}
  }
  metrics(){this.root.dataset.pipelineFrames=this.motion.frames;this.root.dataset.pipelinePending=this.motion.pending===null?'0':'1';this.root.dataset.pipelineActive=this.motion.dots.length;this.root.dataset.pipelineQueue=this.motion.queue.length;this.root.dataset.pipelineGeneration=this.motion.generation;
    if(this.diagnostics)this.diagnostics.textContent=JSON.stringify({profile:PIPE_PROFILE,frames:this.motion.frames,pending:this.motion.pending===null?0:1,active:this.motion.dots.length,queue:this.motion.queue.length,activeMax:this.motion.activeMax,queueMax:this.motion.queueMax,omitted:this.motion.omitted,aggregated:this.motion.aggregated,suppressed:this.motion.suppressed,frameWorkMs:this.motion.samples,mode:this.state.mode,generation:this.motion.generation},null,2);}
  replay(){this.state.replay();if(this.view)this.update(this.view,this.c0,this.options);this.updateInfo();this.metrics();}
  cancel(reason){this.motion.cancel(reason);this.metrics();}
  dispose(){this.state.dispose();this.view=null;this.c0=null;this.abort.abort();this.resize?.disconnect();this.output.ontoggle=null;this.recordsPanel.ontoggle=null;for(const {b}of this.boxes.values())b.onclick=null;this.recent.replaceChildren();this.metrics();}
}
if(typeof module!=='undefined')module.exports={PipelineView,PIPE_STAGES,pipeRoute,pipePoint};
