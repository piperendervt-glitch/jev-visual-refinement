"""Normal manual Viewer, authenticated existing bridge and isolated real workers."""
import argparse
import json
import os
import sys
import threading
import time
from .manual import ROOT,AREA,MODE,settings,ManualBudget,ManualAssets,ManualModels,ManualController,Verification
from .map_bridge import BridgeServer,BridgeHandler,BridgeApp,PublicationOwner
from .server import SVBoundary
from .runtime import configure_cache
from .media import plain_path
from ..lifecycle import serve_controlled


class ManualHandler(BridgeHandler):
    def send(self,status,data,content_type='application/json'):
        if self.path in ('/map','/map.html') and isinstance(data,bytes):
            page=data.decode('utf-8').replace('保存動画の共通記録 · 未評価・意味採用/三場 NOT_CONNECTED',
                '通常利用・ローカル解析 / Jev OFF · 設定v1 · 終了時に一時内容を削除')
            page=page.replace('保存動画でテスト','保存動画をローカル解析')
            page=page.replace('>再生 / 再開</button>','>解析して再生 / 再開</button>')
            page=page.replace('>入力を停止</button>','>解析停止</button>')
            page=page.replace('<h3>ローカル解析の状態</h3>','<p>アプリ終了：起動コンソールでEnter。タブを閉じるだけでは終了しません。初回のモデル準備中も操作できます。</p><h3>ローカル解析の状態</h3>')
            data=page.encode('utf-8')
        return super().send(status,data,content_type)


class ManualServer(BridgeServer):
    def server_close(self):
        super().server_close()
        budget=self.sv.budget
        summary={k:v for k,v in budget.data.items() if k not in ('tickets','failure_reason')}
        summary.update(failed=bool(budget.data.get('failure_reason')),worker_count=len(self.sv.models.executors),
                       workers=[{k:e.info.get(k) for k in ('pid','exit_code','actual_exit_code','actual_pid_gone','closed')} for e in self.sv.models.executors],
                       database_closed=self.app.store.closed,forced_cleanup=False)
        (self.evidence_root.parent/'run-summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--area',required=True);parser.add_argument('--verification',action='store_true')
    parser.add_argument('--player-history-verification',action='store_true')
    args=parser.parse_args();area=plain_path(args.area).resolve()
    if args.verification and args.player_history_verification:parser.error('verification namespaces are exclusive')
    if area.parent!=AREA or not area.is_dir():raise ValueError('manual_area_boundary')
    profile,sha=settings();content=area/'content';content.mkdir(exist_ok=False)
    configure_cache(content/'cache')
    boundary=SVBoundary();sys.addaudithook(boundary.guard)
    verification=Verification(ROOT/'artifacts/sv01/manual-local-verification/usage.json') if args.verification else None
    if args.player_history_verification:
        verification_path=ROOT/'artifacts/sv01/player-history-verification/usage.json'
        verification_path.parent.mkdir(parents=True,exist_ok=True)
        verification=Verification(verification_path)
    budget=ManualBudget(content/'usage.json',profile,sha,verification)
    # Decoder imports before the blocking Windows stdin reader; no model import/inference.
    try:import av,numpy
    except ImportError:pass
    assets=ManualAssets(content/'media',profile)
    server=ManualServer(('127.0.0.1',0),ManualHandler)
    server.app=BridgeApp(content/'context/state.sqlite',area.name,MODE,boundary)
    server.app.store.capacity_bytes=profile['observation_bytes'];server.app.store.record_limit=profile['observation_records']
    server.upload_lock=threading.Lock();server.evidence_root=content
    models=ManualModels(ROOT,content,(ROOT/profile['model_root_relative']).resolve(),profile,'D',budget,boundary)
    server.sv=ManualController(assets,budget,models,profile,observer=server.app.bridge)
    server.app.sv=server.sv;server.app.owner=PublicationOwner(server.sv)
    stopped=threading.Event()
    def capacity_watch():
        while not stopped.wait(2):
            try:
                cache=other=0
                for p in content.rglob('*'):
                    if p.is_file():
                        if p.is_relative_to(content/'media'):continue
                        if p.is_relative_to(content/'cache'):cache+=p.stat().st_size
                        else:other+=p.stat().st_size
                reason=('cache_capacity' if cache>=profile['cache_bytes'] else 'content_capacity' if other>=profile['content_bytes'] else
                        'retention_expired' if time.time()-assets.created>=profile['retention_seconds'] else None)
                if reason:budget.fail(reason)
                budget.check()
            except FileNotFoundError:continue
            except ValueError as error:
                with server.sv.lock:
                    if not server.sv.closed:
                        server.sv.invalidate('manual_admission_stopped',server.sv.position)
                        server.sv.observation_error=str(error)[:160]
                return
    monitor=threading.Thread(target=capacity_watch,name='manual-capacity',daemon=False);monitor.start()
    print(json.dumps(dict(stage='runtime_configured',mode=MODE,settings_version=1,settings_sha256=sha,pid=os.getpid())),flush=True)
    try:serve_controlled(server)
    finally:stopped.set();monitor.join()
