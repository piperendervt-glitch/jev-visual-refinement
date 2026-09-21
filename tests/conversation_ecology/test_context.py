"""MAP-CTX-01 mechanical acceptance. No real models, old runner or private media."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'));sys.path.insert(1,str(ROOT))
from conversation_ecology.context.model import ContextUpdateProposal, validate_record
from conversation_ecology.context.store import ContextStore
from conversation_ecology.context.commits import ContextCommitter
from conversation_ecology.context.dependencies import DependencyIndex, RecheckPlanner
from conversation_ecology.context.output_adapter import OutputAdapter
from conversation_ecology.context.retention import purge_run
from conversation_ecology.context.boundary import ContextBoundary
from conversation_ecology.context.provider import ContextProvider
from conversation_ecology.hearing.coordinator import HearingCoordinator
from conversation_ecology.hearing.evaluation import compare, choose_goal


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT/'artifacts')
        self.path=Path(self.tmp.name)/'state.sqlite';self.s=ContextStore(self.path)
        self.c=HearingCoordinator(self.s,'s');self.c.start()
    def tearDown(self):
        if not self.s.closed:self.s.close()
        self.tmp.cleanup()
    def proposal(self,key='p',ident='entity:new',label='New entity'):
        refs=['utterance:1',ident];v=self.s.snapshot('s','participant-a',refs=refs);self.s.register_projection(v)
        self.s.ingress('s','participant-a','ev:'+key,dict(kind='evaluation',label='合成',status='VALID',projection_id=v.id))
        return ContextUpdateProposal(key,'s','participant-a',v.id,'entity_register',v.data()['read_set'],
            {ident:dict(kind='entity',label=label)}, {ident:self.s.version('s','participant-a',ident)},('utterance:1',),'ev:'+key,time.monotonic()+2)


class ContextContracts(Base):
    def test_CTX01_shared_reference_layers_immutable(self):
        view=self.s.snapshot('s','participant-a');d=view.data();self.assertIn('utterance:1',d['layers']['L1']);self.assertIn('utterance:1',d['layers']['L4'])
        d['items']['utterance:1']['value']['label']='mutated';self.assertNotEqual(view.data()['items']['utterance:1']['value']['label'],'mutated')
        self.assertEqual(set(d['layers']),{'L0','L1','L2','L3','L4','L5'})
    def test_CTX02_scope_same_label_isolation(self):
        self.s.ingress('s','other','utterance:1',dict(kind='source',label='private-synthetic'))
        self.assertNotIn('private-synthetic',self.s.snapshot('s','participant-a').canonical)
        p=self.proposal();self.assertEqual(ContextCommitter(self.s).apply(replace(p,scope='other'))['status'],'REJECTED')
    def test_CTX03_types_values_confirmation_separate(self):
        self.c.reply('動画側で、メモリを減らしたい','r')
        claim=self.c.item('claim:preference')['value'];self.assertEqual(claim['claim_kind'],'preference');self.assertEqual(claim['content_confirmation'],'confirmed')
        self.assertEqual(self.c.item('goal:main')['value']['authority'],'denied')
        self.c.background();fact=self.c.item('fact:brightness')['value'];self.assertEqual(fact['unit'],'fixture_level');self.assertEqual(fact['provider'],'synthetic_program')
    def test_CTX04_independent_background_preserves_inputs(self):
        p=self.proposal();self.c.background();self.assertEqual(ContextCommitter(self.s).apply(p)['status'],'APPLIED')
        states={r['id']:r['state'] for r in self.s.db.execute('SELECT * FROM consumers')};self.assertEqual(states['s:job:background'],'QUEUED')
    def test_CTX05_reference_correction_invalidates(self):
        p=self.proposal();self.c.correct();self.assertEqual(ContextCommitter(self.s).apply(p)['status'],'VERSION_CONFLICT')
        self.assertEqual(self.c.reply('動画解析の方です','r')['status'],'STALE_QUESTION')
        self.assertEqual(len(ContextProvider(self.c).snapshot()['responses']),1)
    def test_CTX06_missing_and_set_version(self):
        p=self.proposal();other=replace(p,update_key='second')
        self.assertEqual(ContextCommitter(self.s).apply(p)['status'],'APPLIED');self.assertEqual(ContextCommitter(self.s).apply(other)['status'],'VERSION_CONFLICT')
        self.s.ingress('s','participant-a','set:candidates',dict(kind='set',label='候補集合',members=['a'],membership_rule_version=1))
        v=self.s.snapshot('s','participant-a',refs=['set:candidates']);self.assertEqual(v.data()['read_set']['set:candidates'],1)
        self.s.ingress('s','participant-a','set:candidates',dict(kind='set',label='候補集合',members=['a','b'],membership_rule_version=1))
        self.assertEqual(self.s.version('s','participant-a','set:candidates'),2)
    def test_CTX07_finite_recheck_scope_and_dedup(self):
        planner=RecheckPlanner();goals=[dict(id=f'g{i}',session='s',scope='a',consumers=[f'c{k}' for k in range(9)]) for i in range(5)]
        result=planner.recheck('change',goals,'s','a');self.assertEqual(len(result),32);self.assertEqual(len(planner.queue),8)
        self.assertEqual(planner.skipped['goal_limit'],1);self.assertEqual(planner.skipped['consumer_limit'],4)
        self.assertEqual(planner.recheck('change',goals,'s','a'),[]);self.assertEqual(planner.recheck('other',goals,'s','b'),[])
    def test_CTX08_same_key_same_payload_no_extra_commit(self):
        p=self.proposal();committer=ContextCommitter(self.s);a=committer.apply(p);before=self.s.db.execute('SELECT COUNT(*) FROM events').fetchone()[0]
        b=committer.apply(p);self.assertEqual(b['status'],'ALREADY_APPLIED');self.assertEqual(a['commit_id'],b['commit_id']);self.assertEqual(before,self.s.db.execute('SELECT COUNT(*) FROM events').fetchone()[0])
    def test_CTX09_same_key_different_payload_conflict(self):
        p=self.proposal();committer=ContextCommitter(self.s);committer.apply(p)
        q=replace(p,writes={'entity:new':dict(kind='entity',label='different')});self.assertEqual(committer.apply(q)['status'],'KEY_CONFLICT');self.assertEqual(self.s.item('s','participant-a','entity:new')['value']['label'],'New entity')
    def test_CTX11_concurrent_same_expected_version(self):
        p=self.proposal();q=replace(p,update_key='race');results=[]
        def commit(x):results.append(ContextCommitter(self.s).apply(x)['status'])
        threads=[threading.Thread(target=commit,args=(x,)) for x in (p,q)]
        for t in threads:t.start()
        for t in threads:t.join()
        self.assertCountEqual(results,['APPLIED','VERSION_CONFLICT'])
    def test_CTX13_commit_boundaries_recovery(self):
        p=self.proposal()
        self.s.fault=lambda stage: (_ for _ in ()).throw(sqlite3.OperationalError('disk full fixture')) if stage=='before_commit' else None
        self.assertEqual(ContextCommitter(self.s).apply(p)['status'],'STORAGE_FAILED');self.assertIsNone(self.s.item('s','participant-a','entity:new'))
        self.s.fault=lambda stage: (_ for _ in ()).throw(sqlite3.OperationalError('notify lost fixture')) if stage=='after_commit_before_notify' else None
        self.assertEqual(ContextCommitter(self.s).apply(p)['status'],'COMMIT_UNCERTAIN')
        self.s.fault=lambda _:None;self.s.close();self.s=ContextStore(self.path,create=False)
        self.assertEqual(ContextCommitter(self.s).apply(p)['status'],'ALREADY_APPLIED');self.assertGreater(self.s.db.execute('SELECT COUNT(*) FROM notification_outbox WHERE delivered=0').fetchone()[0],0)
        self.s.rebuild();self.assertEqual(self.s.item('s','participant-a','entity:new')['revision'],1)
    def test_CTX14_cutoff_and_cursor_two_conditions(self):
        before=self.s.snapshot('s','participant-a').data()['available_cursor']
        self.s.ingress('s','participant-a','late',dict(kind='source',label='late'),cutoff=4)
        self.assertNotIn('late',self.s.snapshot('s','participant-a',cutoff=3).data()['items'])
        self.assertNotIn('late',self.s.snapshot('s','participant-a',cutoff=5,cursor=before).data()['items'])
        self.assertIn('late',self.s.snapshot('s','participant-a',cutoff=5).data()['items'])
    def test_CTX15_reply_only_binding_local_changes(self):
        independent=self.c.item('goal:independent');before=self.c.item('goal:main')['value'];result=self.c.reply('動画解析の方です','r')
        self.assertEqual(result['status'],'APPLIED');self.assertEqual(result['affected'],['s:job:target']);self.assertEqual(self.c.item('goal:independent'),independent)
        after=self.c.item('goal:main')['value'];self.assertEqual(after['target_binding'],'video')
        for k in ('preference','budget','deadline','authority'):self.assertEqual(after[k],before[k])
    def test_CTX16_reply_not_source_revision(self):
        self.c.reply('会話処理の方です','r');self.assertEqual(self.c.item('utterance:1')['revision'],1);self.assertEqual(self.c.item('reply:r')['value']['revision_kind'],'reply')
    def test_CTX17_yes_and_compound(self):
        self.c.reply('はい','yes');self.assertIsNone(self.c.item('goal:main')['value']['target_binding'])
        self.c.reply('動画側で、メモリを減らしたい','compound')
        a=self.c.item('claim:target');b=self.c.item('claim:preference');self.assertEqual(a['cursor'],b['cursor']);self.assertEqual(a['value']['source_refs'],b['value']['source_refs'])
    def test_CTX18_stop_scope_and_protected_write(self):
        p=self.proposal();bad=replace(p,update_key='forbidden',update_kind='L0_grant');self.assertEqual(ContextCommitter(self.s).apply(bad)['status'],'REJECTED')
        self.s.stop();self.assertEqual(ContextCommitter(self.s).apply(p)['status'],'STOPPED')
    def test_CTX19_response_context_counts_and_ack_unique(self):
        out=OutputAdapter(self.s);responses=out.deliver('s','participant-a');self.assertEqual(len(responses),1);cid=responses[0]['id']
        self.assertTrue(out.acknowledge('s','participant-a',cid,'test-only','synthetic_test'));self.assertFalse(out.acknowledge('s','participant-a',cid,'test-only','synthetic_test'))
        self.c.reply('動画解析の方です','r');self.assertEqual(out.deliver('s','participant-a'),responses)
        with self.assertRaises(ValueError):out.acknowledge('s','other',cid,'test-only','synthetic_test')
    def test_CTX20_projection_detached_from_semantic_state(self):
        before=self.s.snapshot('s','participant-a').canonical;v=ContextProvider(self.c).snapshot();v['nodes'][0]['label']='UI only';self.assertEqual(self.s.snapshot('s','participant-a').canonical,before)
    def test_CTX21_delete_invalidates_reuse_replay(self):
        self.c.reply('動画解析の方です','r');self.s.redact('s','participant-a','reply:r')
        self.assertEqual(self.c.item('claim:target')['availability'],'unavailable');self.assertEqual(self.s.replay('s','participant-a')['status'],'incomplete')
    def test_CTX22_caps_stop_and_late(self):
        p=RecheckPlanner()
        for i in range(10000):p.add(str(i),list(p.CAPS)[i%4])
        self.assertEqual(len(p.descriptors),256);self.assertEqual(len(p.queue),64);p.stop();self.assertEqual(p.queue,[]);self.assertEqual(p.add('late'),'STOPPED')
    def test_CTX23_evaluation_intervention_changes_question(self):
        fixture=deepcopy(self.c.fixture)
        fixture['questions'][0]['scores']=dict.fromkeys(('task_fit','context_fit','timing_fit'),1)
        other=HearingCoordinator(self.s,'other',fixture=fixture);other.start()
        self.assertNotEqual(self.c.item('question:target')['value']['candidate_id'],other.item('question:target')['value']['candidate_id'])
    def test_unknown_schema_rejected_without_migration(self):
        self.s.db.execute("UPDATE meta SET value='future' WHERE key='schema'");self.s.close()
        with self.assertRaisesRegex(ValueError,'unknown_schema'):ContextStore(self.path,create=False)
    def test_retention_boundary_and_run_purge(self):
        root=Path(self.tmp.name)/'retention';run=root/'test';store=ContextStore(run/'state.sqlite',clock=lambda:100)
        with self.assertRaisesRegex(ValueError,'retention_not_expired'):purge_run(run,root,now=100)
        store.close();self.assertEqual(purge_run(run,root,now=100+7*86400)['removed'],['state.sqlite']);self.assertFalse(run.exists())
    def test_expiry_control_and_readset_tamper(self):
        p=self.proposal();self.assertEqual(ContextCommitter(self.s,clock=lambda:p.deadline).apply(p)['status'],'APPLIED')
        q=self.proposal('q','another');self.assertEqual(ContextCommitter(self.s,clock=lambda:q.deadline+.001).apply(q)['status'],'EXPIRED')
        r=self.proposal('r','third');self.assertEqual(ContextCommitter(self.s).apply(replace(r,read_set={}))['status'],'REJECTED')
    def test_missing_evaluation_and_projection_rebinding(self):
        p=self.proposal();self.assertEqual(ContextCommitter(self.s).apply(replace(p,evaluation_id=None))['status'],'PENDING_EVALUATION')
        p2=self.proposal('p2','other');self.assertEqual(ContextCommitter(self.s).apply(replace(p2,evaluation_id=p.evaluation_id))['status'],'REJECTED')
    def test_atomic_binding_mismatch_rejects_all(self):
        p=self.proposal();writes={'goal:main':dict(self.c.item('goal:main')['value'],target_binding='video'),'question:target':dict(self.c.item('question:target')['value'],resolved_target='conversation',reply_ref='utterance:1')}
        result=self.c.update('mismatch',writes,'goal_binding_resolve',['utterance:1']);self.assertEqual(result['status'],'REJECTED');self.assertIsNone(self.c.item('goal:main')['value']['target_binding'])
    def test_shared_subscriber_prune_and_fairness(self):
        p=RecheckPlanner();p.add('child');p.subscribe('child','a');p.subscribe('child','b');self.assertEqual(p.prune('child','a'),'QUEUED');self.assertEqual(p.prune('child','b'),'cancelled_before_start')
        for n in range(10):p.add(str(n),protected=n==9)
        p.dispatches['background']=9;self.assertEqual(p.dispatch('background',0),'9')
    def test_context_boundary_closure_and_secrets(self):
        b=ContextBoundary();b.guard('import',('context_fields.fields',))
        for name in ('context_fields.session','torch','av'):
            with self.assertRaises(PermissionError):b.guard('import',(name,))
        with self.assertRaises(PermissionError):b.guard('open',('.env',))
        with self.assertRaises(PermissionError):b.guard('socket.connect',(None,('example.invalid',443)))


class HearingContracts(Base):
    def test_H01_H02_H03_H04_H05_all_axes_and_no_average(self):
        f=self.c.fixture;result=compare(f['previews'],f['axes'],'p')
        self.assertEqual(result['unit_count'],4);self.assertEqual(result['primitive_questions'],8)
        self.assertEqual({r['axis'] for r in result['axes']},{'target','operation','references','deliverable'})
        self.assertEqual({r['dependency_key'] for r in result['axes'] if r['impact']>=3},{'target_binding'})
        previews=deepcopy(f['previews']);previews[1]['target']=previews[0]['target'];self.assertEqual(compare(previews,f['axes'],'p'),result)
    def test_H06_invalid_missing_ambiguous_preserved(self):
        f=self.c.fixture
        for replacement,status in [(None,'not_evaluated'),({'relation':'ambiguous','impact':4},'ambiguous'),({'relation':'equivalent','impact':4},'evaluation_conflict'),({'relation':'materially_different','impact':0},'evaluation_conflict')]:
            rows=deepcopy(f['axes']);rows['pv-a|pv-b|target']=replacement;r=compare(f['previews'],rows,'p');self.assertEqual(r['axes'][0]['status'],status);self.assertEqual(r['status'],'PENDING')
    def test_H07_same_projection_no_response_dependency(self):
        result=compare(self.c.fixture['previews'],self.c.fixture['axes'],'projection-fixed');self.assertEqual({x['projection_id'] for x in result['axes']},{'projection-fixed'})
    def test_H08_explicit_no_ask(self):
        c=HearingCoordinator(self.s,'explicit');c.start(True);self.assertIsNone(c.item('question:target'));self.assertEqual(c.item('goal:main')['value']['target_binding'],'video')
    def test_H09_H18_background_no_requestion(self):
        before=self.c.item('question:target');self.c.background();self.assertEqual(before,self.c.item('question:target'));self.assertEqual(len(ContextProvider(self.c).snapshot()['responses']),1)
    def test_H10_required_missing_and_H25_internal_differences(self):
        goals=deepcopy(self.c.fixture['goals']);self.assertIsNotNone(choose_goal(goals));goals[0]['user_gap']=None;self.assertIsNone(choose_goal(goals))
    def test_H12_H13_H14_reply_semantics(self):
        self.c.reply('はい','r0');self.assertIsNone(self.c.item('goal:main')['value']['target_binding'])
        self.c.reply('動画解析の方です','r1');self.assertEqual(self.c.item('goal:main')['value']['target_binding'],'video');self.assertIsNone(self.c.item('goal:main')['value']['preference'])
    def test_H15_interpretation_correction_retains_observation(self):
        self.s.ingress('s','participant-a','audio:1',dict(kind='fact',label='合成音声観測',value='music',unit='fixture',provider='synthetic_program',acquired_at=0))
        fact=self.c.item('audio:1')
        claim=dict(kind='claim',label='映画を見ているという推測',claim_kind='interpretation',entity_ref='person:a',predicate='activity',typed_value='watching_movie',source_refs=['audio:1'],evidence_state='supported',use_state='adopted',content_confirmation='unconfirmed')
        self.assertEqual(self.c.update('infer',{'claim:movie':claim},'claim_add',['audio:1'])['status'],'APPLIED')
        self.c.index.register('movie-job','s','participant-a','goal:main',{'claim:movie':1},'HELD')
        result=self.c.deny_interpretation('claim:movie','映画は見ていません','denial')
        self.assertEqual(result['status'],'APPLIED');self.assertIn('movie-job',result['affected'])
        self.assertEqual(self.c.item('audio:1'),fact);self.assertEqual(self.c.item('claim:movie')['value']['use_state'],'excluded')
        self.assertEqual(self.c.item('claim:movie')['value']['content_confirmation'],'denied')
    def test_H16_H17_correction_and_new_answer(self):
        self.c.reply('分からない','r');self.assertEqual(self.c.item('question:target')['value']['branch_state'],'DEFERRED');self.assertEqual(self.c.item('utterance:1')['revision'],1)
        self.c.correct();self.assertEqual(self.c.item('question:target')['value']['branch_state'],'SUPERSEDED')
    def test_H19_H20_scope_and_independent_job(self):
        self.c.reply('後で','r');self.assertEqual(self.s.db.execute("SELECT state FROM consumers WHERE id='s:job:background'").fetchone()[0],'QUEUED')
        self.assertEqual(self.s.snapshot('s','other').data()['items'],{})
    def test_H21_prohibition_not_bypassed(self):
        self.c.reply('両方','r');self.assertEqual(self.c.item('goal:main')['value']['authority'],'denied');self.assertIsNone(self.c.item('goal:main')['value']['target_binding'])
    def test_H22_repeated_reply_same_commit(self):
        a=self.c.reply('動画解析の方です','r');b=self.c.reply('動画解析の方です','r');self.assertEqual(a['commit_id'],b['commit_id']);self.assertEqual(b['status'],'ALREADY_APPLIED')
    def test_H23_three_previews_accounting(self):
        previews=self.c.fixture['previews']+[dict(self.c.fixture['previews'][0],id='pv-c')];r=compare(previews,self.c.fixture['axes'],'p');self.assertEqual((r['unit_count'],r['primitive_questions'],r['packet_count'],r['http_sends']),(12,24,2,0));self.assertEqual(r['status'],'PENDING')
    def test_H24_replay_no_network_new_evaluation(self):
        self.c.reply('動画解析の方です','r');before=self.s.replay('s','participant-a');self.s.close();self.s=ContextStore(self.path,create=False);after=self.s.replay('s','participant-a');self.assertEqual(before,after)
    def test_goal_evaluation_changes_ask_not_scenario_name(self):
        fixture=deepcopy(self.c.fixture);fixture['goals'][0]['disposition']='proceed_without_asking';c=HearingCoordinator(self.s,'no-ask',fixture=fixture);c.start();self.assertIsNone(c.item('question:target'))
    def test_reply_unrecognized_no_general_understanding(self):
        self.c.reply('任意の別の文章','r');self.assertEqual(self.c.item('question:target')['value']['branch_state'],'UNCONFIRMED');self.assertIsNone(self.c.item('goal:main')['value']['target_binding'])
    def test_alternate_target_and_multi_target_candidate(self):
        self.c.reply('両方','both');self.assertEqual(self.c.item('question:target')['value']['multi_target_candidate'],['video','conversation'])
        self.c.reply('違う。字幕の方','other');self.assertEqual(self.c.item('goal:main')['value']['target_binding'],'subtitle')


if __name__=='__main__':unittest.main()
