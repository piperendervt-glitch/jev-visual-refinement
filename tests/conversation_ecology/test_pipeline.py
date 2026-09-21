"""PIPE display adapter contracts, synthetic records, no model execution."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from conversation_ecology.pipeline_projection import observation_pipeline,project_pipeline
from conversation_ecology.map_projection import empty_view
from conversation_ecology.map_server import MapApp

def fixture():
    v=empty_view('s','SYNTHETIC_OBSERVATION');v.update(expires_at=9999999999,scope='recorded-media')
    p=dict(run_id='run',session_id='s',epoch=1,available_cursor=1,interval=[0,2])
    es=[dict(cursor=1,kind='input_released',interval=[0,2]),dict(cursor=2,kind='common_input',provenance=p,current=True,common_record=dict(status='recorded',id='input',cursor=7)),dict(cursor=3,kind='analysis_started',analyzer='asr',provenance=p),dict(cursor=4,kind='analysis_completed',analyzer='asr',provenance=p,current=True,result={'secret_body':'must not copy'},common_record=dict(status='recorded',id='result',cursor=9))]
    for e in es:e.update(run_id='run',session_id='s',epoch=1)
    v['nodes']=[dict(id=k,availability='available',record={'acquired_at':42}) for k in ['input','result']]
    live=dict(run_id='run',session_id='s',epoch=1,events=es,queued=0,active=False,status='paused',models={'asr':{'state':'SYNTHETIC_FAKE_NO_MODEL'}})
    return v,live

class PipelineTests(unittest.TestCase):
    def test_PIPE03_explicit_job_refs_and_no_content_copy(self):
        v,live=fixture();original=copy.deepcopy((v,live));p=observation_pipeline(v,live);rows=p['records']
        self.assertEqual(next(r for r in rows if r['stage']=='decode')['source_stage'],'input')
        completed=next(r for r in rows if r['stage']=='analyze' and r['status']=='completed')
        started=next(r for r in rows if r['stage']=='analyze' and r['status']=='running')
        self.assertEqual(completed['parent'],started['id']);self.assertNotIn('must not copy',json.dumps(p));self.assertEqual((v,live),original)
    def test_PIPE03_same_cursor_other_job_not_joined(self):
        v,live=fixture();live['events'][-1]['provenance']=dict(live['events'][-1]['provenance'],interval=[2,4])
        r=next(r for r in observation_pipeline(v,live)['records'] if r['stage']=='analyze' and r['status']=='completed');self.assertIsNone(r['parent']);self.assertIsNone(r['started_at'])
    def test_PIPE04_completion_without_start_and_prepared_not_received(self):
        v,live=fixture();live['events']=[e for e in live['events'] if e['kind']!='analysis_started'];r=next(r for r in observation_pipeline(v,live)['records'] if r['stage']=='analyze');self.assertIsNone(r['parent']);self.assertEqual(r['status'],'completed')
    def test_PIPE05_failed_save_never_projects_success(self):
        v,live=fixture();live['events'][-1]['common_record']={'status':'NOT_RECORDED','reason':'storage_failed'}
        rows=observation_pipeline(v,live)['records'];self.assertTrue(any(r['stage']=='record' and r['status']=='failed' for r in rows));self.assertFalse(any(r['stage']=='project' and r['source_cursor']==4 for r in rows))
    def test_PIPE05_old_epoch_and_cancel_request_not_success(self):
        v,live=fixture();live['epoch']=2;live['events'].append(dict(cursor=5,kind='control',run_id='run',session_id='s',epoch=2,running_completion_pending=True,reason='stopped'))
        rs=observation_pipeline(v,live)['records'];self.assertEqual(rs[-1]['status'],'cancel_requested');self.assertTrue(any(r['status']=='stale' for r in rs));self.assertFalse(any(r['source_stage'] for r in rs if r['media_epoch']==1))
    def test_PIPE06_duplicate_snapshots_are_identical_readonly(self):
        v,live=fixture();self.assertEqual(observation_pipeline(v,live),observation_pipeline(v,live))
    def test_PIPE07_tail_gap_and_bounded_projection_are_distinct(self):
        v,live=fixture();live['events']=live['events'][1:];obs=observation_pipeline(v,live);self.assertTrue(obs['telemetry_gap']);obs['records']*=200;p=project_pipeline(v,obs);self.assertEqual(len(p['records']),512);self.assertGreater(p['omitted_records'],0)
    def test_PIPE10_deleted_reference_is_unavailable_without_animation(self):
        v,live=fixture();v['nodes'][1]['availability']='deleted';p=project_pipeline(v,observation_pipeline(v,live));rs=[r for r in p['records'] if 'result' in r['refs']];self.assertTrue(rs);self.assertTrue(all(r['status']=='unavailable' and r['source_stage'] is None for r in rs))
    def test_PIPE12_observation_never_has_meaning_or_field_transitions(self):
        v,live=fixture();p=project_pipeline(v,observation_pipeline(v,live));self.assertEqual(p['meaning'],'unassessed_observation');self.assertFalse({'evaluate','validate','person','place','conversation'} & {r['stage'] for r in p['records']})
    def test_PIPE15_adapter_error_cannot_change_business_result(self):
        app=MapApp()
        with patch('conversation_ecology.pipeline_projection.project_pipeline',side_effect=ValueError):
            result=app.map_action({'action':'demo'});self.assertEqual(len(result['view']['nodes']),12);self.assertTrue(result['view']['pipeline']['telemetry_gap'])
        self.assertEqual(app.state()['commits'],[])
