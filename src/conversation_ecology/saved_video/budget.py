"""Crash-conservative campaign counters, independent of run/session/epoch."""
import json
import hashlib
import os
from pathlib import Path
import threading
import time


class Budget:
    def __init__(self, path, profile, now=time.time, parent=None, grant=None, root=None):
        from .grants import Q1, M1, L1, R1, resolve_route, validate_q1
        self.q1 = grant in (Q1,M1,L1,R1)
        if grant is not None:
            route = resolve_route(root, grant)
            if Path(path).resolve() != route['ledger'].resolve() or Path(parent).resolve() != route['parent'].resolve() or profile != route['profile']:
                raise ValueError('grant_route_mismatch')
        self.path = Path(path)
        self.profile = profile
        self.now = now
        self.lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # One owner for this campaign. Never silently reset a stale lock.
        self.lease = Path(parent or self.path).with_suffix('.lock')
        self.runtime_begun = False
        self.handle = self.lease.open('x', encoding='utf-8')
        self.handle.write(str(os.getpid()))
        self.handle.flush()
        try:
            if self.q1 and (not self.path.exists() or self.path.with_suffix('.pending').exists()):
                raise ValueError('grant_missing_or_partial_write')
            self.data = json.loads(self.path.read_text()) if self.path.exists() else {
                'profile': profile, 'media_seconds': 0., 'asr_attempts': 0,
                'image_attempts': 0, 'model_started_at': None}
            if self.data['profile'] != profile:
                raise ValueError('campaign_profile_changed')
            if self.q1:
                validate_q1(self.path, self.data, profile, grant)
            if parent:
                raw = Path(parent).read_bytes()
                identity = dict(sha256=hashlib.sha256(raw).hexdigest(), usage=json.loads(raw))
                if self.data.get('parent', identity) != identity:
                    raise ValueError('parent_campaign_changed')
                self.data['parent'] = identity
                self.data['grant'] = grant or 'SV01-F1'
            if self.q1:
                self.check()
            self.save()
        except BaseException:
            self.handle.close()
            self.lease.unlink()
            raise

    def save(self):
        temporary = self.path.with_suffix('.pending')
        with temporary.open('w', encoding='utf-8') as stream:
            json.dump(self.data, stream, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.path)

    def elapsed(self):
        start = self.data['model_started_at']
        return max(0., self.now() - start) if start is not None else 0.

    def check(self):
        for key in ('media_seconds', 'asr_attempts', 'image_attempts'):
            if self.data[key] >= self.profile[key]:
                raise ValueError('budget_' + key)
        if self.data['model_started_at'] is not None and self.elapsed() >= self.profile['model_wall_seconds']:
            raise ValueError('budget_model_wall_seconds')
        if self.data['model_started_at'] is not None and self.elapsed() >= self.profile.get('admission_seconds', float('inf')):
            raise ValueError('budget_admission_seconds')

    def release(self, seconds):
        with self.lock:
            if self.q1 and not self.runtime_begun:
                raise ValueError('runtime_not_started')
            self.check()
            if seconds <= 0 or self.data['media_seconds'] + seconds > self.profile['media_seconds']:
                raise ValueError('budget_media_seconds')
            self.data['media_seconds'] += seconds
            self.save()  # Debit before publication; failed decode is not refunded.

    def start(self, kind):
        with self.lock:
            if kind not in ('asr', 'image'):
                raise ValueError('unknown_analyzer')
            if self.q1 and not self.runtime_begun:
                raise ValueError('runtime_not_started')
            self.check()
            self.data[kind + '_attempts'] += 1
            if self.data['model_started_at'] is None:
                self.data['model_started_at'] = self.now()
            self.save()  # Includes model loading, failures and cancellations.

    def begin_runtime(self):
        with self.lock:
            self.check()
            if self.runtime_begun:
                return
            count = self.data.get('runtime_processes', 0)
            if count >= self.profile.get('runtime_processes', float('inf')):
                raise ValueError('budget_runtime_processes')
            self.data['runtime_processes'] = count + 1
            if self.data['model_started_at'] is None:
                self.data['model_started_at'] = self.now()
            self.runtime_begun = True
            if self.q1:
                self.data.update(state='RUNNING', runtime_in_flight=True)
            self.save()

    def view(self):
        with self.lock:
            return {**self.data, 'model_elapsed_seconds': self.elapsed()}

    def close(self):
        if hasattr(self, 'data'):
            if self.q1:
                self.data.update(state='PAUSED' if self.data['model_started_at'] is not None else 'READY', runtime_in_flight=False,
                                 outer_verification_pending=self.runtime_begun)
            self.data['last_closed_at'] = self.now()
            self.data['last_closed_model_elapsed_seconds'] = self.elapsed()
            self.save()
        self.handle.close()
        self.lease.unlink()
