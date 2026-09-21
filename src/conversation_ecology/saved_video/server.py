"""SV01 mode augments the C0 Viewer, with authenticated opaque media delivery."""
import argparse
from http.cookies import SimpleCookie
import hmac
import json
import mimetypes
import os
from pathlib import Path
import re
import sys
import threading
from urllib.parse import urlsplit, parse_qs
from ..server import App, Handler, FixtureServer, UI
from ..lifecycle import serve_controlled
from .budget import Budget
from .controller import Controller
from .media import Assets, plain_path
from .models import LocalAnalyzers
from .runtime import configure_cache, source_identity, RuntimeEvidence
from .grants import ROUTES, Q1, M1, L1, R1, resolve_route

ROOT = Path(__file__).resolve().parents[3]


class SVBoundary:
    def __init__(self):
        self.denied = dict(external_socket=0, secret_read=0, model_import=0, subprocess=0)
        self.allowed_process_commands=set()  # Empty for all legacy modes.

    def guard(self, event, args):
        if event in ('socket.connect', 'socket.getaddrinfo', 'socket.bind'):
            address = args[0] if event == 'socket.getaddrinfo' else args[1]
            host = address[0] if isinstance(address, tuple) else address
            if host not in ('127.0.0.1', '::1', 'localhost'):
                self.denied['external_socket'] += 1
                raise PermissionError('SV_external_network_denied')
        if event == 'open' and isinstance(args[0], (str, bytes, os.PathLike)):
            path = os.fsdecode(args[0]).replace('\\', '/').lower()
            flags = args[2] if len(args) > 2 else 0
            if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC):
                resolved = Path(os.fsdecode(args[0])).absolute()
                if not resolved.is_relative_to(ROOT/'artifacts/sv01') and path != 'nul':
                    raise PermissionError('SV_write_outside_owned_area')
            if any(p.startswith('.env') or p in ('private', 'runs') for p in path.split('/')) or path.startswith('//./'):
                self.denied['secret_read'] += 1
                raise PermissionError('SV_secret_or_device_denied')
        if event == 'import' and args[0].split('.')[0] in ('sounddevice', 'pyaudio', 'ollama', 'openai', 'anthropic'):
            self.denied['model_import'] += 1
            raise PermissionError('SV_device_external_inference_denied')
        if event in ('subprocess.Popen', 'os.system', 'os.spawn', 'os.exec'):
            if event=='subprocess.Popen' and len(args)>1:
                command=tuple(args[1]) if isinstance(args[1],(list,tuple)) else args[1]
                if command in self.allowed_process_commands:return
            self.denied['subprocess'] += 1
            raise PermissionError('SV_child_process_denied')


