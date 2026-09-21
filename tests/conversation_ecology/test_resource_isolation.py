"""R1 contracts with private synthetic ledgers and fake process executors only."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from test_saved_video import ROOT,FakeAssets
from conversation_ecology.saved_video import grants
from conversation_ecology.saved_video.resource_budget import ResourceBudget
from conversation_ecology.saved_video.resource_controller import IsolatedController
from conversation_ecology.context.observations import ObservationStore,ObservationBridge


class FakeLane:
    def __init__(self,manager,kind):self.manager=manager;self.kind=kind
    def decode(self,job):
        now=time.monotonic();self.job=job
        self.provenance=dict(**job['envelope'],interval=job['interval'],lane=self.kind,source_kind='saved_video',
            asset_id='a',asset_sha256='synthetic',audio={'root':'synthetic-a'} if self.kind=='asr' else None,
            frame={'root':'synthetic-v'} if self.kind=='image' else None)
        return dict(provenance=self.provenance,input_available=True,decode_start=now,decode_end=time.monotonic())
    def infer(self,ticket):
        begin=time.monotonic();self.manager.started[self.kind].set()
        self.manager.gates[self.kind].wait(15)
        if self.manager.fail_kind==self.kind:raise RuntimeError('synthetic_lane_failure')
        self.manager.calls.append((self.kind,self.job['interval'],self.job['envelope']['epoch']))
        return dict(result={'synthetic':True},infer_start=begin,infer_end=time.monotonic())
    def cancel(self):pass
    def close(self):pass


class FakeResourceModels:
    def __init__(self,workers=1):
        self.config={'image_workers':workers};self.status={k:{'state':'synthetic'} for k in ('asr','image')}
        self.started={k:threading.Event() for k in self.status};self.gates={k:threading.Event() for k in self.status}
        for gate in self.gates.values():gate.set()
        self.calls=[];self.fail_kind=None
    def open(self,kind,index):return FakeLane(self,kind)
    def image_headroom(self):return True
    def close(self):pass


class ResourceTests(unittest.TestCase):
    def test_windows_reader_rename_collision_preserves_one_debit(self):
        if os.name!='nt':self.skipTest('Windows sharing contract')
        b=self.budget();reader=self.path.open('rb')
        timer=threading.Timer(.035,reader.close);timer.start()
        try:b.release(2)
        finally:timer.join();reader.close()
        self.assertEqual(json.loads(self.path.read_text())['media_seconds'],2)
        self.assertFalse(self.path.with_suffix('.pending').exists())

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.controllers=[];self.budgets=[]
        self.profile=json.loads((ROOT/'config/sv01_resource_r1.json').read_text())
        config=self.root/'config/sv01_resource_r1.json';config.parent.mkdir();config.write_bytes((ROOT/'config/sv01_resource_r1.json').read_bytes())
        prior={}
        for p in grants.R1_PRIOR:
            path=self.root/Path(p.replace('\\','/'));path.parent.mkdir(parents=True,exist_ok=True);path.write_text('{}');prior[p]=grants.digest(path)
        self.parent=self.root/'artifacts/sv01/campaign.json';self.path=self.root/'artifacts/sv01/resource-r1/grant.json';self.path.parent.mkdir()
        self.initial=dict(grant=grants.R1,state='AUTHORIZED_NOT_STARTED',profile=self.profile,media_seconds=0,asr_attempts=0,image_attempts=0,
            runtime_processes=0,model_loads=0,model_started_at=None,prior_ledgers=prior,lease_required='artifacts/sv01/campaign.lock',native_failure_this_task=False)
        self.path.write_text(json.dumps(self.initial));self.patches=[patch.object(grants,'R1_PRIOR',prior),patch.object(grants,'R1_APPROVAL_SHA',grants.digest(self.path))]
        for p in self.patches:p.start()
    def tearDown(self):
        for c in self.controllers:
            for gate in c.models.gates.values():gate.set()
            c.close()
        for b in self.budgets:
            if not b.handle.closed:b.close()
        for p in reversed(self.patches):p.stop()
        self.tmp.cleanup()
    def budget(self):
        b=ResourceBudget(self.path,self.profile,parent=self.parent,grant=grants.R1,root=self.root);self.budgets.append(b)
        b.select_candidate('A','BENCH_ONLY');b.begin_runtime();return b
    def controller(self,changes=None,observer=None):
        m=FakeResourceModels();p=self.profile| (changes or {})
        c=IsolatedController(FakeAssets(),self.budget(),m,p,observer=observer);self.controllers.append(c)
        self.command(c,'select',asset_id='a');self.command(c,'play');c.play_anchor=(0,time.monotonic()-90)
        return c
    def command(self,c,action,**values):return c.command(dict(action=action,asset_id=c.asset_id,epoch=c.epoch)|values,'s')
    def release(self,c,a,b):return self.command(c,'release',start=a,end=b)
    def until(self,predicate,timeout=3):
        end=time.monotonic()+timeout
        while not predicate() and time.monotonic()<end:time.sleep(.01)
        self.assertTrue(predicate())

    def test_res02_image_ten_seconds_does_not_block_audio_save_control(self):
        store=ObservationStore(self.root/'state.sqlite',synthetic=True)
        try:
            c=self.controller(observer=ObservationBridge(store,'synthetic','NO_REAL_GRANT'));c.models.gates['image'].clear()
            before=time.monotonic();self.release(c,0,2);self.assertTrue(c.models.started['image'].wait(2))
            self.until(lambda:c.lanes['asr']['completed']==1)
            self.release(c,2,4);self.until(lambda:c.lanes['asr']['completed']==2)
            with store.lock:
                values=[json.loads(r[0]) for r in store.db.execute('SELECT payload FROM item_versions')]
            self.assertEqual(sum(v.get('event_kind')=='analysis_completed' for v in values),2)
            times=[]
            while time.monotonic()-before<10:
                at=time.monotonic();v=c.view();times.append(time.monotonic()-at);time.sleep(.1)
            self.assertEqual(c.lanes['image']['completed'],0);self.assertLess(max(times),.25)
            c.models.gates['image'].set();self.until(lambda:c.lanes['image']['completed']==1)
        finally:
            if self.controllers:self.controllers[-1].close();self.controllers.pop()
            store.close()

    def test_res03_full_vision_fifo_preserves_audio_and_playing(self):
        c=self.controller({'image_queue_descriptors':1});c.models.gates['image'].clear()
        self.release(c,0,2);self.assertTrue(c.models.started['image'].wait(2))
        for a in range(2,12,2):self.release(c,a,a+2)
        self.until(lambda:c.lanes['asr']['completed']==6)
        self.assertEqual(c.status,'playing');self.assertEqual(c.lanes['image']['rejected'],1)
        self.assertEqual(c.lanes['image']['state'],'vision_backlog_full')
        self.assertEqual(c.budget.data['media_seconds'],12)

    def test_res04_audio_overload_is_separate_and_debited(self):
        c=self.controller({'audio_queue_chunks':1});c.models.gates['asr'].clear()
        self.release(c,0,2);self.assertTrue(c.models.started['asr'].wait(2));self.release(c,2,4)
        with self.assertRaisesRegex(ValueError,'audio_overload'):self.release(c,4,6)
        self.assertEqual(c.budget.data['media_seconds'],6);self.assertEqual(c.position,4)
        self.assertEqual(c.lanes['image']['rejected'],0)

    def test_res05_seek_old_result_and_cancel_each_lane(self):
        c=self.controller();c.models.gates['image'].clear();self.release(c,0,2)
        self.assertTrue(c.models.started['image'].wait(2))
        for a in (2,4):self.release(c,a,a+2)
        old=c.epoch;self.command(c,'seek',position=20);c.models.gates['image'].set()
        self.until(lambda:not c.active)
        done=[e for e in c.events if e['kind']=='analysis_completed' and e['analyzer']=='image']
        self.assertEqual(done[0]['provenance']['epoch'],old);self.assertFalse(done[0]['current'])
        self.assertGreaterEqual(c.lanes['image']['cancelled'],1);self.assertEqual(c.position,20)

    def test_res05_eof_drains_separately_and_restart_new_epoch(self):
        c=self.controller();c.models.gates['image'].clear();self.release(c,0,2);self.command(c,'eof')
        self.until(lambda:c.lanes['asr']['completed']==1);self.assertEqual(c.status,'eof_draining')
        with self.assertRaisesRegex(ValueError,'eof_not_drained'):self.command(c,'restart')
        c.models.gates['image'].set();self.until(lambda:c.status=='ended')
        old=c.epoch;self.command(c,'restart');self.assertEqual(c.position,0);self.assertGreater(c.epoch,old)

    def test_res07_atomic_reservations_concurrency_and_final_reserve(self):
        b=self.budget();tickets=[];barrier=threading.Barrier(4)
        def work(kind):barrier.wait();tickets.append((kind,b.start(kind)))
        threads=[threading.Thread(target=work,args=(k,)) for k in ('asr','image','image')]
        for t in threads:t.start()
        barrier.wait()
        for t in threads:t.join()
        self.assertEqual(b.data['active'],{'asr':1,'image':2})
        for k in ('asr','image'):
            with self.assertRaisesRegex(ValueError,'lane_concurrency'):b.start(k)
        for k,t in tickets:b.finish(k,t)
        with self.assertRaisesRegex(ValueError,'duplicate_ticket'):b.finish(*tickets[0])
        b.release(780)
        with self.assertRaisesRegex(ValueError,'final_reserve'):b.release(.001)
        b.select_candidate('A','LIVE');b.release(420)
        with self.assertRaises(ValueError):b.release(.001)

    def test_res07_failed_clock_attempt_consumed_once_before_fanout(self):
        c=self.controller();c.play_anchor=(0,time.monotonic())
        with self.assertRaisesRegex(ValueError,'clock_jump'):self.release(c,0,2)
        self.assertEqual(c.budget.data['media_seconds'],2)
        c.play_anchor=(0,time.monotonic()-3);self.release(c,0,2)
        self.until(lambda:c.lanes['image']['completed']==1 and c.lanes['asr']['completed']==1)
        self.assertEqual(c.budget.data['media_seconds'],4)

    def test_res12_image_error_control_remains_callable(self):
        c=self.controller();c.models.fail_kind='image';self.release(c,0,2)
        self.until(lambda:c.budget.data.get('failure_reason'))
        self.assertTrue(c.view()['control_ready']);self.assertEqual(c.budget.data['state'],'FAILED')
        with self.assertRaisesRegex(ValueError,'grant_failed'):self.release(c,2,4)

    def test_res13_stop_cancels_queue_acceptance_precedes_join(self):
        c=self.controller();c.models.gates['image'].clear();self.release(c,0,2)
        self.assertTrue(c.models.started['image'].wait(2))
        for a in (2,4):self.release(c,a,a+2)
        at=time.monotonic();c.stop_admission();self.assertLess(time.monotonic()-at,.25)
        self.assertTrue(c.worker.is_alive());self.assertEqual(c.jobs.qsize(),0)
        c.models.gates['image'].set();c.worker.join();self.assertFalse(c.worker.is_alive())

    def test_res14_model_load_and_unknown_candidate_limits(self):
        b=self.budget()
        with self.assertRaisesRegex(ValueError,'unapproved'):b.select_candidate('X','LIVE')
        for i in range(24):b.load('image',str(i))
        with self.assertRaisesRegex(ValueError,'model_load_limit'):b.load('image','25')

if __name__=='__main__':unittest.main()
