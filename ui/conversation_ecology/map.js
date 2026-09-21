"use strict";
const $=id=>document.getElementById(id), display=new MapState(), ns='http://www.w3.org/2000/svg';
const uiEvents=new AbortController();
function listen(target,type,handler,options={}){target.addEventListener(type,handler,{...options,signal:uiEvents.signal});}
let state=null, transport=true, historyFrozen=null, selectedHistory=null, c0Session=null, pending=Promise.resolve();
const processHistory=new ProcessHistoryView(api);
let zoom=1,panX=0,panY=0,overviewZoom=1,initialFit=true,level=0,expanded=false,wholeSchematic=false,streamTimer=null;
const camera=new CameraMotion(c=>{zoom=c.zoom;panX=c.x;panY=c.y;level=semanticLevel(level,zoom/overviewZoom);renderMap();});
const layout=new LayoutState(), positions=layout.points, sentAcks=new Set(), regionInfo=[['person','人物',250,145,'#46d9e8'],['place','場所',750,145,'#f4b45b'],['conversation','会話内容',500,365,'#d77ce8']];
function el(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;}
function svg(tag,attrs){const e=document.createElementNS(ns,tag);for(const [k,v]of Object.entries(attrs))e.setAttribute(k,v);return e;}
async function api(path,body){if(!transport)throw Error('接続断DEMO・再同期してください');const r=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json','X-C0-Token':state.token},body:JSON.stringify(body)}:{});const data=await r.json();if(!r.ok)throw Error(data.error||r.status);return data;}
function run(operation){const next=pending.then(operation).catch(e=>{$('error').hidden=false;$('error').textContent=String(e.message);});pending=next;return next;}
async function receive(data,useDelta=false){
  if(data.view.expires_at&&Date.now()/1000>=data.view.expires_at)data.view=expiredObservationView(data.view);
  state=data.c0;
  if(data.operation)$('operation').textContent='結果: '+JSON.stringify(data.operation.status?{status:data.operation.status,commit_id:data.operation.commit_id,affected:data.operation.affected}:data.operation);
  const sessionChange=!display.live||layoutKey(display.live)!==layoutKey(data.view);
  if(sessionChange){selectedPipeline=null;pipelineFixedC0=null;pipelineResync=true;display.snapshot(data.view);selectedHistory=null;historyFrozen=null;runner.stop('session_changed');cancelPointer();renderer.clear();positions.clear();fit();drawNotices.clear();}
  else if(useDelta&&data.delta){const outcome=display.delta(data.delta);$('operation').textContent='差分: '+outcome;if(outcome==='gap'){massImmediate=true;pipelineResync=true;display.snapshot((await api('/api/map')).view);$('operation').textContent='欠番 → 同範囲snapshot再同期';}}
  else display.snapshot(data.view);
  if(display.live?.cursor===data.view.cursor&&layoutKey(display.live)===layoutKey(data.view))display.live.pipeline=structuredClone(data.view.pipeline);
  processHistory.projection(data.view);render();
}
function expiredObservationView(v){return {...v,epoch:(v.epoch||0)+1,expires_at:0,retention:'expired',status:'期限切れ・Replay不完全',nodes:[],edges:[],history:[],layers:{},schematic:[],responses:[],acks:[],record_count:0,pipeline:null,field_snapshots:[],mass_distributions:[],mass_status:'expired',fields:Object.fromEntries(['person','place','conversation'].map(k=>[k,{UNKNOWN:null,scope:'expired'}]))};}
const expiryTimer=setInterval(()=>{if(display.live?.expires_at&&Date.now()/1000>=display.live.expires_at){
  display.snapshot(expiredObservationView(display.live));display.live.pipeline=null;display.fixed=null;historyFrozen=null;selectedHistory=null;display.selected=null;pipelineFixedC0=null;selectedPipeline=null;render();
}},1000);
window.addEventListener('pagehide',()=>clearInterval(expiryTimer));
function mapAction(body){if(['demo','context_start','mass_start'].includes(body.action)&&streamTimer){clearInterval(streamTimer);streamTimer=null;}return run(async()=>{await receive(await api('/api/map/action',body),true);});}
function cameraValue(){return {zoom,x:panX,y:panY};}
function moveCamera(target,immediate=false){camera.move(cameraValue(),target,immediate||matchMedia('(prefers-reduced-motion: reduce)').matches);}
function fit(){camera.cancel();zoom=1;panX=0;panY=0;overviewZoom=1;initialFit=true;level=0;}
function fitAll(){const target=graphFit(positions.values());overviewZoom=target.zoom;moveCamera(target);}
function transform(){
  $('world').setAttribute('transform',`translate(${panX} ${panY}) scale(${zoom})`);
  $('minimap').hidden=zoom/overviewZoom<=1.05;
  if(!$('minimap').children.length){for(const [,label,x,y,color]of regionInfo){const t=svg('text',{x,y,fill:color,'font-size':60});t.textContent=label;$('minimap').append(t);}$('minimap').append(svg('rect',{fill:'none',stroke:'#fff','stroke-width':8}));}
  const viewRect=$('minimap').lastElementChild;for(const [k,v]of Object.entries({x:-panX/zoom,y:-panY/zoom,width:1000/zoom,height:500/zoom}))renderer.attr(viewRect,k,v);
  $('map').dataset.zoom=zoom.toFixed(3);$('map').dataset.pan=`${panX.toFixed(2)},${panY.toFixed(2)}`;$('map').dataset.relativeZoom=(zoom/overviewZoom).toFixed(3);
}
function zoomAt(factor,x=500,y=250){moveCamera(graphZoom(camera.target||cameraValue(),factor,x,y,overviewZoom));}
function center(region){const r=regionInfo.find(x=>x[0]===region);if(!r){fitAll();return;}
  const points=display.view.nodes.filter(n=>n.region===region).map(n=>positions.get(n.id)).filter(Boolean);
  moveCamera(graphFit(points.length?points:[{x:r[2],y:r[3]}],[250,170],overviewZoom*3));}
function locate(n){const p=aggregatePoints().get(n.id);select(n.id);if(p){const z=overviewZoom*4;moveCamera({zoom:z,x:500-p.x*z,y:250-p.y*z});}}
function select(id){display.selected=id;selectedHistory=null;selectedPipeline=null;renderMap();renderDetail();renderHistory();}
const renderer=new MapRenderer($('nodes'),$('edges'),svg,select),gesture=new NodeGesture(),drawNotices=new Set();
let massEnabled=true,massImmediate=false,massGeometry=null;
const massMotion=new MassMotion(()=>{if(disposed||!massGeometry)return;renderer.resize(massGeometry);massMetrics();});
const massTools=el('details',undefined,'mass-tools');massTools.append(el('summary','注意量サイズ・合成数値fixture'));$('fields').before(massTools);
for(const [label,body]of [['小型の数値fixture',{action:'mass_start'}],['200点の対照',{action:'mass_start',dense:true}],...['initial','seed','boost','contra','decay','replay'].map(stage=>[({initial:'未観測',seed:'A/B/C支持',boost:'Aの独立根拠追加',contra:'Aの反証',decay:'時刻13秒の減衰',replay:'支持時点をReplay'})[stage],{action:'mass_step',stage}])]){const b=el('button',label);b.onclick=()=>mapAction(body);massTools.append(b);}
const massToggle=el('button','サイズ補間 ON');massToggle.id='mass-motion';massToggle.onclick=()=>{massEnabled=!massEnabled;massToggle.textContent='サイズ補間 '+(massEnabled?'ON':'OFF');massImmediate=true;renderMap();};massTools.append(massToggle);
const massStatus=el('span');massStatus.id='mass-status';massTools.append(massStatus);
const massLegend=el('p','面積の増分＝その分布の注意量（正しさ・承認ではない）。? は分布内UNKNOWN。未評価/未提供は中立サイズ。詳細の数値は受理snapshot、途中サイズは表示補間。','legend');massTools.after(massLegend);
function massMetrics(){$('map').dataset.massFrames=massMotion.frames;$('map').dataset.massPending=massMotion.pending===null?'0':'1';massStatus.textContent=`${display.view?.mass_stage||display.view?.mass_status||'未提供'} · ${massMotion.pending===null?'静止':'サイズ補間中'} · frame ${massMotion.frames}`;}
listen(massTools,'toggle',()=>{if(!massTools.open){massImmediate=true;renderMap();}});
let selectedPipeline=null,pipelineFixedC0=null,pipelineLive=false,pipelineMotion=true,pipelineCollapsed=false,pipelineResync=false;
const pipeline=new PipelineView($('schematic'),r=>{selectedPipeline={id:r.id,stage:r.stage,namespace:r.namespace};selectedHistory=null;
  if(!pipelineLive||!display.fixed){const n=display.view.nodes.find(n=>r.refs.includes(n.id));if(n)display.selected=n.id;}
  renderMap();renderDetail();});
const pipeTools=el('div',undefined,'pipeline-tools');$('schematic').before(pipeTools);
for(const [id,label,handler]of [
  ['pipeline-motion','動き ON',()=>{pipelineMotion=!pipelineMotion;$('pipeline-motion').textContent='動き '+(pipelineMotion?'ON':'OFF');renderPipeline();}],
  ['pipeline-live','図もマップ時点',()=>{pipelineLive=!pipelineLive;$('pipeline-live').textContent=pipelineLive?'図はLIVE（別時点）':'図もマップ時点';pipelineResync=true;renderDetail();}],
  ['pipeline-replay','図の履歴をReplay',()=>pipeline.replay()],
  ['pipeline-collapse','図を折り畳む',()=>{pipelineCollapsed=!pipelineCollapsed;$('schematic').hidden=pipelineCollapsed;$('pipeline-collapse').textContent=pipelineCollapsed?'図を開く':'図を折り畳む';renderPipeline();if(!pipelineCollapsed)pipeline.measure();}]
]){const b=el('button',label);b.id=id;b.onclick=handler;pipeTools.append(b);}
const pipeDiagnostics=el('details',undefined,'layout-diagnostics');pipeDiagnostics.append(el('summary','模式図の表示計測'));pipeline.diagnostics=el('pre');pipeDiagnostics.append(pipeline.diagnostics);if(pipeline.recordsPanel)pipeline.recordsPanel.append(pipeDiagnostics);else $('schematic').after(pipeDiagnostics);
function renderPipeline(){if(!display.view||disposed)return;const v=pipelineLive?display.live:display.view;
  pipeline.update(v,display.fixed&&!pipelineLive?pipelineFixedC0:state,{frozen:!!display.fixed&&!pipelineLive,liveFixed:!!display.fixed&&pipelineLive,
    hidden:document.visibilityState!=='visible',off:!pipelineMotion,collapsed:pipelineCollapsed,reduced:matchMedia('(prefers-reduced-motion: reduce)').matches,
    stopped:disposed||v.media_live?.status==='stopped',resync:pipelineResync,whole:wholeSchematic,selected:display.selected});pipelineResync=false;
}
let aggregateNodes=[],shownNodes=[],resumeLayout=false,disposed=false,noticeFrames=new Set(),inputAt=null;
listen(matchMedia('(prefers-reduced-motion: reduce)'),'change',()=>{massImmediate=true;renderMap();pipelineResync=true;renderPipeline();});
const aggregatePlacement=new Map();let aggregateGeneration=-1;const selectionTrace=[],visibilityTrace=[];
const runner=new LayoutRunner(layout,drawCoordinates);
runner.onSample=layoutMetrics;
camera.onSample=layoutMetrics;
function aggregatePoints(){const all=new Map(positions);if(aggregateGeneration!==layout.key+layout.structure){aggregatePlacement.clear();aggregateGeneration=layout.key+layout.structure;}
  return aggregateLocations(aggregateNodes,positions,aggregatePlacement);}
function layoutMetrics(){const m=$('map');m.dataset.layoutStatus=layout.status;m.dataset.layoutGeneration=layout.generation;m.dataset.layoutTicks=layout.ticks;m.dataset.layoutPending=runner.pending===null?'0':'1';m.dataset.layoutProfile=LAYOUT_PROFILE.version;
  m.dataset.cameraPending=camera.pending===null?'0':'1';m.dataset.cameraFrames=camera.frames;m.dataset.overviewZoom=overviewZoom;
  $('layout-status').textContent=`配置 ${layout.status} · tick ${layout.ticks} · pending ${m.dataset.layoutPending}`;
  // Bounded display telemetry, not context evidence. Full samples are available in visible details.
  $('layout-metrics').textContent=JSON.stringify({profile:LAYOUT_PROFILE,displayProfile:GRAPH_PROFILE,camera:{pending:camera.pending===null?0:1,frames:camera.frames,samples:camera.samples},session:layout.key,structureGeneration:layout.generation,ticks:layout.ticks,status:layout.status,pending:runner.pending===null?0:1,rejected:layout.rejected,samples:runner.samples.slice(-600),inputToDOM:inputSamples.slice(-120),selectionTrace,visibilityTrace,listenersAborted:uiEvents.signal.aborted},null,2);
}
const inputSamples=[];
function drawCoordinates(){if(disposed)return;if(!matchMedia('(prefers-reduced-motion: reduce)').matches||layout.status!=='running')renderer.coordinates(aggregatePoints());layoutMetrics();if(inputAt!==null){inputSamples.push(performance.now()-inputAt);if(inputSamples.length>120)inputSamples.shift();inputAt=null;}}
function renderMap(){
  const started=performance.now(),v=display.view;if(!v||disposed)return;
  massMotion.update(v,{immediate:massImmediate||!!display.fixed||!massEnabled||!massTools.open||document.visibilityState!=='visible'||matchMedia('(prefers-reduced-motion: reduce)').matches||v.media_live?.status==='stopped'});massImmediate=false;
  if(!display.fixed){const changed=layout.sync(v,resumeLayout);resumeLayout=false;if(changed){runner.stop();if(document.visibilityState==='visible')runner.start();else{resumeLayout=true;runner.stop('hidden');}}else if(['frozen','hidden'].includes(layout.status))layout.status='idle';}
  if(display.selected&&!v.nodes.some(n=>n.id===display.selected)&&!display.selected.startsWith('@aggregate:'))display.selected=null;
  if(initialFit){const target=graphFit(positions.values());zoom=overviewZoom=target.zoom;panX=target.x;panY=target.y;initialFit=false;}
  const bounds=$('map').getBoundingClientRect(),scale=Math.max(.001,Math.min(bounds.width/1000,bounds.height/500)*zoom),s=zoom/overviewZoom,font=graphPixels('label',s)/scale;
  if(!$('regions').children.length)for(const [id,label,x,y,color]of regionInfo){const t=svg('text',{x:x-70,y:y-100,fill:color,class:'region-title','data-region-id':id});$('regions').append(t);}
  for(const t of $('regions').querySelectorAll('text')){const r=regionInfo.find(r=>r[0]===t.dataset.regionId);renderer.text(t,r[1]+'領域'+(v.nodes.some(n=>n.region===r[0])?'':' · 項目なし'));t.style.fontSize=graphPixels('region',s)/scale+'px';}
  const grouped=v.nodes.length>60&&level<2&&!expanded;
  shownNodes=grouped?v.nodes.filter(n=>n.kind==='Entity'||n.kind==='Unknown'||(level===1&&n.kind==='Claim')||n.id===display.selected):v.nodes.slice();
  aggregateNodes=[];if(grouped){const shownIds=new Set(shownNodes.map(n=>n.id));for(const [region,label]of regionInfo){const children=v.nodes.filter(n=>n.region===region&&!shownIds.has(n.id)).map(n=>n.id);if(children.length)aggregateNodes.push({id:'@aggregate:'+region,kind:'Aggregate',region,label:`${label} · ${children.length}件を集約`,children,state:'display_only',availability:'display_projection',revision:v.cursor});}}
  const all=[...shownNodes,...aggregateNodes],near=new Set(display.edges().filter(e=>[e.source,e.target].includes(display.selected)).flatMap(e=>[e.source,e.target]).slice(0,12));
  const representatives=new Set();for(const [region]of regionInfo)for(const n of shownNodes.filter(n=>n.region===region&&n.kind==='Entity').slice(0,bounds.width<600?1:3))representatives.add(n.id);
  massGeometry={scale,sizes:n=>nodeDiameter(n,s,massMotion.value(n))/2/scale,hit:n=>Math.max(GRAPH_PROFILE.hit,nodeDiameter(n,s,massMotion.value(n))/2+2)/scale,mass:n=>massValue(n)!==null};
  const labels=renderer.sync(all,display.edges(),{selected:display.selected,level,font,...massGeometry,color:n=>GRAPH_PROFILE.colors[n.region]||'#aaa',
    label:n=>n.kind==='Unknown'||n.kind==='Aggregate'||n.id===display.selected||near.has(n.id)||v.nodes.length<=12||representatives.has(n.id),
    text:n=>{let text=n.label.slice(0,24)+(n.label.length>24?'…':'');if(level>=1&&n.state)text+=' · '+n.state;if(level>=2)text+=` · r${n.revision} · 根拠${n.source_refs?.length??0}`;if(level>=3)text+=' · '+(n.timestamp??n.observed_at??'時刻未取得');return text;}});
  $('counts').textContent=`正本参照 ${new Set(v.nodes.filter(n=>!n.display_only).map(n=>n.canonical_id)).size} · 表示ノード ${shownNodes.length} · UNKNOWN表示 ${v.nodes.filter(n=>n.kind==='Unknown').length} · 集約 ${aggregateNodes.length} · 表示省略 ${v.nodes.length-shownNodes.length} · 辺省略 ${display.edges().length-renderer.edgeCache.size}`;
  $('lod').textContent=`${['全体','領域','対象','根拠'][level]} · ラベル省略 ${all.length-labels}`;
  $('cursor').textContent=`${display.fixed?'固定':'最新'} cursor ${v.cursor}`;$('incoming').textContent=display.incoming;
  for(const [id,label,,,color]of regionInfo){let e=$('fields').querySelector('[data-field="'+id+'"]');if(!e){e=el('div','','field');e.dataset.field=id;e.style.color=color;$('fields').append(e);}const distributions=(v.mass_distributions||[]).filter(d=>d.space===id),summary=distributions.map(d=>`${d.scope}: ${d.status==='available'&&Number.isFinite(d.UNKNOWN)?(d.UNKNOWN*100).toFixed(1)+'%':d.status==='available'?'未提供':d.status}`).join(' / ');renderer.text(e,`${label} · ${v.nodes.filter(n=>n.region===id).length}表示 · UNKNOWN ${summary||'数値未提供'}`);}
  transform();drawCoordinates();massMetrics();$('map').dataset.renderMs=(performance.now()-started).toFixed(2);$('map').dataset.labelPixels=graphPixels('label',s).toFixed(2);$('map').dataset.regionPixels=graphPixels('region',s).toFixed(2);$('map').dataset.lod=level;
  // At most one map notification per actual projection version, independent of layout and camera.
  const key=layoutKey(v)+':'+v.cursor;if(!drawNotices.has(key)&&!display.fixed&&document.visibilityState==='visible'){
    drawNotices.add(key);if(drawNotices.size>1024)drawNotices.delete(drawNotices.values().next().value);
    const frame=requestAnimationFrame(()=>{noticeFrames.delete(frame);const second=requestAnimationFrame(()=>{noticeFrames.delete(second);if(!disposed&&display.view&&layoutKey(display.view)===layoutKey(v)&&display.view.cursor===v.cursor&&!display.fixed){processHistory.projection(v,true);run(()=>api('/api/map/action',{action:'map_draw',session_id:v.session_id,cursor:v.cursor}));}else drawNotices.delete(key);});noticeFrames.add(second);});noticeFrames.add(frame);
  }
}
function renderDetail(){
  const v=display.view;if(!v)return;const n=v.nodes.find(x=>x.id===display.selected)||aggregateNodes.find(x=>x.id===display.selected);
  $('map-detail').open=!!(n||selectedPipeline||selectedHistory);
  $('selected-label').textContent=n?`${n.region} ＞ ${n.label}`:'未選択';$('schematic-cursor').textContent=`${v.mode} · ${v.session_id} · cursor ${v.cursor}（マップと同時点）`;
  if(display.live?.media_live)$('schematic-cursor').textContent+=` ｜ 媒体LIVE epoch ${display.live.media_live.epoch} / ${display.live.media_live.status} · マップ${display.fixed?'固定':'最新'}`;
  $('schematic-cursor').title=$('schematic-cursor').textContent;
  renderPipeline();
  if(selectedPipeline){const r=pipeline.state.records.find(r=>r.id===selectedPipeline.id&&r.namespace===selectedPipeline.namespace);
    $('detail-summary').textContent=`模式図 · ${pipeline.state.mode} · cursor ${pipeline.state.snapshot?.cursor} · ${selectedPipeline.stage}`;
    $('detail').textContent=JSON.stringify(r||{status:'参照不可／記録なし',...selectedPipeline},null,2);$('related').replaceChildren();
    if(r&&(!pipelineLive||!display.fixed))for(const id of r.refs){const target=v.nodes.find(n=>n.id===id);if(target){const go=el('button','地図で表示: '+target.label);go.onclick=()=>locate(target);$('related').append(go);}}return;}
  if(selectedHistory){$('detail-summary').textContent=`履歴cursor ${selectedHistory.cursor}${display.fixed&&selectedHistory.cursor>v.cursor?' · LIVE履歴／固定マップには未反映':''}`;$('detail').textContent=JSON.stringify(selectedHistory,null,2);return;}
  $('detail-summary').textContent=n?`${n.kind} · r${n.revision} · ${n.state} · ${n.display_only?'分布の表示参照':n.availability==='available'?'出典参照あり':n.availability+'／未取得'} · 注意量 ${n.mass?.status==='available'?n.mass.value:n.mass?.status||'未提供'}`:'点・履歴を選ぶと、その時点の参照を表示します。';
  $('detail').textContent=n?JSON.stringify(n.kind==='OpenIssue'?{...n,comparison:v.comparison,goal:v.goal,planned_jobs:v.jobs,last_context_result:v.last_result}:n,null,2):'';$('related').replaceChildren();
  if(n?.kind==='Aggregate'){for(const id of n.children){const child=v.nodes.find(x=>x.id===id),b=el('button',child.label);b.onclick=()=>select(id);$('related').append(b);}}
  if(n){const go=el('button','\u5730\u56f3\u3067\u8868\u793a');go.onclick=()=>locate(n);$('related').append(go);}
  if(n)for(const e of display.edges().filter(e=>[e.source,e.target].includes(n.id))){const other=v.nodes.find(x=>x.id===(e.source===n.id?e.target:e.source));const b=el('button',`${e.source===n.id?'→':'←'} ${e.relation} · ${other.label}`);b.onclick=()=>select(other.id);$('related').append(b);}
}
function renderHistory(){processHistory.synthetic(display.live,state);}
function renderConversation(){
  if(!state)return;if(c0Session!==state.session_id){c0Session=state.session_id;sentAcks.clear();selectedHistory=null;renderDetail();}
  $('important').textContent=`C0 ${state.status} · commit ${state.commits.length} / browser_dom ack ${state.acks.filter(a=>a.kind==='browser_dom').length}${state.main_pending?' · 本題pending':''}${state.snapshot?.work_states.length?' · 合成TaskEvent 承認待ち・実権限なし':''}`;
  if(display.live?.mode==='CONTEXT_FIXTURE')$('important').textContent+=` ｜ 共通文脈: ${display.live.question?.branch_state||'NO_ASK'} · 対象 ${JSON.stringify(display.live.goal?.target_binding)} · 希望 ${display.live.goal?.preference??'未回答'} · 本題pending · 実作業なし`;
  const rows=[...state.events.filter(e=>e.kind==='transcript').map(e=>({id:e.id,text:e.payload.text,label:`合成発話 r${e.payload.revision}`})),...state.commits.map(c=>({id:c.id,text:c.text||'（無応答／保留）',label:'反応 FIXTURE',commit:c}))];
  for(const c of display.live?.responses||[])rows.push({id:c.id,text:c.text,label:'確認 FIXTURE',contextCommit:c});
  for(const u of display.live?.utterances||[])rows.push({id:display.live.session_id+':'+u.id+':r'+u.revision,text:u.text,label:`原文 FIXTURE r${u.revision}`});
  const box=$('messages'), existing=new Map([...box.children].map(e=>[e.dataset.messageId,e]));box.replaceChildren(...rows.map(row=>{let e=existing.get(row.id);if(!e){e=el('div',undefined,'message');e.dataset.messageId=row.id;e.append(el('small',`${row.label} · ${row.id}`),el('div',row.text,'bubble'));}if(row.commit)e.dataset.commitId=row.id;if(row.contextCommit)e.dataset.contextCommitId=row.id;return e;}));
  // Only the last visible message is acknowledged in collapsed mode. Expanding exposes history.
  for(const c of state.commits)ackVisible(c,false);for(const c of display.live?.responses||[])ackVisible(c,true);
  $('reply-actions').replaceChildren();
  if(display.live?.mode==='CONTEXT_FIXTURE'){
    for(const label of ['動画解析の方です','会話処理の方です','はい','分からない','後で','両方','違う。字幕の方','動画側で、メモリを減らしたい']){const b=el('button',label);b.onclick=()=>mapAction({action:'reply',text:label,reply_id:crypto.randomUUID()});$('reply-actions').append(b);}
    for(const [action,label]of [['correct','質問根拠を訂正'],['context_resend','質問を再送'],['replay','保存Replay確認'],['reported_context','三領域の申告例'],['change_preference','希望を速度へ訂正']]){const b=el('button',label);b.onclick=()=>mapAction({action});$('reply-actions').append(b);}
  }
  renderPipeline();
}
async function ackVisible(c,context){const key=(context?'ctx:':'c0:')+c.id,acks=context?display.live.acks:state.acks;if(sentAcks.has(key)||acks.some(a=>a.commit_id===c.id))return;
  const session=context?display.live.session_id:state.session_id;const e=[...$('messages').children].find(e=>e.dataset.messageId===c.id);if(!e)return;
  await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
  const rect=e.getBoundingClientRect(),box=$('messages').getBoundingClientRect();if(!e.isConnected||document.visibilityState!=='visible'||rect.bottom<=box.top||rect.top>=box.bottom||rect.right<=box.left||rect.left>=box.right||rect.top>=innerHeight||rect.bottom<=0||rect.left>=innerWidth||rect.right<=0)return;
  if(session!==(context?display.live.session_id:state.session_id)||sentAcks.has(key))return;sentAcks.add(key);
  run(async()=>{try{if(context){await receive(await api('/api/map/action',{action:'ack',session_id:session,commit_id:c.id,evidence:'visible_dom_after_two_animation_frames'}));}else{state=await api('/api/action',{action:'ack',session_id:session,commit_id:c.id,evidence:'connected_dom_after_two_animation_frames'});renderConversation();renderHistory();}}catch(e){sentAcks.delete(key);throw e;}});
}
function render(){const v=display.view;$('mode').textContent=v.mode;$('session').textContent=v.session_id;$('connection').textContent=display.status;renderMap();renderDetail();renderConversation();renderHistory();}
$('demo').onclick=()=>mapAction({action:'demo'});$('dense').onclick=()=>mapAction({action:'demo',dense:true});$('step').onclick=()=>mapAction({action:'step',kind:$('step-kind').value});
$('stream').onclick=()=>{if(streamTimer)return;let count=0;streamTimer=setInterval(()=>{if(++count>20){clearInterval(streamTimer);streamTimer=null;return;}mapAction({action:'step',kind:'add'});},1000);};
$('fit').onclick=fitAll;$('plus').onclick=()=>zoomAt(1.25);$('minus').onclick=()=>zoomAt(.8);
document.querySelectorAll('[data-region]').forEach(b=>b.onclick=()=>center(b.dataset.region));$('expand').onclick=()=>{expanded=!expanded;$('expand').textContent=expanded?'集約へ戻す':'集約を展開';renderMap();};
$('freeze').onclick=()=>{resumeLayout=layout.status==='running';runner.stop('frozen');gesture.cancel();pipelineFixedC0=structuredClone(state);display.freeze();render();};$('latest').onclick=()=>{massImmediate=true;pipelineResync=true;pipelineFixedC0=null;display.latest();render();};$('close-detail').onclick=()=>select(null);listen(document,'keydown',e=>{if(e.key==='Escape')select(null);});
$('search').oninput=()=>{const q=$('search').value.toLowerCase();$('search-results').replaceChildren();if(!q)return;for(const n of display.view.nodes.filter(n=>(n.label+' '+n.id).toLowerCase().includes(q)).slice(0,15)){const b=el('button',n.label+' · '+n.id);b.onclick=()=>{select(n.id);$('search-results').replaceChildren();};$('search-results').append(b);}};
$('schematic-mode').onclick=()=>{wholeSchematic=!wholeSchematic;$('schematic-mode').textContent=wholeSchematic?'全体を固定':'選択に連動';renderDetail();};
listen($('map'),'wheel',e=>{e.preventDefault();inputAt=performance.now();const p=mapCoords(e.clientX,e.clientY);zoomAt(Math.exp(-Math.max(-120,Math.min(120,e.deltaY*(e.deltaMode===1?16:1)))*.002),p.x,p.y);},{passive:false});
let drag=null;const pointers=new Map();let pinch=null;
function mapCoords(clientX,clientY){const r=$('map').getBoundingClientRect(),scale=Math.min(r.width/1000,r.height/500);return {x:(clientX-r.left-(r.width-1000*scale)/2)/scale,y:(clientY-r.top-(r.height-500*scale)/2)/scale};}
$('map').onpointerdown=e=>{inputAt=performance.now();camera.cancel();const at=mapCoords(e.clientX,e.clientY),rect=$('map').getBoundingClientRect(),scale=Math.min(rect.width/1000,rect.height/500)*zoom;
  const node=graphHit([...shownNodes,...aggregateNodes],aggregatePoints(),(at.x-panX)/zoom,(at.y-panY)/zoom,scale,zoom/overviewZoom,n=>nodeDiameter(n,zoom/overviewZoom,massMotion.value(n)));pointers.set(e.pointerId,{x:e.clientX,y:e.clientY});
  if(node){gesture.begin(node,layoutKey(display.view),e.clientX,e.clientY);gesture.active.cursor=display.view.cursor;gesture.active.layoutStatus=layout.status;runner.paused=true;drag=null;}
  else if(!gesture.active){const p=mapCoords(e.clientX,e.clientY);drag={x:p.x,y:p.y,px:panX,py:panY};}
  if(pointers.size===2&&!gesture.active){const [a,b]=[...pointers.values()];pinch={distance:Math.hypot(a.x-b.x,a.y-b.y)};drag=null;}
  $('map').setPointerCapture(e.pointerId);
};
$('map').onpointermove=e=>{if(!pointers.has(e.pointerId))return;pointers.set(e.pointerId,{x:e.clientX,y:e.clientY});gesture.move(e.clientX,e.clientY);
  if(gesture.active)return;if(pinch&&pointers.size===2){const [a,b]=[...pointers.values()],d=Math.hypot(a.x-b.x,a.y-b.y),p=mapCoords((a.x+b.x)/2,(a.y+b.y)/2);if(pinch.distance>0)zoomAt(d/pinch.distance,p.x,p.y);pinch.distance=d;return;}
  if(drag){const p=mapCoords(e.clientX,e.clientY);panX=drag.px+p.x-drag.x;panY=drag.py+p.y-drag.y;transform();drawCoordinates();}
};
$('map').onpointerup=e=>{const down=gesture.active,id=gesture.end(layoutKey(display.view),new Set([...shownNodes,...aggregateNodes].map(n=>n.id)));if(down){selectionTrace.push({down_id:down.id,down_key:down.key,down_cursor:down.cursor,down_layout:down.layoutStatus,selected_id:id,up_cursor:display.view.cursor,moved:down.moved});if(selectionTrace.length>40)selectionTrace.shift();}pointers.delete(e.pointerId);drag=null;pinch=null;runner.paused=false;if(id)select(id);else layoutMetrics();};
function cancelPointer(){gesture.cancel();pointers.clear();drag=null;pinch=null;runner.paused=false;}
$('map').onpointercancel=cancelPointer;$('map').onlostpointercapture=cancelPointer;
$('map').ondblclick=e=>e.preventDefault();
listen(document,'visibilitychange',()=>{massImmediate=true;massMotion.settle();if(massGeometry)renderer.resize(massGeometry);if(document.visibilityState!=='visible'){camera.cancel();resumeLayout=layout.status==='running';runner.stop('hidden');cancelPointer();}else{renderMap();acknowledgeVisibleMessages();}pipelineResync=true;renderPipeline();visibilityTrace.push({visibility:document.visibilityState,at:Date.now(),ticks:layout.ticks,pending:runner.pending===null?0:1,status:layout.status});if(visibilityTrace.length>20)visibilityTrace.shift();layoutMetrics();});
listen(document,'pointerdown',()=>{inputAt=performance.now();},{capture:true});
function disposeMap(){disposed=true;massMotion.dispose();massGeometry=null;for(const b of massTools.children)b.onclick=null;pipeline.dispose();for(const b of pipeTools.children)b.onclick=null;camera.cancel();runner.stop('disposed');uiEvents.abort();cancelPointer();if(streamTimer)clearInterval(streamTimer);streamTimer=null;for(const id of noticeFrames)cancelAnimationFrame(id);noticeFrames.clear();renderer.clear();$('map').onpointerdown=$('map').onpointermove=$('map').onpointerup=$('map').onpointercancel=$('map').onlostpointercapture=null;layoutMetrics();}
listen(window,'pagehide',disposeMap,{once:true});
// A persisted page has already disposed its display listeners. Bridge pages
// have the same reload boundary in saved-video.js; do not register it twice.
if(!document.querySelector('meta[name="sv-bridge"]'))window.addEventListener('pageshow',e=>{if(e.persisted)location.reload();});
document.querySelectorAll('[data-c0]').forEach(b=>b.onclick=()=>run(async()=>{state=await api('/api/action',{action:'demo',name:b.dataset.c0});renderConversation();renderHistory();}));
$('resend').onclick=()=>run(async()=>{state=await api('/api/action',{action:'resend',session_id:state.session_id});$('operation').textContent=JSON.stringify(state.operation);renderConversation();renderHistory();});
$('conversation-expand').onclick=()=>{$('messages').classList.toggle('expanded');renderConversation();};
function acknowledgeVisibleMessages(){for(const c of state?.commits||[])ackVisible(c,false);for(const c of display.live?.responses||[])ackVisible(c,true);}
$('messages').onscroll=acknowledgeVisibleMessages;listen(window,'scroll',acknowledgeVisibleMessages,{passive:true});listen(window,'resize',acknowledgeVisibleMessages);
listen(window,'resize',()=>{if(display.view)renderMap();});
$('utterance').onsubmit=e=>{e.preventDefault();run(async()=>{if(display.live.mode==='CONTEXT_FIXTURE')await receive(await api('/api/map/action',{action:'reply',text:$('text').value}));else{state=await api('/api/action',{action:'utterance',text:$('text').value});renderConversation();renderHistory();}});};
$('context-start').onclick=()=>mapAction({action:'context_start'});$('background').onclick=()=>mapAction({action:'background'});$('explicit').onclick=()=>mapAction({action:'context_start',explicit:true});
$('media-open').onclick=()=>$('media-dialog').showModal();$('media-close').onclick=()=>$('media-dialog').close();$('stop-help').onclick=()=>$('help-dialog').showModal();$('help-close').onclick=()=>$('help-dialog').close();
$('disconnect').onclick=()=>{transport=false;display.status='接続断DEMO・最後の同期時点を保持';$('connection').textContent=display.status;};$('reconnect').onclick=()=>{massImmediate=true;pipelineResync=true;transport=true;run(async()=>receive(await api('/api/map')));};
run(async()=>receive(await api('/api/map')));
if(document.querySelector('meta[name="sv-bridge"]')){
  $('observations').onclick=()=>mapAction({action:'observations'});
  let polling=false;
  const observerPoll=setInterval(async()=>{if(polling||disposed||!transport)return;polling=true;processHistory.poll();try{await run(async()=>receive(await api('/api/map')));}finally{polling=false;}},750);
  listen(window,'pagehide',()=>clearInterval(observerPoll));
}
