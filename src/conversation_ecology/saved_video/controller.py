"""Release gate and one bounded worker shared by audio and image analysis."""
import math
import queue
import threading
import time
import uuid
from .media import SavedVideoSource


class Controller:
    def __init__(self, assets, budget, models, profile, decoder=None, observer=None, *, start_worker=True):
        self.observer=observer;self.observation_error=None
        self.assets, self.budget, self.models, self.profile = assets, budget, models, profile
        self.decoder = decoder or SavedVideoSource(profile)
        self.lock = threading.RLock()
        self.run_id = uuid.uuid4().hex
        self.session = None
        self.asset_id = None
        self.epoch = self.cursor = 0
        self.position = 0.
        self.status = 'unselected'
        self.events = []
        self.closed = False
        self.active = False
        self.last_tick = time.monotonic()
        self.last_image_end = -float('inf')
        self.jobs = queue.Queue(maxsize=profile['queue_capacity'])
        self.worker = threading.Thread(target=self.work, name='sv01-analysis', daemon=False)
        if start_worker:self.worker.start()

    def event(self, kind, **values):
        self.cursor += 1
        event=dict(cursor=self.cursor, kind=kind, run_id=self.run_id,
                   session_id=self.session, epoch=self.epoch, asset_id=self.asset_id, **values)
        if self.profile.get('profile')=='SV01-LONG-L1':
            event['recorded_at']=time.time()  # One wall clock for release/start/result/save diagnostics.
        if self.observer:
            try:
                result=self.observer(event)
                if result:event['common_record']=result
            except Exception as error:
                self.observation_error=str(error)[:160]
                event['common_record']={'status':'NOT_RECORDED','reason':self.observation_error}
        self.events.append(event)
        # Reserve a final bounded tail for errors/control; do not admit after capacity.
        self.events = self.events[-self.profile['max_events']:]

    def invalidate(self, reason, position=0.):
        self.epoch += 1
        self.position = position
        self.last_image_end = -float('inf')
        self.status = reason
        while True:
            try:
                job = self.jobs.get_nowait()
            except queue.Empty:
                break
            self.event('cancelled_before_start', input_epoch=job[2]['epoch'])
            self.jobs.task_done()
        self.event('control', reason=reason, position=position, running_completion_pending=self.active)

    def command(self, data, session):
        with self.lock:
            if self.closed:
                raise ValueError('closed')
            if self.session != session:
                self.invalidate('session_changed')
                self.session, self.asset_id = session, None
            action = data.get('action')
            if action == 'select':
                asset = self.assets.get(data.get('asset_id'))
                self.invalidate('selected')
                self.asset_id = asset['id']
                self.event('asset_selected',has_audio=asset.get('has_audio'),duration=asset.get('duration'))
            else:
                if data.get('epoch') != self.epoch or data.get('asset_id') != self.asset_id:
                    raise ValueError('stale_source')
                if action == 'seek':
                    position = self.number(data.get('position'))
                    duration = self.assets.get(self.asset_id).get('duration')
                    if duration is not None and position > duration:
                        raise ValueError('seek_past_eof')
                    self.invalidate('paused', position)
                elif action in ('play', 'restart'):
                    self.budget.check()
                    if action == 'restart':
                        if self.status != 'ended' or self.active or not self.jobs.empty():
                            raise ValueError('eof_not_drained')
                        self.invalidate('restarted', 0.)
                    elif self.status in ('eof_draining', 'ended'):
                        raise ValueError('eof_restart_required')
                    if self.assets.get(self.asset_id)['decoder'] != 'ready':
                        self.status = 'preview_only_decoder_BLOCKED'
                    else:
                        self.status = 'playing'
                    self.last_tick = time.monotonic()
                    self.event('control',reason=self.status)
                elif action in ('pause', 'eof'):
                    self.status = 'paused' if action == 'pause' else 'eof_draining' if self.active or not self.jobs.empty() else 'ended'
                    self.event('control', reason=self.status)
                elif action == 'stop':
                    self.invalidate('stopped', self.position)
                elif action == 'release':
                    self.release(data)
                else:
                    raise ValueError('unknown_sv_action')
            return self.view()

    @staticmethod
    def number(value):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError('invalid_position')
        return float(value)

    def release(self, data):
        if self.observation_error:raise ValueError('observation_save_failed:'+self.observation_error)
        if self.status != 'playing':
            raise ValueError('not_playing')
        start, end = self.number(data.get('start')), self.number(data.get('end'))
        now = time.monotonic()
        if abs(start-self.position) > 0.002 or not 0 < end-start <= self.profile['max_chunk_seconds']:
            raise ValueError('noncontinuous_release')
        long_attempt = self.profile.get('profile') == 'SV01-LONG-L1'
        asset = self.assets.get(self.asset_id)
        if end > asset['duration']+0.001:
            raise ValueError('past_eof')
        # L1 includes failed publication attempts. Reserve before clock/queue
        # admission, and never refund a rejected interval or charge success twice.
        if long_attempt:
            self.budget.release(end-start)
        if end-start > now-self.last_tick+0.15:
            if long_attempt:
                self.event('gap_not_analyzed', interval=[start, end], reason='playback_clock_jump', budget_debited=True)
            raise ValueError('playback_clock_jump')
        if len(self.events) >= self.profile['max_events']-16:
            self.status = 'event_capacity'
            if long_attempt:
                self.event('gap_not_analyzed', interval=[start, end], reason=self.status, budget_debited=True)
            raise ValueError(self.status)
        if self.jobs.full():
            self.status = 'backpressure'
            self.event('gap_not_analyzed', interval=[start, end], reason='queue_full',
                       **({'budget_debited': True} if long_attempt else {}))
            raise ValueError('queue_full_pause_required')
        if not long_attempt:
            self.budget.release(end-start)
        envelope = dict(run_id=self.run_id, session_id=self.session, epoch=self.epoch, available_cursor=self.cursor+1)
        self.jobs.put_nowait((asset, (start, end), envelope))
        self.event('input_released', interval=[start, end])
        self.position, self.last_tick = end, now

    def current(self, envelope):
        return not self.closed and self.epoch == envelope['epoch'] and self.session == envelope['session_id']

    def work(self):
        while True:
            try:
                job = self.jobs.get(timeout=0.1)
            except queue.Empty:
                if self.closed:
                    return
                continue
            asset, interval, envelope = job
            try:
                with self.lock:
                    if not self.current(envelope):
                        self.event('cancelled_before_start', input_epoch=envelope['epoch'])
                        continue
                    self.active = True
                packet = self.decoder.decode(asset, *interval, envelope)
                with self.lock:
                    self.event('common_input', provenance=packet.provenance, current=self.current(envelope))
                for kind in ('asr', 'image'):
                    with self.lock:
                        if not self.current(envelope):
                            self.event('cancelled_before_start', analyzer=kind, input_epoch=envelope['epoch'])
                            break
                        if kind == 'asr' and len(packet.pcm) == 0 or kind == 'image' and packet.frame is None:
                            self.event('analysis_not_run', analyzer=kind, reason='input_unavailable', provenance=packet.provenance)
                            continue
                        if kind == 'image' and interval[1]-self.last_image_end < self.profile['image_interval_seconds']:
                            self.event('analysis_not_run', analyzer=kind, reason='sampling_policy', provenance=packet.provenance)
                            continue
                        if not self.models.available(kind):
                            self.event('analysis_blocked', analyzer=kind, reason=self.models.status[kind], provenance=packet.provenance)
                            continue
                        self.budget.start(kind)
                        if kind == 'image':
                            self.last_image_end = interval[1]
                        self.event('analysis_started', analyzer=kind, provenance=packet.provenance)
                    result = self.models.infer(kind, packet)
                    with self.lock:
                        self.event('analysis_completed', analyzer=kind, result=result, provenance=packet.provenance,
                                   current=self.current(envelope), model_elapsed_seconds=self.budget.elapsed())
            except Exception as error:
                with self.lock:
                    self.event('analysis_failed', input_epoch=envelope['epoch'], reason=str(error)[:160], current=self.current(envelope))
                    if self.current(envelope):
                        self.status = 'analysis_failed'
            finally:
                with self.lock:
                    self.active = False
                self.jobs.task_done()
                with self.lock:
                    if self.status == 'eof_draining' and self.jobs.empty():
                        self.status = 'ended'
                        self.event('tail_completed')

    def view(self):
        with self.lock:
            return dict(run_id=self.run_id, session_id=self.session, epoch=self.epoch, asset_id=self.asset_id,
                        status=self.status, observation_error=self.observation_error, released_position=self.position, active=self.active, queued=self.jobs.qsize(),
                        assets=self.assets.public(), events=[{**e, 'current_at_arrival':e['current'],
                          'current':e['current'] and self.current(e['provenance'])} if 'current' in e and 'provenance' in e else dict(e)
                          for e in self.events], models=self.models.status,
                        budget=self.budget.view(), profile=self.profile, context='observation_only_no_field_update')

    def stop_admission(self):
        with self.lock:
            if not self.closed:
                self.invalidate('stopped', self.position)
                self.closed = True

    def close(self):
        self.stop_admission()
        self.worker.join()  # A running native inference is not falsely declared cancelled.
        self.models.close()
        self.assets.close()
        self.budget.close()
