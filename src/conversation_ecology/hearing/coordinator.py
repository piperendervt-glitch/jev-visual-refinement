"""Vertical fixture: one shared LayerView, recorded evaluation and atomic reply resolution."""
from copy import deepcopy
import json
from pathlib import Path
import time
from types import SimpleNamespace
import uuid
from ..evaluation import validate
from ..context.model import ContextUpdateProposal, encoded
from ..context.commits import ContextCommitter
from ..context.output_adapter import OutputAdapter, choose
from ..context.dependencies import DependencyIndex, RecheckPlanner, select_planned_job
from .evaluation import compare, choose_goal
from .accounting import FixtureAccounting

FIXTURE=Path(__file__).resolve().parents[3]/'fixtures/conversation_ecology/context_hearing.json'


class HearingCoordinator:
    def __init__(self,store,session,scope='participant-a',fixture=None):
        self.store=store;self.session=session;self.scope=scope;self.fixture=deepcopy(fixture) if fixture else json.loads(FIXTURE.read_text(encoding='utf-8'))
        self.committer=ContextCommitter(store);self.output=OutputAdapter(store);self.index=DependencyIndex(store)
        self.last_result=None;self.counter=0
        self.planner=RecheckPlanner()

    def item(self,ident):return self.store.item(self.session,self.scope,ident)
    def source(self,ident,text,revision_kind='new_utterance'):
        return self.store.ingress(self.session,self.scope,ident,dict(kind='source',label=text,origin='user_fixture',revision_kind=revision_kind,root=None),cutoff=0)

    def update(self,key,writes,kind,source_refs,refs=None):
        refs=list(dict.fromkeys((refs or [])+list(writes)+list(source_refs)))
        view=self.store.snapshot(self.session,self.scope,refs=refs);self.store.register_projection(view)
        evaluation_id='evaluation:'+key
        FixtureAccounting(self.store,self.session,self.scope).reserve('context',[dict(projection_id=view.id,questions=1)],evaluation_id)
        self.store.ingress(self.session,self.scope,evaluation_id,dict(kind='evaluation',label='合成文脈評価',status='VALID',projection_id=view.id,mode='FIXTURE',profile='context-fixture-v1'))
        p=ContextUpdateProposal(f'{self.session}:{self.scope}:{key}',self.session,self.scope,view.id,kind,view.data()['read_set'],writes,
                                {k:self.store.version(self.session,self.scope,k) for k in writes},tuple(source_refs),evaluation_id,time.monotonic()+2)
        self.last_result=self.committer.apply(p);return self.last_result

    def start(self,explicit=False):
        if self.item('goal:main'):raise ValueError('scenario_already_started')
        f=self.fixture;self.source('utterance:1',f['explicit_utterance'] if explicit else f['utterance'])
        writes={
            'person:a':dict(kind='entity',entity_kind='person',label='参加者A（合成）',region='person'),
            'place:reported':dict(kind='entity',entity_kind='other',label='会話で言及された自宅',region='place'),
            'video':dict(kind='entity',entity_kind='project',label='動画解析',region='conversation'),
            'conversation':dict(kind='entity',entity_kind='project',label='会話処理',region='conversation'),
            'subtitle':dict(kind='entity',entity_kind='project',label='字幕',region='conversation'),
            'goal:main':dict(kind='goal',label='処理を軽くする・本題pending',target_binding='video' if explicit else None,preference=None,budget=None,deadline=None,authority='denied',source_refs=['utterance:1']),
            'goal:independent':dict(kind='goal',label='独立した背景整理',target_binding='background',preference=None,source_refs=[])}
        self.update('seed',writes,'entity_register',['utterance:1'])
        self.index.register(self.session+':job:target',self.session,self.scope,'goal:main',{'goal:main':self.item('goal:main')['revision']},'HELD')
        self.index.register(self.session+':job:background',self.session,self.scope,'goal:independent',{'goal:independent':self.item('goal:independent')['revision']},'QUEUED')
        view=self.store.snapshot(self.session,self.scope,refs=['utterance:1','goal:main','video','conversation']);self.store.register_projection(view)
        comparison=compare(f['previews'],f['axes'],view.id)
        FixtureAccounting(self.store,self.session,self.scope).reserve('hearing',[{'pair':r['pair'],'axis':r['axis'],'projection_id':view.id,'questions':2} for r in comparison['axes']],'comparison:1')
        self.store.ingress(self.session,self.scope,'comparison:1',dict(kind='artifact',label='四軸比較・合成',comparison=comparison,previews=f['previews'],projection_id=view.id,read_set=view.data()['read_set']))
        goals=deepcopy(f['goals'])
        if explicit:
            for g in goals:
                if g['user_gap']=='target_binding':g['resolution_status']='resolved';g['disposition']='proceed_without_asking';g['source_refs']=['utterance:1']
        goal=choose_goal(goals) if comparison['status']=='VALID' else None
        FixtureAccounting(self.store,self.session,self.scope).reserve('hearing',[dict(goal=g['id'],projection_id=view.id,questions=4) for g in goals],'goals:1')
        self.store.ingress(self.session,self.scope,'confirmation-goals',dict(kind='artifact',label='確認目的・合成評価',goals=goals,selected=goal['id'] if goal else None,projection_id=view.id))
        if not goal:
            with self.store.transaction():self.store.event(self.session,self.scope,'no_ask',{'reason':'resolved_or_no_valid_ask_goal','comparison_id':'comparison:1'})
            return
        confirmation_kind=goal.get('confirmation_kind','clarify_initial')
        if confirmation_kind not in {'clarify_initial','clarify_missing','clarify_change'}:raise ValueError('confirmation_kind')
        qid='question:target'
        question=dict(kind='question',label='作業対象が未確定',goal_id='goal:main',branch='target_binding',branch_state='OPEN',
                      question_basis={'utterance:1':1},source_refs=['utterance:1'],comparison_ref='comparison:1',confirmation_goal=goal,confirmation_kind=confirmation_kind,
                      choices=['video','conversation','both','other','unknown','later'],resolved_target=None,reply_ref=None)
        self.update('open-question',{qid:question},'confirmation_transition',['utterance:1'])
        # Reuse C0's exact raw/normalized micro validator, weights and threshold.
        candidates=[SimpleNamespace(id=q['id']) for q in f['questions']]
        snapshot=SimpleNamespace(snapshot_id=view.id,utterance_revision=1)
        evaluation=dict(mode='FIXTURE',rubric_version='micro-c0-v1',snapshot_id=view.id,revision=1,status='COMPLETED',candidate_ids=[c.id for c in candidates],scores={q['id']:q['scores'] for q in f['questions']})
        status,scores=validate(evaluation,snapshot,candidates);selected=choose(scores,[c.id for c in candidates]) if status=='VALID' else None
        FixtureAccounting(self.store,self.session,self.scope).reserve('micro',[dict(candidate=q['id'],projection_id=view.id,questions=3) for q in f['questions']],'questions:1')
        self.store.ingress(self.session,self.scope,'question-evaluation',dict(kind='evaluation',label='質問文適合・合成評価',status=status,raw=evaluation,scores=scores,projection_id=view.id,candidate_texts={q['id']:q['text'] for q in f['questions']}))
        if not selected:return
        q=next(q for q in f['questions'] if q['id']==selected);question['branch_state']='AWAITING_REPLY';question['candidate_id']=selected
        self.update('ask-question',{qid:question},'confirmation_transition',['utterance:1'])
        output_view=self.store.snapshot(self.session,self.scope,refs=['utterance:1','goal:main',qid])
        self.store.register_projection(output_view)
        self.output.commit(self.session,self.scope,'turn-1','clarification',q['text'],qid,view.id,scores[selected]['Q'],'question-evaluation',view.data()['read_set'],selected)
        self.output.deliver(self.session,self.scope)

    def reply(self,text,reply_id=None):
        if not isinstance(text,str) or not 0<len(text)<=4000:raise ValueError('reply_text')
        q=self.item('question:target')
        if not q:raise ValueError('no_question')
        reply_id=reply_id or uuid.uuid4().hex
        ident='reply:'+reply_id
        old=self.item(ident)
        if old:
            if old['value']['label']!=text:raise ValueError('reply_key_conflict')
            row=self.store.db.execute('SELECT result FROM proposals WHERE update_key=?',(f'{self.session}:{self.scope}:resolve:{reply_id}',)).fetchone()
            result=json.loads(row[0]) if row else {'status':'RECORDED_UNRESOLVED'}
            return dict(result,status='ALREADY_APPLIED') if result['status']=='APPLIED' else result
        self.source(ident,text,'reply')
        if any(self.store.version(self.session,self.scope,k)!=v for k,v in q['value']['question_basis'].items()):return {'status':'STALE_QUESTION'}
        if q['value']['branch_state'] in {'RESOLVED','SUPERSEDED'}:return {'status':'QUESTION_CLOSED'}
        resolution=deepcopy(self.fixture['replies'].get(text,{'target':None,'state':'UNCONFIRMED'}))
        FixtureAccounting(self.store,self.session,self.scope).reserve('reply',[dict(question=q['id'],reply_ref=ident,questions=3)],'reply:'+reply_id)
        self.store.ingress(self.session,self.scope,'resolution:'+reply_id,dict(kind='artifact',label='返答対応・fixture限定',question_id=q['id'],question_revision=q['revision'],reply_ref=ident,reply_revision=1,resolution=resolution,mode='FIXTURE'))
        question=deepcopy(q['value']);question['branch_state']=resolution['state'];question['reply_ref']=ident
        question['resolved_target']=resolution['target']
        target=resolution['target'];goal=deepcopy(self.item('goal:main')['value'])
        if isinstance(target,str):goal['target_binding']=target
        if 'preference' in resolution:goal['preference']=resolution['preference']
        # Multi-target is a request candidate, not an automatic dual job or binding.
        if isinstance(target,list):question['multi_target_candidate']=target;question['resolved_target']=goal['target_binding']
        if target is None:question['resolved_target']=goal['target_binding']
        writes={'goal:main':goal,'question:target':question}
        if isinstance(target,str):
            writes['claim:target']=dict(kind='claim',label='今回の対象: '+self.item(target)['value']['label'],claim_kind='utterance_reference',entity_ref=target,
                predicate='request_target',typed_value=target,source_refs=[ident],evaluation_refs=['resolution:'+reply_id],evidence_state='supported',use_state='adopted',content_confirmation='confirmed',
                question_id=q['id'],reply_ref=ident,reply_revision=1,region='conversation',speaker_or_proposer_ref='person:a')
        if 'preference' in resolution:
            writes['claim:preference']=dict(writes['claim:target'],label='今回はメモリ削減を希望',claim_kind='preference',predicate='priority',typed_value='memory')
        result=self.update('resolve:'+reply_id,writes,'goal_binding_resolve',[ident],refs=['utterance:1'])
        if result['status']=='APPLIED':
            candidates=[{'id':'inspect','target':goal['target_binding']},{'id':'explain','target':goal['target_binding']}]
            evaluations=self.fixture.get('planned_job_scores',{})
            if isinstance(target,str):FixtureAccounting(self.store,self.session,self.scope).reserve('work_priority',[dict(candidate=c['id'],reply_ref=ident,questions=3) for c in candidates],'work:'+reply_id)
            selected=select_planned_job(candidates,evaluations) if isinstance(target,str) else None
            newjob=self.session+':job:target:'+reply_id
            self.index.register(newjob,self.session,self.scope,'goal:main',{'goal:main':self.item('goal:main')['revision'],ident:1},'preview_only' if selected else 'HELD')
            with self.store.transaction():self.store.event(self.session,self.scope,'planned_job_selection',{'job':newjob,'target':goal['target_binding'],
                'state':'preview_only' if selected else 'HELD','selected':selected,'scores':evaluations,'real_work':False,'fresh_source':ident})
        return result

    def background(self):
        self.counter+=1
        self.store.ingress(self.session,self.scope,'fact:brightness',dict(kind='fact',label='合成の明るさ測定',value=self.counter,unit='fixture_level',provider='synthetic_program',acquired_at=self.counter),cutoff=0)
        goals=[]
        for gid in ('goal:main','goal:independent'):
            goals.append(dict(id=gid,session=self.session,scope=self.scope,consumers=[r['id'] for r in self.store.db.execute('SELECT id FROM consumers WHERE session=? AND scope=? AND goal=?',(self.session,self.scope,gid))]))
        refs=self.planner.recheck('brightness:'+str(self.counter),goals,self.session,self.scope,now=time.monotonic())
        with self.store.transaction():self.store.event(self.session,self.scope,'finite_recheck',{'references':refs,'semantic_relevance':'pending_fixture_port','skipped':dict(self.planner.skipped),'no_broadcast':True})

    def correct(self):
        self.source('utterance:1','会話処理を軽くしたい（ASR訂正fixture）','asr_revision')
        q=self.item('question:target')
        if q:
            value=deepcopy(q['value']);value['branch_state']='SUPERSEDED'
            return self.update('correction:'+str(self.item('utterance:1')['revision']),{'question:target':value},'confirmation_transition',['utterance:1'])

    def deny_interpretation(self,claim_id,text,reply_id):
        """Recorded fixture denial revises an interpretation, never its observation."""
        claim=self.item(claim_id)
        if not claim or claim['value'].get('claim_kind')!='interpretation':raise ValueError('interpretation_required')
        ref='reply:'+reply_id;self.source(ref,text,'interpretation_denial')
        value=deepcopy(claim['value']);value['use_state']='excluded';value['content_confirmation']='denied'
        value['source_refs']=list(dict.fromkeys(value['source_refs']+[ref]));value['reply_ref']=ref
        return self.update('deny:'+reply_id,{claim_id:value},'claim_revise',value['source_refs'])

    def reported_context(self):
        text='今日は自宅で作業している。動画解析を軽くし、今回はメモリ削減を優先したい'
        result=self.reply(text,'reported')
        if result['status'] not in {'APPLIED','ALREADY_APPLIED'}:return result
        if self.item('claim:reported-place'):return result
        base=dict(kind='claim',claim_kind='utterance_reference',source_refs=['reply:reported'],evidence_state='supported',use_state='adopted',content_confirmation='confirmed',speaker_or_proposer_ref='person:a',observation_status='not_observed')
        return self.update('reported-context',{
            'claim:reported-person':dict(base,label='本人申告: 今日は作業している',entity_ref='person:a',predicate='reported_activity',typed_value='working',region='person'),
            'claim:reported-place':dict(base,label='本人申告: 自宅（現在地の実観測なし）',entity_ref='place:reported',predicate='reported_place',typed_value='home',region='place')},'claim_add',['reply:reported'])

    def change_preference(self):
        prior=self.item('claim:preference')
        if not prior:raise ValueError('preference_not_yet_stated')
        revision=prior['revision'];ref='preference:'+str(revision+1)
        self.source(ref,'今回は速度優先へ変更','preference_correction')
        value=deepcopy(prior['value']);value.update(label='今回は速度を優先',typed_value='speed',source_refs=[ref],reply_ref=ref)
        goal=deepcopy(self.item('goal:main')['value']);goal['preference']='speed'
        return self.update(ref,{'claim:preference':value,'goal:main':goal},'claim_revise',[ref])
