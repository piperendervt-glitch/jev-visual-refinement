"use strict";
const $=selector=>document.querySelector(selector);
const lanes=["S","A","B","C"];
const savedRun=new URLSearchParams(location.search).get("run");
if(savedRun&&!/^[A-Za-z0-9_-]{1,96}$/.test(savedRun))throw new Error("saved_run_id_invalid");
const art=id=>(savedRun?"/api/live/runs/"+encodeURIComponent(savedRun):"/api/live")+
  "/artifacts/"+encodeURIComponent(id);
const state={session:"live_"+crypto.randomUUID().replaceAll("-",""),selectedFrame:null,
  manualCandidate:null,cursor:null,lastSeq:0,renderToken:0,receiptKeys:new Set(),
  pulseSeq:0,hiddenView:false,imageRetry:0};
const names={S:"YOLO11n-seg",A:"YOLO11s-seg",B:"YOLO11m-seg",C:"Mask R-CNN ResNet50-FPN"};
const eventNames={RunCreated:"run開始",KeyframeRequested:"K取得要求",DecodeStarted:"動画decode",
  KeyframePublished:"元K公開",ModelLoadStarted:"モデル読込み",ModelLoaded:"モデル読込み完了",
  InferenceStarted:"推論開始",InferenceFinished:"推論完了",CandidatePublished:"mask公開",
  MeasurementsCommitted:"測定完了",EvidencePublished:"根拠更新",EvaluationQueued:"評価受付",
  EvaluationAttemptReserved:"評価送信予約",EvaluationAttemptFinished:"評価応答",
  EvaluationTransportFailed:"Jev通信失敗",DecisionCommitted:"採用判断",
  JobQueued:"queue受付",JobStarted:"job開始",JobFinished:"job終了",RunStopped:"run終了"};
function message(error){return error instanceof Error?error.message:String(error);}
function showError(error){$("#preview-state").textContent="エラー: "+message(error);document.body.dataset.error=message(error);}
function setImage(img,id){if(!id){img.removeAttribute("src");return;}
  const url=art(id)+(state.imageRetry?"?retry="+state.imageRetry:"");
  if(img.getAttribute("src")!==url)img.src=url;}
async function loaded(img,token){if(!img.getAttribute("src"))return false;
  if(img.complete)return token===state.renderToken&&img.naturalWidth>0;
  return new Promise(resolve=>{const done=()=>{img.removeEventListener("load",done);img.removeEventListener("error",done);
    resolve(token===state.renderToken&&img.naturalWidth>0);};
    img.addEventListener("load",done,{once:true});img.addEventListener("error",done,{once:true});
    setTimeout(done,3000);});}
