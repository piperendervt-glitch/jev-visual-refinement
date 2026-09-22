"use strict";
const state={preview:null,historicalCursor:null,operation:0,appliedSeq:-1,pollTimer:null,
  viewSession:"view_"+crypto.randomUUID().replaceAll("-",""),renderToken:0,
  receiptKeys:new Set(),receiptInFlight:new Set(),laneNodes:new Map(),rowNodes:new Map(),thumbNodes:new Map(),
  events:[],lastEventSeq:0,eventsInitialized:false,logSignature:"",timelineSignature:"",latestView:null};
const $=selector=>document.querySelector(selector);
const artifactUrl=id=>`/api/sc01/artifacts/${encodeURIComponent(id)}`;
const laneOf=id=>id?.match(/_([sabc])(?:_e\d+)?$/i)?.[1]?.toUpperCase()||null;
const stateName={CURRENT_WINNER:"暫定採用",AWAITING_EVALUATION:"評価待ち",BELOW_Q_THRESHOLD:"Q下限未達",
  LOWER_Q:"Qが下位",TIE_KEEP_CURRENT:"同点・採用維持",NO_CURRENT_WINNER:"採用なし",
  AWAITING_SEGMENTATION:"候補待ち",FIRST_ELIGIBLE:"初回採用",FIRST_ELIGIBLE_IN_NEW_EVIDENCE:"新根拠で採用",
  HIGHER_Q:"Q上位へ改訂",REFRESHED_SAME_CANDIDATE:"同候補を再評価",OLD_EVIDENCE:"旧根拠",
  ARTIFACT_UNAVAILABLE:"画像利用不可"};
const eventName={KeyframePublished:"合成Kを公開",CandidatePublished:"候補maskを公開",JobQueued:"評価suiteを待機へ",
  JobStarted:"評価suite開始",JobFinished:"評価suite終了",MeasurementsCommitted:"正規化・測定を記録",
  EvidencePublished:"新根拠を公開",EvaluationQueued:"fixture評価を待機へ",
  EvaluationAttemptFinished:"fixture評価結果を記録",CoverageFinalized:"範囲を確定",RunClosed:"runを終了"};
