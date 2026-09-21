"""Versioned display projection. DEMO records never become context evidence."""
from copy import deepcopy

REGIONS = [('person', '人物', 250, 145), ('place', '場所', 750, 145),
           ('conversation', '会話内容', 500, 365)]


def empty_view(session='map-0', mode='EMPTY'):
    return dict(schema='map-view-v1', session_id=session, epoch=1, cursor=0, mode=mode,
                nodes=[], edges=[], history=[], fields={k: dict(UNKNOWN=None, scope='fixture', reason='未取得') for k, *_ in REGIONS},
                schematic=[], responses=[], acks=[], metrics=dict(tokens=None, cost=None, external_requests=0))


class DemoProvider:
    def __init__(self):
        self.serial = 0
        self.view = empty_view()
        self.snapshots = {0: deepcopy(self.view)}
        self.last_delta = None

    def start(self, dense=False):
        self.serial += 1
        self.view = empty_view(f'demo-{self.serial}', 'DEMO')
        count = 60 if dense else 4
        for region, label, _, _ in REGIONS:
            for n in range(count):
                kind = ['Entity', 'Claim', 'Evidence', 'OpenIssue'][n % 4]
                ident = f'{region}-{n}'
                self.view['nodes'].append(dict(id=ident, canonical_id=f'fixture:{ident}', revision=1,
                    kind=kind, region=region, label=f'{label} {kind} {n}', state='not_evaluated',
                    source_refs=[f'fixture:{region}-2'] if kind=='Claim' else [],
                    availability='available', concentration=None, origin='synthetic_demo'))
                if n:
                    self.view['edges'].append(dict(id=f'edge-{ident}', source=ident, target=f'{region}-0',
                        relation='対象について述べる' if kind=='Claim' else '合成参照', state='fixture'))
        self.view['edges'].append(dict(id='cross', source='conversation-1', target='person-0', relation='発言者', state='fixture'))
        self.snapshots = {}
        return self.change('initial', [])

    def change(self, kind, changed):
        before = self.view['cursor']; self.view['cursor'] += 1
        cursor = self.view['cursor']
        event=dict(id=f"{self.view['session_id']}:event:{cursor}", cursor=cursor, kind=kind,
                   source='DEMO provider', target='MapProjection', state='更新確定' if kind!='evaluation' else '合成評価完了・未確定', refs=changed)
        self.view['history'].append(event)
        self.view['schematic']=[dict(role='input', status='合成入力', refs=changed),
            dict(role='evidence/fixture-v1', status='合成評価', refs=changed),
            dict(role='ContextCommitter', status=event['state'], refs=changed),
            dict(role='DominanceReader', status='設計経路／未接続・読取り専用', refs=[])]
        self.last_delta=dict(update_id=event['id'], session_id=self.view['session_id'], epoch=1,
                             base=before, cursor=cursor, snapshot=deepcopy(self.view))
        self.snapshots[cursor]=deepcopy(self.view)
        return self.last_delta

    def step(self, kind):
        if self.view['mode']!='DEMO': raise ValueError('select_demo_first')
        if self.view['cursor']>=1000:raise ValueError('demo_event_capacity')
        if kind=='duplicate': return deepcopy(self.last_delta)
        if kind=='old':
            old=deepcopy(self.last_delta); old['cursor']=max(0,old['cursor']-1); old['update_id']='old-result'; return old
        if kind=='gap':
            self.change('unreceived', []); return self.change('after_gap', [])
        nodes=self.view['nodes']; target=nodes[1]
        if kind in {'add','evidence'}:
            ident=f"extra-{self.view['cursor']}"
            nodes.append(dict(id=ident,canonical_id='fixture:'+ident,revision=1,kind='Evidence' if kind=='evidence' else 'Claim',
                              label='合成の追加根拠' if kind=='evidence' else '合成の新しい主張',region='conversation',
                              state='not_evaluated',availability='available',source_refs=[],concentration=None,origin='synthetic_demo'))
            self.view['edges'].append(dict(id='edge-'+ident,source='conversation-1',target=ident,relation='根拠にする',state='fixture'))
        elif kind=='hub':
            self.view['edges']=[dict(id='hub-'+n['id'],source=n['id'],target=nodes[0]['id'],
                                    relation='合成hub参照',state='fixture') for n in nodes[1:]]
        elif kind=='exclude':
            target['state']='unavailable'; target['availability']='not_acquired'
        elif kind in {'correction','conflict','hold','decay'}:
            target['revision']+=1
            target['state']={'correction':'superseded','conflict':'contested','hold':'held','decay':'decay_demo_unmeasured'}[kind]
        elif kind!='evaluation': raise ValueError('unknown_demo_event')
        return self.change(kind,[target['id']])

    def snapshot(self): return deepcopy(self.view)
