"use strict";
// Model-free DOM/clock contract tests; these are not real Browser evidence.
const {test}=require('node:test'), assert=require('node:assert/strict');
const fs=require('node:fs'), vm=require('node:vm'), path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../../ui/conversation_ecology/saved-video.js'),'utf8');
const tick=()=>new Promise(r=>setImmediate(r));
class Element {
  constructor(){this.children=[];this.options=[];this.currentTime=6;this.duration=6;this.ended=true;this.paused=true;this.textContent='';this.value='';}
  append(n){this.children.push(n);this.options.push(n);}
  replaceChildren(){this.children=[];}
  removeAttribute(){} load(){} pause(){this.paused=true;}
  getAttribute(){return this.src||null;}
  addEventListener(name,fn){this[name]=fn;}
  async play(){this.playCalls=(this.playCalls||0)+1;this.paused=false;this.ended=false;}
}
async function harness(status='ended',bridge=false){
  const ids=new Map(),timers=[],calls=[];
  const doc={getElementById(id){if(!ids.has(id))ids.set(id,new Element());return ids.get(id);},createElement(){return new Element();}};
  doc.querySelector=()=>bridge?{content:'server-issued-owner'}:null;doc.addEventListener=()=>{};
  let s={status,epoch:2,asset_id:'a',released_position:6,queued:0,active:false,assets:[{id:'a',decoder:'ready'},{id:'b',decoder:'ready'}],events:[],models:{},profile:{chunk_seconds:2}};
  s.budget={grant:'SV01-SAMPLE-Q1',media_seconds:4.5,asr_attempts:2,image_attempts:1};
  let gate=null,reject=false;
  vm.runInNewContext(source,{document:doc,window:{addEventListener(){}},Date,state:{token:'synthetic',session_id:'s1'},setInterval:f=>(timers.push(f),f),clearInterval(){},AbortController,
    fetch:async(url,opts)=>{
      if(opts?.body){const c=JSON.parse(opts.body);calls.push(c);if(gate)await gate;
        if(reject)return {ok:false,json:async()=>({error:'budget_media_seconds'})};
        if(c.action==='restart'){s.epoch++;s.released_position=0;s.status='playing';}
        else if(c.action==='play')s.status=s.mode==='MANUAL_LOCAL_ANALYSIS'&&!s.preparation_complete?'preparing':'playing';
        else if(c.action==='stop'){s.status='stopped';s.epoch++;}
        else if(c.action==='pause')s.status='paused';
        else if(c.action==='seek'){s.epoch++;s.released_position=c.position;s.status='paused';}
        else if(c.action==='release')s.released_position=c.end;
        else if(c.action==='select'){s.epoch++;s.asset_id=c.asset_id;s.status='selected';s.released_position=0;}
      }
      return {ok:true,json:async()=>({...structuredClone(s),...(!opts?.body&&bridge?{publication_owner:true,bridge:{status:'connected',mode:'SYNTHETIC'},expires_at:s.expires_at||Date.now()/1000+100}: {})})};
    }});
  await timers[1]();
  return {ids,doc,calls,timers,get s(){return s;},setGate(p){gate=p;},reject(){reject=true;}};
}

test('manual first start waits for models without playing or releasing, then follows explicit intent',async()=>{
  const h=await harness('selected',true);
  Object.assign(h.s,{mode:'MANUAL_LOCAL_ANALYSIS',settings_version:1,real_analysis_available:true,preparation_complete:false});
  await h.ids.get('sv-play').onclick();
  assert.equal(h.ids.get('sv-video').playCalls,undefined);
  assert.equal(h.calls.filter(c=>c.action==='release').length,0);
  h.s.preparation_complete=true;
  await h.timers[0]();
  assert.equal(h.ids.get('sv-video').playCalls,1);
});

