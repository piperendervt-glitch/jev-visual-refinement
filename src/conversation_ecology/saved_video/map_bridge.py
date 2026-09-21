"""Explicit shared map/SV application; document capabilities own publication."""
import hmac
import json
import os
import secrets
import threading
import time
from urllib.parse import urlsplit, parse_qs
from ..map_server import MapApp, MapHandler, UI
from ..context.observations import ObservationStore, ObservationBridge, ObservationProvider
from .server import SVServer, SVHandler


class PublicationOwner:
    def __init__(self,controller,clock=time.monotonic):
        self.controller=controller;self.clock=clock;self.token=None;self.deadline=0.;self.lock=threading.RLock()
    def expire(self):
        with self.lock:
            if self.token and self.clock()>=self.deadline:
                with self.controller.lock:self.controller.invalidate('owner_expired',self.controller.position)
                self.token=None
    def claim(self):
        with self.lock:
            self.expire()
            if self.token:raise ValueError('publication_owned_by_another_view')
            self.token=secrets.token_hex(32);self.deadline=self.clock()+6
            return self.token
    def check(self,token):
        with self.lock:
            self.expire()
            if not self.token or not token or not hmac.compare_digest(self.token,token):raise ValueError('publication_owner_required')
            self.deadline=self.clock()+6
    def release(self,token):
        with self.lock:
            self.check(token)
            with self.controller.lock:self.controller.invalidate('view_released',self.controller.position)
            self.token=None


class BridgeApp(MapApp):
    def __init__(self,path,integration_run,grant,boundary=None,synthetic=False):
        super().__init__()
        if boundary:self.boundary=boundary
        self.store=ObservationStore(path,synthetic=synthetic)
        self.bridge=ObservationBridge(self.store,integration_run,grant)
        self.sv=None;self.owner=None
        self.history_projection={}
        self.provider=ObservationProvider(self)
    def expire_observations(self):
        with self.sv.lock:
            try:
                with self.store.lock:self.store.ensure_available()
            except ValueError as error:
                if str(error)!='retention_expired':raise
                if self.sv.status!='retention_expired':self.sv.invalidate('retention_expired',self.sv.position)
                self.sv.events.clear();self.sv.observation_error='retention_expired'
                self.bridge.last_result=None
                return True
        return False
    def map_action(self,command):
        if command.get('action')=='observations':
            with self.lock:
                if not self.accepting:raise ValueError('STOPPED')
                self.provider=ObservationProvider(self);return self.map_state()
        result=super().map_action(command)
        if command.get('action')=='map_draw' and isinstance(self.provider,ObservationProvider):
            try:self.store.notify('observation-map:'+self.engine.session_id,command['cursor'])
            except ValueError as error:
                if str(error)!='retention_expired':raise
        return result


class BridgeHandler(SVHandler,MapHandler):
    def end_headers(self):
        if self.path in ('/map','/map.html'):
            self.send_header('Set-Cookie','SV01='+self.server.app.token+'; HttpOnly; SameSite=Strict; Path=/')
        super().end_headers()
    def do_GET(self):
        if not self.allowed():return self.send(403,{'error':'origin_denied'})
        self.server.app.expire_observations()
        route=urlsplit(self.path)
        if route.path in ('/api/sv/history','/api/sv/history/detail'):
            if not self.media_allowed():return self.send(403,{'error':'session_denied'})
            from .history import history_page,history_detail
            try:
                query=parse_qs(route.query)
                number=int(query.get('cursor' if route.path.endswith('/detail') else 'after',['0'])[0])
                if not 0<=number<2**53:raise ValueError('history_cursor')
                run=query.get('run',[None])[0]
                data=history_detail(self.server.app,run,number) if route.path.endswith('/detail') else history_page(self.server.app,number,run)
                return self.send(200,data)
            except (ValueError,TypeError):return self.send(400,{'error':'history_query'})
        if self.path in ('/map','/map.html'):
            app=self.server.app
            try:owner=app.owner.claim()
            except ValueError:owner=''
            html=(UI/'map.html').read_text(encoding='utf-8')
            html=html.replace('</head>',f'<meta name="sv-owner" content="{owner}"><meta name="sv-bridge" content="1"></head>')
            from ..player_template import dock_player
            html=dock_player(html,(UI/'saved-video.html').read_text(encoding='utf-8'))
            html=html.replace('モデルなし・未接続stub · この起動の実入力・実解析なし／専用入口はREADME参照',
                '保存動画の共通記録 · 未評価・意味採用/三場 NOT_CONNECTED')
            html=html.replace('実Jev / モデル / 作業 未接続','実Jev / 実デバイス / 作業 未接続 · 保存動画ローカル観測')
            html=html.replace('<button id="media-open">','<button id="observations">保存動画の観測へ</button><button id="media-open">')
            html=html.replace('<label for="sv-assets">','<button id="sv-owner-claim">入力操作を引き継ぐ</button><p id="sv-owner-status"></p><label for="sv-assets">')
            return self.send(200,html.encode(),'text/html; charset=utf-8')
        if self.path in ('/','/c0'):return MapHandler.do_GET(self)
        if self.path=='/api/sv/state':
            if not self.media_allowed():return self.send(403,{'error':'session_denied'})
            token=self.headers.get('X-SV-Owner')
            if token:
                try:self.server.app.owner.check(token)
                except ValueError:pass
            else:self.server.app.owner.expire()
            data=self.server.sv.view();data['publication_owner']=bool(token and self.server.app.owner.token==token)
            with self.server.app.store.lock:
                data['expires_at']=float(self.server.app.store.db.execute("SELECT value FROM meta WHERE key='expires'").fetchone()[0])
            data['bridge']=dict(status='NOT_RECORDED' if self.server.sv.observation_error else 'connected',
                last_result=self.server.app.bridge.last_result,mode='SYNTHETIC_OBSERVATION' if self.server.app.store.synthetic else 'LOCAL_OBSERVATION_NO_JEV')
            return self.send(200,data)
        return super().do_GET()
    def do_POST(self):
        if self.path.startswith('/api/sv/'):
            if not self.server.app.accepting:return self.send(503,{'error':'STOPPED'})
            if not self.allowed(True) or self.headers.get('X-SV-Session')!=self.server.app.engine.session_id:
                return self.send(403,{'error':'origin_token_session_denied'})
            if self.server.app.expire_observations():return self.send(410,{'error':'retention_expired'})
            try:
                if self.path=='/api/sv/owner':return self.send(200,{'owner':self.server.app.owner.claim()})
                if self.path=='/api/sv/owner/release':
                    self.server.app.owner.release(self.headers.get('X-SV-Owner'));return self.send(200,{'released':True})
                self.server.app.owner.check(self.headers.get('X-SV-Owner'))
            except ValueError as error:return self.send(409,{'error':str(error)})
        return super().do_POST()


class BridgeServer(SVServer):
    def shutdown(self):
        self.app.accepting=False
        return super().shutdown()
    def server_close(self):
        # SV closes HTTP workers, then joins analysis and saves its final state.
        super().server_close()
        if hasattr(self,'app') and self.app.store and not self.app.store.closed:
            self.app.store.stop()
            print(json.dumps(dict(stage='observation_saved',pid=os.getpid(),writer_active=self.app.store.db.in_transaction)),flush=True)
            self.app.store.close()
            print(json.dumps(dict(stage='context_closed',pid=os.getpid(),http_workers_joined=True,worker_alive=self.sv.worker.is_alive())),flush=True)