const congestionName={NORMAL:"通常",ATTENTION:"注意",CONGESTED:"混雑",SATURATED:"満杯"};
const shortReason=value=>stateName[value]||value||"—";
function schedule(){clearTimeout(state.pollTimer);state.pollTimer=setTimeout(()=>loadView(false).catch(showError),400);}
function showError(error){document.body.dataset.error=error.message;schedule();}
async function fetchEvents(until){
  if(until<=state.lastEventSeq)return [];
  let after=state.lastEventSeq,added=[];
  for(let page=0;page<26;page++){
    const response=await fetch(`/api/sc01/events?after=${after}&until=${until}`,{cache:"no-store"});
    if(!response.ok)throw new Error(`events_${response.status}`);
    const data=await response.json();added.push(...data.events);
    if(data.complete)break;
    if(data.next_after===null)throw new Error("events_incomplete");
    after=data.next_after;
  }
  state.events.push(...added);state.lastEventSeq=until;
  return added;
}
async function loadView(userOperation=true){
  if(userOperation)state.operation+=1;
  const operation=state.operation,historical=state.historicalCursor!==null;
  const url=historical?`/api/sc01/replay?frame=frame_k0&cursor=${state.historicalCursor}`:
    `/api/sc01/snapshot?frame=frame_k0${state.preview?`&preview=${encodeURIComponent(state.preview)}`:""}`;
  const response=await fetch(url,{cache:"no-store"});if(!response.ok)throw new Error(`snapshot_${response.status}`);
  const payload=await response.json();if(operation!==state.operation)return;
  const view=payload.view||payload;
  if(!historical&&view.snapshot_seq<state.appliedSeq){schedule();return;}
  let events,newEvents=[];
  if(historical){events=payload.events||[];}
  else{newEvents=await fetchEvents(view.snapshot_seq);events=state.events;state.appliedSeq=view.snapshot_seq;}
  if(operation!==state.operation)return;
  document.body.dataset.error="";state.latestView=view;
  render(view,events,newEvents,state.eventsInitialized&&!historical);
  if(!historical)state.eventsInitialized=true;
  schedule();
}
function chooseCandidate(candidate){if(!candidate)return;state.preview=candidate;state.historicalCursor=null;loadView(true).catch(showError);}
function laneStatus(row){
  if(row.generation_status==="SUCCEEDED_EMPTY")return "出力なし / 未評価";
  if(row.evaluation_status==="COMPLETE")return "評価完了";
  if(row.evaluation_status==="QUEUED")return "評価待ち";
  return "候補待ち";
}
function keyedLane(row,view){
  let node=state.laneNodes.get(row.lane_id);
  if(!node){node=$("#lane-template").content.firstElementChild.cloneNode(true);
    node.dataset.lane=row.lane_id;node.addEventListener("click",()=>chooseCandidate(node.dataset.candidate));
    state.laneNodes.set(row.lane_id,node);$("#lanes").append(node);}
  node.dataset.candidate=row.candidate_id||"";node.disabled=!row.candidate_id;
  node.classList.toggle("selected",row.candidate_id===view.selection.winner_id);
  node.querySelector(".lane-letter").textContent=row.lane_id+"帯";
  node.querySelector(".lane-name").textContent=row.architecture_label||"構成未指定";
  const laneQueue=row.queue||{};
  node.querySelector(".lane-queue").textContent=`評価queue ${laneQueue.queued??0}`;
  node.querySelector(".lane-stage").textContent=laneStatus(row);
  const img=node.querySelector(".lane-img");if(row.thumbnail_ref){const url=artifactUrl(row.thumbnail_ref);if(img.getAttribute("src")!==url)img.src=url;img.alt=`${row.lane_id}帯 fixture mask`;}else img.removeAttribute("src");
}
function scoreCell(cell,axis,primary){
  cell.replaceChildren();const wrapper=document.createElement("span");wrapper.className="score"+(primary?" q":"");
  if(axis?.status==="VALID"){
    const bar=document.createElement("span");bar.className="bar";
    const fill=document.createElement("i");fill.style.width=`${Math.max(0,Math.min(100,Number(axis.score_decimal)*25))}%`;
    bar.append(fill);wrapper.append(bar);
    const value=document.createElement("b");value.textContent=axis.score_decimal;wrapper.append(value);
  }else{wrapper.classList.add("missing");wrapper.textContent="— "+(axis?.status==="INVALID"?"無効":axis?.status==="NOT_APPLICABLE"?"対象外":"未評価");}
  cell.append(wrapper);
}
function rowVerdict(row,view){
  if(row.generation_status==="SUCCEEDED_EMPTY")return "候補なし";
  if(row.candidate_id===view.selection.winner_id)return "暫定採用";
  if(row.candidate_id&&row.candidate_id===view.selection.stale_fallback_id)return "旧根拠表示";
  if(row.selection_status==="BELOW_THRESHOLD")return "下限未達";
  if(row.selection_status==="ELIGIBLE_NOT_SELECTED")return "非採用";
  return "評価待ち";
}
function rowReason(row,view){
  if(row.generation_status==="SUCCEEDED_EMPTY")return "mask 0 / 評価対象外";
  if(row.candidate_id&&row.candidate_id===view.selection.stale_fallback_id)return `E${Math.max(0,view.evidence_version-1)}の旧根拠・再評価待ち`;
  if(row.candidate_id===view.selection.winner_id)return `E${view.evidence_version} / Q主軸で採用`;
  if(row.current_reason_code==="LOWER_Q"&&row.current_q_delta!==null)return `主採用よりQ ${row.current_q_delta} / 維持`;
  let reason=shortReason(row.current_reason_code);
  if(row.ever_selected&&row.candidate_id!==view.selection.winner_id)reason+="・以前採用";
  return reason;
}
function keyedRow(row,view){
  let tr=state.rowNodes.get(row.lane_id);
  if(!tr){tr=document.createElement("tr");for(let i=0;i<10;i++)tr.append(document.createElement("td"));
    state.rowNodes.set(row.lane_id,tr);$("#matrix").append(tr);}
  tr.dataset.lane=row.lane_id;tr.classList.toggle("winner",row.candidate_id===view.selection.winner_id);
  tr.children[0].replaceChildren();const pill=document.createElement("span");pill.className="lane-pill";pill.style.setProperty("--lane",`var(--${row.lane_id.toLowerCase()})`);pill.textContent=row.lane_id;tr.children[0].append(pill);
  tr.children[1].textContent=row.architecture_label||"構成未指定";
  if(row.thumbnail_ref){let img=tr.children[2].firstElementChild;if(!img){img=document.createElement("img");img.className="table-thumb";tr.children[2].append(img);}
    const url=artifactUrl(row.thumbnail_ref);if(img.getAttribute("src")!==url)img.src=url;img.alt=`${row.lane_id}候補`;
  }else tr.children[2].replaceChildren();
  for(const [index,axis] of ["Q","A","R","I","C"].entries())scoreCell(tr.children[index+3],row.axis_results[axis],axis==="Q");
  tr.children[8].replaceChildren();const verdict=document.createElement("span");verdict.className="verdict";verdict.textContent=rowVerdict(row,view);tr.children[8].append(verdict);
  tr.children[9].className="reason";tr.children[9].textContent=rowReason(row,view);
}
function keyedThumb(row,view){
  let button=state.thumbNodes.get(row.lane_id);
  if(!button){button=document.createElement("button");button.type="button";button.className="thumb";
    button.innerHTML='<span class="thumb-title"><b></b><span></span></span><img alt=""><span class="thumb-status"></span>';
    button.addEventListener("click",()=>chooseCandidate(button.dataset.candidate));
    state.thumbNodes.set(row.lane_id,button);$("#thumbs").append(button);}
  button.dataset.lane=row.lane_id;button.dataset.candidate=row.candidate_id||"";button.disabled=!row.candidate_id;
  button.classList.toggle("active",row.candidate_id===view.preview.rendered_candidate_id);
  button.querySelector(".thumb-title b").textContent=row.lane_id;
  button.querySelector(".thumb-title span").textContent=row.architecture_label||"構成未指定";
  const img=button.querySelector("img");if(row.thumbnail_ref){const url=artifactUrl(row.thumbnail_ref);if(img.getAttribute("src")!==url)img.src=url;img.alt=`${row.lane_id}帯 maskプレビュー`;}else img.removeAttribute("src");
  button.querySelector(".thumb-status").textContent=`mask ${row.mask_count??"—"} · ${rowVerdict(row,view)}`;
}
function timelineItem(item,cursor){
  const button=document.createElement("button");button.type="button";button.className="time-node"+(item.evidence?" evidence":"");
  if(item.lane)button.dataset.lane=item.lane;
  button.classList.toggle("historical",cursor===item.seq);
  button.innerHTML="<small></small><strong></strong><em></em>";
  button.querySelector("small").textContent=`#${item.seq} / ${item.evidence?"根拠":"評価"}`;
  button.querySelector("strong").textContent=item.title;
  button.querySelector("em").textContent=item.detail;
  button.addEventListener("click",()=>{state.historicalCursor=item.seq;state.preview=null;loadView(true).catch(showError);});
  return button;
}
function renderTimeline(view,events){
  const items=view.timeline_page.decisions.map(d=>{
    const lane=laneOf(d.evaluation_id),previous=laneOf(d.previous_winner_id),after=laneOf(d.winner_after_id);
    let detail=d.reason_code==="HIGHER_Q"?`${previous||"なし"}→${after}に改訂`:
      d.reason_code==="LOWER_Q"||d.reason_code==="TIE_KEEP_CURRENT"?`維持 (${after||"なし"})`:
      d.reason_code==="REFRESHED_SAME_CANDIDATE"?"新根拠で更新":shortReason(d.reason_code);
    return {seq:d.commit_seq,lane,title:`${lane||"?"} Q ${d.candidate_q??"—"}`,detail};
  });
  for(const event of events)if(event.event_type==="EvidencePublished"&&event.frame_id===view.frame_id&&event.commit_seq<=view.snapshot_seq){
    items.push({seq:event.commit_seq,evidence:true,title:`E${event.payload.previous_version} → E${event.payload.previous_version+1}`,detail:"旧根拠を保留"});}
  items.sort((a,b)=>a.seq-b.seq);
  const timeline=$("#timeline");const signature=items.map(item=>item.seq).join(",")+`|${state.historicalCursor}`;
  if(signature!==state.timelineSignature){timeline.replaceChildren(...items.map(item=>timelineItem(item,state.historicalCursor)));state.timelineSignature=signature;}
  if(!items.length&&!timeline.querySelector(".timeline-empty")){const empty=document.createElement("span");empty.className="timeline-empty";empty.textContent="評価結果待ち。記録されたDecisionがここに並びます。";timeline.append(empty);}
  $("#timeline-mode").textContent=state.historicalCursor===null?"現在":`過去 cursor #${state.historicalCursor}`;
  const winner=laneOf(view.selection.winner_id),fallback=laneOf(view.selection.stale_fallback_id);
  $("#timeline-summary").textContent=winner?`${state.historicalCursor===null?"現在":`過去 #${state.historicalCursor}`}: ${winner}帯 / E${view.evidence_version} / Q主軸`:
    fallback?`旧根拠: ${fallback}帯を表示 / E${view.evidence_version}評価待ち`:"現在: 採用待ち";
}
function renderQueue(view){
  const q=view.queues?.[0];if(!q)return;
  const terminal=view.run_status.startsWith("CLOSED"),label=congestionName[q.congestion]||q.congestion;
  const count=`待機 ${q.queued} / 実行 ${q.active} / 完了 ${q.succeeded_total}`;
  $("#queue-compact").textContent=`評価queue: ${label} · ${count}`;
  $("#queue-state").textContent=terminal?`停止済み / ${label}`:`${label} / ${q.queued}件`;
  const detail=$("#queues");detail.className=`queue-detail ${q.congestion.toLowerCase()}`;
  detail.replaceChildren();
  const first=document.createElement("div");first.innerHTML=`<b></b> · stage ${q.stage||"EVALUATION"} · scope ${q.scope_kind} / ${q.frame_id}`;
  first.querySelector("b").textContent=terminal?`終了時未処理 ${q.queued} / ${label}`:`${label} · ${count}`;
  const second=document.createElement("div");second.textContent=`単位 ${q.unit} · 最古待機 ${q.oldest_queued_ms===null?"—":`${q.oldest_queued_ms}ms`} · 容量 ${q.capacity}${terminal?" · 停止済み":""}`;
  detail.append(first,second);
}
function renderLog(view,events){
  const relevant=events.filter(e=>e.frame_id===view.frame_id&&e.commit_seq<=view.snapshot_seq).slice(-30).reverse();
  const signature=relevant.map(e=>e.commit_seq).join(",")+"|"+view.snapshot_seq;
  if(signature===state.logSignature)return;
  const target=$("#log"),oldScroll=target.scrollTop;state.logSignature=signature;
  target.replaceChildren(...relevant.map(e=>{
    const row=document.createElement("div");row.className="log-entry";
    const seq=document.createElement("span");seq.className="seq";seq.textContent=`#${e.commit_seq}`;
    const dot=document.createElement("span");dot.className="log-dot";dot.textContent="●";
    const label=document.createElement("span");label.className="log-text";label.textContent=`${e.lane_id?`${e.lane_id}帯 `:""}${eventName[e.event_type]||e.event_type}`;
    row.append(seq,dot,label);return row;}));
  target.scrollTop=oldScroll;
}
function flowPulse(event,view){
  if(!event.lane_id||!{CandidatePublished:1,JobStarted:1,MeasurementsCommitted:1,EvaluationAttemptFinished:1}[event.event_type])return null;
  const edge={CandidatePublished:"K_TO_LANE",JobStarted:"LANE_PROCESS",MeasurementsCommitted:"LANE_TO_MEASUREMENT",EvaluationAttemptFinished:"MEASUREMENT_TO_EVALUATION"}[event.event_type];
  return {pulse_id:`pulse_${event.event_id}`,event_id:event.event_id,edge_id:edge,run_id:view.run_id,
    frame_id:event.frame_id,candidate_id:view.rows.find(r=>r.lane_id===event.lane_id)?.candidate_id||null,
    lane_id:event.lane_id,phase:event.event_type,duration_ms:500,origin:"FIXTURE"};
}
function playPulses(events,view){
  const projected=new Map((view.flow_pulses||[]).map(p=>[p.event_id,p]));
  const pulses=events.map(event=>projected.get(event.event_id)||flowPulse(event,view)).filter(Boolean),shown=pulses.slice(-12);
  for(const pulse of shown){const node=state.laneNodes.get(pulse.lane_id);if(!node)continue;
    const dot=document.createElement("span");dot.className="flow-dot";dot.dataset.eventId=pulse.event_id;
    node.querySelector(".pulse-track").append(dot);dot.addEventListener("animationend",()=>dot.remove(),{once:true});
    setTimeout(()=>dot.remove(),pulse.duration_ms+120);}
  if(pulses.length)$("#flow-note").textContent=`記録遷移 ${shown.length}件を再生${pulses.length>shown.length?` / ${pulses.length-shown.length}件省略`:""} · 各500ms`;
}
function imageReady(element,url,token){
  if(!url){element.removeAttribute("src");element.dataset.ref="";element.dataset.failed="true";if(element.id==="main-image")$("#retry-image").hidden=true;return Promise.resolve(false);}
  if(element.dataset.ref!==url){element.dataset.ref=url;element.dataset.failed="false";element.src=url;}
  const settle=()=>{const ready=token===state.renderToken&&element.naturalWidth>0;
    if(token===state.renderToken){element.dataset.failed=ready?"false":"true";
      if(element.id==="main-image"){$("#retry-image").hidden=ready;$("#main-placeholder").textContent=ready?"":"画像を表示できません";}}
    return ready;};
  if(element.complete)return Promise.resolve(settle());
  return new Promise(resolve=>{
    const done=()=>{element.removeEventListener("load",done);element.removeEventListener("error",done);resolve(settle());};
    element.addEventListener("load",done,{once:true});element.addEventListener("error",done,{once:true});
    setTimeout(done,2500);
  });
}
async function postReceipt(view,mode,rendered,token,imagesReady){
  const revision=view.selection.display_revision_id,seq=view.selection.display_revision_seq;
  if(!revision||seq===null||!rendered||!imagesReady||token!==state.renderToken)return;
  const key=`${revision}|${mode}|${rendered}`;if(state.receiptKeys.has(key)||state.receiptInFlight.has(key))return;
  state.receiptInFlight.add(key);
  const body={receipt_id:"receipt_"+crypto.randomUUID().replaceAll("-",""),view_session_id:state.viewSession,
    source_revision_id:revision,source_commit_seq:seq,run_id:view.run_id,frame_id:view.frame_id,
    generation:view.generation,display_mode:mode,rendered_candidate_id:rendered,
    visible:document.visibilityState==="visible",skipped_revision_ids:[]};
  try{for(let attempt=0;attempt<2;attempt++){
    if(token!==state.renderToken)return;
    try{const response=await fetch("/api/sc01/receipts",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
      if(response.ok){state.receiptKeys.add(key);document.body.dataset.receipt="accepted";return;}}
    catch(error){if(attempt===1)document.body.dataset.receipt="failed";}
  }}finally{state.receiptInFlight.delete(key);}
}
function render(view,events,newEvents,animate){
  const token=++state.renderToken,historical=state.historicalCursor!==null;
  $("#run-badge").textContent=`${view.run_status} · E${view.evidence_version}`;
  $("#frame-evidence").textContent=`E${view.evidence_version}`;
  $("#info-evidence").textContent=`E${view.evidence_version}${view.selection.stale_fallback_id?" / 旧根拠表示中":""}`;
  $("#frame-id").textContent=view.frame_id;
  $("#info-run").textContent=`${view.run_id} / ${view.run_status}`;
  $("#meta").textContent=`${view.frame_id} · E${view.evidence_version} · seq ${view.snapshot_seq}${historical?" · 過去表示":""}`;
  view.rows.forEach(row=>{keyedLane(row,view);keyedRow(row,view);keyedThumb(row,view);});
  const rendered=view.preview.rendered_candidate_id,renderedRow=view.rows.find(row=>row.candidate_id===rendered);
  const mode=historical?"HISTORICAL_REPLAY":view.preview.display_mode;
  $("#preview-state").textContent=mode==="MANUAL_CANDIDATE"?`手動 ${laneOf(rendered)||"?"}帯`:
    historical?`過去 #${state.historicalCursor}`:view.selection.stale_fallback_id?"旧根拠 / 採用追従":"採用追従";
  $("#winner-card").textContent=view.selection.winner_id?`${laneOf(view.selection.winner_id)}帯 · ${historical?"過去時点の採用":"現在の暫定採用"}`:
    view.selection.stale_fallback_id?`${laneOf(view.selection.stale_fallback_id)}帯 · E${view.evidence_version-1}の旧根拠を表示`:"採用待ち";
  $("#selection-note").textContent=mode==="MANUAL_CANDIDATE"?`手動閲覧 ${laneOf(rendered)}帯。採用判定は変更しません。`:
    historical?`過去cursor #${state.historicalCursor}の採用状態を表示中。`:
    `根拠 E${view.evidence_version} · ${view.coverage_state}${view.run_status.startsWith("CLOSED")?" · 停止済み":""}`;
  $("#main-placeholder").textContent=rendered?"画像読込み中":"未選択";
  const keyUrl=artifactUrl(view.preview.keyframe_artifact_ref);
  const keyReady=imageReady($("#keyframe-image"),keyUrl,token);
  imageReady($("#pipe-keyframe"),keyUrl,token);
  const displayUrl=renderedRow?.thumbnail_ref?
    `${artifactUrl(renderedRow.thumbnail_ref)}?display=${state.viewSession}_${mode}_${view.selection.display_revision_id||"none"}`:"";
  const mainReady=imageReady($("#main-image"),displayUrl,token);
  Promise.all([keyReady,mainReady]).then(result=>postReceipt(view,mode,rendered,token,result.every(Boolean)));
  renderTimeline(view,events);renderQueue(view);renderLog(view,events);
  if(animate)playPulses(newEvents,view);
}
async function control(path,action){
  state.operation+=1;
  const response=await fetch(path,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({action})});
  if(!response.ok)throw new Error(`control_${response.status}`);
  state.historicalCursor=null;await loadView(false);
}
$("#release").addEventListener("click",()=>control("/api/sc01/fixture/release","release_next").catch(showError));
$("#evidence").addEventListener("click",()=>control("/api/sc01/fixture/evidence","publish_e1").catch(showError));
$("#release-e1").addEventListener("click",()=>control("/api/sc01/fixture/evidence","release_next_e1").catch(showError));
$("#follow").addEventListener("click",()=>{state.preview=null;state.historicalCursor=null;loadView(true).catch(showError);});
$("#retry-image").addEventListener("click",()=>{$("#main-image").dataset.ref="";loadView(true).catch(showError);});
$("#current").addEventListener("click",()=>{state.historicalCursor=null;loadView(true).catch(showError);});
loadView(true).catch(showError);
