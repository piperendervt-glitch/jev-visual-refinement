"""SM01-12 synthetic boundaries; no real models or campaign mutation."""
import copy
import http.client
import json
from pathlib import Path
import re
import tempfile
import threading
import unittest
from unittest.mock import patch
from test_saved_video import ROOT,PROFILE,FakeModels,FakeDecoder,FakeAssets
from conversation_ecology.context.observations import ObservationStore,ObservationBridge,ObservationProvider
from conversation_ecology.saved_video.map_bridge import BridgeApp,BridgeServer,BridgeHandler,PublicationOwner
from conversation_ecology.saved_video.budget import Budget
from conversation_ecology.saved_video.controller import Controller
from conversation_ecology.saved_video.media import Assets
from conversation_ecology.saved_video import grants


def event(cursor=1,kind='common_input',epoch=1,run='source-run',session='s',interval=None):
    interval=interval or [0,2]
    p=dict(run_id=run,session_id=session,epoch=epoch,available_cursor=10,asset_id='opaque',asset_sha256='synthetic-sha',
           source_kind='saved_video',interval=interval,media_origin_s=0,frame={'root':'physical-v','pts':24,'time_base':[1,12]},
           audio={'root':'physical-a','samples':32000,'sample_rate':16000,'status':'decoded','mapping':[]})
    e=dict(cursor=cursor,kind=kind,run_id=run,session_id=session,epoch=epoch,provenance=p,current=True)
    if kind=='analysis_completed':e.update(analyzer='asr',result={'transcript_original':'synthetic text <script>do not execute</script>'})
    return e


