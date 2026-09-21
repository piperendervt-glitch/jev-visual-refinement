"use strict";
// Independent read-only view: no playback, map mutation, inference or acknowledgement.
const historyTime=s=>Number.isFinite(s)?`${Math.floor(s/60).toString().padStart(2,'0')}:${(s%60).toFixed(3).padStart(6,'0')}`:'時刻なし';
function historyLabel(e){
  const times=e.frame?`frame PTS ${e.frame.pts??'未取得'} · ${historyTime(e.frame.media_s)}`:e.interval?e.interval.map(historyTime).join('–'):Number.isFinite(e.position)?historyTime(e.position):'時刻なし';
  const stages={asset_selected:'素材選択',control:'動画制御',input_released:'媒体入力・受付',analysis_queued:'解析受付・待機',decode_started:'入力変換・処理中',common_input:e.analyzer==='asr'?'音声入力':'画像入力',analysis_started:e.analyzer==='asr'?'音声認識・処理中':'画像解析・処理中',analysis_completed:e.analyzer==='asr'?'音声認識結果':'画像解析結果・未評価',analysis_failed:'解析失敗',analysis_not_run:'解析未実行',cancelled_before_start:'解析取消し',gap_not_analyzed:'入力非受付',lane_ready:'解析担当・準備完了',lane_failed:'解析担当・失敗',tail_completed:'末尾処理完了',projection_received:'マップ投影・受信',map_dom_applied:'マップDOM適用（paint／既読ではない）'};
  let body=e.excerpt??e.reason??e.result_status??'';
  if(e.output_empty)body='空の認識結果（無音判定ではない）';
  if(e.excerpt_omitted)body+='…［一覧省略・選択で全文］';
  if(e.kind==='common_input')body=e.audio?`${e.audio.status==='no_audio_track'?'音声trackなし':e.audio.status} · PCM ${e.audio.sample_rate}Hz / ${e.audio.channels}ch / ${e.audio.samples}samples`:e.frame?'画像frame・公開区間内':'入力未取得';
  if(e.kind==='asset_selected'||e.kind==='asset_registered')body=(e.kind==='asset_registered'?'素材取込み完了 · ':'')+(e.has_audio===false?'音声trackなし':e.has_audio===true?'音声trackあり':'音声track未確認');
  if(e.analyzer)body=`${e.analyzer==='asr'?'Audio / ASR':'Vision'} · `+body;
  if(e.common_record)body+=` · SQLite保存 ${e.common_record.status}${e.common_record.reason?' / '+e.common_record.reason:''}`;
  if(e.projection_cursor!==undefined)body+=` · 記録cursor ${e.projection_cursor} / 未評価・意味採用なし`;
  return `${e.stream==='synthetic'?'合成／C0':e.synthetic?'合成観測':'保存動画'} · ${times} · ${e.kind==='asset_registered'?'素材登録':stages[e.kind]||e.kind} · ${body||e.state||'記録あり'}${e.stale||e.current===false?' · 旧epoch／履歴のみ':''}`;
}
class ProcessHistoryModel{
  constructor(limit=4096){this.limit=limit;this.rows=new Map();this.order=0;this.version=0;this.evicted=0;this.gap=0;this.after=0;this.run=null;this.asset=null;this.epoch=null;this.held=null;this.selected=null;this.reason=null;this.frozenAt=0;}
  add(id,e){if(this.rows.has(id))return;this.rows.set(id,{...e,id,received:++this.order});while(this.rows.size>this.limit){this.rows.delete(this.rows.keys().next().value);this.evicted++;}this.version++;}
  page(p){if(p.expired){this.clear();return;}if(this.run&&this.run!==p.run_id)this.clear();this.run=p.run_id;this.gap+=p.gap||0;this.serverEvicted=p.evicted||0;for(const e of p.events)this.add(`sv:${p.run_id}:${e.cursor}`,{...e,stream:'video'});this.after=Math.max(this.after,p.next||0);}
  clear(){this.rows.clear();this.held=null;this.selected=null;this.reason=null;this.after=0;this.run=null;this.version++;}
  visible(scope,query='',kind=''){
    const source=this.held||[...this.rows.values()].reverse();
    return source.filter(e=>(scope==='all'||(scope==='video'?e.stream==='video'&&(!e.asset_id||e.asset_id===this.asset):e.stream==='synthetic'))&&(!kind||e.kind.includes(kind))&&(!query||historyLabel(e).toLowerCase().includes(query)||e.id.toLowerCase().includes(query))).slice(0,64);
  }
  hold(reason,rows){if(!this.held){this.held=rows;this.frozenAt=this.order;}this.reason=reason;}
  resume(){this.held=null;this.reason=null;this.version++;}
}
class ProcessHistoryView{
  constructor(api){
    this.api=api;this.model=new ProcessHistoryModel();this.nodes=new Map();this.frame=null;this.disposed=false;this.polling=false;this.signatures=new Map();this.current=[];this.dirty=true;this.renders=0;this.lastKey='';this.mediaState=null;this.detailGeneration=0;
    this.$=id=>document.getElementById(id);
    this.$('process-detail').hidden=true;
    this.$('history-pause').onclick=()=>{const m=this.model;if(m.reason==='paused')m.resume();else m.hold('paused',this.current);this.schedule();};
    this.$('history-latest').onclick=()=>{this.model.resume();this.$('history-rows').scrollTop=0;this.schedule();};
    this.$('history-rows').onscroll=()=>{if(this.$('history-rows').scrollTop>2&&!this.model.held){this.model.hold('reading',this.current);this.schedule();}};
    for(const id of ['history-source','history-filter','history-search'])this.$(id)[id==='history-search'?'oninput':'onchange']=()=>{this.model.resume();this.schedule();};
    this.$('history-expand').onclick=()=>this.$('history-rows').parentElement.classList.toggle('expanded');
    window.addEventListener('pagehide',()=>{this.disposed=true;if(this.frame!==null)cancelAnimationFrame(this.frame);this.clear();},{once:true});
  }
  media(s){
    if(s.status==='retention_expired'){this.clear();return;}
    if(s.asset_id!==this.model.asset){this.model.asset=s.asset_id;this.model.resume();this.model.selected=null;this.detailGeneration++;this.$('process-detail-text').textContent='未選択';if(s.asset_id)this.$('history-source').value='video';}
    this.model.epoch=s.epoch;this.mediaState=s;
    this.schedule();
  }
  synthetic(view,c0){
    for(const [namespace,rows] of [[`context:${view?.session_id}:${view?.mode}`,view?.provider==='saved_video'?[]:view?.history||[]],[`C0:${c0?.session_id}`,c0?.events||[]]]){
      const signature=`${rows.length}:${rows.at(-1)?.cursor}:${rows.at(-1)?.id}`;if(this.signatures.get(namespace)===signature)continue;this.signatures.set(namespace,signature);if(this.signatures.size>64)this.signatures.delete(this.signatures.keys().next().value);
      for(const e of rows.slice(-4096))this.model.add(`${namespace}:${e.id||e.cursor}`,{...e,stream:'synthetic',reason:JSON.stringify(e.payload||e.detail||e.state||{}).slice(0,180)});
    }
    if(!this.mediaState?.asset_id&&this.$('history-source').value==='video')this.$('history-source').value='synthetic';
    this.schedule();
  }
  projection(v,applied=false){
    if(v?.provider!=='saved_video'||!v.cursor)return;
    const kind=applied?'map_dom_applied':'projection_received';
    this.model.add(`${kind}:${v.session_id}:${v.layer_view_id}`,{stream:'video',kind,session_id:v.session_id,projection_cursor:v.cursor,layer_view_id:v.layer_view_id,synthetic:v.mode==='SYNTHETIC_OBSERVATION',reason:'既存LayerViewの参照。履歴の受信順は因果順ではありません。'});this.schedule();
  }
  async poll(){
    if(this.polling||this.disposed)return;this.polling=true;const generation=this.detailGeneration;
    try{const m=this.model,p=await this.api(`/api/sv/history?after=${m.after}&run=${encodeURIComponent(m.run||'')}`);if(this.disposed||generation!==this.detailGeneration)return;if(p.expired){this.clear();return;}m.page(p);this.error='';this.schedule();}
    catch(e){this.error='履歴の通信未確認・次回同cursorから再取得: '+e.message;this.schedule();}finally{this.polling=false;}
  }
  clear(){this.model.clear();this.mediaState=null;this.current=[];this.nodes.clear();this.detailGeneration++;this.$('history-rows').replaceChildren();this.$('process-detail-text').textContent='参照不可／期限切れ・ページ終了';this.schedule();}
  schedule(){
    const m=this.model,s=this.mediaState;
    const signature=[m.version,m.reason,m.selected,m.asset,m.epoch,m.gap,this.error,this.$('history-source').value,this.$('history-filter').value,this.$('history-search').value,s?.lanes?.asr.completed,s?.lanes?.image.completed].join('|');
    if(this.disposed||this.frame!==null||signature===this.scheduledKey)return;this.scheduledKey=signature;
    this.frame=requestAnimationFrame(()=>{this.frame=null;this.render();});
  }
  render(){
    const m=this.model,s=this.mediaState,scope=this.$('history-source').value,query=this.$('history-search').value.toLowerCase(),kind=this.$('history-filter').value;
    const key=[m.version,m.held?'held':'live',m.reason,m.selected,m.asset,m.epoch,scope,query,kind].join('|');
    const changed=key!==this.lastKey,rows=changed?m.visible(scope,query,kind):this.current;
    const text=(id,value)=>{if(this.$(id).textContent!==value)this.$(id).textContent=value;};
    text('history-pause',m.reason==='paused'?'表示を再開':'表示を一時停止');
    text('history-count',`${m.reason==='paused'?'表示停止':m.reason==='reading'?'閲覧位置保持':'LIVE'} · 保持 ${m.rows.size}/4096 · 表示 ${rows.length}/64 · 新着 ${m.held?m.order-m.frozenAt:0} · 表示保持外 ${m.evicted} / 配信保持外 ${m.serverEvicted||0} / 通信欠番 ${m.gap} · ASR完了 ${s?.lanes?.asr.completed??0} / 画像完了 ${s?.lanes?.image.completed??0} · Jev OFF${this.error?' · '+this.error:''}`);
    if(!changed)return;this.lastKey=key;
    const box=this.$('history-rows'),scroll=box.scrollTop,ids=new Set(rows.map(e=>e.id));
    for(const [id,node]of this.nodes)if(!ids.has(id)){node.remove();this.nodes.delete(id);}
    rows.forEach((e,i)=>{let b=this.nodes.get(e.id);if(!b){b=document.createElement('button');b.dataset.eventId=e.id;b.onclick=()=>this.select(e);this.nodes.set(e.id,b);}const label=historyLabel({...e,stale:e.stream==='video'&&e.input_epoch!=null&&e.input_epoch!==m.epoch});if(b.textContent!==label)b.textContent=label;b.setAttribute('aria-pressed',String(m.selected===e.id));if(box.children[i]!==b)box.insertBefore(b,box.children[i]||null);});
    box.scrollTop=m.held?scroll:0;this.current=rows;this.renders++;box.dataset.renderCount=this.renders;
  }
  async select(e){
    const m=this.model;m.selected=e.id;m.hold(m.reason==='paused'?'paused':'reading',this.current);this.schedule();
    this.$('process-detail').hidden=false;this.$('process-detail').open=true;this.$('history-rows').parentElement.classList.add('expanded');
    const generation=++this.detailGeneration;this.$('process-detail-text').textContent='既存記録を参照中…';
    try{
      const data=e.stream==='video'&&e.run_id&&Number.isFinite(e.cursor)?await this.api(`/api/sv/history/detail?run=${encodeURIComponent(e.run_id)}&cursor=${e.cursor}`):e;
      if(this.disposed||generation!==this.detailGeneration||m.selected!==e.id)return;
      this.$('process-detail-text').textContent=JSON.stringify(data,null,2);
    }catch(error){if(generation===this.detailGeneration)this.$('process-detail-text').textContent='参照不可: '+error.message;}
  }
}
if(typeof module!=='undefined')module.exports={ProcessHistoryModel,historyLabel};
