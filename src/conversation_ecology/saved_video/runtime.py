"""Bounded metadata diagnostics; configure before importing native runtimes."""
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time

CACHE_KEYS = {'CUDA_CACHE_PATH':'cuda', 'HF_HOME':'hf', 'TORCH_HOME':'torch',
              'TMP':'temp', 'TEMP':'temp', 'TMPDIR':'temp', 'XDG_CACHE_HOME':'xdg',
              'TRITON_CACHE_DIR':'triton', 'NUMBA_CACHE_DIR':'numba'}


def configure_cache(root):
    for key, name in CACHE_KEYS.items():
        path = root / name
        path.mkdir(parents=True, exist_ok=True)
        os.environ[key] = str(path)
    os.environ.update(CUDA_CACHE_DISABLE='1', CUDA_CACHE_MAXSIZE=str(16*1024*1024),
                      HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1')
    return {key:os.environ[key] for key in (*CACHE_KEYS, 'CUDA_CACHE_DISABLE', 'CUDA_CACHE_MAXSIZE',
                                          'HF_HUB_OFFLINE','TRANSFORMERS_OFFLINE','HF_HUB_DISABLE_TELEMETRY')}


def cache_sizes(root):
    result = {}
    for name in sorted(set(CACHE_KEYS.values())):
        sizes = []
        for path in (root/name).rglob('*'):
            try:
                if path.is_file(): sizes.append(path.stat().st_size)
            except FileNotFoundError:
                pass
        result[name] = dict(files=len(sizes), bytes=sum(sizes))
    return result


def source_identity(root, profile):
    paths = sorted([* (root/'src/conversation_ecology/saved_video').glob('*.py'),
                    * (root/'ui/conversation_ecology').glob('saved-video.*'),
                    root/'scripts/sv01_saved_video.py', root/'scripts/sv01_verify_run.py', profile])
    if profile.name in ('sv01_map_m1.json','sv01_long_l1.json','sv01_resource_r1.json'):
        paths+=list((root/'src/conversation_ecology/context').glob('*.py'))
        paths+=list((root/'ui/conversation_ecology').glob('map*'))
        paths+=list((root/'ui/conversation_ecology').glob('pipeline*'))
        paths += [root/'src/conversation_ecology/map_server.py',root/'src/conversation_ecology/map_projection.py']
        if profile.name=='sv01_resource_r1.json':paths += [root/'scripts/sv01_resource_worker.py',root/'src/conversation_ecology/pipeline_projection.py']
    return {str(p.relative_to(root)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


class RuntimeEvidence:
    def __init__(self, root, cache, identity, environment):
        self.root, self.cache = root, cache
        self.lock, self.done = threading.Lock(), threading.Event()
        self.stream = (root/'runtime.jsonl').open('w', encoding='utf-8')
        self.sample('before_native_import', source_sha256=identity, environment=environment,
                    executable=sys.executable, app_module=__file__, pid=os.getpid())
        self.thread = threading.Thread(target=self.monitor, name='sv01-cache-observer', daemon=True)
        self.thread.start()

    def sample(self, stage, **values):
        with self.lock:
            self.stream.write(json.dumps(dict(stage=stage, at=time.time(), cache=cache_sizes(self.cache), **values))+'\n')
            self.stream.flush()

    def monitor(self):
        while not self.done.wait(1):
            self.sample('processing_sample')

    def close(self):
        self.done.set()
        self.thread.join()
        self.sample('after_model_cleanup')
        self.stream.close()
