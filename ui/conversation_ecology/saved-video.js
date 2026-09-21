"use strict";
(() => {
  const $ = id => document.getElementById(id), video = $("sv-video");
  const bridge=!!document.querySelector?.('meta[name="sv-bridge"]');
  let owner=bridge?document.querySelector('meta[name="sv-owner"]').content:null;
  let sv = null, chain = Promise.resolve(), base = 0, enabled = false, uploading = null, selected = null, busy = false;
  let svSession = null, tail = Promise.resolve(), generation = 0, playPending = false, ending = false;
  let awaitingPreparation = false;
  let previewing=false, lastEvents='';
  const clockText=s=>Number.isFinite(s)?`${Math.floor(s/60).toString().padStart(2,'0')}:${(s%60).toFixed(3).padStart(6,'0')}`:'未取得';
  const setText=(id,text)=>{const node=$(id);if(node&&node.textContent!==text)node.textContent=text;};
  function playerState(){
    if(!sv)return;
    const asset=sv.assets.find(a=>a.id===sv.asset_id);
    setText('sv-name',asset?.display_name|| (sv.asset_id?'登録動画':'素材未選択'));
    const states={unselected:'素材未選択',selected:'選択済み・開始待ち',preparing:'モデル準備中',playing:'再生・解析中',paused:'一時停止',stopped:'解析停止・位置保持',eof_draining:'末尾解析中',ended:'終了・再解析可能'};
    setText('sv-brief',`${bridge&&!sv.publication_owner?'ownerなし・参照のみ':states[sv.status]||sv.status} · Audio待${sv.lanes?.asr.queued??sv.queued} / Vision待${sv.lanes?.image.queued??sv.queued} · epoch ${sv.epoch} · Jev OFF`);
    const range=$('sv-range');if(range){range.disabled=!sv.asset_id||!Number.isFinite(video.duration)||video.duration<=0||!!video.error||(bridge&&!sv.publication_owner);range.max=Number.isFinite(video.duration)?video.duration:0;if(!previewing)range.value=video.currentTime;}
    if(typeof processHistory!=='undefined')processHistory.media(sv);
  }
  const halt = () => {generation++;enabled=false;awaitingPreparation=false;video.pause();};
  const error = e => {$("sv-error").textContent = String(e.message || e);};
  async function api(path, body, extra = {}) {
    const headers=bridge&&owner?{"X-SV-Owner":owner}:{};
    const response = await fetch(path, body ? {method:"POST",headers:{...headers,"X-C0-Token":state.token,"X-SV-Session":state.session_id,...extra.headers},body:body,...(extra.signal?{signal:extra.signal}:{})} : {headers});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "http_"+response.status);
    return data;
  }
  function render(data) {
    if(bridge)data={...data,publication_owner:data.publication_owner??sv?.publication_owner,bridge:data.bridge??sv?.bridge,expires_at:data.expires_at??sv?.expires_at};
    sv = data;
    if (svSession !== state?.session_id) {halt();video.removeAttribute("src");svSession=state?.session_id;selected=null;}
    $("sv-status").textContent = `${sv.status} · 公開位置 ${sv.released_position.toFixed(3)} s · epoch ${sv.epoch} · 待機 ${sv.queued} / 処理中 ${sv.active} · ${sv.budget.grant || sv.profile.profile} · 累計 ${sv.budget.media_seconds.toFixed(3)} s / ASR ${sv.budget.asr_attempts} / 画像 ${sv.budget.image_attempts} · LOCAL_OBSERVATION_NO_JEV`;
    $("sv-models").textContent = JSON.stringify(sv.models,null,2);
    if(sv.mode==='MANUAL_LOCAL_ANALYSIS'){
      $('sv-status').textContent=`通常利用・ローカル解析 / Jev OFF · 設定v${sv.settings_version} · ${sv.real_analysis_available?'実解析の準備可能':'解析準備不足'}\n`+$('sv-status').textContent;
      if(sv.status==='preparing')$('sv-status').textContent+='\n初回モデル準備中です。完了後に今回の開始操作を続行します。停止・切替で取り消せます。';
      if(sv.status==='eof_draining')$('sv-status').textContent+='\n動画EOF・公開済みのAudio/Visionを排出中です。完了後に再解析できます。';
      $('sv-play').textContent=sv.status==='ended'?'同じ動画を再解析':sv.status==='paused'||sv.status==='stopped'?'解析して再開':'解析して再生';
    }
    if(sv.lanes){
      const laneText=(name,l)=>`${name}: 待ち${l.queued} / 実行${l.active} / 完了${l.completed} / 非受付${l.rejected} / 取消${l.cancelled} · 最古${l.oldest_media==null?'なし':l.oldest_media.toFixed(3)+'s'} · 結果遅延${l.last_latency==null?'未取得':l.last_latency.toFixed(3)+'s'} · ${l.state}`;
      $('sv-status').textContent+='\n'+laneText('Audio',sv.lanes.asr)+'\n'+laneText('Vision',sv.lanes.image)+` · ${sv.phase} · 表示ログ最近${sv.visible_event_limit}件／保持${sv.event_total}件`;
    }
    $("sv-state").textContent = JSON.stringify(sv,null,2);
    if(bridge){
      if(!sv.publication_owner)halt();
      $('sv-owner-status').textContent=sv.publication_owner?'この画面が入力を操作します':'参照表示・入力操作は他画面または未取得';
      for(const id of ['sv-file','sv-assets','sv-play','sv-pause','sv-stop','sv-go'])$(id).disabled=!sv.publication_owner;
      if(sv.bridge)$('sv-status').textContent+=` · 共通記録 ${sv.bridge.status} · ${sv.bridge.mode}`;
      if(sv.observation_error){halt();error('共通記録未保存: '+sv.observation_error);}
    }
    const chooser = $("sv-assets");
    for (const asset of sv.assets) if (![...chooser.options].some(o=>o.value===asset.id)) {
      const option=document.createElement("option");option.value=asset.id;option.textContent=`${asset.display_name||'素材 '+chooser.options.length} · ${asset.id.slice(0,8)} · ${asset.decoder}${asset.has_audio===false?' · 音声trackなし':''}`;chooser.append(option);
    }
    chooser.value = sv.asset_id || "";
    if(bridge&&sv.publication_owner&&sv.asset_id&&!video.getAttribute('src')){
      video.src=`/media/${sv.asset_id}?session=${encodeURIComponent(state.session_id)}`;video.load();base=sv.released_position;
      video.addEventListener('loadedmetadata',()=>{video.currentTime=base;},{once:true});
    }
    playerState();
    const eventsKey=sv.events.map(e=>`${e.cursor}:${e.current}`).join(',');
    if(eventsKey!==lastEvents){lastEvents=eventsKey;$("sv-events").replaceChildren();
    for(const event of [...sv.events].reverse()) {
      const button=document.createElement("button");button.textContent=`#${event.cursor} ${event.kind} · epoch ${event.provenance?.epoch ?? event.epoch}${event.current===false?" · 旧結果":""}`;
      button.onclick=()=>{selected=event.cursor;$("sv-detail").textContent=JSON.stringify(event,null,2);};$("sv-events").append(button);
    }
    }
    if (selected !== null) {const event=sv.events.find(e=>e.cursor===selected);$("sv-detail").textContent=event?JSON.stringify(event,null,2):"保持範囲外";}
    if (["analysis_failed","event_capacity","session_changed"].includes(sv.status)) {enabled=false;video.pause();}
  }
  function command(action, fields={}) {
    const expectedGeneration=generation;
    const operation=chain.then(async()=>{
      if(expectedGeneration!==generation)throw new Error('superseded_control');
      const data=await api("/api/sv/action",JSON.stringify({action,asset_id:sv?.asset_id,epoch:sv?.epoch,...fields}),{headers:{"Content-Type":"application/json"}});
      if(expectedGeneration===generation)render(data);else sv={...sv,epoch:data.epoch,asset_id:data.asset_id};return data;
    });
    chain=operation.catch(e=>{enabled=false;video.pause();error(e);});return operation;
  }
  function releaseTail() {
    const end=video.currentTime, expectedGeneration=generation;
    const next=tail.then(async()=>{
      if(expectedGeneration!==generation)return;
      if(end>base+0.01) {await command("release",{start:base,end});base=end;}
    });
    tail=next.catch(()=>{});return next;
  }
  $("sv-file").onchange=async()=>{
    const files=[...$("sv-file").files];if(!files.length)return;
    halt();$("sv-error").textContent="";
    uploading=new AbortController();
    try {
      if(sv?.asset_id)await command("stop");
      let first=null;
      for(const file of files){
        const suffix=file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
        const result=await api("/api/sv/upload",file,{headers:{"X-SV-Suffix":suffix,"X-SV-Name":encodeURIComponent(file.name)},signal:uploading.signal});
        if(first===null)first=result.asset_id;
      }
      await select(first);
    } catch(e){error(e.name==="AbortError"?"取込み取消し":e);} finally{uploading=null;}
  };
  $("sv-cancel").onclick=()=>uploading?.abort();
  async function select(id) {
    halt();await command("select",{asset_id:id});base=0;
    video.src=`/media/${id}?session=${encodeURIComponent(state.session_id)}`;video.load();
  }
  $("sv-assets").onchange=()=>{if($("sv-assets").value)select($("sv-assets").value).catch(error);};
  $("sv-play").onclick=async()=>{
    if(playPending)return;
    if(ending || sv?.status==='eof_draining'){error('末尾処理中です。完了後に再開してください。');return;}
    playPending=true;$("sv-play").disabled=true;const requestGeneration=generation;
    try {
      const restart=sv?.status==='ended';
      await command(restart?'restart':'play');
      if(requestGeneration!==generation)return;
      if(sv.status==='preparing'){awaitingPreparation=true;return;}
      awaitingPreparation=false;
      if(restart)video.currentTime=0;
      base=sv.released_position;await video.play();
      if(requestGeneration!==generation){video.pause();return;}
      enabled=sv.status==='playing';$("sv-error").textContent='';
    }catch(e){
      enabled=false;video.pause();
      if(requestGeneration===generation && sv?.status==='playing')try{await command('pause');}catch(_){}
      error(e);
    }finally{playPending=false;$("sv-play").disabled=bridge&&!sv?.publication_owner;}
  };
  $("sv-pause").onclick=async()=>{
    const was=enabled;halt();
    try {if(was)await releaseTail();await command("pause");}catch(e){error(e);}
  };
  $("sv-stop").onclick=()=>{halt();return command("stop").catch(error);};
  async function seek(target){
    if(!Number.isFinite(video.duration)||!Number.isFinite(target)||target<0||target>video.duration){error("移動先が範囲外、またはmetadata未取得です");return;}
    halt();const requestGeneration=generation;
    try{await command("seek",{position:target});if(requestGeneration!==generation)return;video.currentTime=target;base=target;setText('sv-preview','');}catch(e){if(requestGeneration===generation)error(e);}
  }
  $("sv-go").onclick=()=>seek(Number($("sv-seek").value));
  if($('sv-range')){
    $('sv-range').oninput=()=>{previewing=true;setText('sv-preview',clockText(Number($('sv-range').value))+' へ移動');};
    $('sv-range').onchange=()=>{const target=Number($('sv-range').value);previewing=false;return seek(target);};
    $('sv-range').onpointercancel=()=>{previewing=false;setText('sv-preview','');};
  }
  if($('sv-volume'))$('sv-volume').oninput=()=>{video.volume=Number($('sv-volume').value);};
  if($('sv-open'))$('sv-open').onclick=()=>$('media-dialog')?.showModal();
  $("sv-monitor").onchange=()=>{video.muted=!$("sv-monitor").checked;};
  video.onended=async()=>{const was=enabled, expectedGeneration=generation;enabled=false;ending=true;try{if(was)await releaseTail();if(expectedGeneration===generation)await command("eof");}catch(e){error(e);}finally{ending=false;}};
  video.onerror=()=>{enabled=false;error("ブラウザーが動画を再生できません（codec/破損/配送を確認）。");};
  // Browser playback is the release clock. No capture, hidden seek, or full-file analysis.
  const poll=setInterval(async()=>{
    if(bridge&&sv?.expires_at&&Date.now()/1000>=sv.expires_at){
      halt();sv.events=[];sv.bridge=null;selected=null;
      $('sv-events').replaceChildren();$('sv-detail').textContent='期限切れ・内容削除';$('sv-state').textContent='期限切れ・内容削除';
      $('sv-status').textContent='retention_expired';return;
    }
    setText('sv-position',`${clockText(video.currentTime)} / ${clockText(video.duration)}`);playerState();
    if(busy || !sv || !state)return;
    busy=true;
    try {
      if(enabled && !video.paused && !video.seeking && video.currentTime-base>=sv.profile.chunk_seconds) await releaseTail();
      else render(await api("/api/sv/state"));
      if(awaitingPreparation&&sv?.status==='preparing'&&sv.preparation_complete)await $('sv-play').onclick();
    } catch(e){enabled=false;video.pause();error(e);} finally{busy=false;}
  },250);
  const init=setInterval(async()=>{if(!state)return;clearInterval(init);try{render(await api("/api/sv/state"));}catch(e){error(e);}},100);
  if(bridge){
    $('sv-owner-claim').onclick=async()=>{try{const r=await api('/api/sv/owner','{}');owner=r.owner;render(await api('/api/sv/state'));}catch(e){error(e);}};
    const releaseOwner=async()=>{halt();if(owner&&state){const prior=owner;owner=null;await fetch('/api/sv/owner/release',{method:'POST',keepalive:true,headers:{'X-C0-Token':state.token,'X-SV-Session':state.session_id,'X-SV-Owner':prior}});}};
    document.addEventListener('click',e=>{const a=e.target.closest?.('a[href="/c0"]');if(a){e.preventDefault();releaseOwner().finally(()=>location.assign('/c0'));}});
    // Drawer close is display-only. The one main-page player retains ownership.
    window.addEventListener('pagehide',()=>{clearInterval(poll);clearInterval(init);releaseOwner().catch(()=>{});});
    window.addEventListener('pageshow',e=>{if(e.persisted)location.reload();});
  }
})();
