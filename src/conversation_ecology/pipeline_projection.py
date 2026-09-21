"""Read-only, content-free pipeline projection. No writes, inference or clocks."""
import json

SCHEMA = 'pipeline-view-v1'
LIMIT = 512


def namespace(provider, run, session, scope):
    return json.dumps([provider, run, session, scope], ensure_ascii=False, separators=(',', ':'))


def record(ns, event, stage, status, *, refs=(), parent=None, source=None, **metadata):
    cursor = event['cursor']
    return dict(id=ns+':'+str(cursor)+':'+stage, namespace=ns, source_event_id=event.get('id'),
                source_cursor=cursor, stage=stage, status=status, refs=list(refs),
                parent=parent, source_stage=source, schema=SCHEMA, **metadata)


def observation_pipeline(view, live):
    ns = namespace('saved_video', live['run_id'], live['session_id'], 'recorded-media')
    events = [e for e in live['events'] if e.get('session_id') == live['session_id']]
    nodes = {n['id']: n for n in view['nodes']}
    released, decoded, started, records = {}, {}, {}, []
    for e in events:
        kind=e['kind'];p=e.get('provenance',{});cursor=e['cursor']
        # A job is identified by its source run/session/epoch/accepted cursor/interval.
        key=json.dumps([p.get(k) for k in ('run_id','session_id','epoch','available_cursor','interval')])
        if p.get('lane'):key+=':'+p['lane']
        common=e.get('common_record') or {};refs=[common['id']] if common.get('id') else []
        meta=dict(media_epoch=p.get('epoch',e.get('input_epoch',e['epoch'])),
                  media_interval=p.get('interval',e.get('interval')),clock='media_seconds',
                  acquired_at=(nodes.get(common.get('id'),{}).get('record') or {}).get('acquired_at'),
                  expires_at=view.get('expires_at'),attempt=None,analyzer=e.get('analyzer'),
                  origin=view['mode'],started_at=None,completed_at=None)
        current=e.get('current',True) and meta['media_epoch']==live['epoch']
        row=None
        if kind=='input_released':
            row=record(ns,e,'input','queued' if current else 'stale',**meta);released[cursor]=row
        elif kind=='common_input':
            parent=released.get(p.get('available_cursor'))
            if parent and (parent['media_epoch']!=p.get('epoch') or parent['media_interval']!=p.get('interval')):parent=None
            row=record(ns,e,'decode','completed' if current else 'stale',refs=refs,
                       parent=parent and parent['id'],source='input' if parent and current else None,**meta)
            decoded[key]=row
        elif kind.startswith('analysis_'):
            status={'analysis_started':'running','analysis_completed':'completed','analysis_failed':'failed',
                    'analysis_blocked':'disabled','analysis_not_run':'not_run'}.get(kind,'unknown')
            if not current and status in ('running','completed'):status='stale'
            parent=decoded.get(key) if kind=='analysis_started' else started.get((key,e.get('analyzer')))
            row=record(ns,e,'analyze',status,refs=refs or (parent or {}).get('refs',[]),parent=parent and parent['id'],
                       source=(parent or {}).get('stage') if parent and status in ('running','completed') else None,
                       reason=e.get('reason'),**meta)
            if kind=='analysis_started':started[key,e.get('analyzer')]=row
        elif kind=='cancelled_before_start':row=record(ns,e,'analyze','cancelled',reason='cancelled_before_start; job ref unavailable',**meta)
        elif kind=='control':
            row=record(ns,e,'input','cancel_requested' if e.get('running_completion_pending') else e.get('reason','unknown'),**meta)
        elif kind=='gap_not_analyzed':row=record(ns,e,'input','failed',reason='queue_full',**meta)
        if row:records.append(row)
        if common.get('status')=='NOT_RECORDED':records.append(record(ns,e,'record','failed',reason=common.get('reason'),**meta))
        elif refs and common.get('status') in ('recorded','already_recorded','recorded_notification_pending'):
            available=all(r in nodes and nodes[r]['availability']=='available' for r in refs)
            saved=record(ns,e,'record','completed' if available else 'unavailable',refs=refs,
                         parent=row and row['id'],source=row['stage'] if available and current and row else None,
                         common_cursor=common['cursor'],save_status=common['status'],**meta)
            records.append(saved)
            if available:
                records.append(record(ns,e,'project','projected' if current else 'retained_old_epoch',refs=refs,parent=saved['id'],
                                      source='record' if current else None,common_cursor=common['cursor'],**meta))
    for row in records:
        if any(r in nodes and nodes[r]['availability']!='available' for r in row['refs']):row.update(status='unavailable',source_stage=None,parent=None)
    return dict(records=records,source_cursor=live.get('events',[])[-1]['cursor'] if live.get('events') else 0,
                namespace=ns,media_epoch=live['epoch'],queued=live['queued'],active=live['active'],
                input_status=live['status'],models=live['models'],lanes=live.get('lanes'),
                telemetry_gap=bool(events and events[0]['cursor']>1),observation_error=live.get('observation_error'))