test('manual preparation stop cancels intent; later ready cannot autoplay',async()=>{
  const h=await harness('selected',true);
  Object.assign(h.s,{mode:'MANUAL_LOCAL_ANALYSIS',settings_version:1,preparation_complete:false});
  await h.ids.get('sv-play').onclick();await h.ids.get('sv-stop').onclick();
  h.s.preparation_complete=true;await h.timers[0]();
  assert.equal(h.ids.get('sv-video').playCalls,undefined);
  assert.equal(h.s.status,'stopped');
});
test('independent lane backlog is shown without pausing playback',async()=>{
  const h=await harness('playing');
  const lane={queued:0,active:1,completed:7,rejected:0,cancelled:0,oldest_media:null,last_latency:.2,state:'ready'};
  h.s.lanes={asr:lane,image:{...lane,queued:40,completed:2,oldest_media:4,last_latency:20,state:'vision_backlog_full',rejected:1}};
  h.s.phase='LIVE';h.s.visible_event_limit=64;h.s.event_total=150;
  await h.timers[0]();const text=h.ids.get('sv-status').textContent;
  assert.match(text,/Audio: 待ち0/);assert.match(text,/Vision: 待ち40/);assert.match(text,/非受付1/);
  assert.equal(h.s.status,'playing');assert.equal(h.calls.length,0);
});
test('one EOF click resets time and epoch; double click admits only one restart',async()=>{
  const h=await harness();let release;h.setGate(new Promise(r=>release=r));
  const first=h.ids.get('sv-play').onclick();await tick();await h.ids.get('sv-play').onclick();
  assert.equal(h.calls.length,1);assert.equal(h.calls[0].action,'restart');release();await first;
  assert.equal(h.s.epoch,3);assert.equal(h.ids.get('sv-video').currentTime,0);assert.equal(h.ids.get('sv-video').playCalls,1);
});
test('QR12 actual grant and cumulative usage are visible',async()=>{
  const h=await harness();const text=h.ids.get('sv-status').textContent;
  assert.match(text,/SV01-SAMPLE-Q1/);assert.match(text,/4.500 s \/ ASR 2 \/ 画像 1/);
  assert.match(text,/LOCAL_OBSERVATION_NO_JEV/);
});
test('tail still draining blocks playback without a request',async()=>{
  const h=await harness('eof_draining');await h.ids.get('sv-play').onclick();assert.equal(h.calls.length,0);
});
test('rejected browser play returns backend to pause without releasing media',async()=>{
  const h=await harness();h.ids.get('sv-video').play=async()=>{throw Error('NotAllowedError');};
  await h.ids.get('sv-play').onclick();assert.deepEqual(h.calls.map(c=>c.action),['restart','pause']);assert.equal(h.s.status,'paused');
});
test('insufficient grant does not reset video time or invoke play',async()=>{
  const h=await harness();h.reject();await h.ids.get('sv-play').onclick();
  assert.equal(h.ids.get('sv-video').currentTime,6);assert.equal(h.ids.get('sv-video').playCalls,undefined);
});
test('stop wins while restart request is pending',async()=>{
  const h=await harness();let release;h.setGate(new Promise(r=>release=r));
  const first=h.ids.get('sv-play').onclick();await tick();const stop=h.ids.get('sv-stop').onclick();release();await Promise.all([first,stop]);
  assert.equal(h.s.status,'stopped');assert.equal(h.ids.get('sv-video').playCalls,undefined);
});
test('stop wins while native browser play promise is pending',async()=>{
  const h=await harness();let release;const video=h.ids.get('sv-video');video.play=()=>new Promise(r=>release=()=>{video.paused=false;r();});
  const first=h.ids.get('sv-play').onclick();await tick();await h.ids.get('sv-stop').onclick();release();await first;
  assert.equal(video.paused,true);assert.equal(h.s.status,'stopped');
});
test('seek and material selection fence queued old releases',async()=>{
  const h=await harness('paused');h.ids.get('sv-video').ended=false;await h.ids.get('sv-play').onclick();
  h.ids.get('sv-video').currentTime=8.1;
  const poll=h.timers[0]();h.doc.getElementById('sv-seek').value='1';await h.ids.get('sv-go').onclick();await poll;
  assert.ok(!h.calls.some(c=>c.action==='release'));assert.equal(h.s.released_position,1);
  h.ids.get('sv-assets').value='b';h.ids.get('sv-assets').onchange();await tick();assert.equal(h.s.asset_id,'b');
});
test('SM08 bridge command response preserves ownership and releases played intervals',async()=>{
  const h=await harness('paused',true);await h.ids.get('sv-play').onclick();
  h.ids.get('sv-video').currentTime=8.1;await h.timers[0]();
  assert.ok(h.calls.some(c=>c.action==='release'));assert.equal(h.ids.get('sv-play').disabled,false);
});
test('SM09 expired bridge content clears screen even without a server response',async()=>{
  const h=await harness('paused',true);h.s.expires_at=1;await h.timers[0]();await h.timers[0]();
  assert.equal(h.ids.get('sv-state').textContent,'期限切れ・内容削除');assert.equal(h.ids.get('sv-video').paused,true);
});

test('PH03 drawer close is display-only; same owner keeps publishing',async()=>{
  const h=await harness('paused',true);await h.ids.get('sv-play').onclick();
  const epoch=h.s.epoch;const close=h.doc.getElementById('media-dialog').close;
  if(close)await close();
  h.ids.get('sv-video').currentTime=8.1;await h.timers[0]();
  assert.equal(h.s.epoch,epoch);assert.equal(h.s.status,'playing');assert.ok(h.calls.some(c=>c.action==='release'));
  assert.equal(h.calls.filter(c=>['pause','stop'].includes(c.action)).length,0);
});
test('PH06 range preview causes no seek; change commits exactly once, programmatic clock never seeks',async()=>{
  const h=await harness('paused',true),range=h.ids.get('sv-range');
  for(let i=0;i<20;i++){range.value=i/4;range.oninput();}assert.equal(h.calls.length,0);
  await range.onchange();assert.equal(h.calls.filter(c=>c.action==='seek').length,1);assert.equal(h.s.epoch,3);
  await h.timers[0]();assert.equal(h.calls.filter(c=>c.action==='seek').length,1);
});
test('PH06 latest seek wins pending response; volume is playback-only',async()=>{
  const h=await harness('paused',true);let release;h.setGate(new Promise(r=>release=r));const range=h.ids.get('sv-range');
  range.value=1;const a=range.onchange();await tick();range.value=3;const b=range.onchange();release();await Promise.all([a,b]);
  assert.equal(h.ids.get('sv-video').currentTime,3);assert.equal(h.s.released_position,3);
  const before=h.calls.length;h.ids.get('sv-volume').value='.25';h.ids.get('sv-volume').oninput();h.ids.get('sv-monitor').checked=true;h.ids.get('sv-monitor').onchange();
  assert.equal(h.ids.get('sv-video').volume,.25);assert.equal(h.ids.get('sv-video').muted,false);assert.equal(h.calls.length,before);
});
