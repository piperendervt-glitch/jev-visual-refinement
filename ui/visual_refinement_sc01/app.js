"use strict";
const state={preview:null,lastSeq:0,viewSession:"view_"+crypto.randomUUID().replaceAll("-","")};
const esc=s=>String(s??"");
const score=a=>a.status==="VALID"?a.score_decimal:`— ${a.missing_reason||a.status}`;
async function snapshot(){
  const suffix=state.preview?`?preview=${encodeURIComponent(state.preview)}`:"";
  const response=await fetch("/api/sc01/snapshot"+suffix,{cache:"no-store"});
  if(!response.ok)throw new Error("snapshot_failed");
  render(await response.json());
}
function render(view){
  const lanes=document.querySelector("#lanes");lanes.replaceChildren();
  const body=document.querySelector("#matrix");body.replaceChildren();
  for(const row of view.rows){
    const lane=document.querySelector("#lane-template").content.firstElementChild.cloneNode(true);
    lane.dataset.candidate=row.candidate_id||"";lane.querySelector(".lane-name").textContent=`${row.lane_id} — ${row.architecture_label}`;
    lane.querySelector(".lane-stage").textContent=`${row.generation_status} / ${row.evaluation_status}`;
    lane.querySelector(".lane-queue").textContent=row.current_reason_code;
    lane.disabled=!row.candidate_id;lane.addEventListener("click",()=>{state.preview=row.candidate_id;snapshot();});lanes.append(lane);
    const tr=document.createElement("tr");if(row.candidate_id===view.selection.winner_id)tr.className="winner";
    const cells=[row.lane_id,...["Q","A","R","I","C"].map(a=>score(row.axis_results[a])),row.current_reason_code+(row.current_q_delta!==null?` (${row.current_q_delta})`:"")];
    for(const value of cells){const td=document.createElement("td");td.textContent=esc(value);tr.append(td);}body.append(tr);
  }
  const rendered=view.preview.rendered_candidate_id;
  const row=view.rows.find(r=>r.candidate_id===rendered);
  document.querySelector("#keyframe-image").src=`/api/sc01/artifacts/${encodeURIComponent(view.preview.keyframe_artifact_ref)}`;
  document.querySelector("#main-image").src=row?.thumbnail_ref?`/api/sc01/artifacts/${encodeURIComponent(row.thumbnail_ref)}`:"";
  document.querySelector("#preview-state").textContent=view.preview.display_mode==="MANUAL_CANDIDATE"?`手動閲覧: ${rendered}（主採用は変更しません）`:`主採用を追従: ${rendered||"採用なし"}`;
  const timeline=document.querySelector("#timeline");timeline.replaceChildren();
  for(const decision of view.timeline_page.decisions){const li=document.createElement("li");li.textContent=`#${decision.commit_seq} ${decision.reason_code}: ${decision.previous_winner_id||"なし"} → ${decision.winner_after_id||"なし"}`;timeline.append(li);}
  const q=view.queues[0];document.querySelector("#queues").textContent=`${q.congestion} / 待機 ${q.queued} / 実行 ${q.active} / 完了 ${q.succeeded_total} / 最古待機 ${q.oldest_queued_ms??"—"}`;
  if(view.selection.display_revision_id&&view.snapshot_seq!==state.lastSeq){
    state.lastSeq=view.snapshot_seq;
    requestAnimationFrame(()=>requestAnimationFrame(()=>fetch("/api/sc01/receipts",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({receipt_id:"receipt_"+crypto.randomUUID().replaceAll("-",""),view_session_id:state.viewSession,source_revision_id:view.selection.display_revision_id,source_commit_seq:view.snapshot_seq,frame_id:view.frame_id,display_mode:view.preview.display_mode,rendered_candidate_id:rendered,visible:document.visibilityState==="visible",skipped_revision_ids:[]})})));
  }
}
document.querySelector("#follow").addEventListener("click",()=>{state.preview=null;snapshot();});
snapshot().catch(error=>{document.body.dataset.error=error.message;});
