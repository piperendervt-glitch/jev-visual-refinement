"use strict";
// Logical unit tests with a small fake DOM/fetch/animation clock.
// No browser is started, no socket is used, no real browser ack is produced.
const {test}=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const vm=require("node:vm");
const source=fs.readFileSync(path.join(__dirname,"../../ui/conversation_ecology/app.js"),"utf8");
const clone=x=>structuredClone(x);
const tick=()=>new Promise(resolve=>setImmediate(resolve));
class Element {
  constructor(tag="div"){this.tag=tag;this.children=[];this.dataset={};this.attributes={};this.parent=null;this.textContent="";this.className="";this.hidden=false;this.disabled=false;this.classList={toggle:()=>{}};}
  get isConnected(){return this.root===true || Boolean(this.parent?.isConnected);}
  set innerHTML(value){throw new Error("Unsafe HTML assignment");}
  append(...nodes){for(const n of nodes){n.parent=this;this.children.push(n);}}
  replaceChildren(...nodes){for(const n of this.children)n.parent=null;this.children=[];this.append(...nodes);}
  setAttribute(k,v){this.attributes[k]=v;}
  querySelectorAll(selector){
    const match=n=>selector==="[data-message-id]"?Boolean(n.dataset.messageId):selector==="[data-commit-id]"?Boolean(n.dataset.commitId):selector===".bubble"?n.className==="bubble":false;
    return this.children.flatMap(n=>[...(match(n)?[n]:[]),...n.querySelectorAll(selector)]);
  }
  querySelector(s){return this.querySelectorAll(s)[0]||null;}
}
function fixture({acked=true,empty=false,session="unit-ui-1"}={}){
  const cid=session+":commit-1";
  const commit={id:cid,text:"unit fixture response",Q:.95,candidate_id:"c1",evaluation_id:"e1"};
  const event={id:session+":event-1",cursor:1,fixture_monotonic_ms:25,kind:"commit",payload:commit};
  return {token:"unit-only-not-a-real-token",session_id:session,clock_ms:25,status:"fixture",main_pending:false,threads:{},
    snapshot:null,evaluations:[],candidates:[],commits:empty?[]:[commit],events:empty?[]:[event],
    acks:acked&&!empty?[{commit_id:cid,kind:"browser_dom",evidence:"unit-only-mocked-state"}]:[]};
}
function resent(s){const v=clone(s);v.operation={result:s.commits.length?"resent":"no_commits",commit_ids:s.commits.map(c=>c.id),browser_acked_commit_ids:s.acks.filter(a=>a.kind==="browser_dom").map(a=>a.commit_id)};return v;}
async function harness(initial=fixture()){
  const ids=new Map(),frames=[],calls=[];
  const doc={getElementById(id){if(!ids.has(id)){const n=new Element();n.root=true;ids.set(id,n);}return ids.get(id);},
    createElement:tag=>new Element(tag),querySelectorAll:s=>s==="[data-demo]"?[]:doc.getElementById("conversation").querySelectorAll(s)};
  let handler=async cmd=>resent(initial);
  const context=vm.createContext({document:doc,requestAnimationFrame:f=>frames.push(f),
    fetch:async (url,opts)=>{if(!opts?.body)return {ok:true,json:async()=>clone(initial)};
      const cmd=JSON.parse(opts.body);calls.push(cmd);return handler(cmd);}});
  vm.runInContext(source,context);
  await tick();
  return {doc,ids,frames,calls,run:code=>vm.runInContext(code,context),
    setHandler:f=>{handler=f;},reply:data=>({ok:true,json:async()=>clone(data)}),
    async frame(){const pending=frames.splice(0);pending.forEach(f=>f());await tick();}};
}
test("acked resend reuses the same message and keeps selected event, including repeated operations",async()=>{
  const s=fixture(),h=await harness(s);h.setHandler(async()=>h.reply(resent(s)));
  const original=h.doc.querySelectorAll("[data-commit-id]")[0];
  h.ids.get("events").children[0].onclick();
  for(let i=0;i<3;i++)await h.ids.get("resend").onclick();
  assert.equal(h.doc.querySelectorAll("[data-commit-id]").length,1);
  assert.equal(h.doc.querySelectorAll("[data-commit-id]")[0],original);
  assert.equal(h.calls.length,3);assert.ok(h.calls.every(c=>c.action==="resend"&&c.session_id===s.session_id));
  assert.match(h.ids.get("operation-result").textContent,/ack受理済み1件/);
  assert.match(h.ids.get("operation-result").textContent,/追加表示なし/);
  assert.equal(h.ids.get("events").children[0].attributes["aria-pressed"],"true");
  assert.equal(JSON.parse(h.ids.get("detail").textContent).id,s.events[0].id);
});
test("no commit reports no target without adding a response",async()=>{
  const s=fixture({empty:true}),h=await harness(s);h.setHandler(async()=>h.reply(resent(s)));
  await h.ids.get("resend").onclick();
  assert.match(h.ids.get("operation-result").textContent,/再送対象なし/);
  assert.equal(h.doc.querySelectorAll("[data-commit-id]").length,0);
});
test("unacked response waits two mock frames and suppresses concurrent ack attempts",async()=>{
  const s=fixture({acked:false}),h=await harness(s);
  h.setHandler(async cmd=>{const v=clone(s);v.acks=[{commit_id:cmd.commit_id,kind:"browser_dom",evidence:"unit-only-mocked-state"}];return h.reply(v);});
  h.run("render(); render();");
  assert.equal(h.calls.length,0);await h.frame();assert.equal(h.calls.length,0);await h.frame();
  assert.equal(h.calls.length,1);
  assert.equal(h.calls[0].action,"ack");assert.equal(h.calls[0].session_id,s.session_id);
  assert.equal(h.calls[0].commit_id,s.commits[0].id);
  assert.equal(h.calls[0].evidence,"connected_dom_after_two_animation_frames");
  assert.equal(h.ids.get("ack-count").textContent,"1"); // Mock-only counter, not actual rendering.
});
test("detached node or changed session produces no ack",async()=>{
  for(const change of ["detach","session"]){
    const h=await harness(fixture({acked:false}));
    if(change==="detach")h.ids.get("conversation").replaceChildren();
    else h.run('state.session_id="different-unit-session"');
    await h.frame();await h.frame();assert.equal(h.calls.length,0);
  }
});
test("pending resend disables repeat clicks; HTTP/network failures stay failures and recover",async()=>{
  const s=fixture(),h=await harness(s);let resolve;
  h.setHandler(()=>new Promise(r=>{resolve=r;}));
  const operation=h.ids.get("resend").onclick();
  assert.equal(h.ids.get("resend").disabled,true);
  await h.ids.get("resend").onclick();await tick();assert.equal(h.calls.length,1);
  resolve({ok:false,status:403});await operation;
  assert.equal(h.ids.get("resend").disabled,false);
  assert.match(h.ids.get("operation-result").textContent,/失敗.*http_403/);
  h.setHandler(async()=>{throw new Error("private error text must not escape");});
  await h.ids.get("resend").onclick();assert.match(h.ids.get("operation-result").textContent,/失敗.*network_error/);
  assert.doesNotMatch(h.ids.get("error").textContent,/private/);
  h.setHandler(async()=>h.reply(resent(s)));await h.ids.get("resend").onclick();
  assert.match(h.ids.get("operation-result").textContent,/再送処理を完了/);
});
test("detail selection uses event ID, is safe text, and clears for another session with same cursor",async()=>{
  const s=fixture();s.events[0].payload.text="<img src=x onerror=unitOnly>";
  const h=await harness(s);h.ids.get("events").children[0].onclick();
  assert.equal(JSON.parse(h.ids.get("detail").textContent).payload.text,s.events[0].payload.text);
  h.run("render()");assert.equal(h.ids.get("events").children[0].attributes["aria-pressed"],"true");
  const next=fixture({session:"unit-ui-2"});h.setHandler(async()=>h.reply(next));await h.run('act({action:"demo",name:"short"})');
  assert.equal(h.ids.get("detail").textContent,"イベントを選択してください。");
  assert.equal(h.ids.get("events").children[0].attributes["aria-pressed"],"false");
});
test("old server response without operation is reported as unconfirmed",async()=>{
  const s=fixture(),h=await harness(s);h.setHandler(async()=>h.reply(s));
  await h.ids.get("resend").onclick();assert.match(h.ids.get("operation-result").textContent,/server_result_missing/);
});
test("ack failure is visible and can retry after a later render",async()=>{
  const s=fixture({acked:false}),h=await harness(s);
  h.setHandler(async()=>({ok:false,status:400}));await h.frame();await h.frame();
  assert.match(h.ids.get("error").textContent,/ack未確認: http_400/);
  h.setHandler(async cmd=>{const v=clone(s);v.acks=[{commit_id:cmd.commit_id,kind:"browser_dom",evidence:"unit-only-mocked-state"}];return h.reply(v);});
  h.run("render()");await h.frame();await h.frame();assert.equal(h.calls.length,2);
});

test("resend before initial state is available has an explicit result and sends nothing",async()=>{
  const h=await harness(fixture());h.run("state=null");
  await h.ids.get("resend").onclick();
  assert.equal(h.calls.length,0);assert.equal(h.ids.get("resend").disabled,false);
  assert.match(h.ids.get("operation-result").textContent,/state_unavailable/);
});
