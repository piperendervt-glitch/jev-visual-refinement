"""Finite, explicitly synthetic evidence through the unchanged FieldReducer."""
from copy import deepcopy
import uuid
from .context.field_adapter import field_snapshot
from .map_projection import empty_view
from .mass_projection import distribution_key,token

class MassFixture:
    def __init__(self,dense=False):
        self.session='mass-'+uuid.uuid4().hex[:12];self.cursor=0;self.dense=dense;self.history=[];self.saved={}
        self.hypotheses=[dict(id=h,space=space,scope='session',subject=subject,facet='synthetic-alternatives',value=h,reference_mode='observed',label='合成仮説 '+h) for h,space,subject in [('A','place','room'),('B','place','room'),('C','place','room'),('D','person','speaker')]]
        self.set_stage('seed')
    def records(self,count,contra=False):
        records=[]
        for i,h in enumerate(['A','B','C','D']+['A']*max(0,count-4)+(['A'] if contra else [])):
            root=f'synthetic:1:video:cam{i}:0';subject='speaker' if h=='D' else 'room'
            obs=dict(id=f'o{i}',kind='observation',revision=1,epoch=1,dependencies={},scope='session',subject=subject,reference_mode='observed',input_roots=[root],evidence_roots=[root],root_sources={root:dict(modality='video',stream=f'cam{i}',interval=[0,1],pts=1,time_base=[1,1])},citations={root:1},input_cutoff_s=1)
            negative=contra and i==count
            ev=dict(id=f'e{i}',kind='evidence_evaluation',revision=1,epoch=1,dependencies={obs['id']:1},evaluation_kind='evidence',observation_id=obs['id'],hypothesis_id=h,q=1,r=1,a=1,p_support=0 if negative else 1,p_contradict=1 if negative else 0,accepted_wall_s=0)
            records.extend(dict(record=r,available_cursor=1,source_cutoff=1) for r in (obs,ev))
        return records if count else []
    def set_stage(self,stage):
        if stage not in ('initial','seed','boost','contra','decay','replay'):raise ValueError('unknown_mass_stage')
        if self.cursor>=100:raise ValueError('mass_fixture_capacity')
        self.cursor+=1
        if stage=='replay':shot=deepcopy(self.saved['seed'])
        else:
            count=0 if stage=='initial' else 4 if stage=='seed' else 6
            shot=field_snapshot(self.records(count,stage=='contra'),self.hypotheses,cutoff=13 if stage=='decay' else 1,cursor=1,session=self.session)
            self.saved[stage]=deepcopy(shot)
        v=empty_view(self.session,'FIELD_MASS_FIXTURE');v.update(cursor=self.cursor,scope='synthetic-participant',provider='field-mass',mass_stage=stage)
        bundle=dict(scope=v['scope'],snapshot=shot);v['field_snapshots']=[bundle]
        v['fields']={k:dict(UNKNOWN=d['UNKNOWN'],scope=v['scope'],reason='合成数値核・実意味採用なし') for k,d in shot['spaces'].items()}
        for h in self.hypotheses:
            ref=dict(distribution_key=distribution_key(bundle,h['space']),hypothesis_id=h['id'],snapshot_token=token(shot))
            v['nodes'].append(dict(id='mass:'+h['id'],canonical_id='synthetic-hyp:'+h['id'],revision=self.cursor,kind='Claim',region=h['space'],label=h['label'],state='synthetic_numerical',availability='available',source_refs=[],field_refs=[ref]))
        duplicate=deepcopy(v['nodes'][0]);duplicate.update(id='mass:A-copy',label='A（同じ仮説の別表示）');v['nodes'].append(duplicate)
        multiple=deepcopy(v['nodes'][0]);multiple.update(id='mass:multiple',canonical_id='synthetic:multiple',label='複数参照（合算しない）',field_refs=[*v['nodes'][0]['field_refs'],*v['nodes'][3]['field_refs']]);v['nodes'].append(multiple)
        for i in range(194 if self.dense else 3):
            v['nodes'].append(dict(id=f'mass:neutral:{i}',canonical_id=f'synthetic:neutral:{i}',revision=1,kind=['Entity','Evidence','OpenIssue'][i%3],region=['person','place','conversation'][i%3],label='未評価の中立 '+str(i),state='not_evaluated',availability='available',concentration=None,source_refs=[]))
        self.history.append(dict(id=self.session+':'+str(self.cursor),cursor=self.cursor,kind='synthetic_field_snapshot',source='FieldReducer fixture',target='mass display',refs=[],payload={'stage':stage,'snapshot_token':token(shot)}))
        v['history']=deepcopy(self.history);self._view=v
    @property
    def view(self):return self.snapshot()
    def snapshot(self):return deepcopy(self._view)
