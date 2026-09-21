"""Unassessed source records in the existing run store, never semantic commits."""
from copy import deepcopy
import json
import time
from .store import ContextStore
from .model import encoded, hashed
from ..map_projection import empty_view


class ObservationStore(ContextStore):
    def __init__(self,path,*,clock=time.time,fault=None,create=True,synthetic=False):
        self.synthetic=synthetic
        super().__init__(path,clock=clock,fault=fault,create=create)
        self.db.execute('PRAGMA secure_delete=ON')
        if create:
            self.db.executescript('''CREATE TABLE observation_receipts(id TEXT PRIMARY KEY,hash TEXT,cursor INTEGER,record_id TEXT);
                CREATE TABLE observation_roots(root TEXT PRIMARY KEY);
                CREATE TABLE observation_inputs(id TEXT PRIMARY KEY,record_id TEXT);
                CREATE TABLE observation_conflicts(id TEXT,at REAL);''')
            self.db.execute("INSERT INTO meta VALUES ('retention_kind',?)",('synthetic' if synthetic else 'real_observation',))
            if not synthetic:self.db.execute("UPDATE meta SET value=? WHERE key='expires'",(str(clock()+86400),))
        else:
            kind=self.db.execute("SELECT value FROM meta WHERE key='retention_kind'").fetchone()
            if kind is None:
                self.close();raise ValueError('not_an_observation_run')
            self.synthetic=kind[0]=='synthetic'

    def expire_contents(self):
        """Erase this run's content and derived copies, keep only expiry metadata."""
        with self.lock:
            if self.closed:return
            if self.clock()<float(self.db.execute("SELECT value FROM meta WHERE key='expires'").fetchone()[0]):return
            if self.db.execute("SELECT value FROM meta WHERE key='content_purged'").fetchone():return
            self.db.execute('BEGIN IMMEDIATE')
            try:
                for table in ('acknowledgements','deliveries','response_commits','consumers','projections','projection_checkpoints',
                              'notification_outbox','context_commits','proposals','current_items','item_versions','events',
                              'observation_receipts','observation_roots','observation_inputs','observation_conflicts'):
                    self.db.execute('DELETE FROM '+table)
                self.db.execute("INSERT INTO meta VALUES ('content_purged','expired')");self.db.execute('COMMIT')
                self.db.execute('VACUUM')
            except BaseException:
                if self.db.in_transaction:self.db.execute('ROLLBACK')
                raise

    def ensure_available(self):
        if hasattr(self,'db') and not self.closed:
            # Constructor calls this before the observation tables exist.
            if self.db.execute("SELECT name FROM sqlite_master WHERE name='observation_receipts'").fetchone():self.expire_contents()
        return super().ensure_available()

    @staticmethod
    def unpack(row):
        item=ContextStore.unpack(row)
        item['mode']=item['value'].get('mode','FIXTURE')
        return item

    def accept(self,event,*,integration_run,grant,acquired_at,expires_at):
        if event['kind'] not in ('common_input','analysis_completed'):return None
        if expires_at<=self.clock():raise ValueError('source_expired')
        event={k:v for k,v in event.items() if k!='common_record'}
        identity=integration_run+':'+event['run_id']+':'+str(event['cursor'])
        ident='observation:'+hashed(identity);canonical=hashed(event)
        session=event['provenance']['session_id'];scope='recorded-media'
        with self.lock:
            self.ensure_available()
            old=self.db.execute('SELECT * FROM observation_receipts WHERE id=?',(identity,)).fetchone()
            if old:
                if old['hash']!=canonical:
                    with self.transaction():self.db.execute('INSERT INTO observation_conflicts VALUES (?,?)',(identity,self.clock()))
                    raise ValueError('observation_payload_conflict')
                return dict(status='already_recorded',id=old['record_id'],cursor=old['cursor'])
            prov=deepcopy(event['provenance']);roots=[prov[k]['root'] for k in ('audio','frame') if prov.get(k) and prov[k].get('root')]
            input_parts=[integration_run,prov['run_id'],prov['session_id'],prov['epoch'],prov['available_cursor'],prov['interval']]
            if prov.get('lane'):input_parts.append(prov['lane'])
            input_key=hashed(input_parts)
            prior_input=self.db.execute('SELECT record_id FROM observation_inputs WHERE id=?',(input_key,)).fetchone()
            if event['kind']=='analysis_completed' and not prior_input:raise ValueError('missing_input_record')
            value=dict(kind='source',label=('入力区間' if event['kind']=='common_input' else event['analyzer'].upper()+' 原出力')+' · '+str(prov['interval']),
                       mode='SYNTHETIC_OBSERVATION' if self.synthetic else 'LOCAL_OBSERVATION_NO_JEV',
                       source_kind='saved_video',assessment='pending_evaluation',semantic_adoption='NOT_CONNECTED',authority='denied',
                       integration_run=integration_run,source_run=event['run_id'],grant=grant,source_cursor=event['cursor'],
                       event_kind=event['kind'],source_refs=[prior_input[0]] if prior_input and event['kind']=='analysis_completed' else [],
                       source_result_id=identity,source_epoch=prov['epoch'],provenance=prov,raw_result=deepcopy(event.get('result')),
                       acquired_at=acquired_at,expires_at=min(expires_at,acquired_at+(7 if self.synthetic else 1)*86400),
                       current_at_arrival=event.get('current',True),physical_roots=roots,independent_evidence_weight=None)
            if len(encoded(value).encode())>64000:raise ValueError('record_size')
            try:
                with self.transaction():
                    if self.path.stat().st_size>getattr(self,'capacity_bytes',8*1024*1024):raise ValueError('observation_capacity')
                    if hasattr(self,'record_limit') and self.db.execute('SELECT COUNT(*) FROM observation_receipts').fetchone()[0]>=self.record_limit:
                        raise ValueError('observation_record_capacity')
                    cursor=self.event(session,scope,'observation_registered',{'id':ident,'source_cursor':event['cursor'],'assessment':'pending_evaluation'})
                    self.put(session,scope,ident,value,prov['interval'][1],cursor)
                    self.db.execute('INSERT INTO observation_receipts VALUES (?,?,?,?)',(identity,canonical,cursor,ident))
                    if event['kind']=='common_input':self.db.execute('INSERT OR IGNORE INTO observation_inputs VALUES (?,?)',(input_key,ident))
                    self.db.executemany('INSERT OR IGNORE INTO observation_roots VALUES (?)',[(x,) for x in roots])
                    expiry=min(float(self.db.execute("SELECT value FROM meta WHERE key='expires'").fetchone()[0]),value['expires_at'])
                    self.db.execute("UPDATE meta SET value=? WHERE key='expires'",(str(expiry),))
            except Exception:
                # A COMMIT followed by notification failure is already durable.
                saved=self.db.execute('SELECT cursor FROM observation_receipts WHERE id=?',(identity,)).fetchone()
                if saved:return dict(status='recorded_notification_pending',id=ident,cursor=saved[0])
                raise
            return dict(status='recorded',id=ident,cursor=cursor)

    def replay(self,session,scope):
        try:return super().replay(session,scope)
        except ValueError as error:
            if str(error)!='retention_expired':raise
            return dict(status='incomplete',reason='expired',view=None,events=[],missing=['expired_content'],network_calls=0)

    def stop(self):
        try:return super().stop()
        except ValueError as error:
            if str(error)!='retention_expired':raise
            self.stopped=True


