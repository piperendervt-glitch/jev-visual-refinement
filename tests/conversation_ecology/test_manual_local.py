"""Manual mode contracts with fake inference, no legacy grants or real models."""
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from test_saved_video import ROOT,FakeAssets
from test_resource_isolation import FakeResourceModels
from conversation_ecology.saved_video.manual import settings,ManualBudget,ManualController,ManualAssets,Verification


class ManualTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)
        self.profile,self.sha=settings();self.b=ManualBudget(self.path/'usage.json',self.profile,self.sha)
        self.controllers=[]
    def tearDown(self):
        for c in self.controllers:
            for gate in c.models.gates.values():gate.set()
            c.close()
        self.tmp.cleanup()
    def controller(self,changes=None):
        models=FakeResourceModels(workers=2);models.status={k:{'state':'ready_to_load'} for k in ('asr','image')}
        c=ManualController(FakeAssets(),self.b,models,self.profile| (changes or {}));self.controllers.append(c)
        self.command(c,'select',asset_id='a');return c
    def command(self,c,action,**args):return c.command(dict(action=action,asset_id=c.asset_id,epoch=c.epoch)|args,'s')
    def until(self,fn):
        limit=time.monotonic()+3
        while not fn() and time.monotonic()<limit:time.sleep(.01)
        self.assertTrue(fn())
    def play(self,c):
        self.command(c,'play');self.until(c.ready_models);self.command(c,'play');c.play_anchor=(0,time.monotonic()-1000)
    def test_selection_does_not_start_models(self):
        c=self.controller();self.assertFalse(c.workers_started);self.assertFalse(self.b.runtime_begun)
        self.assertEqual(c.view()['mode'],'MANUAL_LOCAL_ANALYSIS')
    def test_bad_epoch_cannot_start_models(self):
        c=self.controller()
        with self.assertRaisesRegex(ValueError,'stale_source'):c.command(dict(action='play',epoch=-1,asset_id='a'),'s')
        self.assertFalse(c.workers_started)
    def test_missing_model_visible_no_fallback(self):
        c=self.controller();c.models.status['image']={'state':'BLOCKED_missing_weights'}
        with self.assertRaisesRegex(ValueError,'解析準備不足'):self.command(c,'play')
        self.assertFalse(c.workers_started);self.assertFalse(c.view()['real_analysis_available'])
    def test_manual_no_lifetime_limit_but_invalid_input_rejected(self):
        self.b.begin_runtime();self.b.data.update(media_seconds=100000,asr_attempts=100000,image_attempts=100000,model_started_at=time.time()-90000)
        self.b.release(2);ticket=self.b.start('asr','asr-0');self.b.finish('asr',ticket);self.b.check()
        self.assertEqual(self.b.data['asr_attempts'],100001)
        for bad in (float('nan'),-1,4):
            with self.assertRaises(ValueError):self.b.release(bad)
    def test_tickets_bounded_and_concurrency_enforced(self):
        self.b.begin_runtime();ticket=self.b.start('asr','asr-0')
        with self.assertRaisesRegex(ValueError,'concurrency'):self.b.start('asr','asr-0')
        self.b.finish('asr',ticket);self.assertEqual(self.b.data['tickets'],[])
    def test_explicit_restart_new_analysis_old_result_separated(self):
        c=self.controller();self.play(c);old=c.analysis_id;epoch=c.epoch
        self.command(c,'release',start=0,end=2);self.until(lambda:c.jobs.empty() and not c.active)
        self.command(c,'eof');self.command(c,'restart')
        self.assertGreater(c.epoch,epoch);self.assertNotEqual(c.analysis_id,old)
        results=[e for e in c.view()['events'] if e['kind']=='analysis_completed']
        self.assertTrue(results);self.assertTrue(all(not e['current'] for e in results))
    def test_rolling_display_history_does_not_stop_publication(self):
        c=self.controller({'max_events':40});self.play(c)
        for _ in range(80):c.event('synthetic_diagnostic')
        self.command(c,'release',start=0,end=2);self.until(lambda:c.lanes['asr']['completed']==1)
        self.assertEqual(c.status,'playing');self.assertLessEqual(len(c.events),40)
    def test_vision_saturation_not_audio_stop(self):
        c=self.controller({'image_queue_descriptors':1,'image_interval_seconds':0});c.models.gates['image'].clear();self.play(c)
        for n in range(5):
            self.command(c,'release',start=n*2,end=n*2+2)
            self.until(lambda:c.lanes['asr']['completed']==n+1)
        self.assertGreater(c.lanes['image']['rejected'],0);self.assertEqual(c.status,'playing')
    def test_stop_cancels_preparation_intent(self):
        c=self.controller();self.play(c);self.command(c,'stop')
        self.assertIsNone(c.pending_start);self.assertEqual(c.status,'stopped')
    def test_upload_unknown_hash_and_rollback(self):
        assets=ManualAssets(self.path/'media',self.profile)
        with patch('conversation_ecology.saved_video.media.probe',return_value=dict(decoder='ready',duration=6,has_audio=False)):
            a=assets.import_stream(io.BytesIO(b'first'),5,'.mp4')
            b=assets.import_stream(io.BytesIO(b'other'),5,'.mp4')
            self.assertNotEqual(a,b);self.assertNotEqual(assets.get(a)['sha256'],assets.get(b)['sha256'])
            with self.assertRaisesRegex(ValueError,'upload_cancelled'):assets.import_stream(io.BytesIO(b'x'),50,'.mp4')
            self.assertEqual(len(list(assets.root.iterdir())),2)
        assets.close()
    def test_new_run_no_previous_closed_dependency(self):
        self.b.close();other=ManualBudget(self.path/'second.json',self.profile,self.sha);other.begin_runtime();other.check();other.close()
    def test_verification_caps_not_normal_profile(self):
        v=Verification(self.path/'verification.json');v.charge('media_seconds',599)
        with self.assertRaisesRegex(ValueError,'verification_limit'):v.charge('media_seconds',2)
        self.assertNotIn('media_seconds',self.profile)
        v.data['state']='CLOSED'
        with self.assertRaisesRegex(ValueError,'verification_closed'):v.charge(None,0)
    def test_failed_run_cannot_resume(self):
        self.b.fail('synthetic_failure')
        with self.assertRaisesRegex(ValueError,'manual_run_failed'):self.b.check()

if __name__=='__main__':unittest.main()
