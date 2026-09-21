"""SV01 contract tests. Synthetic packets do not count as real ASR/media."""
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'src'))
from conversation_ecology.saved_video.budget import Budget
from conversation_ecology.saved_video.controller import Controller
from conversation_ecology.saved_video.media import Assets, InputPacket, plain_path
from conversation_ecology.saved_video.server import SVBoundary

PROFILE = json.loads((ROOT/'config/sv01.json').read_text())


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)/'campaign.json'
        self.now = [100.]
        self.b = Budget(self.path, PROFILE, lambda:self.now[0])

    def tearDown(self):
        self.b.close()
        self.tmp.cleanup()

    def test_restart_preserves_all_counts(self):
        self.b.release(2)
        self.b.start('asr')
        self.b.close()
        self.b = Budget(self.path, PROFILE, lambda:self.now[0])
        self.assertEqual(self.b.data['media_seconds'], 2)
        self.assertEqual(self.b.data['asr_attempts'], 1)
        self.assertEqual(self.b.data['model_started_at'], 100)

    def test_repeat_media_and_hard_limit(self):
        self.b.release(60)
        self.b.release(60)
        with self.assertRaisesRegex(ValueError, 'budget_media'):
            self.b.release(.001)

    def test_failed_started_attempts_not_refunded(self):
        for _ in range(24):
            self.b.start('asr')
        with self.assertRaisesRegex(ValueError, 'budget_asr'):
            self.b.start('image')

    def test_wall_clock_survives_idle_and_restart(self):
        self.b.start('image')
        self.now[0] += 600
        with self.assertRaisesRegex(ValueError, 'budget_model_wall'):
            self.b.release(1)

    def test_second_campaign_owner_denied(self):
        with self.assertRaises(FileExistsError):
            Budget(self.path, PROFILE)


class AssetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.assets = Assets(Path(self.tmp.name)/'uploads', PROFILE)

    def tearDown(self):
        self.assets.close()
        self.tmp.cleanup()

    def test_same_bytes_opaque_and_cleanup(self):
        with patch('conversation_ecology.saved_video.media.probe', return_value={'decoder':'synthetic'}):
            ident = self.assets.import_stream(io.BytesIO(b'abc'), 3, '.mp4')
        item = self.assets.get(ident)
        self.assertEqual(item['path'].read_bytes(), b'abc')
        self.assertEqual(item['sha256'], 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad')
        self.assertNotIn('path', self.assets.public()[0])
        with self.assertRaisesRegex(ValueError, 'unknown_asset'):
            self.assets.get('../../secret')

    def test_size_and_format_before_read(self):
        for size, suffix, reason in [(0,'.mp4','size'),(PROFILE['max_asset_bytes']+1,'.mp4','size'),(3,'.exe','unsupported')]:
            with self.assertRaisesRegex(ValueError, reason):
                self.assets.import_stream(io.BytesIO(b'abc'), size, suffix)

    def test_cancel_removes_partial(self):
        with self.assertRaisesRegex(ValueError, 'upload_cancelled'):
            self.assets.import_stream(io.BytesIO(b'ab'), 4, '.mp4')
        self.assertEqual(list(self.assets.root.iterdir()), [])

    def test_probe_failure_removes_copy(self):
        with patch('conversation_ecology.saved_video.media.probe', side_effect=ValueError('corrupt')):
            with self.assertRaisesRegex(ValueError, 'corrupt'):
                self.assets.import_stream(io.BytesIO(b'bad'), 3, '.mp4')
        self.assertEqual(list(self.assets.root.iterdir()), [])

    def test_retention_refuses_expired(self):
        self.assets.created -= PROFILE['retention_seconds']
        with self.assertRaisesRegex(ValueError, 'expired'):
            self.assets.get('anything')


class FakeAssets:
    def get(self, ident):
        if ident not in ('a','b'):
            raise ValueError('unknown_asset')
        return dict(id=ident, duration=90, decoder='ready')
    def public(self): return []
    def close(self): pass


class FakeModels:
    status = {'asr':{'state':'synthetic'}, 'image':{'state':'synthetic'}}
    def __init__(self):
        self.started = threading.Event()
        self.proceed = threading.Event()
        self.proceed.set()
        self.calls = []
    def available(self, kind): return True
    def infer(self, kind, packet):
        self.started.set()
        self.proceed.wait(3)
        self.calls.append((kind,packet.provenance))
        return {'synthetic':True}
    def close(self): pass


class FakeDecoder:
    def decode(self, asset, start, end, envelope):
        return InputPacket(dict(**envelope, asset_id=asset['id'], interval=[start,end],
                                root=f"{asset['id']}:{start}:{end}"), object(), [0.1]*16)


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.b = Budget(Path(self.tmp.name)/'campaign.json', PROFILE)
        self.m = FakeModels()
        self.c = Controller(FakeAssets(),self.b,self.m,PROFILE,FakeDecoder())
        self.cmd('select', asset_id='a')

    def tearDown(self):
        self.m.proceed.set()
        self.c.close()
        self.tmp.cleanup()

    def cmd(self, action, **values):
        return self.c.command(dict(action=action,asset_id=self.c.asset_id,epoch=self.c.epoch,**values) if 'asset_id' not in values
                              else dict(action=action,epoch=self.c.epoch,**values), 's1')

    def release(self, start=0., end=2.):
        self.cmd('play')
        self.c.last_tick -= end-start
        self.cmd('release',start=start,end=end)

    def drain(self):
        self.c.jobs.join()

    def test_pause_rejects_future_release(self):
        self.release()
        self.cmd('pause')
        with self.assertRaisesRegex(ValueError,'not_playing'):
            self.cmd('release',start=2,end=3)
        self.assertEqual(self.c.position,2)

    def test_seek_gap_never_submitted(self):
        self.release()
        self.drain()
        self.cmd('seek',position=60)
        self.release(60,62)
        self.drain()
        intervals=[e['interval'] for e in self.c.events if e['kind']=='input_released']
        self.assertEqual(intervals,[[0.,2.],[60.,62.]])

    def test_clock_jump_and_nonfinite_denied(self):
        self.cmd('play')
        for start,end,reason in [(0,2,'clock_jump'),(0,float('nan'),'invalid_position'),(2,3,'noncontinuous')]:
            with self.assertRaisesRegex(ValueError,reason):
                self.cmd('release',start=start,end=end)

    def test_old_result_is_history_only_and_second_analyzer_cancelled(self):
        self.m.proceed.clear()
        self.release()
        self.assertTrue(self.m.started.wait(1))
        self.cmd('select',asset_id='b')
        self.m.proceed.set()
        self.drain()
        result=next(e for e in self.c.events if e['kind']=='analysis_completed')
        self.assertFalse(result['current'])
        self.assertEqual(result['provenance']['asset_id'],'a')
        self.assertEqual(len(self.m.calls),1)

    def test_revisit_same_physical_root(self):
        self.release()
        self.drain()
        self.cmd('seek',position=0)
        self.release()
        self.drain()
        packets=[e['provenance'] for e in self.c.events if e['kind']=='common_input']
        self.assertEqual(packets[0]['root'],packets[1]['root'])
        self.assertNotEqual(packets[0]['epoch'],packets[1]['epoch'])
        self.assertEqual(self.b.data['media_seconds'],4)

    def test_queue_saturation_backpressure_and_stop(self):
        self.m.proceed.clear()
        self.release()
        self.assertTrue(self.m.started.wait(1))
        self.release(2,4)
        self.release(4,6)
        with self.assertRaisesRegex(ValueError,'queue_full'):
            self.release(6,8)
        self.assertEqual(self.b.data['media_seconds'],6)
        self.cmd('stop')
        self.assertEqual(self.c.jobs.qsize(),0)
        self.m.proceed.set()
        self.drain()
        self.assertEqual(len(self.m.calls),1)

    def test_eof_no_new_release_and_stop_actual_worker_join(self):
        self.release()
        self.cmd('eof')
        with self.assertRaisesRegex(ValueError,'not_playing'):
            self.cmd('release',start=2,end=3)
        self.drain()
        self.c.stop_admission()
        with self.assertRaisesRegex(ValueError,'closed'):
            self.cmd('play')

    def test_session_change_invalidates_old_request(self):
        old=self.c.epoch
        with self.assertRaisesRegex(ValueError,'stale_source'):
            self.c.command(dict(action='play',epoch=old,asset_id='a'),'s2')
        self.assertIsNone(self.c.asset_id)

    def test_eof_drains_to_ended_and_rejects_seek_past_end(self):
        self.release()
        self.cmd('eof')
        self.drain()
        self.assertEqual(self.c.status,'ended')
        with self.assertRaisesRegex(ValueError,'seek_past_eof'):
            self.cmd('seek',position=91)

    def test_current_projection_changes_without_rewriting_arrival(self):
        self.release()
        self.drain()
        self.cmd('seek',position=0)
        rows=[e for e in self.c.view()['events'] if e['kind']=='analysis_completed']
        self.assertTrue(all(e['current_at_arrival'] for e in rows))
        self.assertTrue(all(not e['current'] for e in rows))


class BoundaryTests(unittest.TestCase):
    def test_network_device_secret_and_subprocess_denied(self):
        b=SVBoundary()
        for event,args in [('socket.connect',(None,('example.com',443))),('socket.bind',(None,('0.0.0.0',1))),
                           ('open',('C:/x/.env',)),('open',('//./camera',)),('import',('sounddevice',)),
                           ('subprocess.Popen',('ignored',))]:
            with self.assertRaises(PermissionError):b.guard(event,args)
        b.guard('socket.connect',(None,('127.0.0.1',123)))


if __name__ == '__main__': unittest.main()