class SVHandler(Handler):
    def send_header(self, keyword, value):
        if keyword == 'Content-Security-Policy':
            value += "; media-src 'self'"
        super().send_header(keyword, value)

    def end_headers(self):
        if self.path == '/':
            super().send_header('Set-Cookie', 'SV01=' + self.server.app.token + '; HttpOnly; SameSite=Strict; Path=/')
        super().end_headers()

    def media_allowed(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get('Cookie', ''))
            return self.allowed() and 'SV01' in cookie and hmac.compare_digest(cookie['SV01'].value, self.server.app.token)
        except Exception:
            return False

    def do_GET(self):
        if not self.allowed():
            return self.send(403, {'error': 'origin_denied'})
        if self.path=='/api/sv/resource-status' and hasattr(self.server.sv,'lanes'):
            sv=self.server.sv
            with sv.lock:
                data=dict(control_ready=True,position=sv.position,status=sv.status,
                    lanes={k:dict(queued=len(v['queue']),active=v['active'],state=v['state'],completed=v['completed']) for k,v in sv.lanes.items()})
            return self.send(200,data)
        if self.path == '/':
            page = (UI/'index.html').read_text(encoding='utf-8')
            page = page.replace('</head>', '<script defer src="/saved-video.js"></script><link rel="stylesheet" href="/saved-video.css"></head>')
            page = page.replace('<main>', '<main>' + (UI/'saved-video.html').read_text(encoding='utf-8'))
            return self.send(200, page.encode(), 'text/html; charset=utf-8')
        if self.path in ('/saved-video.js', '/saved-video.css'):
            return self.send(200, (UI/self.path[1:]).read_bytes(), 'text/javascript' if self.path.endswith('.js') else 'text/css')
        if self.path == '/api/sv/state':
            if not self.media_allowed():
                return self.send(403, {'error': 'session_denied'})
            return self.send(200, self.server.sv.view())
        if self.path.startswith('/media/'):
            if not self.media_allowed():
                return self.send(403, {'error': 'session_denied'})
            try:
                url = urlsplit(self.path)
                ident = url.path.removeprefix('/media/')
                query = parse_qs(url.query)
                if query.get('session') != [self.server.app.engine.session_id]:
                    raise ValueError('stale_session')
                asset = self.server.sv.assets.get(ident)
                size = asset['size']
                start, end, status = 0, size-1, 200
                value = self.headers.get('Range')
                if value:
                    match = re.fullmatch(r'bytes=(\d+)-(\d*)', value)
                    if not match:
                        return self.send(416, {'error': 'range'})
                    start = int(match[1])
                    end = min(size-1, int(match[2])) if match[2] else size-1
                    if not 0 <= start <= end < size:
                        return self.send(416, {'error': 'range'})
                    status = 206
                self.send_response(status)
                self.send_header('Content-Type', mimetypes.guess_type(str(asset['path']))[0] or 'video/mp4')
                self.send_header('Content-Length', str(end-start+1))
                self.send_header('Accept-Ranges', 'bytes')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                if status == 206:
                    self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
                self.end_headers()
                with asset['path'].open('rb') as source:
                    source.seek(start)
                    remaining = end-start+1
                    while remaining:
                        data = source.read(min(remaining, 1024*1024))
                        if not data:
                            break
                        self.wfile.write(data)
                        remaining -= len(data)
                return
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                return
            except ValueError as error:
                return self.send(400, {'error': str(error)})
        return super().do_GET()

    def do_POST(self):
        if self.path not in ('/api/sv/upload', '/api/sv/action'):
            if self.path == '/api/action' and self.allowed(True):
                # C0 session change also revokes the saved-source epoch immediately.
                super().do_POST()
                with self.server.sv.lock:
                    session = self.server.app.engine.session_id
                    if self.server.sv.session != session:
                        self.server.sv.invalidate('session_changed')
                        self.server.sv.session, self.server.sv.asset_id = session, None
                return
            return super().do_POST()
        if not self.allowed(True):
            return self.send(403, {'error': 'origin_or_token_denied'})
        try:
            if self.headers.get('X-SV-Session') != self.server.app.engine.session_id:
                raise ValueError('stale_session')
            if self.server.sv.closed:
                raise ValueError('stopped')
            size = int(self.headers.get('Content-Length', '0'))
            if self.path == '/api/sv/upload':
                if not self.server.upload_lock.acquire(blocking=False):
                    raise ValueError('upload_busy')
                try:
                    self.connection.settimeout(10)
                    ident = self.server.sv.assets.import_stream(self.rfile, size, self.headers.get('X-SV-Suffix', ''))
                    if self.server.sv.profile.get('manual_local'):
                        from urllib.parse import unquote
                        name=unquote(self.headers.get('X-SV-Name',''))[:240]
                        self.server.sv.assets.items[ident]['display_name']=name.replace('\\','/').split('/')[-1]
                    with self.server.sv.lock:
                        asset=self.server.sv.assets.get(ident)
                        self.server.sv.event('asset_registered',registered_asset_id=ident,duration=asset.get('duration'),has_audio=asset.get('has_audio'))
                    return self.send(200, {'asset_id': ident})
                finally:
                    self.server.upload_lock.release()
            if not 0 < size <= 4096:
                raise ValueError('request_size')
            data = json.loads(self.rfile.read(size), parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite_json')))
            if not isinstance(data, dict):
                raise ValueError('request_object')
            result = self.server.sv.command(data, self.server.app.engine.session_id)
            return self.send(200, result)
        except (ValueError, KeyError, TypeError, TimeoutError) as error:
            return self.send(400, {'error': str(error)[:160]})


class SVServer(FixtureServer):
    def shutdown(self):
        if hasattr(self, 'runtime_evidence'):
            self.runtime_evidence.sample('stop_accepted_before_cleanup')
        self.sv.stop_admission()
        return super().shutdown()

    def server_close(self):
        super().server_close()
        if hasattr(self, 'sv'):
            self.sv.stop_admission()
            self.sv.worker.join()
            evidence = getattr(self, 'evidence_root', ROOT/'artifacts/sv01')/('final-'+self.sv.run_id+'.json')
            snapshot=self.sv.audit_snapshot() if hasattr(self.sv,'audit_snapshot') else self.sv.view()
            evidence.write_text(json.dumps(snapshot,ensure_ascii=False,allow_nan=False),encoding='utf-8')
            self.sv.close()
            if hasattr(self, 'runtime_evidence'):
                self.runtime_evidence.close()
            print(json.dumps(dict(stage='sv_cleanup',pid=os.getpid(),sv_run_id=self.sv.run_id,
                                  worker_alive=self.sv.worker.is_alive(),queue_remaining=self.sv.jobs.qsize(),
                                  temporary_media_removed=not self.sv.assets.root.exists(),
                                  model_elapsed_seconds=self.sv.budget.elapsed())),flush=True)


def main():
    parser = argparse.ArgumentParser(description='SV01 saved video only; no devices, Jev or downloads')
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--model-root', type=Path)
    parser.add_argument('--profile', type=Path)
    parser.add_argument('--selected-manifest', type=Path,
                        help='Explicit approved file paths and SHA256, for re-registering previously selected assets')
    parser.add_argument('--diagnostics', action='store_true')
    parser.add_argument('--grant', choices=list(ROUTES))
    parser.add_argument('--map-bridge',action='store_true',help='Explicit integrated map with the MAP-M1 grant')
    parser.add_argument('--resource-candidate',choices=('A','B','C','D'))
    parser.add_argument('--resource-phase',choices=('BENCH_ONLY','LIVE'),default='LIVE')
    parser.add_argument('--resource-lanes',choices=('both','asr','image'),default='both')
    args = parser.parse_args()
    if args.map_bridge != (args.grant in (M1,L1,R1)):
        raise ValueError('map_bridge_requires_M1_or_L1_grant')
    if (args.grant==R1) != bool(args.resource_candidate):raise ValueError('resource_candidate_requires_R1')
    if args.resource_lanes!='both' and not (args.grant==R1 and args.resource_phase=='BENCH_ONLY'):
        raise ValueError('single_lane_benchmark_only')
    route = resolve_route(ROOT, args.grant, args.profile)
    args.profile, profile = route['profile_path'], route['profile']
    sys.dont_write_bytecode = True
    root = plain_path(ROOT/'artifacts/sv01')
    root.mkdir(parents=True, exist_ok=True)
    import uuid
    # Validate approval and acquire the common lease before any model/native work.
    from .resource_budget import ResourceBudget
    budget_class=ResourceBudget if args.grant==R1 else Budget
    budget = budget_class(route['ledger'], profile, parent=route['parent'], grant=args.grant, root=ROOT)
    if args.grant==R1:budget.select_candidate(args.resource_candidate,args.resource_phase)
    evidence_root = route['evidence']/uuid.uuid4().hex
    cache = evidence_root/'cache'
    environment = configure_cache(cache)
    identity = source_identity(ROOT, args.profile)
    boundary = SVBoundary()
    sys.addaudithook(boundary.guard)
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TRANSFORMERS_OFFLINE'] = '1'
    os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
    # Stable campaign location, never a per-run budget reset.
    diagnostics = RuntimeEvidence(evidence_root, cache, identity, environment)
    # Fault-only trace, with a descriptor kept alive by the owner through exit.
    # Periodic watchdog dumps are deliberately not part of the acceptance setup.
    import faulthandler
    faulthandler.enable(file=sys.stderr, all_threads=True)
    print(json.dumps(dict(stage='runtime_configured', pid=os.getpid(), grant=args.grant, evidence_root=str(evidence_root),
                          source_sha256=identity, environment=environment)), flush=True)
    if args.grant in (L1,R1):
        # L1 includes all native preparation, including registered-asset probing.
        budget.begin_runtime()
        diagnostics.sample('model_runtime_begin',budget=budget.view())
        print(json.dumps(dict(stage='model_runtime_begin',started_at=budget.data['model_started_at'],
                              admission_seconds=profile['admission_seconds'])),flush=True)
    assets = Assets(evidence_root/'media' if args.grant==R1 else root/('media-'+uuid.uuid4().hex), profile)
    if args.selected_manifest:
        import hashlib
        manifest = json.loads(args.selected_manifest.read_text(encoding='utf-8'))
        for entry in manifest:
            if 'expires_at' in entry:
                import time
                if time.time() >= entry['expires_at']:
                    raise ValueError('selected_original_expired')
            path = plain_path(entry['path'])
            with path.open('rb') as stream:
                if hashlib.file_digest(stream,'sha256').hexdigest() != entry['sha256']:
                    raise ValueError('selected_original_changed')
                stream.seek(0)
                assets.import_stream(stream,path.stat().st_size,path.suffix.lower())
    if args.map_bridge:
        from .map_bridge import BridgeServer,BridgeHandler,BridgeApp,PublicationOwner
        server=BridgeServer(('127.0.0.1',args.port),BridgeHandler)
        server.app=BridgeApp(evidence_root/'context'/'state.sqlite',evidence_root.name,args.grant,boundary)
    else:
        server = SVServer(('127.0.0.1', args.port), SVHandler)
        server.app = App(boundary)
    server.upload_lock = threading.Lock()
    server.evidence_root = evidence_root
    server.runtime_evidence = diagnostics
    # Native imports while a Windows CRT stdin read is pending can stall DLL
    # initialization (observed NumPy stack). Finish them before serve_controlled.
    try:
        import numpy
        import av
    except ImportError:
        pass  # UI remains usable with an explicit missing-decoder state.
    if args.grant==R1:
        from .resource_process import ResourceModels
        from .resource_controller import IsolatedController
        models=ResourceModels(ROOT,evidence_root,args.model_root,profile,args.resource_candidate,budget,boundary)
        lanes=('asr','image') if args.resource_lanes=='both' else (args.resource_lanes,)
        server.sv=IsolatedController(assets,budget,models,profile,observer=server.app.bridge,enabled_lanes=lanes)
        server.app.sv=server.sv;server.app.owner=PublicationOwner(server.sv)
        try:serve_controlled(server)
        finally:faulthandler.disable()
        return
    models = LocalAnalyzers(args.model_root)
    try:
        if any(models.available(k) for k in ('asr','image')):
            if not budget.runtime_begun:
                budget.begin_runtime()
                diagnostics.sample('model_runtime_begin', budget=budget.view())
                print(json.dumps(dict(stage='model_runtime_begin', started_at=budget.data['model_started_at'],
                                      admission_seconds=profile.get('admission_seconds',profile['model_wall_seconds']))),flush=True)
            models.prepare_runtime()
            diagnostics.sample('after_native_init')
    except Exception as error:
        for kind in models.status:
            models.status[kind] = {'state':'BLOCKED_runtime_prepare', 'reason':str(error)[:160]}
    server.sv = Controller(assets, budget, models, profile,observer=server.app.bridge if args.map_bridge else None)
    if args.map_bridge:
        server.app.sv=server.sv;server.app.owner=PublicationOwner(server.sv)
    try:
        serve_controlled(server)
    finally:
        faulthandler.disable()


if __name__ == '__main__':
    main()