class ObservationBridge:
    def __init__(self,store,integration_run,grant):
        self.store,self.run,self.grant=store,integration_run,grant
        self.last_result=None;self.error=None

    def __call__(self,event):
        now=self.store.clock()
        result=self.store.accept(event,integration_run=self.run,grant=self.grant,acquired_at=now,expires_at=now+(7 if self.store.synthetic else 1)*86400)
        if result:self.last_result=result
        return result


class ObservationProvider:
    def __init__(self,app):self.app=app
    @property
    def view(self):return self.snapshot()
    def snapshot(self):
        live=self.app.sv.view()
        with self.app.store.lock:return self._snapshot(live)
    def _snapshot(self,live):
        app=self.app;store=app.store;session=app.engine.session_id
        v=empty_view(session,'SYNTHETIC_OBSERVATION' if store.synthetic else 'LOCAL_OBSERVATION_NO_JEV')
        v['provider']='saved_video';v['scope']='recorded-media'
        try:
            layer=store.snapshot(session,'recorded-media');data=layer.data()
        except ValueError as error:
            if str(error)!='retention_expired':raise
            v.update(epoch=2,retention='expired',status='Replay不完全・実内容期限切れ',expires_at=0)
            return v
        v.update(cursor=data['available_cursor'],layer_view_id=layer.id,layers=data['layers'],
            expires_at=float(store.db.execute("SELECT value FROM meta WHERE key='expires'").fetchone()[0]),media_live=dict(epoch=live['epoch'],status=live['status'],position=live['released_position']))
        for ident,item in data['items'].items():
            value=item['value']
            if value.get('source_kind')!='saved_video':continue
            current=value['source_epoch']==live['epoch'] and session==live['session_id'] and value['current_at_arrival'] and not app.sv.closed
            v['nodes'].append(dict(id=ident,canonical_id=ident,kind='Evidence',region='conversation',label=value['label'],revision=item['revision'],
                state='pending_evaluation' if current else 'history_only',availability=item['availability'],scope='recorded-media',concentration=None,
                source_refs=value.get('source_refs',[]),source_cutoff=item['source_cutoff'],available_cursor=item['cursor'],record=value,current_applicability=current))
            for target in value.get('source_refs',[]):v['edges'].append(dict(id=ident+':input:'+target,source=ident,target=target,relation='公開入力から得た未評価候補',state='recorded'))
        v['history']=[dict(e,id='observation-event:'+str(e['cursor']),source='SV common record',target='L4 / map',state='pending_evaluation',refs=[e['payload']['id']]) for e in store.events(session,'recorded-media') if 'id' in e['payload']]
        refs=[n['id'] for n in v['nodes']]
        v['schematic']=[dict(role='保存動画 / frame・PCM',status='公開区間のみ',refs=refs),dict(role='ASR原文・画像候補',status='未評価 / pending_evaluation',refs=refs),
            dict(role='L4 / SQLite・LayerView',status='共通記録へ保存',refs=refs),dict(role='評価 → 意味採用 → 三場',status='NOT_CONNECTED',refs=[])]
        # Formal empty numerical state, not a contribution from these observations.
        from .field_adapter import field_snapshot
        shot=field_snapshot(session=session)
        v['field_snapshots']=[dict(scope='recorded-media',snapshot=shot)]
        v['fields']={k:dict(UNKNOWN=d['UNKNOWN'],scope='未評価観測・寄与なし') for k,d in shot['spaces'].items()}
        v['record_count']=len(v['nodes']);v['physical_root_count']=store.db.execute('SELECT COUNT(*) FROM observation_roots').fetchone()[0]
        from ..pipeline_projection import observation_pipeline
        try:v['_pipeline_observation']=observation_pipeline(v,live)
        except Exception:v['_pipeline_observation']=dict(records=[],telemetry_gap=True,observation_error='pipeline_projection_unavailable')
        # Transient reference to an actually produced LayerView, not a semantic update.
        if hasattr(app,'history_projection'):
            app.history_projection[session]=dict(cursor=v['cursor'],layer_view_id=layer.id,session_id=session)
            if len(app.history_projection)>64:app.history_projection.pop(next(iter(app.history_projection)))
        return v
