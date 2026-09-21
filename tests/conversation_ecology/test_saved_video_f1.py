"""F1 model-free boundary, restart and cache order checks."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from test_saved_video import PROFILE, FakeAssets, FakeModels, FakeDecoder, ROOT
from conversation_ecology.saved_video.budget import Budget
from conversation_ecology.saved_video.controller import Controller
from conversation_ecology.saved_video.runtime import configure_cache, RuntimeEvidence, source_identity

F1 = json.loads((ROOT/'config/sv01_f1.json').read_text())


class GrantTests(unittest.TestCase):
    def test_parent_immutable_restart_limits_and_shared_lease(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent=Path(tmp)/'campaign.json';grant=Path(tmp)/'f1/grant.json'
            old=Budget(parent,PROFILE);old.release(33);old.close();raw=parent.read_bytes()
            now=[100.]
            b=Budget(grant,F1,lambda:now[0],parent=parent)
            with self.assertRaises(FileExistsError):Budget(parent,PROFILE)
            b.begin_runtime();b.begin_runtime();b.release(2);b.start('asr');b.close()
            for _ in range(4):
                b=Budget(grant,F1,lambda:now[0],parent=parent);b.begin_runtime();b.close()
            b=Budget(grant,F1,lambda:now[0],parent=parent)
            try:
                self.assertEqual(b.data['runtime_processes'],5)
                self.assertEqual(b.data['media_seconds'],2)
                with self.assertRaisesRegex(ValueError,'runtime_processes'):b.begin_runtime()
                now[0]=880
                for action in (lambda:b.release(1),lambda:b.start('asr')):
                    with self.assertRaisesRegex(ValueError,'admission_seconds'):action()
            finally:b.close()
            self.assertEqual(raw,parent.read_bytes())

    def test_invalid_profile_never_overwrites_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'campaign.json';b=Budget(path,PROFILE);b.close();raw=path.read_bytes()
            with self.assertRaisesRegex(ValueError,'profile_changed'):Budget(path,F1)
            self.assertEqual(raw,path.read_bytes())
            self.assertFalse(path.with_suffix('.lock').exists())

    def test_final_media_limit_counts_revisit(self):
        with tempfile.TemporaryDirectory() as tmp:
            b=Budget(Path(tmp)/'grant.json',F1)
            try:
                for _ in range(30):b.release(2)
                with self.assertRaisesRegex(ValueError,'media_seconds'):b.release(.01)
            finally:b.close()


class RestartTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.b=Budget(Path(self.tmp.name)/'grant.json',F1)
        self.m=FakeModels();self.c=Controller(FakeAssets(),self.b,self.m,F1,FakeDecoder())
        self.cmd('select',asset_id='a')

    def tearDown(self):
        self.m.proceed.set();self.c.close();self.tmp.cleanup()

    def cmd(self,action,**values):
        return self.c.command(dict(action=action,epoch=self.c.epoch,asset_id=self.c.asset_id)|values,'s1')

    def release(self):
        self.cmd('play');self.c.last_tick-=2;self.cmd('release',start=0,end=2)

    def test_pending_tail_rejects_restart_then_new_epoch_root_and_repeat_debit(self):
        self.m.proceed.clear();self.release();self.assertTrue(self.m.started.wait(1));self.cmd('eof')
        with self.assertRaisesRegex(ValueError,'eof_not_drained'):self.cmd('restart')
        self.m.proceed.set();self.c.jobs.join();old=self.c.epoch
        self.cmd('restart');self.assertEqual(self.c.epoch,old+1);self.assertEqual(self.c.position,0)
        with self.assertRaisesRegex(ValueError,'eof_not_drained'):self.cmd('restart')
        self.c.last_tick-=2;self.cmd('release',start=0,end=2);self.c.jobs.join()
        packets=[e['provenance'] for e in self.c.events if e['kind']=='common_input']
        self.assertEqual(packets[0]['root'],packets[1]['root']);self.assertEqual(self.b.data['media_seconds'],4)
        oldrows=[e for e in self.c.view()['events'] if e['kind']=='analysis_completed' and e['provenance']['epoch']==old]
        self.assertTrue(oldrows);self.assertTrue(all(not e['current'] for e in oldrows))

    def test_budget_rejection_does_not_create_epoch(self):
        self.cmd('eof');old=self.c.epoch;self.b.data['media_seconds']=60
        with self.assertRaisesRegex(ValueError,'budget_media'):self.cmd('restart')
        self.assertEqual(self.c.epoch,old);self.assertEqual(self.c.status,'ended')

    def test_stop_race_and_close_wait_for_actual_worker(self):
        self.cmd('eof');old=self.c.epoch;self.cmd('stop')
        with self.assertRaisesRegex(ValueError,'stale_source'):
            self.c.command(dict(action='restart',asset_id='a',epoch=old),'s1')
        self.m.proceed.clear();self.release();self.assertTrue(self.m.started.wait(1))
        self.c.stop_admission();self.assertTrue(self.c.worker.is_alive())
        self.m.proceed.set();self.c.jobs.join()
        self.assertEqual(len(self.m.calls),1)


class RuntimeTests(unittest.TestCase):
    def test_child_cache_settings_recorded_before_native_init(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ):
            root=Path(tmp);environment=configure_cache(root/'cache')
            self.assertEqual(environment['CUDA_CACHE_DISABLE'],'1')
            self.assertEqual(environment['CUDA_CACHE_MAXSIZE'],'16777216')
            self.assertTrue(all(Path(environment[k]).is_relative_to(root) for k in ('HF_HOME','TEMP','TORCH_HOME','CUDA_CACHE_PATH')))
            evidence=RuntimeEvidence(root,root/'cache',{},environment)
            (root/'cache/cuda/synthetic').write_bytes(b'123')
            evidence.sample('after_native_init');evidence.close()
            rows=[json.loads(line) for line in (root/'runtime.jsonl').read_text().splitlines()]
            self.assertEqual(rows[0]['stage'],'before_native_import')
            self.assertEqual(rows[1]['cache']['cuda'],dict(files=1,bytes=3))
            self.assertEqual(rows[-1]['stage'],'after_model_cleanup')

    def test_final_source_fingerprint_covers_configuration(self):
        identity=source_identity(ROOT,ROOT/'config/sv01_f1.json')
        self.assertIn('config/sv01_f1.json',identity)
        self.assertIn('ui/conversation_ecology/saved-video.js',identity)
        self.assertIn('src/conversation_ecology/saved_video/models.py',identity)


if __name__=='__main__':unittest.main()
