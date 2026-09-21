"""Additional map route; one C0 state and no real media/model runtime."""
import argparse
import json
import os
import uuid
from pathlib import Path
from .server import App, Handler, FixtureServer
from .isolation import Boundary
from .lifecycle import serve_controlled
from .map_projection import DemoProvider

ROOT=Path(__file__).resolve().parents[2]
UI=ROOT/'ui/conversation_ecology'


class MapApp(App):
    def __init__(self):
        super().__init__()
        self.provider=DemoProvider()
        self.map_draws=set()
        self.store=None
        self.coordinator=None
        self.accepting=True

    def map_state(self):
        from .pipeline_projection import project_pipeline
        view=self.provider.snapshot()
        observation=view.pop('_pipeline_observation',None)
        try:view['pipeline']=project_pipeline(view,observation)
        except Exception:
            # Display metadata must not change a successful business operation.
            view['pipeline']=dict(schema='pipeline-view-v1',namespace=view['session_id'],session_id=view['session_id'],
                epoch=view.get('epoch',1),cursor=view['cursor'],mode=view['mode'],records=[],telemetry_gap=True,
                error='pipeline_projection_unavailable',retention=view.get('retention','available'))
        from .mass_projection import project_mass
        try:project_mass(view)
        except (KeyError,TypeError,ValueError):
            view['mass_status']='invalid_reference'
            for node in view['nodes']:node['mass']=dict(status='invalid_reference',value=None)
        return dict(view=view, c0=self.state(), map_draw_count=len(self.map_draws))

    def map_action(self, command):
        with self.lock:
            if not self.accepting:raise ValueError('STOPPED')
            action=command.get('action')
            if action=='mass_start':
                from .mass_fixture import MassFixture
                self.provider=MassFixture(dense=command.get('dense',False));return self.map_state()
            if action=='mass_step':
                from .mass_fixture import MassFixture
                if not isinstance(self.provider,MassFixture):raise ValueError('select_mass_fixture')
                self.provider.set_stage(command.get('stage'));return self.map_state()
            if action=='context_start':
                from .context.store import ContextStore
                from .context.provider import ContextProvider
                from .hearing.coordinator import HearingCoordinator
                if self.store is None:self.store=ContextStore(ROOT/'artifacts/context_fixture'/uuid.uuid4().hex/'state.sqlite')
                self.coordinator=HearingCoordinator(self.store,'ctx-'+uuid.uuid4().hex[:10],scope=command.get('scope','participant-a'))
                self.coordinator.start(command.get('explicit',False));self.provider=ContextProvider(self.coordinator)
                return self.map_state()
            if action in {'reply','background','correct','ack','context_resend','replay','reported_context','change_preference'}:
                if not self.coordinator or self.provider.__class__.__name__!='ContextProvider':raise ValueError('select_context_fixture')
                c=self.coordinator;result=None
                if action=='reply':result=c.reply(command.get('text'),command.get('reply_id'))
                elif action=='background':c.background()
                elif action=='correct':result=c.correct()
                elif action=='reported_context':result=c.reported_context()
                elif action=='change_preference':result=c.change_preference()
                elif action=='ack':
                    if command.get('session_id')!=c.session:raise ValueError('stale_session')
                    c.output.acknowledge(c.session,c.scope,command['commit_id'],command.get('evidence'))
                elif action=='context_resend':c.output.deliver(c.session,c.scope)
                elif action=='replay':result=c.store.replay(c.session,c.scope)
                return dict(self.map_state(),operation=result)
            if action=='demo':
                if not isinstance(self.provider,DemoProvider):self.provider=DemoProvider()
                delta=self.provider.start(command.get('dense',False))
            elif action=='step':
                if not isinstance(self.provider,DemoProvider):raise ValueError('DEMO専用操作です')
                delta=self.provider.step(command['kind'])
            elif action=='map_draw':
                v=self.provider.view
                if command.get('session_id')!=v['session_id'] or command.get('cursor',-1)>v['cursor']: raise ValueError('stale_view')
                self.map_draws.add((v['session_id'],command['cursor']))
                if self.store and v['mode']=='CONTEXT_FIXTURE':self.store.notify('map:'+v['session_id'],command['cursor'])
                return self.map_state()
            else: raise ValueError('unknown_map_action')
            return dict(self.map_state(),delta=delta)

    def sv_stub(self):
        return dict(status='未接続・この起動はモデルなし',released_position=0.,epoch=0,queued=0,active=False,
                    models={'ASR':'NOT_RUN','image':'NOT_RUN'},assets=[],asset_id=None,
                    events=[],profile={'chunk_seconds':2,'profile':'NOT_CONNECTED'},
                    budget={'media_seconds':0.,'asr_attempts':0,'image_attempts':0},mode='NOT_CONNECTED')


