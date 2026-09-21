"""Project canonical records to the very same CP1 map contract."""
import json
from ..map_projection import empty_view
from .field_adapter import field_snapshot


class ContextProvider:
    def __init__(self,coordinator):self.coordinator=coordinator
    @property
    def view(self):return self.snapshot()
    def snapshot(self):
        c=self.coordinator;s=c.store;data=s.snapshot(c.session,c.scope).data();view=empty_view(c.session,'CONTEXT_FIXTURE')
        view['scope']=c.scope
        view['expires_at']=float(s.db.execute("SELECT value FROM meta WHERE key='expires'").fetchone()[0])
        view['cursor']=data['available_cursor'];view['layer_view_id']=s.snapshot(c.session,c.scope).id
        shot=field_snapshot(session=c.session)
        view['field_snapshots']=[dict(scope=c.scope,snapshot=shot)]
        view['layers']=data['layers'];view['fields']={k:dict(UNKNOWN=v['UNKNOWN'],scope=c.scope,reason='合成・未観測') for k,v in shot['spaces'].items()}
        types={'entity':'Entity','claim':'Claim','source':'Evidence','fact':'Evidence','question':'OpenIssue'}
        for ident,item in data['items'].items():
            value=item['value'];kind=types.get(value['kind'])
            if not kind:continue
            view['nodes'].append(dict(id=ident,canonical_id=f'{c.session}:{c.scope}:{ident}',revision=item['revision'],kind=kind,
                label=value['label'],region=value.get('region','place' if value['kind']=='fact' else 'conversation'),state=value.get('use_state',value.get('branch_state','recorded')),
                availability=item['availability'],source_refs=value.get('source_refs',[]),concentration=None,scope=c.scope,source_cutoff=item['source_cutoff'],available_cursor=item['cursor'],record=value))
            for target in value.get('source_refs',[]):view['edges'].append(dict(id=f'{ident}:source:{target}',source=ident,target=target,relation='根拠にする',state='recorded'))
            if value.get('entity_ref'):view['edges'].append(dict(id=ident+':entity',source=ident,target=value['entity_ref'],relation='対象について述べる',state='recorded'))
            if value.get('reply_ref'):view['edges'].append(dict(id=ident+':reply',source=ident,target=value['reply_ref'],relation='解決根拠',state='recorded'))
        view['history']=[dict(e,source='ContextStore',target='projection',state=e['kind'],refs=[x['id'] for x in e['payload'].get('changeset',[])]) for e in s.events(c.session,c.scope)]
        view['responses']=[json.loads(r[0]) for r in s.db.execute('SELECT payload FROM response_commits WHERE session=? AND scope=?',(c.session,c.scope))]
        view['utterances']=[dict(id=r['id'],text=json.loads(r['payload'])['label'],revision=r['revision'],cursor=r['cursor']) for r in s.db.execute('SELECT * FROM item_versions WHERE session=? AND scope=? ORDER BY cursor',(c.session,c.scope)) if json.loads(r['payload'])['kind']=='source']
        view['acks']=[json.loads(r[0]) for r in s.db.execute("SELECT a.payload FROM acknowledgements a JOIN response_commits r ON r.id=a.commit_id WHERE r.session=? AND r.scope=? AND a.kind='browser_dom'",(c.session,c.scope))]
        view['jobs']=[dict(r) for r in s.db.execute('SELECT * FROM consumers WHERE session=? AND scope=?',(c.session,c.scope))]
        view['goal']=data['items'].get('goal:main',{}).get('value')
        view['question']=data['items'].get('question:target',{}).get('value')
        view['comparison']=data['items'].get('comparison:1',{}).get('value')
        view['last_result']=c.last_result
        refs=[n['id'] for n in view['nodes']]
        view['schematic']=[dict(role='L4 / SourceIngress',status='合成原文・取得値',refs=refs),dict(role='四軸 / hearing-recorded-v1',status='合成評価・実Jev未接続',refs=['question:target']),
            dict(role='ContextCommitter / SQLite',status=(c.last_result or {}).get('status','未確定'),refs=refs),dict(role='OutputArbiter',status=f"質問commit {len(view['responses'])} / browser_dom ack {len(view['acks'])}",refs=['question:target']),
            dict(role='DominanceReader',status='未接続・読取り専用',refs=[])]
        return view
