"""QR01-12: isolated synthetic approval/ledger, no real grant consumption."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from test_saved_video import ROOT, FakeAssets, FakeModels, FakeDecoder
from conversation_ecology.saved_video.budget import Budget
from conversation_ecology.saved_video.controller import Controller
from conversation_ecology.saved_video import grants
import sys
sys.path.insert(0,str(ROOT/'scripts'))
from sv01_verify_run import record_q1_exit


class Q1Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.profile=json.loads((ROOT/'config/sv01_sample_q1.json').read_text())
        p=self.root/'config/sv01_sample_q1.json';p.parent.mkdir();p.write_bytes((ROOT/'config/sv01_sample_q1.json').read_bytes())
        self.parent=self.root/'artifacts/sv01/campaign.json';self.parent.parent.mkdir(parents=True)
        self.parent.write_text('{"synthetic":"old campaign"}')
        self.f1=self.parent.parent/'f1/grant.json';self.f1.parent.mkdir();self.f1.write_text('{"synthetic":"old F1"}')
        prior={str(p.relative_to(self.root)).replace('/','\\'):grants.digest(p) for p in (self.parent,self.f1)}
        self.path=self.parent.parent/'sample-q1/grant.json';self.path.parent.mkdir()
        self.initial=dict(grant=grants.Q1,state='AUTHORIZED_NOT_STARTED_BLOCKED_GRANT_ROUTING',profile=self.profile,
            media_seconds=0,asr_attempts=0,image_attempts=0,runtime_processes=0,model_started_at=None,
            prior_ledgers=prior,lease_required='artifacts/sv01/campaign.lock',native_failure_this_task=False)
        self.path.write_text(json.dumps(self.initial));self.raw=self.path.read_bytes()
        self.patches=[patch.object(grants,'PRIOR',prior),patch.object(grants,'APPROVAL_SHA',grants.digest(self.path))]
        for p in self.patches:p.start()
        self.now=[100.];self.owners=[]

    def tearDown(self):
        for b in self.owners:
            if not b.handle.closed:b.close()
        for p in reversed(self.patches):p.stop()
        self.tmp.cleanup()

    def open(self,**kw):
        b=Budget(self.path,self.profile,lambda:self.now[0],parent=self.parent,grant=grants.Q1,root=self.root,**kw)
        self.owners.append(b);return b

    def write(self,data):self.path.write_text(json.dumps(data))

    def close_verified(self,b):
        b.close();record_q1_exit(grants.resolve_route(self.root,grants.Q1),0,self.now[0])

    def test_QR01_route_and_preparation_no_clock(self):
        route=grants.resolve_route(self.root,grants.Q1)
        self.assertEqual(route['ledger'],self.path);self.assertEqual(route['evidence'],self.path.parent)
        b=self.open();self.assertEqual(b.data['state'],'READY');self.assertIsNone(b.data['model_started_at'])
        self.assertEqual(b.data['runtime_processes'],0)
        with self.assertRaisesRegex(ValueError,'runtime_not_started'):b.release(1)

    def test_QR02_unknown_profile_and_parent_rejected_without_write(self):
        for grant,profile in [('unknown',None),(grants.Q1,self.root/'other.json')]:
            with self.assertRaises(ValueError):grants.resolve_route(self.root,grant,profile)
        self.parent.write_text('changed')
        with self.assertRaisesRegex(ValueError,'prior_ledger'):self.open()
        self.assertEqual(self.raw,self.path.read_bytes())

    def test_QR02_route_path_cannot_escape(self):
        with self.assertRaisesRegex(ValueError,'route_mismatch'):
            Budget(self.root/'other.json',self.profile,parent=self.parent,grant=grants.Q1,root=self.root)
        self.assertFalse((self.root/'other.json').exists())

    def test_QR02_ledger_identity_mismatches_rejected(self):
        for change in ({'grant':'SV01-F1'},{'profile':self.profile|{'asr_attempts':49}},{'prior_ledgers':{}},{'lease_required':'another.lock'}):
            self.write(self.initial|change);raw=self.path.read_bytes()
            with self.assertRaises(ValueError):self.open()
            self.assertEqual(raw,self.path.read_bytes())

    def test_QR03_05_restart_preserves_debits_and_initialization_clock(self):
        old=(self.parent.read_bytes(),self.f1.read_bytes());b=self.open();b.begin_runtime();b.release(2);b.start('asr');self.close_verified(b)
        self.now[0]=120;b=self.open();self.assertEqual(b.elapsed(),20);b.begin_runtime();self.close_verified(b)
        b=self.open();self.assertEqual(b.data['runtime_processes'],2);self.assertEqual(b.data['asr_attempts'],1)
        with self.assertRaisesRegex(ValueError,'runtime_processes'):b.begin_runtime()
        self.assertEqual(old,(self.parent.read_bytes(),self.f1.read_bytes()))

    def test_QR04_common_owner_denied(self):
        self.open()
        with self.assertRaises(FileExistsError):self.open()
        with self.assertRaises(FileExistsError):Budget(self.parent,{},parent=None)

    def test_QR06_exact_attempt_limits_and_no_refund(self):
        for kind,limit in [('asr',48),('image',24)]:
            self.write(self.initial);b=self.open();b.begin_runtime()
            for _ in range(limit):b.start(kind)
            with self.assertRaisesRegex(ValueError,'budget_'):b.start(kind)
            self.assertEqual(b.data[kind+'_attempts'],limit);b.close()

    def test_QR06_media_repeat_limit(self):
        b=self.open();b.begin_runtime()
        for _ in range(60):b.release(2)
        with self.assertRaisesRegex(ValueError,'budget_media'):b.release(.01)
        self.assertEqual(b.data['media_seconds'],120)

    def test_QR06_serial_heavy_and_11_worker_cleanup(self):
        b=self.open();b.begin_runtime();m=FakeModels();c=Controller(FakeAssets(),b,m,self.profile,FakeDecoder())
        c.command(dict(action='select',asset_id='a'),'s1')
        def cmd(action,**v):return c.command(dict(action=action,epoch=c.epoch,asset_id='a',**v),'s1')
        cmd('play');c.last_tick-=2;cmd('release',start=0,end=2);c.jobs.join()
        c.last_tick-=2;cmd('release',start=2,end=4);c.jobs.join();c.close()
        self.assertFalse(c.worker.is_alive());self.assertEqual(b.data['asr_attempts'],2);self.assertEqual(b.data['image_attempts'],1)

    def test_QR07_clock_no_restart_and_outer_deadline(self):
        b=self.open();b.begin_runtime();self.close_verified(b);self.now[0]=879;b=self.open();self.assertEqual(b.elapsed(),779)
        self.now[0]=880
        with self.assertRaisesRegex(ValueError,'admission'):b.check()
        b.close();route=grants.resolve_route(self.root,grants.Q1)
        result=record_q1_exit(route,0,1001,True)
        self.assertFalse(result['within_exit_deadline']);self.assertEqual(result['elapsed_seconds'],901)
        with self.assertRaisesRegex(ValueError,'not_reopenable'):self.open()

    def test_QR08_native_failure_blocks_and_preserves_reservations(self):
        b=self.open();b.begin_runtime();b.start('asr');b.close()
        record_q1_exit(grants.resolve_route(self.root,grants.Q1),0xC0000005,110)
        data=json.loads(self.path.read_text());self.assertTrue(data['native_failure_this_task']);self.assertEqual(data['asr_attempts'],1)
        with self.assertRaises(ValueError):self.open()

    def test_QR10_unknown_schema_incomplete_and_partial_write(self):
        b=self.open();b.close();valid=json.loads(self.path.read_text())
        for change in ({'schema':99},{'runtime_in_flight':True},{'state':'CLOSED'},{'model_started_at':None,'asr_attempts':1},{'media_seconds':float('nan')}):
            self.write(valid|change);raw=self.path.read_bytes()
            with self.assertRaises(ValueError):self.open()
            self.assertEqual(raw,self.path.read_bytes())
        self.write(valid);self.path.with_suffix('.pending').write_text('{')
        with self.assertRaisesRegex(ValueError,'partial_write'):self.open()

    def test_QR10_original_approval_not_reinitialized(self):
        self.write(self.initial|{'asr_attempts':1})
        with self.assertRaisesRegex(ValueError,'approval_bytes_changed'):self.open()

    def test_QR09_no_grant_cannot_select_q1_profile(self):
        with self.assertRaisesRegex(ValueError,'path_mismatch'):
            grants.resolve_route(self.root,None,self.root/'config/sv01_sample_q1.json')

    def test_QR11_outer_verification_required_before_next_owner(self):
        b=self.open();b.begin_runtime();b.close()
        with self.assertRaisesRegex(ValueError,'previous_runtime_incomplete'):self.open()
        record_q1_exit(grants.resolve_route(self.root,grants.Q1),0,self.now[0])
        self.open()


if __name__=='__main__':unittest.main()