class Records(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.now=[1000.]
        self.s=ObservationStore(Path(self.tmp.name)/'state.sqlite',clock=lambda:self.now[0])
    def tearDown(self):
        if not self.s.closed:self.s.close()
        self.tmp.cleanup()
    def put(self,e,**v):return self.s.accept(e,integration_run='integration',grant='TEST_ONLY',acquired_at=1000.,expires_at=87400.,**v)
    def test_SM03_L4_identity_revision_cutoff_and_arrival_cursor(self):
        a=self.put(event());b=self.put(event(2,'analysis_completed'))
        v=self.s.snapshot('s','recorded-media').data();self.assertEqual(len(v['layers']['L4']),2)
        x=v['items'][b['id']];self.assertEqual(x['revision'],1);self.assertEqual(x['value']['source_cursor'],2)
        self.assertEqual(x['value']['source_refs'],[a['id']]);self.assertEqual(x['source_cutoff'],2)
        self.assertEqual(self.s.snapshot('s','recorded-media',cursor=a['cursor']).data()['read_set'],{a['id']:1})
        self.assertFalse(self.s.snapshot('s','recorded-media',cutoff=1).data()['items'])
    def test_SM04_duplicate_conflict_and_distinct_runs(self):
        original=event();a=self.put(original);self.assertEqual(self.put(original)['id'],a['id'])
        other=copy.deepcopy(original);other['provenance']['interval']=[0,3]
        with self.assertRaisesRegex(ValueError,'payload_conflict'):self.put(other)
        self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM observation_conflicts').fetchone()[0],1)
        self.put(event(run='other'));self.assertEqual(len(self.s.snapshot('s','recorded-media').data()['items']),2)
        self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM observation_roots').fetchone()[0],2)
    def test_SM04_revisit_is_new_result_not_new_physical_root(self):
        self.put(event());self.put(event(2,epoch=2));self.put(event(3,interval=[2,4]))
        self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM observation_roots').fetchone()[0],2)
        self.assertEqual({x['revision'] for x in self.s.snapshot('s','recorded-media').data()['items'].values()},{1})
    def test_SM05_old_arrival_retained_without_current_adoption(self):
        e=event();e['current']=False;r=self.put(e)
        self.assertFalse(self.s.item('s','recorded-media',r['id'])['value']['current_at_arrival'])
        self.assertFalse(self.s.snapshot('other','recorded-media').data()['items'])
    def test_SM06_unassessed_no_semantic_commit_score_or_permission(self):
        self.put(event());self.put(event(2,'analysis_completed'))
        for item in self.s.snapshot('s','recorded-media').data()['items'].values():
            v=item['value'];self.assertEqual(v['assessment'],'pending_evaluation');self.assertEqual(v['authority'],'denied')
            self.assertIsNone(v['independent_evidence_weight']);self.assertNotIn('confidence',v);self.assertNotIn('score',v)
        for table in ('context_commits','response_commits','acknowledgements','proposals'):
            self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0],0)
    def test_SM09_real_expiry_erases_content_projection_outbox_and_replay(self):
        self.put(event());self.put(event(2,'analysis_completed'));self.s.register_projection(self.s.snapshot('s','recorded-media'))
        self.now[0]=87400.;r=self.s.replay('s','recorded-media');self.assertEqual(r['status'],'incomplete')
        for table in ('item_versions','events','projections','notification_outbox','observation_receipts'):
            self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0],0)
        self.assertNotIn(b'synthetic text',self.s.path.read_bytes())
        with self.assertRaisesRegex(ValueError,'expired'):self.put(event(3))
    def test_SM09_shortest_expiry_not_restarted_and_synthetic_seven_days(self):
        self.s.accept(event(),integration_run='i',grant='t',acquired_at=900,expires_at=1100)
        self.assertEqual(float(self.s.db.execute("SELECT value FROM meta WHERE key='expires'").fetchone()[0]),1100)
        other=ObservationStore(Path(self.tmp.name)/'fake.sqlite',clock=lambda:1000.,synthetic=True)
        self.assertEqual(float(other.db.execute("SELECT value FROM meta WHERE key='expires'").fetchone()[0]),1000+7*86400);other.close()
    def test_SM09_deleted_source_unavailable_not_recreated_by_redelivery(self):
        r=self.put(event());self.s.redact('s','recorded-media',r['id']);self.put(event())
        self.assertEqual(self.s.item('s','recorded-media',r['id'])['availability'],'deleted')
        self.assertEqual(self.s.replay('s','recorded-media')['status'],'incomplete')
    def test_SM11_before_commit_rolls_back_and_after_commit_is_durable(self):
        self.s.fault=lambda stage:(_ for _ in ()).throw(OSError('disk full')) if stage=='before_commit' else None
        with self.assertRaises(OSError):self.put(event())
        self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM events').fetchone()[0],0)
        self.s.fault=lambda stage:(_ for _ in ()).throw(OSError('notify interrupted')) if stage=='after_commit_before_notify' else None
        r=self.put(event());self.assertEqual(r['status'],'recorded_notification_pending')
        self.s.fault=lambda _:None;self.assertEqual(self.put(event())['id'],r['id'])
    def test_SM11_stop_rejects_new_record(self):
        self.s.stop()
        with self.assertRaisesRegex(ValueError,'STOPPED'):self.put(event())


