"use strict";
const $=selector=>document.querySelector(selector);
const art=id=>`/api/sc02/artifacts/${encodeURIComponent(id)}`;
const lanes=["S","A","B","C"];
const state={session:"sc02_"+crypto.randomUUID().replaceAll("-",""),selectedFrame:null,
  cursor:null,latest:null,lastSeq:0,renderToken:0,receiptKeys:new Set(),lastPulseSeq:0,
  imageRetry:0,stopped:false,thumbSignature:null,resetView:false};
const eventNames={RunCreated:"実run開始",KeyframeRequested:"K取得要求",DecodeStarted:"動画decode開始",
  KeyframePublished:"元K公開",ModelLoadStarted:"モデル読込み開始",ModelLoaded:"モデル読込み完了",
  JobStarted:"実job開始",WarmupStarted:"GPU warm-up",InferenceStarted:"GPU推論開始",
  InferenceFinished:"GPU推論完了",NormalizationStarted:"元座標mask正規化",
  CandidatePublished:"実mask公開",JobFinished:"実job終了",JobFailed:"実job失敗",
  JobCancelled:"実job取消し",AnalysisStopRequested:"解析停止要求",RunStopped:"実run終了"};
function reason(error){return error instanceof Error?error.message:String(error);}
function errorView(error){document.body.dataset.error=reason(error);$("#preview-state").textContent=`エラー: ${reason(error)}`;}
function setImage(img,id,retry=false){
  if(!id){img.removeAttribute("src");return;}
  const url=art(id);
  if(img.getAttribute("src")!==url)img.src=url;
}
function nodeForLane(lane){
  let node=$(`#lanes .pipe-lane[data-lane="${lane}"]`);
  if(!node){node=$("#lane-template").content.firstElementChild.cloneNode(true);
    node.dataset.lane=lane;$("#lanes").append(node);}
  return node;
}
function renderLane(lane,candidate,view,frame){
  const node=nodeForLane(lane),real=lane==="S";
  node.disabled=!candidate;
  node.classList.toggle("selected",Boolean(candidate));
  node.querySelector(".lane-letter").textContent=lane+"帯";
  node.querySelector(".lane-name").textContent=real?"YOLO11n-seg":"未実装 / 未実行";
  node.querySelector(".lane-origin").textContent=real?"REAL_MODEL":"SC03以降";
  node.querySelector(".lane-queue").textContent=real?`分割job ${view.job_count}/${view.max_jobs}`:"待機0";
  node.querySelector(".lane-stage").textContent=real?(candidate?`実mask ${candidate.mask_count} / ${candidate.device}`:
    frame?(view.active_phase||"解析待ち"):"K待ち"):"未実行";
  const img=node.querySelector(".lane-img");setImage(img,candidate?.preview_artifact_id);
  img.alt=real&&candidate?"S帯の実mask重畳":"未実行";
  node.onclick=()=>{if(candidate){state.selectedFrame=candidate.frame_id;state.cursor=null;refresh().catch(errorView);}};
}
function renderMatrix(candidate){
  const body=$("#matrix");body.replaceChildren();
  for(const lane of lanes){
    const tr=document.createElement("tr");tr.dataset.lane=lane;
    for(let i=0;i<10;i++)tr.append(document.createElement("td"));
    const pill=document.createElement("span");pill.className="lane-pill";
    pill.style.setProperty("--lane",`var(--${lane.toLowerCase()})`);pill.textContent=lane;
    tr.children[0].append(pill);
    tr.children[1].textContent=lane==="S"?"YOLO11n-seg":"未実行";
    if(lane==="S"&&candidate){const img=document.createElement("img");img.className="table-thumb";
      img.src=art(candidate.preview_artifact_id);img.alt="実mask";tr.children[2].append(img);}
    for(let index=3;index<=7;index++){const span=document.createElement("span");span.className="score missing";
      span.textContent="— 未評価";tr.children[index].append(span);}
    const verdict=document.createElement("span");verdict.className="verdict";
    verdict.textContent=lane==="S"?(candidate?"未評価プレビュー":"実mask待ち"):"未実行";
    tr.children[8].append(verdict);
    tr.children[9].className="reason";
    tr.children[9].textContent=lane==="S"?(candidate?`mask ${candidate.mask_count} / Jev採用なし`:"実分割後に表示"):"SC02対象外";
    body.append(tr);
  }
}
function renderThumbs(candidate){
  const signature=candidate?.candidate_id||"none";
  if(state.thumbSignature===signature)return;
  state.thumbSignature=signature;
  const target=$("#thumbs");target.replaceChildren();
  for(const lane of lanes){const button=document.createElement("button");button.type="button";
    button.className="thumb";button.dataset.lane=lane;button.disabled=lane!=="S"||!candidate;
    const title=document.createElement("span");title.className="thumb-title";
    title.innerHTML="<b></b><span></span>";title.querySelector("b").textContent=lane;
    title.querySelector("span").textContent=lane==="S"?"YOLO11n-seg":"未実行";
    const img=document.createElement("img");img.alt=lane==="S"?"元Kと実mask":"未実行";
    if(lane==="S"&&candidate)img.src=art(candidate.preview_artifact_id);
    const status=document.createElement("span");status.className="thumb-status";
    status.textContent=lane==="S"?(candidate?`mask ${candidate.mask_count} · 未評価プレビュー`:"実mask待ち"):"未実行";
    button.append(title,img,status);button.onclick=()=>{state.cursor=null;refresh().catch(errorView);};target.append(button);}
}
function renderTimeline(view,frame){
  const events=view.events.filter(e=>!frame||e.frame_id===frame.frame_id||e.frame_id===null);
  const strip=$("#timeline");strip.replaceChildren();
  const displayed=events.filter(e=>["KeyframePublished","InferenceStarted","CandidatePublished","JobFailed","RunStopped"].includes(e.kind));
  for(const event of displayed.slice(-8)){const button=document.createElement("button");button.type="button";
    button.className="time-node "+(event.kind==="CandidatePublished"?"mask":"event");
    button.classList.toggle("historical",state.cursor===event.seq);
    button.innerHTML="<small></small><strong></strong><em></em>";
    button.querySelector("small").textContent=`#${event.seq} / 実event`;
    button.querySelector("strong").textContent=eventNames[event.kind]||event.kind;
    button.querySelector("em").textContent=event.frame_id?.slice(0,12)||"run";
    button.onclick=()=>{state.cursor=event.seq;$("#timeline-mode").textContent=`保存cursor #${event.seq}`;
      refresh().catch(errorView);};strip.append(button);}
  if(!displayed.length){const empty=document.createElement("span");empty.className="timeline-empty";
    empty.textContent="実event待ち。Jev採用履歴はありません。";strip.append(empty);}
  $("#timeline-summary").textContent=state.cursor===null?"Jev採用履歴なし / 実eventのみ":
    `保存cursor #${state.cursor} / 再推論・再評価なし`;
  $("#timeline-mode").textContent=state.cursor===null?"現在":`過去 #${state.cursor}`;
}
function renderLog(view,frame){
  const target=$("#log");target.replaceChildren();
  const events=view.events.filter(e=>!frame||e.frame_id===frame.frame_id||e.frame_id===null).slice(-24).reverse();
  for(const e of events){const row=document.createElement("div");row.className="log-entry";
    const seq=document.createElement("span");seq.className="seq";seq.textContent=`#${e.seq}`;
    const dot=document.createElement("span");dot.className="log-dot";dot.textContent="●";
    const label=document.createElement("span");label.className="log-text";
    label.textContent=eventNames[e.kind]||e.kind;row.append(seq,dot,label);target.append(row);}
}
function pulse(view){
  if(state.cursor!==null||!state.lastPulseSeq){state.lastPulseSeq=view.snapshot_seq;return;}
  const newEvents=view.events.filter(e=>e.seq>state.lastPulseSeq&&
    ["KeyframePublished","InferenceStarted","CandidatePublished"].includes(e.kind));
  state.lastPulseSeq=view.snapshot_seq;
  const track=$("#lanes .pipe-lane[data-lane=S] .pulse-track");
  for(const event of newEvents){const dot=document.createElement("span");dot.className="flow-dot";
    dot.dataset.eventId=String(event.seq);track.append(dot);setTimeout(()=>dot.remove(),650);}
  if(newEvents.length)$("#flow-note").textContent=`実記録遷移 ${newEvents.length}件 / 各500ms`;
}
async function loaded(img,token){
  if(!img.getAttribute("src"))return false;
  if(img.complete)return token===state.renderToken&&img.naturalWidth>0;
  return new Promise(resolve=>{const done=()=>{img.removeEventListener("load",done);img.removeEventListener("error",done);
    resolve(token===state.renderToken&&img.naturalWidth>0);};
    img.addEventListener("load",done,{once:true});img.addEventListener("error",done,{once:true});setTimeout(done,3000);});
}
async function receipt(frame,candidate,token){
  if(!frame||!candidate||state.cursor!==null)return;
  const key=`${candidate.candidate_id}|${candidate.seq}`;
  if(state.receiptKeys.has(key))return;
  const ready=await Promise.all([loaded($("#pipe-keyframe"),token),loaded($("#main-image"),token)]);
  if(!ready.every(Boolean)||token!==state.renderToken)return;
  const payload={id:"r_"+crypto.randomUUID().replaceAll("-",""),session_id:state.session,
    frame_id:frame.frame_id,candidate_id:candidate.candidate_id,mode:"UNSCORED_PREVIEW",
    source_seq:candidate.seq};
  const response=await fetch("/api/sc02/receipts",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify(payload)});
  if(response.ok){state.receiptKeys.add(key);document.body.dataset.receipt="accepted";}
  else document.body.dataset.receipt="failed";
}
function render(view){
  state.latest=view;const token=++state.renderToken;
  const frame=state.resetView?null:(state.selectedFrame?(view.frames.find(f=>f.frame_id===state.selectedFrame)||view.frames.at(-1)):view.frames.at(-1));
  if(!state.selectedFrame&&frame)state.selectedFrame=frame.frame_id;
  const candidate=frame?view.candidates.find(c=>c.frame_id===frame.frame_id):null;
  $("#run-badge").textContent=`${view.run_id} · ${view.lifecycle}`;
  $("#source-name").textContent=view.source?.filename||"保存run";
  const choice=$("#video-choice");if(!choice.options.length){const opt=document.createElement("option");
    opt.textContent=view.source?.filename||"保存run";choice.append(opt);}
  $("#frame-evidence").textContent=frame?`K / ${frame.actual_seconds.toFixed(3)}s`:"K未選択";
  $("#pts").textContent=frame?`要求 ${frame.requested_seconds.toFixed(3)} / 実 ${frame.pts} × ${frame.time_base[0]}/${frame.time_base[1]}`:"—";
  $("#frame-id").textContent=frame?.frame_id||state.selectedFrame||"—";
  $("#frame-id").title=frame?`sample ${frame.sample_id} / pixel SHA-256 ${frame.pixel_sha256}`:"";
  $("#info-run").textContent=`${view.run_id} / ${view.business}`;
  $("#neighbor-current").textContent=frame?`K / ${frame.actual_seconds.toFixed(3)}s`:"K 未選択";
  const frameIndex=frame?view.frames.findIndex(f=>f.frame_id===frame.frame_id):-1;
  for(const [id,offset,label] of [["#prev-k",-1,"前"],["#next-k",1,"次"]]){
    const control=$(id),neighbor=frameIndex<0?null:view.frames[frameIndex+offset];
    control.disabled=!neighbor;control.textContent=neighbor?`${label} K / ${neighbor.actual_seconds.toFixed(3)}s`:`${label} K —`;
    control.onclick=neighbor?()=>{state.selectedFrame=neighbor.frame_id;state.cursor=null;
      state.resetView=false;refresh().catch(errorView);}:null;
  }
  $("#pipe-k-label").textContent=frame?`元K / 実PTS ${frame.pts}`:"元K 未選択";
  $("#k-state").textContent=frame?"✓ 元K公開済み":"選択待ち";
  $("#meta").textContent=`${frame?.frame_id||"K未選択"} · seq ${view.snapshot_seq} · ${candidate?candidate.device:"GPU待ち"}`;
  setImage($("#pipe-keyframe"),frame?.image_artifact_id);
  const saved=view.lifecycle!=="RUNNING"||!view.accepting;
  if(saved){$("#player").hidden=true;$("#keyframe-image").hidden=false;
    setImage($("#keyframe-image"),frame?.image_artifact_id);$("#image-stamp").textContent="保存K / 再推論なし";}
  else{$("#player").hidden=false;$("#keyframe-image").hidden=true;}
  for(const control of ["#play","#pause","#scrub"])$(control).disabled=saved;
  $("#analyze").disabled=saved||view.worker_alive||view.selected_count>=view.max_keyframes;
  $("#stop-analysis").disabled=saved||!view.worker_alive;
  $("#reset").disabled=saved;
  $("#preview-state").textContent=state.cursor!==null?`保存cursor #${state.cursor}`:
    view.failure?`失敗: ${view.failure}`:view.worker_alive?`解析中: ${view.active_phase||"待機"}`:
    candidate?`実mask ${candidate.mask_count} / 未評価プレビュー`:"選択Kのみ推論";
  for(const lane of lanes)renderLane(lane,lane==="S"?candidate:null,view,frame);
  renderMatrix(candidate);renderThumbs(candidate);renderTimeline(view,frame);renderLog(view,frame);
  const finished=view.events.filter(e=>e.kind==="JobFinished").length;
  const failed=view.events.filter(e=>e.kind==="JobFailed").length;
  $("#queue-compact").textContent=`分割job: 待機 0 / 実行 ${view.worker_alive?1:0} / 完了 ${finished}`;
  $("#queue-state").textContent=failed?`保留/失敗 ${failed}`:view.worker_alive?"実行中 1":"待機 0";
  $("#queues").textContent=`単位 SEGMENTATION_JOB · S帯 · 待機 0 · 実行 ${view.worker_alive?1:0} · 完了 ${finished} · 失敗 ${failed} · 最古待機 — · 上限 ${view.job_count}/${view.max_jobs}`;
  $("#winner-card").textContent=candidate?`S帯 実mask ${candidate.mask_count} · Jev採用なし`:"Jev採用なし";
  $("#selection-note").textContent=candidate?`元K ${frame.actual_seconds.toFixed(3)}s / ${candidate.segmentation_status} / Q/A/R/I/C未評価`:
    "実mask待ち / Q/A/R/I/C未評価";
  const img=$("#main-image");setImage(img,candidate?.preview_artifact_id,state.imageRetry>0);
  $("#main-placeholder").textContent=candidate?"画像読込み中":"実mask待ち";
  $("#retry-image").hidden=true;
  if(candidate){loaded(img,token).then(ok=>{if(token!==state.renderToken)return;
    img.dataset.failed=ok?"false":"true";$("#retry-image").hidden=ok;
    $("#main-placeholder").textContent=ok?"":"画像を表示できません";});
    if(!saved)receipt(frame,candidate,token).catch(errorView);}
  else img.removeAttribute("src");
  pulse(view);
}
async function refresh(){
  const path="/api/sc02/snapshot"+(state.cursor===null?"":`?cursor=${state.cursor}`);
  const response=await fetch(path,{cache:"no-store"});if(!response.ok)throw new Error(`snapshot_${response.status}`);
  const view=await response.json();if(state.cursor===null&&view.snapshot_seq<state.lastSeq)return;
  if(state.cursor===null)state.lastSeq=view.snapshot_seq;
  document.body.dataset.error="";render(view);
}
async function post(path,payload){const response=await fetch(path,{method:"POST",headers:{"Content-Type":"application/json"},
  body:JSON.stringify(payload)});if(!response.ok){const body=await response.json().catch(()=>({}));
    throw new Error(body.error||`request_${response.status}`);}return response.json();}
