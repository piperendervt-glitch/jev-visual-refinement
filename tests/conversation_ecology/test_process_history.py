"""Read-only history producer -> paging -> detail/save references, no models."""
import copy
from types import SimpleNamespace
from pathlib import Path
import tempfile
import threading
import time
import unittest
from test_map_saved_video import event
from conversation_ecology.context.observations import ObservationStore,ObservationBridge
from conversation_ecology.saved_video.history import summary,history_page,history_detail
from conversation_ecology.player_template import dock_player
from test_saved_video import ROOT


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=ObservationStore(Path(self.tmp.name)/'state.sqlite',synthetic=True)
        self.sv=SimpleNamespace(lock=threading.RLock(),status='paused',run_id='source-run',events=[],cursor=0,session='s',epoch=1,asset_id='opaque')
        self.app=SimpleNamespace(sv=self.sv,store=self.store,history_projection={})
    def tearDown(self):self.store.close();self.tmp.cleanup()
    def add(self,e):
        e=copy.deepcopy(e);e.setdefault('analyzer','asr');self.sv.events.append(e);self.sv.cursor=e['cursor']
        result=ObservationBridge(self.store,'integration','SYNTHETIC_ONLY')(e)
        if result:e['common_record']=result
        return e
    def test_result_original_excerpt_empty_not_silence_and_image_untrusted(self):
        e=event(2,'analysis_completed');e['result']['transcript_original']='x'*201
        s=summary(e);self.assertEqual(len(s['excerpt']),180);self.assertTrue(s['excerpt_omitted']);self.assertNotIn('result',s)
        e['result']['transcript_original']='';self.assertTrue(summary(e)['output_empty'])
        e['result']={'observation_untrusted':'<script>image output</script>'};self.assertEqual(summary(e)['excerpt'],e['result']['observation_untrusted'])
    def test_input_result_sqlite_projection_and_existing_dom_checkpoint(self):
        a=self.add(event());b=self.add(event(2,'analysis_completed'))
        layer=self.store.snapshot('s','recorded-media');self.app.history_projection['s']={'cursor':2,'layer_view_id':layer.id}
        self.store.notify('observation-map:s',2)
        before=self.store.db.total_changes
        d=history_detail(self.app,'source-run',2)
        self.assertEqual(d['saved_record']['value']['source_refs'],[a['common_record']['id']])
        self.assertEqual(d['event']['result'],b['result']);self.assertEqual(len(d['related']),2)
        self.assertTrue(d['map_dom_application']['covers_record']);self.assertEqual(d['projection']['layer_view_id'],layer.id)
        self.assertEqual(self.store.db.total_changes,before)
    def test_paging_gap_dedupe_reset_bounded_without_copying_full_results(self):
        self.sv.events=[dict(cursor=i,kind='control',run_id='source-run',epoch=1) for i in range(100,4100)];self.sv.cursor=4099
        p=history_page(self.app,10,'source-run');self.assertEqual(p['gap'],89);self.assertEqual(len(p['events']),128)
        self.assertEqual(history_page(self.app,p['next'],'source-run')['events'][0]['cursor'],228)
        self.assertEqual(history_page(self.app,4099,'source-run')['events'],[])
        self.assertTrue(history_page(self.app,4099,'old-run')['reset'])
    def test_missing_evicted_expired_and_old_epoch_separate(self):
        e=self.add(event());e['current']=False
        self.assertFalse(history_page(self.app)['events'][0]['current'])
        self.assertIn('unavailable',history_detail(self.app,'other',1))
        self.sv.events=[];self.assertIn('unavailable',history_detail(self.app,'source-run',1))
        self.sv.status='retention_expired';self.assertTrue(history_page(self.app)['expired'])
        self.assertIn('unavailable',history_detail(self.app,'source-run',1))
    def test_deleted_source_does_not_reexpose_retained_event_content(self):
        a=self.add(event());b=self.add(event(2,'analysis_completed'))
        self.store.redact('s','recorded-media',b['common_record']['id'])
        d=history_detail(self.app,'source-run',2)
        self.assertIn('unavailable',d);self.assertNotIn('event',d);self.assertNotIn('saved_record',d)
    def test_single_player_outside_drawer_with_controls_no_upper_edits(self):
        ui=ROOT/'ui/conversation_ecology';html=dock_player((ui/'map.html').read_text(encoding='utf-8'),(ui/'saved-video.html').read_text(encoding='utf-8'))
        self.assertEqual(html.count('<video '),1)
        self.assertNotIn('<video ',html.split('<dialog id="media-dialog">')[1].split('</dialog>')[0])
        self.assertIn('id="sv-range"',html.split('id="video-dock"')[1].split('</section>')[0])

if __name__=='__main__':unittest.main()
