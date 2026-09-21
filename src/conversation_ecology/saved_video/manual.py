"""Reusable manual-use contract, separate from every historical test grant."""
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import threading
import time
import uuid
from .resource_budget import ResourceBudget
from .resource_controller import IsolatedController
from .resource_process import ResourceModels
from .media import Assets, plain_path
from .models import LocalAnalyzers

MODE = 'MANUAL_LOCAL_ANALYSIS'
ROOT = Path(__file__).resolve().parents[3]
SETTINGS = ROOT/'config/manual_local.json'
AREA = ROOT/'artifacts/sv01/manual-local'


def settings():
    raw=SETTINGS.read_bytes();p=json.loads(raw)
    if p.get('mode')!=MODE or p.get('settings_version')!=1 or p.get('candidate')!='D':raise ValueError('manual_settings_mode')
    for key in ('max_events','max_assets','max_asset_bytes','max_total_bytes','max_pixels','audio_queue_chunks',
                'audio_queue_seconds','audio_queue_bytes','image_queue_descriptors','image_queue_bytes',
                'content_bytes','cache_bytes','retention_seconds','worker_io_timeout_seconds','observation_records','observation_bytes'):
        if not isinstance(p[key],(int,float)) or isinstance(p[key],bool) or not 0<p[key]<2**40:raise ValueError('manual_settings_resource:'+key)
    if p['heavy_asr']!=1 or p['heavy_image']!=2 or p['candidates']['D']['image_workers']!=2:raise ValueError('manual_concurrency')
    if any(k in p for k in ('allowed_asset_sha256','media_seconds','asr_attempts','image_attempts','model_wall_seconds')):
        raise ValueError('manual_settings_contains_test_lifetime')
    return p,hashlib.sha256(raw).hexdigest()


class Verification:
    """Only Codex's finite automatic check. Never applied to normal launches."""
    def __init__(self,path):
        self.path=path;self.lock=threading.RLock()
        self.data=json.loads(path.read_text()) if path.exists() else dict(started_at=None,cohorts=0,media_seconds=0.,asr_attempts=0,image_attempts=0)
    def charge(self,key,amount):
        with self.lock:
            now=time.time();d=self.data
            if d.get('state')=='CLOSED':raise ValueError('verification_closed_not_user_mode')
            if d['started_at'] is None:d['started_at']=now
            if now-d['started_at']>=1500:raise ValueError('verification_admission_25min')
            if key:
                if d[key]+amount>{'cohorts':3,'media_seconds':600,'asr_attempts':400,'image_attempts':200}[key]:raise ValueError('verification_limit_'+key)
                d[key]+=amount
            self.path.write_text(json.dumps(d),encoding='utf-8')


class ManualBudget:
    save=ResourceBudget.save
    def __init__(self,path,profile,settings_sha256,verification=None):
        self.path=Path(path);self.profile=profile;self.settings_sha256=settings_sha256
        self.lock=threading.RLock();self.now=time.time;self.phase='MANUAL_LOCAL';self.runtime_begun=False
        self.verification=verification;self.active={'asr':set(),'image':set()};self.loaded=set()
        self.data=dict(mode=MODE,settings_sha256=settings_sha256,state='READY',cohort=uuid.uuid4().hex,
                       media_seconds=0.,asr_attempts=0,image_attempts=0,model_started_at=None,model_loads=0,
                       runtime_in_flight=False,tickets=[],active={'asr':0,'image':0},native_failure_this_task=False)
        self.save()
    def check(self):
        if self.data.get('failure_reason'):raise ValueError('manual_run_failed:'+self.data['failure_reason'])
        if self.data['state']=='CLOSED':raise ValueError('manual_run_closed')
        if self.runtime_begun and self.verification:self.verification.charge(None,0)
    def elapsed(self):return max(0.,self.now()-self.data['model_started_at']) if self.runtime_begun else 0.
    def begin_runtime(self):
        with self.lock:
            self.check()
            if self.runtime_begun:return
            if self.verification:self.verification.charge('cohorts',1)
            self.runtime_begun=True;self.data.update(state='RUNNING',runtime_in_flight=True,model_started_at=self.now());self.save()
    def release(self,seconds):
        with self.lock:
            self.check()
            if not self.runtime_begun or not math.isfinite(seconds) or not 0<seconds<=self.profile['max_chunk_seconds']:raise ValueError('manual_publication_bounds')
            if self.verification:self.verification.charge('media_seconds',seconds)
            self.data['media_seconds']+=seconds;self.save()
    def load(self,kind,worker):
        with self.lock:
            self.check()
            if not self.runtime_begun or worker not in ('asr-0','image-0','image-1') or not worker.startswith(kind+'-') or worker in self.loaded:raise ValueError('manual_worker_reservation')
            self.loaded.add(worker);self.data['model_loads']+=1
            return self.ticket('load',kind,worker)
    def ticket(self,stage,kind,worker):
        ident=uuid.uuid4().hex
        self.data['tickets'].append(dict(id=ident,kind=stage,lane=kind,worker=worker,cohort=self.data['cohort']))
        self.save();return ident
    def start(self,kind,worker=None):
        with self.lock:
            self.check()
            if not self.runtime_begun or kind not in self.active or len(self.active[kind])>=self.profile['heavy_'+kind]:raise ValueError('lane_concurrency_limit')
            if self.verification:self.verification.charge(kind+'_attempts',1)
            self.data[kind+'_attempts']+=1
            ident=self.ticket('inference',kind,worker);self.active[kind].add(ident)
            self.data['active']={k:len(v) for k,v in self.active.items()};self.save();return ident
    def finish(self,kind,ticket):
        with self.lock:
            self.active[kind].remove(ticket)
            self.data['tickets']=[t for t in self.data['tickets'] if t['id']!=ticket]
            self.data['active']={k:len(v) for k,v in self.active.items()};self.save()
    def fail(self,reason,native=False):
        with self.lock:
            self.data.update(state='FAILED',failure_reason=self.data.get('failure_reason') or str(reason)[:160],
                             native_failure_this_task=bool(native or self.data['native_failure_this_task']));self.save()
    def view(self):
        with self.lock:return {**self.data,'model_elapsed_seconds':self.elapsed()}
    def close(self):
        with self.lock:
            self.data.update(state='FAILED' if self.data.get('failure_reason') else 'CLOSED',runtime_in_flight=False);self.save()