$("#play").onclick=()=>$("#player").play().catch(errorView);
$("#pause").onclick=()=>$("#player").pause();
$("#player").addEventListener("timeupdate",()=>{const player=$("#player");
  $("#time-label").textContent=`${player.currentTime.toFixed(2)} s`;
  if(Number.isFinite(player.duration)&&player.duration>0)$("#scrub").value=String(Math.round(player.currentTime/player.duration*1000));});
$("#scrub").oninput=()=>{const player=$("#player");if(Number.isFinite(player.duration))
  player.currentTime=Number($("#scrub").value)/1000*player.duration;};
$("#analyze").onclick=async()=>{try{const result=await post("/api/sc02/select",{seconds:$("#player").currentTime});
  state.selectedFrame=result.frame_id;state.resetView=false;state.cursor=null;await refresh();}catch(error){errorView(error);}};
$("#stop-analysis").onclick=async()=>{try{await post("/api/sc02/analysis-stop",{action:"stop"});
  await refresh();}catch(error){errorView(error);}};
$("#current").onclick=()=>{state.cursor=null;state.resetView=false;refresh().catch(errorView);};
$("#reset").onclick=async()=>{try{await post("/api/sc02/reset",{action:"reset"});
  state.cursor=null;state.selectedFrame=null;state.resetView=true;await refresh();}catch(error){errorView(error);}};
$("#retry-image").onclick=()=>{state.imageRetry++;$("#main-image").removeAttribute("src");refresh().catch(errorView);};
$("#shutdown").onclick=async()=>{try{await post("/api/sc02/shutdown",{action:"shutdown"});
  state.stopped=true;$("#preview-state").textContent="正常終了を要求しました";}catch(error){errorView(error);}};
refresh().catch(errorView);
setInterval(()=>{if(!state.stopped&&state.cursor===null)refresh().catch(errorView);},650);
