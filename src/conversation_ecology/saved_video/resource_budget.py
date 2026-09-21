"""One owner, short durable reservations for the explicitly approved R1 cohort."""
import time
import uuid
import json
import os
from .budget import Budget


class ResourceBudget(Budget):
    def save(self):
        # Windows readers can briefly deny DELETE sharing. Keep one durable
        # reservation and retry only its atomic rename, never reserve again.
        temporary=self.path.with_suffix('.pending')
        with temporary.open('w',encoding='utf-8') as stream:
            json.dump(self.data,stream,allow_nan=False);stream.flush();os.fsync(stream.fileno())
        for attempt in range(11):
            try:os.replace(temporary,self.path);return
            except PermissionError:
                if attempt==10:raise
                time.sleep(.01)

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.data.setdefault('model_loads',0)
        self.data.setdefault('candidates',[])
        self.data.setdefault('tickets',[])
        self.active={'asr':set(),'image':set()}
        self.phase='BENCH_ONLY'
        self.save()

    def check(self):
        if self.data.get('failure_reason'):raise ValueError('resource_grant_failed')
        super().check()

    def select_candidate(self,name,phase):
        with self.lock:
            self.check()
            if name not in self.profile['candidates'] or phase not in ('BENCH_ONLY','LIVE'):
                raise ValueError('unapproved_candidate')
            names=self.data.setdefault('candidates',[])
            if name not in names:
                if len(names)>=self.profile['candidate_limit']:raise ValueError('candidate_limit')
                names.append(name)
            self.phase=phase;self.data['current_candidate']=name;self.data['phase']=phase;self.save()

    def reserve_final(self,key,amount):
        reserve=self.profile['final_reserve'].get(key,0) if self.phase=='BENCH_ONLY' else 0
        if self.data[key]+amount>self.profile[key]-reserve:raise ValueError('final_reserve_'+key)

    def release(self,seconds):
        with self.lock:
            self.reserve_final('media_seconds',seconds)
            super().release(seconds)

    def load(self,kind,worker):
        with self.lock:
            self.check()
            if not self.runtime_begun:raise ValueError('runtime_not_started')
            if self.data['model_loads']>=self.profile['model_loads']:raise ValueError('model_load_limit')
            self.data['model_loads']+=1
            ticket=dict(id=uuid.uuid4().hex,kind='load',lane=kind,worker=worker,at=self.now(),phase=self.phase,cohort=self.data['cohort'])
            self.data['tickets'].append(ticket);self.save();return ticket['id']

    def begin_runtime(self):
        with self.lock:
            begun=self.runtime_begun
            super().begin_runtime()
            if not begun:self.data['cohort']=uuid.uuid4().hex;self.save()

    def start(self,kind,worker=None):
        with self.lock:
            if kind not in self.active:raise ValueError('unknown_analyzer')
            if len(self.active[kind])>=self.profile['heavy_'+kind]:raise ValueError('lane_concurrency_limit')
            self.reserve_final(kind+'_attempts',1)
            super().start(kind)
            ticket=uuid.uuid4().hex;self.active[kind].add(ticket)
            self.data['tickets'].append(dict(id=ticket,kind='inference',lane=kind,worker=worker,at=self.now(),phase=self.phase,cohort=self.data['cohort']))
            self.data['active']={k:len(v) for k,v in self.active.items()};self.save()
            return ticket

    def finish(self,kind,ticket):
        with self.lock:
            if ticket not in self.active[kind]:raise ValueError('unknown_or_duplicate_ticket')
            self.active[kind].remove(ticket)
            self.data['active']={k:len(v) for k,v in self.active.items()};self.save()

    def fail(self,reason,native=False):
        with self.lock:
            self.data.update(state='FAILED',failure_reason=self.data.get('failure_reason') or str(reason)[:160],
                             native_failure_this_task=bool(native or self.data.get('native_failure_this_task')))
            self.save()

    def close(self):
        failed=self.data.get('failure_reason')
        super().close()
        if failed:
            self.data['state']='FAILED';self.save()
