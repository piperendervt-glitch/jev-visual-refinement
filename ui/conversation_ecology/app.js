"use strict";
const byId = id => document.getElementById(id);
let state = null;
let selectedEventId = null;
let renderedSession = null;
let resendPending = false;
const sentAcks = new Set();
let requestQueue = Promise.resolve();
function node(tag, cls, text) { const n = document.createElement(tag); if(cls)n.className=cls; if(text!==undefined)n.textContent=text; return n; }
function request(command) {
  const operation = requestQueue.then(() => requestNow(command));
  requestQueue = operation.catch(() => {});
  return operation;
}
async function requestNow(command) {
  const options = command ? {method:"POST",headers:{"Content-Type":"application/json","X-C0-Token":state.token},body:JSON.stringify(command)} : {};
  let response;
  try { response = await fetch(command?"/api/action":"/api/state", options); }
  catch { throw new Error("network_error"); }
  if(!response.ok)throw new Error("http_"+response.status);
  try { return await response.json(); }
  catch { throw new Error("invalid_response"); }
}
async function act(command) {
  try {
    byId("error").hidden=true;
    const data=await request(command); state=data;
    return {ok:true, operation:data.operation, display:render()};
  } catch(e) {
    byId("error").textContent=String(e.message);byId("error").hidden=false;
    return {ok:false, reason:e.message};
  }
}
function renderEvents() {
  const selected=state.events.find(e=>e.id===selectedEventId);
  if(!selected)selectedEventId=null;
  byId("detail").textContent=selected?JSON.stringify(selected,null,2):"イベントを選択してください。";
  byId("events").replaceChildren();
  for(const e of [...state.events].reverse()){
    const row=node("button","event");
    row.dataset.eventId=e.id;row.setAttribute("aria-pressed",String(e.id===selectedEventId));
    row.append(node("span","",String(e.fixture_monotonic_ms)+" ms"),node("b","",e.kind),node("span","","#"+e.cursor+" · FIXTURE"));
    row.onclick=()=>{selectedEventId=e.id;renderEvents();};byId("events").append(row);
  }
}
async function resend() {
  if(resendPending)return;
  if(!state){byId("operation-result").textContent="再送を開始できません（state_unavailable）。";return;}
  resendPending=true;byId("resend").disabled=true;
  byId("operation-result").textContent="再送処理中…";
  try {
    const result=await act({action:"resend",session_id:state.session_id});
    if(!result.ok){
      byId("operation-result").textContent="再送処理に失敗（"+result.reason+"）。";return;
    }
    const op=result.operation;
    if(!op || !["resent","no_commits"].includes(op.result)){
      byId("operation-result").textContent="再送結果を確認できません（server_result_missing）。";return;
    }
    byId("operation-result").textContent=op.result==="no_commits"
      ?"再送対象なし。応答commitはまだありません。"
      :"再送処理を完了（"+op.commit_ids.length+"件、うちack受理済み"+op.browser_acked_commit_ids.length+"件）。"
        +(result.display.addedCommitCount===0?"同じ応答の追加表示なし。":"未表示の応答を"+result.display.addedCommitCount+"件表示しました。");
  } finally {resendPending=false;byId("resend").disabled=false;}
}
function render() {
  let addedCommitCount=0;
  if(renderedSession!==state.session_id){
    renderedSession=state.session_id;selectedEventId=null;sentAcks.clear();
    byId("operation-result").textContent="";
  }
  byId("clock").textContent=`合成時計 ${state.clock_ms} ms`;
  byId("status").textContent=state.status+(state.main_pending?" · 本題はpending／backend未接続":"");
  byId("commit-count").textContent=String(state.commits.length);
  byId("ack-count").textContent=String(state.acks.filter(a=>a.kind==="browser_dom").length);
  byId("thread-count").textContent=Object.keys(state.threads).length+" threads";
  byId("task").hidden=!state.snapshot?.work_states.length;
  byId("task").textContent="合成TaskEvent：承認待ち · 実作業なし／実権限の発行なし";
  byId("fields").replaceChildren();
  for(const [key,label] of [["person","人物"],["place","場所"],["conversation","会話"]]){
    const item=node("div","field"), title=node("div","name");title.append(node("span","",label),node("span","","UNKNOWN 100%"));
    item.append(title,node("div","bar"),node("small","","合成・未観測の濃度 / 実観測なし"));byId("fields").append(item);
  }
  const box=byId("conversation");
  if(state.events.length){
    // Reconcile by semantic ID. Repeated render/send never duplicates messages.
    const existing=new Map([...box.querySelectorAll("[data-message-id]")].map(n=>[n.dataset.messageId,n]));
    const rows=[];
    for(const e of state.events){
      if(e.kind==="transcript") rows.push({id:e.id,who:`合成発話 · r${e.payload.revision} · ${e.payload.phase}`,text:e.payload.text,user:true});
      if(e.kind==="correction")rows.push({id:e.id,who:"訂正イベント",text:"旧版を失効しました。表示済みの履歴は残します。",user:false});
      if(e.kind==="commit")rows.push({id:e.payload.id,who:"選ばれた反応 · FIXTURE",text:e.payload.text||"（無応答／本題へ保留）",commit:e.payload});
    }
    const elements=rows.map(row=>{
      const message=existing.get(row.id)||node("div",row.user?"message user":"message");message.dataset.messageId=row.id;
      if(!existing.has(row.id)){message.append(node("div","who",row.who),node("div","bubble",row.text));
        if(row.commit){addedCommitCount++;message.dataset.commitId=row.commit.id;message.append(node("small","",`${row.commit.id} · 適合Q ${row.commit.Q.toFixed(3)}`));}}
      return message;
    });box.replaceChildren(...elements);
  }
  byId("candidates").replaceChildren();
  const evaluation=[...state.evaluations].reverse().find(e=>e.snapshot_id===state.snapshot?.snapshot_id);
  for(const c of state.candidates){
    const row=node("div","candidate"), info=node("div","",c.text||c.act);info.append(node("small","",c.proposers.join(" / ")+(c.eligible?"":" · 前提不成立")));
    const q=evaluation?.scores?.[c.id]?.Q;row.append(info,node("span","score",q===undefined?(evaluation?.status||"未評価"):`適合Q ${q.toFixed(3)}`));byId("candidates").append(row);
  }
  const chosen=state.commits.at(-1);byId("selection").textContent=chosen?`${chosen.candidate_id} → ${chosen.evaluation_id} → ${chosen.id}`:"候補 → 評価 → 採用 → commit → ack";
  renderEvents();
  for(const commit of state.commits)ackAfterRender(commit);
  return {addedCommitCount};
}
async function ackAfterRender(commit){
  const sessionId=state.session_id;
  if(sentAcks.has(commit.id)||state.acks.some(a=>a.commit_id===commit.id&&a.kind==="browser_dom"))return;
  const element=[...document.querySelectorAll("[data-commit-id]")].find(n=>n.dataset.commitId===commit.id);
  if(!element)return;
  await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
  if(!element.isConnected || element.dataset.commitId!==commit.id || !element.querySelector(".bubble"))return;
  if(state.session_id!==sessionId || sentAcks.has(commit.id) ||
     state.acks.some(a=>a.commit_id===commit.id&&a.kind==="browser_dom"))return;
  sentAcks.add(commit.id);
  try{state=await request({action:"ack",session_id:sessionId,commit_id:commit.id,evidence:"connected_dom_after_two_animation_frames"});render();}
  catch(e){sentAcks.delete(commit.id);byId("error").textContent="ack未確認: "+e.message;byId("error").hidden=false;}
}
document.querySelectorAll("[data-demo]").forEach(button=>button.onclick=()=>{
  document.querySelectorAll("[data-demo]").forEach(b=>b.classList.toggle("active",b===button));act({action:"demo",name:button.dataset.demo});
});
byId("utterance").onsubmit=e=>{e.preventDefault();act({action:"utterance",text:byId("text").value,revision:byId("revision").checked,phase:byId("partial").checked?"partial":"finalized"});};
byId("advance").onclick=()=>act({action:"advance",ms:25});
byId("interval").onclick=()=>act({action:"advance",ms:300});
byId("evaluate").onclick=()=>act({action:"evaluate",profile:byId("profile").value});
byId("resend").onclick=resend;
act(null);
