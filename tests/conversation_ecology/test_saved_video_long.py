"""L1 fixed grant and long synthetic publication; no real grant/model consumption."""
import io,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from test_saved_video import ROOT,FakeAssets,FakeModels,FakeDecoder
from conversation_ecology.saved_video import grants
from conversation_ecology.saved_video.budget import Budget
from conversation_ecology.saved_video.controller import Controller
from conversation_ecology.saved_video.media import Assets
from conversation_ecology.saved_video.runtime import source_identity
sys.path.insert(0,str(ROOT/'scripts'))
from sv01_verify_run import record_q1_exit

class LongGrantTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.owners=[];self.now=[100.]
        profile_path=self.root/'config/sv01_long_l1.json';profile_path.parent.mkdir()
        profile_path.write_bytes((ROOT/'config/sv01_long_l1.json').read_bytes());self.profile=json.loads(profile_path.read_text())
        prior={}
        for name in grants.L1_PRIOR:
            p=self.root/Path(name.replace('\\','/'));p.parent.mkdir(parents=True,exist_ok=True);p.write_text('{"synthetic_prior":true}')
            prior[name]=grants.digest(p)
        self.parent=self.root/'artifacts/sv01/campaign.json';self.path=self.root/'artifacts/sv01/long-l1/grant.json';self.path.parent.mkdir()
        self.initial=dict(grant=grants.L1,state='AUTHORIZED_NOT_STARTED',profile=self.profile,media_seconds=0,asr_attempts=0,image_attempts=0,runtime_processes=0,model_started_at=None,prior_ledgers=prior,lease_required='artifacts/sv01/campaign.lock',native_failure_this_task=False)
        self.path.write_text(json.dumps(self.initial));self.raw=self.path.read_bytes()
        self.patches=[patch.object(grants,'L1_PRIOR',prior),patch.object(grants,'L1_APPROVAL_SHA',grants.digest(self.path))]
        for p in self.patches:p.start()
    def tearDown(self):
        for b in self.owners:
            if not b.handle.closed:b.close()
        for p in reversed(self.patches):p.stop()
        self.tmp.cleanup()
    def open(self):
        b=Budget(self.path,self.profile,lambda:self.now[0],parent=self.parent,grant=grants.L1,root=self.root);self.owners.append(b);return b
    def verified(self,b,code=0,finish=False):
        b.close();return record_q1_exit(grants.resolve_route(self.root,grants.L1),code,self.now[0],finish)
    def test_fixed_route_hash_and_prior_rejection(self):
        r=grants.resolve_route(self.root,grants.L1);self.assertEqual(r['ledger'],self.path)
        with self.assertRaisesRegex(ValueError,'unknown_grant'):grants.resolve_route(self.root,'SV01-LONG-L2')
        self.parent.write_text('changed')
        with self.assertRaisesRegex(ValueError,'prior_ledger_changed'):self.open()
        self.assertEqual(self.path.read_bytes(),self.raw)
    def test_profile_bytes_and_ungranted_path_rejected(self):
        p=self.root/'config/sv01_long_l1.json'
        with self.assertRaisesRegex(ValueError,'path_mismatch'):grants.resolve_route(self.root,None,p)
        p.write_text(p.read_text()+' ')
        with self.assertRaisesRegex(ValueError,'unapproved_profile'):self.open()
    def test_ready_native_clock_restart_and_shared_lease(self):
        b=self.open();self.assertIsNone(b.data['model_started_at'])
        with self.assertRaisesRegex(ValueError,'runtime_not_started'):b.release(1)
        with self.assertRaises(FileExistsError):self.open()
        b.begin_runtime();b.release(2);b.start('asr');self.verified(b)
        self.now[0]=130;b=self.open();b.begin_runtime();self.assertEqual(b.elapsed(),30);self.assertEqual(b.data['asr_attempts'],1)
        self.verified(b);b=self.open()
        with self.assertRaisesRegex(ValueError,'runtime_processes'):b.begin_runtime()
    def test_l1_clock_uses_1800_and_1680_not_q1_900(self):
        b=self.open();b.begin_runtime();self.now[0]=1779;b.check();self.now[0]=1780
        with self.assertRaisesRegex(ValueError,'admission'):b.check()
        self.now[0]=1899;r=self.verified(b,finish=True);self.assertTrue(r['within_exit_deadline'])
        with self.assertRaisesRegex(ValueError,'not_reopenable'):self.open()
    def test_deadline_overrun_and_native_failure_are_failed(self):
        for code,at in [(0,1901),(0xC0000005,110)]:
            self.path.write_bytes(self.raw);self.now[0]=100;b=self.open();b.begin_runtime();b.start('image');self.now[0]=at
            r=self.verified(b,code);self.assertEqual(r['state'],'FAILED')
            with self.assertRaisesRegex(ValueError,'not_reopenable'):self.open()
            self.assertEqual(json.loads(self.path.read_text())['image_attempts'],1)
    def test_incomplete_and_tampered_approval_rejected(self):
        b=self.open();b.begin_runtime();b.close()
        with self.assertRaisesRegex(ValueError,'previous_runtime_incomplete'):self.open()
        self.path.write_bytes(self.raw+b' ')
        with self.assertRaisesRegex(ValueError,'approval_bytes_changed'):self.open()
    def test_counter_limits(self):
        for kind,limit in [('asr',120),('image',60)]:
            self.path.write_bytes(self.raw);b=self.open();b.begin_runtime()
            for _ in range(limit):b.start(kind)
            with self.assertRaisesRegex(ValueError,'budget_'):b.start(kind)
            b.close()
        self.path.write_bytes(self.raw);b=self.open();b.begin_runtime();b.release(210)
        with self.assertRaisesRegex(ValueError,'budget_media'):b.release(.001)
    def test_asset_hash_rejected_before_probe_and_copy_removed(self):
        assets=Assets(self.root/'assets',self.profile)
        with patch('conversation_ecology.saved_video.media.probe') as probe:
            with self.assertRaisesRegex(ValueError,'asset_not_in_grant'):assets.import_stream(io.BytesIO(b'wrong'),5,'.mp4')
            probe.assert_not_called()
        self.assertEqual(list(assets.root.iterdir()),[]);assets.close()
    def test_full_178_seconds_and_short_restart_fit_event_budget(self):
        class LongAssets(FakeAssets):
            def get(self,ident):return super().get(ident)|{'duration':178.496}
        b=self.open();b.begin_runtime();c=Controller(LongAssets(),b,FakeModels(),self.profile,FakeDecoder())
        def command(action,**v):return c.command(dict(action=action,epoch=c.epoch,asset_id='a',**v),'s')
        try:
            command('select');command('play');position=0
            while position<178.496:
                end=min(position+2,178.496);c.last_tick-=end-position;command('release',start=position,end=end);c.jobs.join();position=end
            command('eof');self.assertEqual(c.status,'ended');old=c.epoch
            command('restart');self.assertGreater(c.epoch,old)
            for start in (0,2,4):c.last_tick-=2;command('release',start=start,end=start+2);c.jobs.join()
            command('pause');self.assertAlmostEqual(b.data['media_seconds'],184.496)
            self.assertEqual(b.data['asr_attempts'],93);self.assertEqual(b.data['image_attempts'],47)
            self.assertLess(len(c.events),self.profile['max_events']-16)
            self.assertTrue(all('recorded_at' in e for e in c.events));self.assertEqual(c.jobs.qsize(),0)
        finally:c.close()
        self.assertFalse(c.worker.is_alive())
    def test_final_identity_covers_pipeline_and_grant(self):
        identity=source_identity(ROOT,ROOT/'config/sv01_long_l1.json')
        for p in ['ui/conversation_ecology/pipeline-view.js','ui/conversation_ecology/map.js','config/sv01_long_l1.json','src/conversation_ecology/context/observations.py']:
            self.assertIn(p,identity)

    def test_failed_publications_are_debited_and_retry_not_refunded(self):
        b=self.open();b.begin_runtime();c=Controller(FakeAssets(),b,FakeModels(),self.profile,FakeDecoder())
        def command(action,**v):return c.command(dict(action=action,epoch=c.epoch,asset_id='a',**v),'s')
        try:
            command('select');command('play')
            with self.assertRaisesRegex(ValueError,'playback_clock_jump'):command('release',start=0,end=2)
            self.assertEqual(b.data['media_seconds'],2);self.assertEqual(c.position,0)
            self.assertTrue(c.events[-1]['budget_debited'])
            c.last_tick-=2
            with patch.object(c.jobs,'full',return_value=True):
                with self.assertRaisesRegex(ValueError,'queue_full'):command('release',start=0,end=2)
            self.assertEqual(b.data['media_seconds'],4);self.assertEqual(c.position,0)
            self.assertTrue(c.events[-1]['budget_debited'])
            command('play');c.last_tick-=2;command('release',start=0,end=2);c.jobs.join()
            self.assertEqual(b.data['media_seconds'],6)
            self.assertEqual(sum(e['kind']=='input_released' for e in c.events),1)
        finally:c.close()

    def test_failed_attempt_exhausts_remaining_media_before_retry(self):
        b=self.open();b.begin_runtime();b.release(208)
        c=Controller(FakeAssets(),b,FakeModels(),self.profile,FakeDecoder())
        try:
            c.command(dict(action='select',asset_id='a'),'s')
            c.command(dict(action='play',asset_id='a',epoch=c.epoch),'s');c.last_tick-=2
            with patch.object(c.jobs,'full',return_value=True):
                with self.assertRaisesRegex(ValueError,'queue_full'):c.release(dict(start=0,end=2))
            self.assertEqual(b.data['media_seconds'],210)
            with self.assertRaisesRegex(ValueError,'budget_media_seconds'):
                c.command(dict(action='play',asset_id='a',epoch=c.epoch),'s')
            self.assertEqual(c.jobs.qsize(),0);self.assertEqual(b.data['asr_attempts'],0)
        finally:c.close()

    def test_invalid_intervals_do_not_consume_and_capacity_failure_does(self):
        b=self.open();b.begin_runtime();c=Controller(FakeAssets(),b,FakeModels(),self.profile,FakeDecoder())
        try:
            c.command(dict(action='select',asset_id='a'),'s')
            c.command(dict(action='play',asset_id='a',epoch=c.epoch),'s');c.last_tick-=3
            for start,end,reason in [(1,2,'noncontinuous'),(0,4,'noncontinuous')]:
                with self.assertRaisesRegex(ValueError,reason):c.release(dict(start=start,end=end))
            self.assertEqual(b.data['media_seconds'],0)
            with patch.object(c.assets,'get',return_value={'duration':1}):
                with self.assertRaisesRegex(ValueError,'past_eof'):c.release(dict(start=0,end=2))
            self.assertEqual(b.data['media_seconds'],0)
            c.events=[{}]*(self.profile['max_events']-16)
            with self.assertRaisesRegex(ValueError,'event_capacity'):c.release(dict(start=0,end=2))
            self.assertEqual(b.data['media_seconds'],2);self.assertTrue(c.events[-1]['budget_debited'])
        finally:c.close()

if __name__=='__main__':unittest.main()