def project_pipeline(view, observations=None):
    ns=namespace(view.get('provider','context' if view['mode']=='CONTEXT_FIXTURE' else 'demo'),
                 None,view['session_id'],view.get('scope'))
    records=[];nodes={n['id']:n for n in view['nodes']};evaluations={};outputs={};deliveries={}
    for e in view.get('history',[]):
        p=e.get('payload',{});kind=e['kind'];refs=list(e.get('refs',[]));row=None
        meta=dict(origin=view['mode'],expires_at=view.get('expires_at'),started_at=None,completed_at=None,
                  media_epoch=None,clock='no_start_end_record')
        if view['mode']=='CONTEXT_FIXTURE':
            if kind in ('source','artifact'):row=record(ns,e,'input','completed',refs=[p['id']] if p.get('id') in nodes else [],**meta)
            elif kind=='evaluation':
                row=record(ns,e,'evaluate','completed',refs=[p['id']],role='hearing-recorded-v1 / fixture',**meta);evaluations[p['id']]=row
            elif kind in ('context_commit','proposal_result'):
                parent=evaluations.get(p.get('evaluation_id'));refs+=p.get('source_refs',[])
                row=record(ns,e,'validate',p.get('status','unknown'),refs=refs,parent=parent and parent['id'],
                           source='evaluate' if parent and p.get('status')=='APPLIED' else None,reason=p.get('reason'),**meta)
            elif kind=='response_commit':
                row=record(ns,e,'output','committed',refs=[p['question_id']],commit_id=p['id'],**meta);outputs[p['id']]=row
            elif kind in ('delivery','ack'):
                parent=(outputs if kind=='delivery' else deliveries).get(p.get('commit_id'))
                row=record(ns,e,kind,'prepared' if kind=='delivery' else p.get('kind','unknown'),
                           refs=(parent or {}).get('refs',[]),parent=parent and parent['id'],source=parent and parent['stage'],commit_id=p.get('commit_id'),**meta)
                if kind=='delivery':deliveries[p['commit_id']]=row
            elif kind=='deleted':row=record(ns,e,'record','unavailable',refs=[p['id']],**meta)
        elif view['mode']=='DEMO':
            row=record(ns,e,'project','DEMO_DISPLAY_ONLY',refs=refs,reason='合成表示更新・業務経路を推定しない',**meta)
        if row:
            if any(r in nodes and nodes[r]['availability']!='available' for r in row['refs']):row.update(status='unavailable',source_stage=None,parent=None)
            records.append(row)
            if row['stage']=='validate' and row['status']=='APPLIED' and refs:
                records.append(record(ns,e,'project','projected',refs=[r for r in refs if r in nodes],parent=row['id'],source='validate',**meta))
    if observations:records=observations['records']
    dropped=max(0,len(records)-LIMIT);records=records[-LIMIT:]
    return dict(schema=SCHEMA,namespace=ns,session_id=view['session_id'],scope=view.get('scope'),epoch=view.get('epoch',1),
                cursor=view['cursor'],mode=view['mode'],expires_at=view.get('expires_at'),records=records,
                media_epoch=(observations or {}).get('media_epoch'),
                source_status={k:v for k,v in (observations or {}).items() if k not in ('records','namespace')},
                telemetry_gap=(observations or {}).get('telemetry_gap',False),omitted_records=dropped,
                retention=view.get('retention','available'),meaning='unassessed_observation' if observations else 'fixture' if view['mode']=='CONTEXT_FIXTURE' else 'display_only')