class MapHandler(Handler):
    def send_header(self,keyword,value):
        if keyword=='Content-Security-Policy' and self.path in {'/map','/map-layout-check.html'}:
            value=value.replace("frame-ancestors 'none'", "frame-src 'self'; frame-ancestors 'self'")
        return super().send_header(keyword,value)
    def do_GET(self):
        if not self.allowed(): return self.send(403,{'error':'origin_denied'})
        if self.path=='/api/map':
            if not self.server.app.accepting:return self.send(503,{'error':'STOPPED'})
            with self.server.app.lock: return self.send(200,self.server.app.map_state())
        if self.path=='/api/sv/state': return self.send(200,self.server.app.sv_stub())
        if self.path in {'/map','/map.html'}:
            html=(UI/'map.html').read_text(encoding='utf-8')
            sv=(UI/'saved-video.html').read_text(encoding='utf-8')
            # Same component, one player; real upload explicitly disabled in fixture mode.
            sv=sv.replace('<input id="sv-file"','<input disabled id="sv-file"')
            sv=sv.replace('選んだ動画をこのPC内だけで解析します。観測まで接続・文脈反映は後段。下の会話は独立したC0合成デモです。','既存SV01操作コンポーネントです。この起動は未接続stubで、素材取込み・解析を行いません。実SV01の入口と成果は保持しています。')
            from .player_template import dock_player
            return self.send(200,dock_player(html,sv).encode(),'text/html; charset=utf-8')
        assets={'/map.js':'text/javascript','/map-state.js':'text/javascript','/map-camera.js':'text/javascript','/map-layout.js':'text/javascript','/map-renderer.js':'text/javascript','/map.css':'text/css',
                '/pipeline.js':'text/javascript','/pipeline-view.js':'text/javascript','/pipeline.css':'text/css','/map-mass.js':'text/javascript',
                '/map-layout-check.html':'text/html','/map-layout-check.js':'text/javascript','/map-layout-check.css':'text/css',
                '/saved-video.js':'text/javascript','/saved-video.css':'text/css','/process-history.js':'text/javascript'}
        if self.path in assets: return self.send(200,(UI/self.path[1:]).read_bytes(),assets[self.path]+'; charset=utf-8')
        if self.path in {'/','/c0'}:
            html=(UI/'index.html').read_text(encoding='utf-8').replace('<body>','<body><p><a href="/map">統合マップへ戻る（同じC0状態）</a></p>')
            return self.send(200,html.encode(),'text/html; charset=utf-8')
        return super().do_GET()

    def do_POST(self):
        if not self.server.app.accepting:return self.send(503,{'error':'STOPPED'})
        if self.path.startswith('/api/sv/'):
            return self.send(400 if self.allowed(True) else 403,{'error':'NOT_CONNECTED: 実入力・解析はこのfixtureでは未接続'})
        if self.path!='/api/map/action': return super().do_POST()
        if not self.allowed(True): return self.send(403,{'error':'origin_or_token_denied'})
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=32000: raise ValueError('request_size')
            data=json.loads(self.rfile.read(size),parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite_json')))
            if not isinstance(data,dict): raise ValueError('request_object')
            return self.send(200,self.server.app.map_action(data))
        except (ValueError,TypeError,KeyError) as error: return self.send(400,{'error':str(error)})


class MapServer(FixtureServer):
    def shutdown(self):
        with self.app.lock:
            self.app.accepting=False
            if self.app.store:
                self.app.store.stop()
                print(json.dumps(dict(stage='context_saved',pid=os.getpid(),pending_outbox=self.app.store.db.execute('SELECT COUNT(*) FROM notification_outbox WHERE delivered=0').fetchone()[0],writer_active=self.app.store.db.in_transaction)),flush=True)
        super().shutdown()
    def server_close(self):
        super().server_close()
        if self.app.store and not self.app.store.closed:
            self.app.store.close()
            print(json.dumps(dict(stage='context_closed',pid=os.getpid(),writer_active=False,projection_worker='synchronous_no_thread',http_workers_joined=True)),flush=True)


def make_map_server(port=0):
    server=MapServer(('127.0.0.1',port),MapHandler); server.app=MapApp(); return server


def main():
    parser=argparse.ArgumentParser(description='MAP-CTX-01 synthetic only')
    parser.add_argument('--port',type=int,default=0)
    parser.add_argument('--control-stdin',action='store_true',required=True)
    args=parser.parse_args()
    from .context.boundary import ContextBoundary
    boundary=ContextBoundary(); boundary.install()
    server=make_map_server(args.port); server.app.boundary=boundary
    serve_controlled(server)