class ManualAssets(Assets):
    def import_stream(self,*args):
        ident=super().import_stream(*args)
        try:
            registry={k:dict(sha256=v['sha256'],file=v['path'].name) for k,v in self.items.items()}
            target=self.root.parent/'assets.json';pending=target.with_suffix('.pending')
            pending.write_text(json.dumps(registry),encoding='utf-8');os.replace(pending,target)
            return ident
        except BaseException:
            self.items.pop(ident)['path'].unlink();raise


class ManualModels(ResourceModels):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.status=LocalAnalyzers(self.model_root).status
        if importlib.util.find_spec('av') is None:
            self.status={k:dict(state='BLOCKED_missing_PyAV') for k in ('asr','image')}
    def record_worker(self,pid):
        # Each file is independently owned; no lost-update shared list.
        (self.area.parent/f'worker-{pid}.json').write_text(json.dumps({'pid':pid}),encoding='utf-8')


class ManualController(IsolatedController):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs,start_workers=False)
        self.analysis_id=None;self.pending_start=None
    def command(self,data,session):
        with self.lock:
            action=data.get('action')
            if action in ('play','restart'):
                self.budget.check()
                # Validate the selected source and epoch before starting any model.
                if session!=self.session or data.get('epoch')!=self.epoch or data.get('asset_id')!=self.asset_id:raise ValueError('stale_source')
                asset=self.assets.get(self.asset_id)
                if asset['decoder']!='ready':raise ValueError('解析準備不足: '+asset['decoder'])
                if not self.workers_started:
                    if any(v['state']!='ready_to_load' for v in self.models.status.values()):
                        raise ValueError('解析準備不足: '+json.dumps(self.models.status,ensure_ascii=False))
                    self.budget.begin_runtime();self.start_workers()
                if any(v['state']=='failed' for v in self.lanes.values()):raise ValueError('解析準備失敗・状態詳細を確認してください')
                if not self.ready_models():
                    self.pending_start=action;self.status='preparing';return self.view()
            previous=self.epoch
            result=super().command(data,session)
            if self.epoch!=previous:self.analysis_id=uuid.uuid4().hex
            if action not in ('play','restart','release'):self.pending_start=None
            result.update(analysis_id=self.analysis_id)
            return result
    def ready_models(self):
        return len([x for x in self.models.executors if 'ready' in x.info])==3 if hasattr(self.models,'executors') else all(v['state']!='loading' for v in self.lanes.values())
    def view(self):
        result=super().view()
        result.update(mode=MODE,settings_version=self.profile['settings_version'],settings_sha256=self.budget.settings_sha256,
                      analysis_id=getattr(self,'analysis_id',None),real_analysis_available=not any(v['state'].startswith('BLOCKED') for v in self.models.status.values()),
                      preparation_complete=self.ready_models() if self.workers_started else False,
                      retention_policy='temporary_content_deleted_on_exit',jev='OFF')
        return result
