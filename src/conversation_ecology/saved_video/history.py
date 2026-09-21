"""Read-only, bounded views of existing producer events. No inference or ack."""
from copy import deepcopy


def source_key(event):
    p=event.get('provenance') or {}
    return (p.get('run_id',event.get('run_id')),p.get('session_id',event.get('session_id')),
            p.get('epoch',event.get('input_epoch',event.get('epoch'))),p.get('available_cursor',event.get('input_cursor')),
            p.get('lane',event.get('analyzer')))


def summary(event):
    e={k:v for k,v in event.items() if k not in ('result','provenance')}
    p=event.get('provenance') or {}
    e['source_key']=source_key(event)
    e['interval']=p.get('interval',event.get('interval'))
    e['asset_id']=p.get('asset_id',event.get('registered_asset_id',event.get('asset_id')))
    e['input_epoch']=p.get('epoch',event.get('input_epoch',event.get('epoch')))
    e['frame']=p.get('frame')
    a=p.get('audio')
    e['audio']={k:a.get(k) for k in ('status','sample_rate','channels','samples')} if a else None
    r=event.get('result')
    if r is not None:
        e['synthetic']=bool(isinstance(r,dict) and r.get('synthetic'))
        text=r if isinstance(r,str) else r.get('transcript_original',r.get('observation_untrusted',r.get('text'))) if isinstance(r,dict) else None
        e['excerpt']=text[:180] if isinstance(text,str) else None
        e['excerpt_omitted']=isinstance(text,str) and len(text)>180
        e['output_empty']=text==''
        e['result_status']=r.get('status') if isinstance(r,dict) else None
    return e


def history_page(app,after=0,run=None):
    sv=app.sv
    with sv.lock:
        if sv.status=='retention_expired':return dict(expired=True,events=[],run_id=sv.run_id)
        # Cursor sequences are contiguous; slice by offset, not an unbounded payload scan.
        first=sv.events[0]['cursor'] if sv.events else sv.cursor+1
        reset=bool(run and run!=sv.run_id)
        after=0 if reset else after
        index=max(0,after-first+1)
        rows=list(sv.events[index:index+128])
        meta=dict(run_id=sv.run_id,first=first,last=sv.cursor,reset=reset,session_id=sv.session,
                  epoch=sv.epoch,asset_id=sv.asset_id,evicted=max(0,first-1),
                  gap=max(0,first-after-1) if after else 0)
    meta['events']=[summary(e) for e in rows]
    meta['next']=rows[-1]['cursor'] if rows else max(after,first-1)
    meta['more']=meta['next']<meta['last']
    return meta


def history_detail(app,run,cursor):
    sv=app.sv
    with sv.lock:
        if sv.status=='retention_expired':return dict(unavailable='期限切れ')
        if run!=sv.run_id:return dict(unavailable='別run・参照不可')
        event=next((e for e in sv.events if e['cursor']==cursor),None)
        if not event:return dict(unavailable='表示保持範囲外・参照不可')
        key=source_key(event)
        related=[e for e in sv.events if key[3] is not None and source_key(e)==key]
        result=dict(event=deepcopy(event),related=[summary(e) for e in related],
                    source_order='producer cursor（複数streamの因果順ではない）',
                    missing='記録がない工程・時刻・jobは未取得。paint／既読／browser_dom ackはこの履歴では判定しない。')
    record=next((e.get('common_record') for e in reversed(related or [event]) if e.get('common_record',{}).get('id')),None)
    if record:
        with app.store.lock:
            try:
                app.store.ensure_available()
                row=app.store.db.execute('SELECT * FROM item_versions WHERE id=? ORDER BY revision DESC LIMIT 1',(record['id'],)).fetchone()
                result['saved_record']=app.store.unpack(row) if row else None
                if not row or result['saved_record']['availability']!='available':return dict(unavailable='削除済み／参照不可')
                checkpoint=app.store.db.execute('SELECT cursor FROM projection_checkpoints WHERE consumer=?',('observation-map:'+key[1],)).fetchone()
                result['map_dom_application']=dict(cursor=checkpoint[0] if checkpoint else None,
                    covers_record=bool(checkpoint and checkpoint[0]>=record['cursor']),evidence='既存map_draw通知。paint・既読・応答ackではない')
            except ValueError:
                return dict(unavailable='期限切れ・参照不可')
        projection=getattr(app,'history_projection',{}).get(key[1])
        result['projection']=projection if projection and projection['cursor']>=record['cursor'] else dict(status='未取得／この記録の投影なし')
    return result
