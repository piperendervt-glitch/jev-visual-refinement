"""Independent admission, FIFO execution and publication for audio and vision."""
from collections import deque
import json
import threading
import time
from .controller import Controller


class WorkerGroup:
    def __init__(self,controller):self.controller=controller
    def join(self):
        for worker in self.controller.workers:
            if worker.ident is not None:worker.join()
    def is_alive(self):return any(t.is_alive() for t in self.controller.workers)


class QueueGroup:
    def __init__(self,controller):self.controller=controller
    def qsize(self):return sum(len(v['queue']) for v in self.controller.lanes.values())
    def empty(self):return self.qsize()==0


class IsolatedController(Controller):
    def __init__(self,assets,budget,models,profile,observer=None,*,enabled_lanes=('asr','image'),start_workers=True):
        super().__init__(assets,budget,models,profile,observer=observer,start_worker=False)
        self.enabled_lanes=enabled_lanes
        self.lanes={k:dict(queue=deque(),active=0,queued_seconds=0.,queued_bytes=0,
                          accepted=0,started=0,completed=0,cancelled=0,rejected=0,failed=0,
                          oldest=None,last_interval=None,last_latency=None,state='loading') for k in ('asr','image')}
        self.condition=threading.Condition(self.lock);self.workers=[]
        self.jobs=QueueGroup(self);self.worker=WorkerGroup(self)
        self.play_anchor=(0.,time.monotonic());self.metrics=[]
        for kind in enabled_lanes:
            count=1 if kind=='asr' else models.config['image_workers']
            for i in range(count):
                thread=threading.Thread(target=self.lane_work,args=(kind,i),name=f'resource-{kind}-{i}',daemon=False)
                self.workers.append(thread)
        self.workers_started=False
        if start_workers:self.start_workers()

    def start_workers(self):
        if not self.workers_started:
            self.workers_started=True
            for thread in self.workers:thread.start()

    def event(self,kind,**values):
        values.setdefault('recorded_at',time.time());values.setdefault('monotonic',time.monotonic())
        super().event(kind,**values)

    def command(self,data,session):
        with self.lock:
            result=super().command(data,session)
            if data.get('action') in ('play','restart') and self.status=='playing':
                self.play_anchor=(self.position,time.monotonic())
            return result

    def invalidate(self,reason,position=0.):
        self.epoch+=1;self.position=position;self.last_image_end=-float('inf');self.status=reason
        for kind,lane in self.lanes.items():
            while lane['queue']:
                job=lane['queue'].popleft();lane['cancelled']+=1
                self.event('cancelled_before_start',analyzer=kind,input_epoch=job['envelope']['epoch'],
                           interval=job['interval'],input_cursor=job['envelope']['available_cursor'],reason=reason)
            lane['queued_seconds']=0.;lane['queued_bytes']=0
        self.event('control',reason=reason,position=position,running_completion_pending=self.active)
        self.condition.notify_all()

    def release(self,data):
        if self.observation_error:raise ValueError('observation_save_failed:'+self.observation_error)
        if self.status!='playing':raise ValueError('not_playing')
        start,end=self.number(data.get('start')),self.number(data.get('end'))
        if abs(start-self.position)>.002 or not 0<end-start<=self.profile['max_chunk_seconds']:
            raise ValueError('noncontinuous_release')
        asset=self.assets.get(self.asset_id)
        if end>asset['duration']+.001:raise ValueError('past_eof')
        self.budget.release(end-start)  # One attempt before all fallible lane admission.
        now=time.monotonic();anchor,at=self.play_anchor
        if end>anchor+(now-at)+.15:
            self.event('gap_not_analyzed',interval=[start,end],reason='playback_clock_jump',budget_debited=True)
            raise ValueError('playback_clock_jump')
        if not self.profile.get('rolling_history') and len(self.events)>=self.profile['max_events']-32:
            self.status='event_capacity';self.event('gap_not_analyzed',interval=[start,end],reason=self.status,budget_debited=True)
            raise ValueError(self.status)
        audio=self.lanes['asr'];seconds=end-start;pcm_bytes=int(seconds*16000*4)
        if 'asr' in self.enabled_lanes and (len(audio['queue'])>=self.profile['audio_queue_chunks'] or
                audio['queued_seconds']+seconds>self.profile['audio_queue_seconds'] or audio['queued_bytes']+pcm_bytes>self.profile['audio_queue_bytes']):
            audio['rejected']+=1;audio['state']='audio_overload';self.status='audio_overload'
            self.event('gap_not_analyzed',analyzer='asr',interval=[start,end],reason='audio_overload',budget_debited=True)
            raise ValueError('audio_overload')
        envelope=dict(run_id=self.run_id,session_id=self.session,epoch=self.epoch,available_cursor=self.cursor+1)
        self.event('input_released',interval=[start,end],phase=self.budget.phase)
        def enqueue(kind,size):
            lane=self.lanes[kind];job=dict(asset=asset,interval=[start,end],envelope=envelope.copy(),
                                          released_at=now,queued_at=time.monotonic(),size=size)
            lane['queue'].append(job);lane['queued_seconds']+=seconds;lane['queued_bytes']+=size;lane['accepted']+=1
            self.event('analysis_queued',analyzer=kind,input_cursor=envelope['available_cursor'],interval=[start,end])
        if 'asr' in self.enabled_lanes:enqueue('asr',pcm_bytes)
        if 'image' in self.enabled_lanes and end-self.last_image_end>=self.profile['image_interval_seconds']:
            self.last_image_end=end  # Sampling by published media, never by completion speed.
            image=self.lanes['image'];size=len(json.dumps(dict(asset_id=self.asset_id,interval=[start,end],envelope=envelope)).encode())
            if len(image['queue'])>=self.profile['image_queue_descriptors'] or image['queued_bytes']+size>self.profile['image_queue_bytes']:
                image['rejected']+=1;image['state']='vision_backlog_full'
                self.event('analysis_not_run',analyzer='image',interval=[start,end],reason='vision_backlog_full')
            else:enqueue('image',size)
        self.position,self.last_tick=end,now;self.condition.notify_all()

    def lane_work(self,kind,index):
        executor=None
        try:
            executor=self.models.open(kind,index)
            with self.lock:
                self.lanes[kind]['state']='ready';self.event('lane_ready',analyzer=kind,worker=index)
            while True:
                with self.condition:
                    lane=self.lanes[kind]
                    while not self.closed and not lane['queue']:self.condition.wait(.2)
                    if self.closed:return
                    job=lane['queue'].popleft();a,b=job['interval'];lane['queued_seconds']=max(0,lane['queued_seconds']-(b-a));lane['queued_bytes']-=job['size']
                    if not self.current(job['envelope']):
                        lane['cancelled']+=1;self.event('cancelled_before_start',analyzer=kind,input_epoch=job['envelope']['epoch'],interval=job['interval']);continue
                    lane['active']+=1;lane['state']='decoding';self.active=True
                    self.event('decode_started',analyzer=kind,input_cursor=job['envelope']['available_cursor'],interval=job['interval'])
                ticket=None;pending=False
                try:
                    decoded=executor.decode(job);pending=True;provenance=decoded['provenance']
                    with self.lock:
                        self.event('common_input',provenance=provenance,current=self.current(job['envelope']),analyzer=kind)
                        valid=self.current(job['envelope'])
                    if not valid or not decoded['input_available']:
                        executor.cancel();pending=False
                        with self.lock:
                            lane['cancelled']+=not valid
                            self.event('analysis_not_run' if valid else 'cancelled_before_start',analyzer=kind,provenance=provenance,
                                       reason='input_unavailable' if valid else 'old_epoch')
                        continue
                    # Only this vision executor waits for resource headroom. Audio/control never join it.
                    while kind=='image' and not self.models.image_headroom():
                        with self.condition:
                            lane['state']='resource_deferred'
                            if not self.current(job['envelope']):break
                            self.condition.wait(.2)
                    with self.lock:
                        if not self.current(job['envelope']):
                            executor.cancel();pending=False;lane['cancelled']+=1
                            self.event('cancelled_before_start',analyzer=kind,provenance=provenance,reason='old_epoch');continue
                        ticket=self.budget.start(kind,worker=f'{kind}-{index}');lane['started']+=1;lane['state']='running'
                        self.event('analysis_started',analyzer=kind,provenance=provenance,ticket=ticket)
                    response=executor.infer(ticket);pending=False;returned=time.monotonic()
                    with self.lock:
                        self.event('analysis_completed',analyzer=kind,provenance=provenance,result=response['result'],
                                   current=self.current(job['envelope']),ticket=ticket)
                        saved=time.monotonic();lane['completed']+=1;lane['last_interval']=job['interval'];lane['last_latency']=saved-job['released_at']
                        self.metrics.append(dict(lane=kind,epoch=job['envelope']['epoch'],interval=job['interval'],
                            released=job['released_at'],queued=job['queued_at'],decode_start=decoded['decode_start'],decode_end=decoded['decode_end'],
                            infer_start=response['infer_start'],infer_end=response['infer_end'],returned=returned,saved=saved,
                            worker_before=response.get('before'),worker_after=response.get('after')))
                        if self.profile.get('metric_history'):self.metrics=self.metrics[-self.profile['metric_history']:]
                except Exception as error:
                    if pending:
                        try:executor.cancel()
                        except Exception:pass
                    with self.lock:
                        lane['failed']+=1;lane['state']='failed'
                        self.event('analysis_failed',analyzer=kind,input_epoch=job['envelope']['epoch'],interval=job['interval'],reason=str(error)[:160])
                    self.budget.fail(str(error),native=getattr(error,'native',False))
                    return
                finally:
                    if ticket:self.budget.finish(kind,ticket)
                    with self.condition:
                        lane['active']-=1;self.active=any(v['active'] for v in self.lanes.values())
                        if lane['state'] not in ('failed','vision_backlog_full'):lane['state']='active' if lane['active'] else 'ready'
                        if self.status=='eof_draining' and not self.active and self.jobs.empty():
                            self.status='ended';self.event('tail_completed')
                        self.condition.notify_all()
        except Exception as error:
            with self.lock:
                self.lanes[kind]['state']='failed';self.event('lane_failed',analyzer=kind,reason=str(error)[:160])
            self.budget.fail(str(error),native=getattr(error,'native',False))
        finally:
            if executor:
                try:executor.close()
                except Exception as error:self.budget.fail(str(error),native=getattr(error,'native',False))

    def view(self):
        with self.lock:
            now=time.monotonic()
            # Keep control/UI payload bounded; complete events are retained for the final audit.
            events=[{**e,'current_at_arrival':e['current'],'current':e['current'] and self.current(e['provenance'])}
                    if 'current' in e and 'provenance' in e else dict(e) for e in self.events[-64:]]
            budget={k:v for k,v in self.budget.view().items() if k not in ('tickets','parent','profile','prior_ledgers')}
            result=dict(run_id=self.run_id,session_id=self.session,epoch=self.epoch,asset_id=self.asset_id,
                        status=self.status,observation_error=self.observation_error,released_position=self.position,active=self.active,
                        queued=self.jobs.qsize(),assets=self.assets.public(),events=events,event_total=len(self.events),
                        visible_event_limit=64,models=self.models.status,budget=budget,profile=self.profile,context='observation_only_no_field_update')
            result['lanes']={k:{**{key:val for key,val in v.items() if key!='queue'},'queued':len(v['queue']),
                'oldest_media':v['queue'][0]['interval'][0] if v['queue'] else None,
                'oldest_wait_seconds':now-v['queue'][0]['queued_at'] if v['queue'] else 0} for k,v in self.lanes.items()}
            result['control_ready']=True;result['phase']=self.budget.phase
            return result

    def audit_snapshot(self):
        with self.lock:return {**self.view(),'events':list(self.events),'resource_metrics':list(self.metrics)}

    def close(self):
        self.stop_admission();self.worker.join()
        try:self.models.close()
        finally:
            try:self.assets.close()
            finally:self.budget.close()