class Owners(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.b=Budget(Path(self.tmp.name)/'budget.json',PROFILE)
        self.c=Controller(FakeAssets(),self.b,FakeModels(),PROFILE,FakeDecoder());self.now=[0.]
        self.o=PublicationOwner(self.c,lambda:self.now[0])
    def tearDown(self):self.c.close();self.tmp.cleanup()
    def test_SM01_08_server_capability_one_owner_and_handoff(self):
        a=self.o.claim()
        for fake in (None,'self-declared-tab-id',''):
            with self.assertRaises(ValueError):self.o.check(fake)
        with self.assertRaises(ValueError):self.o.claim()
        epoch=self.c.epoch;self.o.release(a);self.assertGreater(self.c.epoch,epoch)
        b=self.o.claim();self.assertNotEqual(a,b)
        with self.assertRaises(ValueError):self.o.check(a)
        self.o.check(b)
    def test_SM05_expired_owner_cannot_publish_or_keep_old_epoch(self):
        a=self.o.claim();epoch=self.c.epoch;self.now[0]=6
        with self.assertRaises(ValueError):self.o.check(a)
        self.assertGreater(self.c.epoch,epoch);self.assertEqual(self.c.status,'owner_expired')
    def test_SM11_storage_failure_does_not_claim_recorded_and_blocks_intake(self):
        self.c.observer=lambda e:(_ for _ in ()).throw(OSError('no space')) if e['kind']=='common_input' else None
        self.c.command(dict(action='select',asset_id='a'),'s')
        self.c.command(dict(action='play',asset_id='a',epoch=self.c.epoch),'s');self.c.last_tick-=2
        self.c.command(dict(action='release',asset_id='a',epoch=self.c.epoch,start=0,end=2),'s');self.c.jobs.join()
        self.assertEqual(self.c.observation_error,'no space')
        self.assertTrue(any(e.get('common_record',{}).get('status')=='NOT_RECORDED' for e in self.c.events))
        with self.assertRaisesRegex(ValueError,'save_failed'):
            self.c.command(dict(action='release',asset_id='a',epoch=self.c.epoch,start=2,end=4),'s')


class Grant(unittest.TestCase):
    def test_SM02_M1_approval_limits_closed_failed_and_prior_isolation(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);profile=json.loads((ROOT/'config/sv01_map_m1.json').read_text())
            (root/'config').mkdir();(root/'config/sv01_map_m1.json').write_bytes((ROOT/'config/sv01_map_m1.json').read_bytes())
            prior={}
            for name in grants.M1_PRIOR:
                p=root/name.replace('\\','/');p.parent.mkdir(parents=True,exist_ok=True);p.write_text('{"synthetic":"CLOSED"}')
                prior[name]=grants.digest(p)
            ledger=root/'artifacts/sv01/map-m1/grant.json';ledger.parent.mkdir()
            initial=dict(grant=grants.M1,state='AUTHORIZED_NOT_STARTED',profile=profile,prior_ledgers=prior,
                lease_required='artifacts/sv01/campaign.lock',native_failure_this_task=False,media_seconds=0,
                asr_attempts=0,image_attempts=0,runtime_processes=0,model_started_at=None)
            ledger.write_text(json.dumps(initial));raw=ledger.read_bytes()
            with patch.object(grants,'M1_PRIOR',prior),patch.object(grants,'M1_APPROVAL_SHA',grants.digest(ledger)):
                route=grants.resolve_route(root,grants.M1)
                for wrong in (None,'UNKNOWN'):
                    with self.assertRaises(ValueError):grants.resolve_route(root,wrong,root/'config/sv01_map_m1.json')
                for changed in ({'grant':grants.Q1},{'profile':{}},{'prior_ledgers':{}}):
                    ledger.write_text(json.dumps(initial|changed))
                    with self.assertRaises(ValueError):Budget(ledger,profile,parent=route['parent'],grant=grants.M1,root=root)
                for kind,limit in (('asr',24),('image',12)):
                    ledger.write_bytes(raw)
                    b=Budget(ledger,profile,lambda:100.,parent=route['parent'],grant=grants.M1,root=root)
                    try:
                        self.assertIsNone(b.data['model_started_at']);b.begin_runtime()
                        for _ in range(limit):b.start(kind)
                        with self.assertRaises(ValueError):b.start(kind)
                    finally:b.close()
                ledger.write_bytes(raw)
                b=Budget(ledger,profile,lambda:100.,parent=route['parent'],grant=grants.M1,root=root)
                try:
                    b.begin_runtime();b.release(60)
                    with self.assertRaises(ValueError):b.release(.01)
                finally:b.close()
                valid=json.loads(ledger.read_text())
                for state in ('CLOSED','FAILED'):
                    ledger.write_text(json.dumps(valid|{'state':state}))
                    with self.assertRaises(ValueError):Budget(ledger,profile,parent=route['parent'],grant=grants.M1,root=root)
                for name,digest in prior.items():self.assertEqual(grants.digest(root/name.replace('\\','/')),digest)


class Http(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();root=Path(self.tmp.name)
        self.s=BridgeServer(('127.0.0.1',0),BridgeHandler);self.s.upload_lock=threading.Lock();self.s.evidence_root=root
        self.s.app=BridgeApp(root/'context/state.sqlite','test-run','FAKE',synthetic=True)
        self.s.sv=Controller(Assets(root/'media',PROFILE),Budget(root/'budget.json',PROFILE),FakeModels(),PROFILE,FakeDecoder(),self.s.app.bridge)
        self.s.app.sv=self.s.sv;self.s.app.owner=PublicationOwner(self.s.sv)
        self.t=threading.Thread(target=self.s.serve_forever,kwargs={'poll_interval':.01});self.t.start()
        self.headers={'Origin':f'http://127.0.0.1:{self.s.server_port}','X-C0-Token':self.s.app.token,'X-SV-Session':'fixture-0','Cookie':'SV01='+self.s.app.token}
    def tearDown(self):self.s.shutdown();self.t.join();self.s.server_close();self.tmp.cleanup()
    def req(self,path,body=None,extra=None):
        c=http.client.HTTPConnection('127.0.0.1',self.s.server_port,timeout=3);c.request('GET' if body is None else 'POST',path,body,self.headers|(extra or {}))
        r=c.getresponse();value=(r.status,r.read());c.close();return value
    def test_SM01_08_one_map_player_old_c0_has_none_second_view_read_only(self):
        code,page=self.req('/map');self.assertEqual(code,200);self.assertEqual(page.count(b'<video '),1)
        owner=re.search(rb'name="sv-owner" content="([^"]*)"',page).group(1).decode()
        self.assertTrue(owner);self.assertIn(b'name="sv-owner" content=""',self.req('/map')[1])
        self.assertNotIn(b'<video ',self.req('/c0')[1]);self.assertNotIn(b'<video ',self.req('/')[1])
        self.assertEqual(self.req('/api/sv/owner',b'{}')[0],409)
        self.assertEqual(self.req('/api/sv/owner/release',b'',{'X-SV-Owner':owner})[0],200)
        self.assertEqual(self.req('/api/sv/owner',b'{}')[0],200)
    def test_SM10_owner_auth_host_session_and_path(self):
        self.req('/map')
        for changes in ({'Origin':'https://invalid.example'},{'X-C0-Token':'bad'},{'X-SV-Session':'old'},{'Host':'elsewhere'}):
            self.assertEqual(self.req('/api/sv/owner',b'{}',changes)[0],403)
        self.assertEqual(self.req('/api/sv/action',b'{"action":"play"}',{'X-SV-Owner':'self_id'})[0],409)
        self.assertEqual(self.req('/media/../../.env?session=fixture-0')[0],400)
    def test_SM03_06_projection_refs_pending_and_no_fields_update(self):
        e=event(session='fixture-0');self.s.app.bridge(e);self.s.app.bridge(event(2,'analysis_completed',session='fixture-0'))
        code,body=self.req('/api/map');self.assertEqual(code,200);view=json.loads(body)['view']
        self.assertEqual(len([n for n in view['nodes'] if not n.get('display_only')]),2);self.assertEqual(len(view['edges']),1)
        self.assertEqual(len([n for n in view['nodes'] if n.get('kind')=='Unknown']),3)
        self.assertTrue(view['layer_view_id']);self.assertTrue(all(f['UNKNOWN']==1 for f in view['fields'].values()))
        self.assertFalse(view['responses']);self.assertTrue(all(n['kind']=='Evidence' for n in view['nodes'] if not n.get('display_only')))
    def test_SM12_same_C0_state_and_fixture_context_survives_switch(self):
        self.req('/api/action',b'{"action":"demo","name":"short"}')
        state=json.loads(self.req('/api/map')[1]);self.assertEqual(len(state['c0']['commits']),1)
        self.req('/api/map/action',b'{"action":"context_start"}')
        self.assertEqual(json.loads(self.req('/api/map')[1])['view']['mode'],'CONTEXT_FIXTURE')
        self.req('/api/map/action',b'{"action":"observations"}')
        self.assertEqual(json.loads(self.req('/api/map')[1])['view']['mode'],'SYNTHETIC_OBSERVATION')

    def test_SM09_expiry_purges_browser_api_memory_and_refuses_intake(self):
        self.s.app.bridge(event(session='fixture-0'));self.s.sv.events.append(event())
        self.s.app.store.db.execute("UPDATE meta SET value='1' WHERE key='expires'")
        data=json.loads(self.req('/api/sv/state')[1]);self.assertEqual(data['events'],[])
        self.assertIsNone(data['bridge']['last_result']);self.assertEqual(data['observation_error'],'retention_expired')
        self.assertEqual(self.req('/api/sv/owner',b'{}')[0],410)
        self.assertEqual(json.loads(self.req('/api/map')[1])['view']['retention'],'expired')


if __name__=='__main__':unittest.main()
