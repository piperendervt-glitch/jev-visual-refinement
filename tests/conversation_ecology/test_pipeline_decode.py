"""New generated media -> real decoder -> fake analyzer -> common SQLite.

This is a backend contract test, not browser playback or learned inference.
"""
import copy
import io
from pathlib import Path
import tempfile
import unittest
import test_saved_video_decode as generated
from test_saved_video import PROFILE, FakeModels
from conversation_ecology.saved_video.media import Assets
from conversation_ecology.saved_video.controller import Controller
from conversation_ecology.saved_video.budget import Budget
from conversation_ecology.saved_video.map_bridge import BridgeApp


class PipelineDecode(unittest.TestCase):
    def test_PIPE12_real_decode_fake_results_record_projection_and_cleanup(self):
        maker=generated.DecodeTests();maker.setUp()
        try:
            source=maker.make();data=source['path'].read_bytes()
            with tempfile.TemporaryDirectory() as directory:
                root=Path(directory);assets=Assets(root/'uploads',PROFILE)
                ident=assets.import_stream(io.BytesIO(data),len(data),'.mkv')
                app=BridgeApp(root/'context.sqlite','pipeline-synthetic-only','SYNTHETIC_TEST',synthetic=True)
                models=FakeModels();controller=Controller(assets,Budget(root/'budget.json',PROFILE),models,PROFILE,observer=app.bridge)
                app.sv=controller
                try:
                    session=app.engine.session_id
                    controller.command(dict(action='select',asset_id=ident),session)
                    controller.command(dict(action='play',asset_id=ident,epoch=controller.epoch),session)
                    controller.last_tick-=2  # Fixture wall time; not a claim of UI playback.
                    controller.command(dict(action='release',asset_id=ident,epoch=controller.epoch,start=0,end=2),session)
                    controller.jobs.join()
                    self.assertEqual([kind for kind,_ in models.calls],['asr','image'])
                    before=copy.deepcopy(controller.view())
                    result=app.map_state()['view'];rows=result['pipeline']['records']
                    self.assertEqual(result['mode'],'SYNTHETIC_OBSERVATION')
                    self.assertEqual(len([r for r in rows if r['stage']=='record' and r['status']=='completed']),3)
                    self.assertEqual(len([r for r in rows if r['stage']=='project' and r['status']=='projected']),3)
                    self.assertTrue(any(r['stage']=='decode' and r['source_stage']=='input' for r in rows))
                    self.assertTrue(any(r['stage']=='analyze' and r['source_stage']=='decode' for r in rows))
                    self.assertFalse(any(r['stage'] in ('evaluate','validate','person','place','conversation','ack') for r in rows))
                    after=controller.view()
                    self.assertEqual(before['events'],after['events'])
                    self.assertEqual(before['epoch'],after['epoch'])
                    self.assertEqual(before['released_position'],after['released_position'])
                    for n in result['nodes']:
                        if n.get('record'):
                            self.assertEqual(n['record']['assessment'],'pending_evaluation')
                            self.assertIsNone(n['mass']['value'])
                            self.assertEqual(n['mass']['status'],'not_evaluated')
                    unknowns=[n for n in result['nodes'] if n['kind']=='Unknown']
                    self.assertEqual(len(unknowns),3)
                    self.assertTrue(all(n['mass']['value']==1 and n['display_only'] for n in unknowns))
                    for table in ('context_commits','response_commits','acknowledgements'):
                        self.assertEqual(app.store.db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0],0)
                    controller.command(dict(action='seek',asset_id=ident,epoch=controller.epoch,position=0),session)
                    later=app.map_state()['view']['pipeline']['records']
                    self.assertFalse(any(r['stage']=='project' and r['status']=='projected' for r in later))
                finally:
                    controller.close();app.store.stop();app.store.close()
                self.assertFalse(controller.worker.is_alive());self.assertTrue(app.store.closed)
                self.assertFalse((root/'uploads').exists())
        finally:maker.tearDown()


if __name__=='__main__':unittest.main()