async function post(path,payload){const response=await fetch(path,{method:"POST",
  headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
  if(!response.ok){const body=await response.json().catch(()=>({}));
    throw new Error(body.error||"request_"+response.status);}return response.json();}
function candidatesFor(view,frame){return frame?view.candidates.filter(x=>x.frame_id===frame.frame_id):[];}
function activeEvaluation(view,candidate,version){return candidate?view.evaluations.find(
  x=>x.candidate_id===candidate.candidate_id&&x.evidence_version===version):null;}
function lastDecision(view,candidate,version){return [...view.decisions].reverse().find(
  x=>x.candidate_id===candidate?.candidate_id&&x.evidence_version===version);}
function laneJob(view,frame,lane){return [...view.jobs].reverse().find(
  x=>x.frame_id===frame?.frame_id&&x.lane_id===lane&&x.stage==="SEGMENTATION");}
function nodeForLane(lane){let node=$('#lanes .pipe-lane[data-lane="'+lane+'"]');
  if(!node){node=$("#lane-template").content.firstElementChild.cloneNode(true);
    node.dataset.lane=lane;$("#lanes").append(node);}return node;}
function renderLane(lane,candidate,view,frame,winner){const node=nodeForLane(lane),job=laneJob(view,frame,lane);
  node.disabled=!candidate;node.classList.toggle("selected",candidate?.candidate_id===state.manualCandidate);
  node.classList.toggle("winner",candidate?.candidate_id===winner);
  node.querySelector(".lane-letter").textContent=lane+"帯";
  node.querySelector(".lane-name").textContent=candidate?.architecture_label||names[lane];
  node.querySelector(".lane-origin").textContent=candidate?.origin||"実行待ち";
  node.querySelector(".lane-queue").textContent=job?job.status:"待機 0";
  node.querySelector(".lane-stage").textContent=candidate?((candidate.origin==="REAL_MODEL"?"実mask ":"fixture mask ")+candidate.mask_count+" / "+candidate.device):
    job?(job.phase||job.status):"K待ち";
  setImage(node.querySelector(".lane-img"),candidate?.preview_artifact_id);
  node.querySelector(".lane-img").alt=candidate?(lane+"帯の元K"+(candidate.origin==="REAL_MODEL"?"実mask":"fixture mask")+"重畳"):"結果待ち";
  node.onclick=()=>{if(candidate){state.manualCandidate=candidate.candidate_id;state.cursor=null;
    refresh(true).catch(showError);}};}
function scoreCell(axis){const span=document.createElement("span");span.className="score missing";
  if(axis?.status==="VALID"){span.className="score valid";const score=Number(axis.score_decimal);
    span.style.setProperty("--score-width",(Math.max(0,Math.min(4,score))*25).toFixed(1)+"%");
    span.textContent=axis.score_decimal+" / 4";}
  else span.textContent=axis?.status==="INVALID"?"— 無効":
    axis?.status==="MISSING"?"— 欠測":"— 未評価";return span;}
function renderMatrix(view,frame,byLane,winner,version){const body=$("#matrix");body.replaceChildren();
  for(const lane of lanes){const c=byLane[lane],evaluation=activeEvaluation(view,c,version),
    decision=lastDecision(view,c,version),row=document.createElement("tr");
    row.dataset.lane=lane;for(let i=0;i<10;i++)row.append(document.createElement("td"));
    const pill=document.createElement("span");pill.className="lane-pill";
    pill.style.setProperty("--lane","var(--"+lane.toLowerCase()+")");pill.textContent=lane;
    row.children[0].append(pill);row.children[1].textContent=c?.architecture_label||names[lane];
    if(c){const img=document.createElement("img");img.className="table-thumb";img.src=art(c.preview_artifact_id);
      img.alt=c.origin==="REAL_MODEL"?"実mask":"fixture mask";row.children[2].append(img);}
    for(let i=0;i<5;i++)row.children[i+3].append(scoreCell(evaluation?.axes?.[["Q","A","R","I","C"][i]]));
    const verdict=document.createElement("span");verdict.className="verdict";
    verdict.textContent=!c?"未実行":c.candidate_id===winner?"現在採用":
      evaluation?.axes?.Q?.status==="VALID"?"非採用":evaluation?"評価未成立":"未評価";
    row.children[8].append(verdict);row.children[9].className="reason";
    row.children[9].textContent=decision?.reason_code||(!c?"実分割待ち":
      evaluation?.transport_status&&evaluation.transport_status!=="QUEUED"?
        evaluation.transport_status:evaluation?"Q未確定":"評価応答待ち");body.append(row);}}
function renderThumbs(byLane,winner){const target=$("#thumbs");
  const focused=document.activeElement?.closest(".thumb")?.dataset.lane;
  target.replaceChildren();
  for(const lane of lanes){const c=byLane[lane],button=document.createElement("button");
    button.type="button";button.className="thumb";button.dataset.lane=lane;button.disabled=!c;
    const title=document.createElement("span");title.className="thumb-title";
    const b=document.createElement("b");b.textContent=lane;const text=document.createElement("span");
    text.textContent=c?.architecture_label||names[lane];title.append(b,text);
    const img=document.createElement("img");img.alt=c?(c.origin==="REAL_MODEL"?"実mask重畳":"fixture mask重畳"):"結果待ち";
    if(c)img.src=art(c.preview_artifact_id);
    const status=document.createElement("span");status.className="thumb-status";
    status.textContent=c?(c.candidate_id===winner?"採用 · ":"非採用/未評価 · ")+
      "mask "+c.mask_count:"実分割待ち";
    button.append(title,img,status);button.onclick=()=>{if(c){state.manualCandidate=c.candidate_id;
      state.cursor=null;refresh(true).catch(showError);}};target.append(button);}
  if(focused){const next=target.querySelector('.thumb[data-lane="'+focused+'"]');
    if(next&&!next.disabled)next.focus({preventScroll:true});}}
function renderTimeline(view,frame){const target=$("#timeline"),scrollLeft=target.scrollLeft;
  target.replaceChildren();
  const relevant=view.events.filter(e=>!frame||e.frame_id===frame.frame_id||e.frame_id===null);
  const shown=relevant.filter(e=>["KeyframePublished","CandidatePublished","EvidencePublished",
    "DecisionCommitted","RunStopped"].includes(e.kind));
  for(const event of shown.slice(-9)){const button=document.createElement("button");
    button.type="button";button.className="time-node "+(event.kind==="CandidatePublished"?"mask":"event");
    button.classList.toggle("historical",state.cursor===event.seq);
    const small=document.createElement("small");small.textContent="#"+event.seq+" / "+
      (event.kind==="DecisionCommitted"?"採用判断":"記録event");
    const strong=document.createElement("strong");strong.textContent=eventNames[event.kind]||event.kind;
    const em=document.createElement("em");em.textContent=event.lane_id||event.frame_id?.slice(0,12)||"run";
    button.append(small,strong,em);button.onclick=()=>{state.cursor=event.seq;refresh().catch(showError);};
    target.append(button);}
  if(!shown.length){const empty=document.createElement("span");empty.className="timeline-empty";
    empty.textContent="記録event待ち";target.append(empty);}
  $("#timeline-mode").textContent=state.cursor===null?"現在":"保存cursor #"+state.cursor;
  $("#timeline-summary").textContent=state.cursor===null?"実Q判断と根拠更新を時系列表示":
    "過去cursor #"+state.cursor+" / 再送・再推論なし";
  target.scrollLeft=scrollLeft;}
function renderLog(view,frame){const target=$("#log"),scrollTop=target.scrollTop;
  target.replaceChildren();
  for(const e of view.events.filter(x=>!frame||x.frame_id===frame.frame_id||x.frame_id===null)
      .slice(-24).reverse()){const row=document.createElement("div");row.className="log-entry";
    const seq=document.createElement("span");seq.className="seq";seq.textContent="#"+e.seq;
    const dot=document.createElement("span");dot.className="log-dot";dot.textContent="●";
    const label=document.createElement("span");label.className="log-text";
    label.textContent=eventNames[e.kind]||e.kind;row.append(seq,dot,label);target.append(row);}
  target.scrollTop=scrollTop;}
function pulse(view){if(state.cursor!==null||!state.pulseSeq){state.pulseSeq=view.snapshot_seq;return;}
  const fresh=view.events.filter(e=>e.seq>state.pulseSeq&&
    ["KeyframePublished","InferenceStarted","CandidatePublished","EvaluationAttemptFinished",
     "DecisionCommitted"].includes(e.kind));
  state.pulseSeq=view.snapshot_seq;
  for(const event of fresh){const lane=event.lane_id||"S",track=$('#lanes .pipe-lane[data-lane="'+lane+'"] .pulse-track');
    if(!track)continue;const dot=document.createElement("span");dot.className="flow-dot";
    dot.dataset.eventId=String(event.seq);track.append(dot);setTimeout(()=>dot.remove(),650);}
  if(fresh.length)$("#flow-note").textContent="実記録遷移 "+fresh.length+"件 / 各650ms";}
function queueView(view){const waiting=view.jobs.filter(x=>x.status==="QUEUED");
  const running=view.jobs.filter(x=>x.status==="RUNNING");
  const done=view.jobs.filter(x=>x.status==="SUCCEEDED");
  const failed=view.jobs.filter(x=>["FAILED","EXPIRED","CANCELLED"].includes(x.status));
  const oldest=waiting.length?Math.max(0,Math.round((Date.now()-
    Math.min(...waiting.map(x=>x.queued_ms||Date.now())))/1000))+"秒":"—";
  $("#queue-compact").textContent="待機 "+waiting.length+" / 実行 "+running.length+
    " / 完了 "+done.length;
  const color=waiting.length>=3?"saturated":waiting.length?"congested":"normal";
  $("#queues").classList.remove("saturated","congested","normal");
  $("#queues").classList.add(color);
  const last=view.events.at(-1)?.at_ms||Date.now();
  $("#queues").dataset.freshnessMs=String(Math.max(0,Date.now()-last));
  $("#queue-state").textContent=failed.length?"保留/失敗 "+failed.length:
    waiting.length?"待機 "+waiting.length:running.length?"実行中 "+running.length:"待機 0";
  $("#queues").textContent="単位 SEGMENTATION_JOB / EVALUATION_SUITE · 待機 "+waiting.length+
    " · 実行 "+running.length+" · 完了 "+done.length+" · 保留/失敗 "+failed.length+
    " · 最古待機 "+oldest;}
async function receipt(view,frame,candidate,sourceSeq,mode,token){if(!candidate||!frame||
  state.cursor!==null||(!savedRun&&view.lifecycle!=="RUNNING")||
  document.visibilityState!=="visible")return;
  const key=candidate.candidate_id+"|"+sourceSeq+"|"+mode;
  if(state.receiptKeys.has(key))return;
  const ready=await Promise.all([loaded($("#pipe-keyframe"),token),loaded($("#main-image"),token)]);
  if(!ready.every(Boolean)||token!==state.renderToken||document.visibilityState!=="visible")return;
  const payload={id:"r_"+crypto.randomUUID().replaceAll("-",""),session_id:state.session,
    frame_id:frame.frame_id,candidate_id:candidate.candidate_id,source_seq:sourceSeq,mode};
  if(savedRun){payload.run_id=savedRun;
    payload.mode=mode==="MANUAL_CANDIDATE"?"MANUAL_SAVED_CANDIDATE":"SAVED_REPLAY";}
  const result=await post(savedRun?"/api/live/view-receipts":"/api/live/receipts",payload);
  if(result.accepted){state.receiptKeys.add(key);document.body.dataset.receipt="accepted";}}
function render(view){const token=++state.renderToken;const frame=state.hiddenView?null:
    state.selectedFrame?(view.frames.find(x=>x.frame_id===state.selectedFrame)||view.frames.at(-1)):
    view.frames.at(-1);
  if(frame&&!state.selectedFrame)state.selectedFrame=frame.frame_id;
  const candidates=candidatesFor(view,frame),byLane=Object.fromEntries(candidates.map(x=>[x.lane_id,x]));
  const selection=view.selection?.[frame?.frame_id]||{},version=selection.evidence_version||0;
  const winner=selection.winner_id,displayed=candidates.find(x=>x.candidate_id===state.manualCandidate)||
    candidates.find(x=>x.candidate_id===winner)||
    candidates.find(x=>x.candidate_id===selection.stale_fallback_id)||candidates[0]||null;
  const manual=Boolean(displayed&&state.manualCandidate===displayed.candidate_id);
  const fixture=view.experiment?.origin==="FIXTURE"||view.candidates.some(x=>x.origin==="FIXTURE");
  const winnerEvaluation=view.evaluations.find(x=>x.candidate_id===winner&&x.evidence_version===version);
  $("#header-mode").textContent=fixture?"FIXTURE / 固定4経路 / 模擬評価":
    winnerEvaluation?.origin==="REAL_JEV"?"実動画 / 固定4経路 / 実Jev評価":
    "実動画 / 固定4経路 / Jev評価待ち";
  $("#run-badge").textContent=view.run_id+" · "+view.lifecycle;
  $("#source-name").textContent=view.source?.filename||"保存run";
  if(!$("#video-choice").options.length){const option=document.createElement("option");
    option.textContent=view.source?.filename||"保存run";$("#video-choice").append(option);}
  $("#frame-evidence").textContent=frame?"K / "+frame.actual_seconds.toFixed(3)+"s":"K未選択";
  $("#pts").textContent=frame?"要求 "+frame.requested_seconds.toFixed(3)+" / 実 "+frame.pts+
    " × "+frame.time_base[0]+"/"+frame.time_base[1]:"—";
  $("#frame-id").textContent=frame?.frame_id||"—";
  $("#frame-id").title=frame?"sample "+frame.sample_id+" / pixel SHA-256 "+frame.pixel_sha256:"";
  $("#info-evidence").textContent=frame?"E"+version+" / "+
    (selection.stale_fallback_id&&!winner?"旧採用を保持":"現在根拠"):"根拠待ち";
  $("#info-run").textContent=view.run_id+" / "+view.business;
  $("#neighbor-current").textContent=frame?"K / "+frame.actual_seconds.toFixed(3)+"s":"K 未選択";
  const index=frame?view.frames.findIndex(x=>x.frame_id===frame.frame_id):-1;
  for(const [id,offset,label] of [["#prev-k",-1,"前"],["#next-k",1,"次"]]){
    const button=$(id),neighbor=index<0?null:view.frames[index+offset];
    button.disabled=!neighbor;button.textContent=neighbor?label+" K / "+neighbor.actual_seconds.toFixed(3)+"s":label+" K —";
    button.onclick=neighbor?()=>{state.selectedFrame=neighbor.frame_id;state.manualCandidate=null;
      state.cursor=null;refresh(true).catch(showError);}:null;}
  $("#pipe-k-label").textContent=frame?"元K / 実PTS "+frame.pts:"元K 未選択";
  $("#k-state").textContent=frame?"✓ 元K公開済み":"選択待ち";
  $("#meta").textContent=(frame?.frame_id||"K未選択")+" · seq "+view.snapshot_seq+
    " · E"+version+" · "+(displayed?.device||"GPU待ち");
  setImage($("#pipe-keyframe"),frame?.image_artifact_id);
  const saved=view.lifecycle!=="RUNNING"||!view.accepting;
  $("#player").hidden=saved;$("#keyframe-image").hidden=!saved;
  if(saved){setImage($("#keyframe-image"),frame?.image_artifact_id);
    $("#image-stamp").textContent="保存K / 再推論・再評価なし";}
  for(const id of ["#play","#pause","#scrub"])$(id).disabled=saved;
  $("#analyze").disabled=saved||view.worker_alive||view.selected_count>=view.max_keyframes;
  $("#stop-analysis").disabled=saved||!view.worker_alive;
  $("#reset").disabled=saved;
  $("#preview-state").textContent=state.cursor!==null?"保存cursor #"+state.cursor:
    view.failure?"失敗: "+view.failure:view.worker_alive?"解析中: "+(view.active_phase||"待機"):
    winner?(winnerEvaluation?.origin==="REAL_JEV"?"実Jev採用 / E":"fixture採用 / E")+version:
    displayed?(displayed.origin==="REAL_MODEL"?"実mask ":"fixture mask ")+displayed.mask_count+" / 評価待ち":"Kを選んで解析";
  for(const lane of lanes)renderLane(lane,byLane[lane],view,frame,winner);
  renderMatrix(view,frame,byLane,winner,version);renderThumbs(byLane,winner);
  renderTimeline(view,frame);renderLog(view,frame);queueView(view);
  const evaluation=activeEvaluation(view,displayed,version),q=evaluation?.axes?.Q;
  $("#winner-card").textContent=winner?(manual?"手動閲覧 "+displayed?.lane_id+"帯":
    (winnerEvaluation?.origin==="REAL_JEV"?"現在採用 ":"fixture採用 ")+displayed?.lane_id+"帯")+
    " · Q "+(q?.score_decimal||"—"):selection.stale_fallback_id?"旧根拠の採用を保持 / 再評価中":
    displayed?"未評価プレビュー "+displayed.lane_id+"帯":"Jev採用なし";
  $("#selection-note").textContent=displayed?"元K "+frame.actual_seconds.toFixed(3)+"s / E"+version+
    " / "+(lastDecision(view,displayed,version)?.reason_code||"Q未確定")+
    (manual?" / 手動閲覧":""):"元Kと実maskを待機";
  setImage($("#main-image"),displayed?.preview_artifact_id);
  $("#main-image").alt=displayed?.origin==="REAL_MODEL"?"選択Kの実mask重畳":"fixture mask重畳";
  $("#main-placeholder").textContent=displayed?"画像読込み中":"実mask待ち";
  $("#retry-image").hidden=true;
  if(displayed){loaded($("#main-image"),token).then(ok=>{if(token!==state.renderToken)return;
      $("#main-image").dataset.failed=ok?"false":"true";$("#retry-image").hidden=ok;
      $("#main-placeholder").textContent=ok?"":"画像を表示できません";});
    const decision=lastDecision(view,displayed,version);
    const mode=manual?"MANUAL_CANDIDATE":winner?"FOLLOW_SELECTION":"UNSCORED_PREVIEW";
    receipt(view,frame,displayed,decision?.seq||displayed.seq,mode,token).catch(showError);}
  pulse(view);}
async function refresh(force=false){const base=savedRun?"/api/live/runs/"+encodeURIComponent(savedRun)+"/snapshot":
  "/api/live/snapshot";const path=base+(state.cursor===null?"":"?cursor="+state.cursor);
  const response=await fetch(path,{cache:"no-store"});if(!response.ok)throw new Error("snapshot_"+response.status);
  const view=await response.json();if(state.cursor===null&&view.snapshot_seq<state.lastSeq)return;
  if(!force&&state.cursor===null&&view.snapshot_seq===state.lastSeq){queueView(view);return;}
  if(state.cursor===null)state.lastSeq=view.snapshot_seq;
  document.body.dataset.error="";render(view);}
$("#play").onclick=()=>$("#player").play().catch(showError);
$("#pause").onclick=()=>$("#player").pause();
$("#player").addEventListener("timeupdate",()=>{const player=$("#player");
  $("#time-label").textContent=player.currentTime.toFixed(2)+" s";
  if(Number.isFinite(player.duration)&&player.duration>0)
    $("#scrub").value=String(Math.round(player.currentTime/player.duration*1000));});
$("#scrub").oninput=()=>{const player=$("#player");if(Number.isFinite(player.duration))
  player.currentTime=Number($("#scrub").value)/1000*player.duration;};
$("#analyze").onclick=async()=>{try{const result=await post("/api/live/select",
  {seconds:$("#player").currentTime});state.selectedFrame=result.frame_id;
  state.manualCandidate=null;state.cursor=null;state.hiddenView=false;await refresh();}catch(e){showError(e);}};
$("#stop-analysis").onclick=async()=>{try{await post("/api/live/analysis-stop",{action:"stop"});await refresh();}
  catch(e){showError(e);}};
$("#current").onclick=()=>{state.cursor=null;state.manualCandidate=null;state.hiddenView=false;refresh(true).catch(showError);};
$("#reset").onclick=()=>{state.cursor=null;state.selectedFrame=null;state.manualCandidate=null;
  state.hiddenView=true;refresh(true).catch(showError);};
$("#retry-image").onclick=()=>{state.imageRetry++;$("#main-image").removeAttribute("src");refresh(true).catch(showError);};
$("#shutdown").onclick=async()=>{try{await post("/api/live/shutdown",{action:"shutdown"});
  $("#preview-state").textContent="正常終了を要求しました";}catch(e){showError(e);}};
function chosenProfiles(){return [...document.querySelectorAll(".profile-check:checked")].map(x=>x.value);}
function chosenK(){return [...document.querySelectorAll(".k-check:checked")].map(x=>Number(x.value));}
function experimentPayload(){return {profiles:chosenProfiles(),
  repeats:Number($("#experiment-repeats").value),k_seconds:chosenK(),
  bucket:"VALIDATION"};}
function experimentText(value){$("#experiment-result").replaceChildren(
  document.createTextNode(value));}
async function getJson(path){const r=await fetch(path,{cache:"no-store"});
  if(!r.ok)throw new Error("request_"+r.status);return r.json();}
async function showPlan(){const plan=await post("/api/live/batch/plan",experimentPayload());
  experimentText("計画 "+plan.run_count+" run / 分割 "+plan.segmentation_jobs+
    " job / E0 "+plan.e0_suites+"・E1 "+plan.e1_suites+" suite / HTTP最大 "+
    plan.max_http_attempts+" / 予約上限 US$"+
    (plan.max_reserved_micro_usd/1e6).toFixed(3)+" / 既使用 "+
    plan.ledger_before.gpu_jobs+" GPU job");}
$("#k-save").onclick=async()=>{try{const result=await post("/api/live/k-set",{seconds:chosenK()});
  experimentText("K集合を保存: "+result.seconds.join(", ")+" 秒");}catch(e){showError(e);}};
$("#k-load").onclick=async()=>{try{const data=await getJson("/api/live/k-set");
  for(const input of document.querySelectorAll(".k-check"))
    input.checked=data.seconds.includes(Number(input.value));
  experimentText("K集合を読込: "+data.seconds.join(", ")+" 秒");}catch(e){showError(e);}};
$("#experiment-plan").onclick=()=>showPlan().catch(showError);
$("#experiment-start").onclick=async()=>{try{const data=await post("/api/live/batch/start",experimentPayload());
  experimentText(data.batch_id+" 開始 / "+data.plan.run_count+" run を順次実行");}
  catch(e){showError(e);}};
$("#experiment-stop").onclick=async()=>{try{await post("/api/live/batch/stop",{action:"stop"});
  experimentText("batch停止を要求しました");}catch(e){showError(e);}};
$("#experiment-list").onclick=async()=>{try{const data=await getJson("/api/live/runs");
  const box=$("#experiment-result");box.replaceChildren();
  const heading=document.createElement("p");heading.textContent="保存run "+data.all_target_run_count+
    "件 / 比較可能群 "+data.comparable_groups.length+"件";box.append(heading);
  for(const run of data.runs){const row=document.createElement("div");row.className="experiment-run";
    const link=document.createElement("a");link.href="/?run="+encodeURIComponent(run.run_id);
    link.textContent=run.run_id;row.append(link,document.createTextNode(" · "+
      (run.experiment?.profile||"手動")+" · "+(run.lifecycle||run.status)+
      " · K "+(run.frames??"—")+" · Q "+(run.valid_q??"—")));box.append(row);}
  if(!data.runs.length)box.append(document.createTextNode("保存runなし"));}
  catch(e){showError(e);}};
$("#experiment-compare").onclick=async()=>{try{const data=await getJson("/api/live/compare"),
  box=$("#experiment-result");box.replaceChildren();
  const heading=document.createElement("p");heading.textContent="全対象 "+
    data.index.all_target_run_count+" run / 比較可能群 "+data.index.comparable_groups.length+
    " / 除外 "+data.index.excluded.length+" / 未完了 "+data.index.incomplete.length+" · 独立品質の正解なし";box.append(heading);
  for(const group of data.actual_configuration_comparison){const row=document.createElement("p");
    row.textContent=group.profile+" 実構成 "+group.run_count+" run / 完了 "+group.complete_run_count+" / 未完了 "+group.incomplete_run_count+" · 初回採用 "+
      group.first_adoptions+" · 最終採用 "+group.final_adoptions+
      " · 初mask中央値 "+(group.median_first_mask_ms??"—")+"ms"+
      " · 初採用中央値 "+(group.median_first_adoption_ms??"—")+"ms"+
      " · 分割累計 "+(group.segmentation_duration_ms/1000).toFixed(1)+"秒"+
      " · 既知入力費用 US$"+group.known_input_cost_usd+
      " · 使用量不明 "+group.unknown_usage_attempts+"件 · 失敗 "+group.failures;
    box.append(row);}
  const cf=data.saved_policy_comparison.flatMap(x=>x.saved_policy);
  const fixed=data.evaluator_comparison.flatMap(x=>x.fixed_evaluator);
  const note=document.createElement("p");note.textContent="保存policy反実仮想 "+
    cf.length+" K×根拠 / Jev対固定規則 "+fixed.length+
    " K (画像品質の優劣は未判定)";box.append(note);  const laneOf=id=>id?id.split("_").at(-1).toUpperCase():"—";
  for(const entry of data.saved_policy_comparison){
    const section=document.createElement("details"),summary=document.createElement("summary");
    summary.textContent=entry.run_id+" · 保存policy "+entry.saved_policy.length+
      "根拠 · 固定規則 "+entry.fixed_evaluator.length+"K";
    section.append(summary);
    for(const policy of entry.saved_policy){const row=document.createElement("p");
      const wait=policy.first_eligible_at_ms!==null&&policy.full_wait_at_ms!==null?
        Math.max(0,policy.full_wait_at_ms-policy.first_eligible_at_ms)+"ms":"—";
      row.textContent=policy.frame_id+" E"+policy.evidence_version+
        " · 到着順 "+laneOf(policy.first_eligible_id)+
        " → 全件待ち "+laneOf(policy.full_wait_winner_id)+" · 差 "+wait;
      row.title=[policy.first_eligible_id,policy.full_wait_winner_id].join(" / ");
      section.append(row);}
    for(const fixedResult of entry.fixed_evaluator){const row=document.createElement("p");
      row.textContent=fixedResult.frame_id+" · Jev "+laneOf(fixedResult.jev_choice_id)+
        " / 固定被覆率規則 "+laneOf(fixedResult.fixed_choice_id)+
        " · 同候補 "+(fixedResult.same_candidate?"はい":"いいえ");
      row.title=[fixedResult.jev_choice_id,fixedResult.fixed_choice_id].join(" / ");
      section.append(row);}
    box.append(section);}
  for(const incomplete of data.index.incomplete){const row=document.createElement("p");
    row.textContent="未完了run "+incomplete.run_id+" · "+incomplete.reason;box.append(row);}
  for(const excluded of data.index.excluded){const row=document.createElement("p");
    row.textContent="比較除外 "+excluded.run_id+" · "+excluded.reason;box.append(row);}
}
  catch(e){showError(e);}};
if(savedRun){$("#player").removeAttribute("src");
  for(const id of ["#k-save","#k-load","#experiment-plan","#experiment-start",
                    "#experiment-stop"])$(id).disabled=true;}
refresh().catch(showError);
const timer=setInterval(()=>{if(!document.hidden&&state.cursor===null)refresh().catch(showError);},500);
window.addEventListener("beforeunload",()=>clearInterval(timer));
