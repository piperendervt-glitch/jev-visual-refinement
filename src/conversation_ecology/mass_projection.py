"""Read-only numerical snapshot references; no new field arithmetic or writes."""
from copy import deepcopy
import hashlib
import json
import math

REGIONS=('person','place','conversation')

def token(snapshot):
    return hashlib.sha256(json.dumps(snapshot,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode()).hexdigest()

def distribution_key(bundle,space):
    s=bundle['snapshot']
    return json.dumps([s['session'],s['media_id'],s['epoch'],bundle['scope'],s['shot'],s['scope_revision'],space],ensure_ascii=False,separators=(',',':'))

def valid(value):return type(value) in (float,int) and math.isfinite(value) and 0<=value<=1

def project_mass(view):
    """Mutate only the caller's fresh projection. Keep incomplete data explicit."""
    distributions={};scope=view.get('scope');allowed=view.get('field_scopes',[scope])
    for bundle in view.get('field_snapshots',[]):
        s=bundle['snapshot']
        try:stamp=token(s)
        except (ValueError,TypeError):stamp=None
        header_ok=(stamp is not None and s.get('session')==view['session_id'] and s.get('epoch')==view['epoch'] and bundle.get('scope') in allowed and s.get('field_rule_id')=='evidence-mass-v1.1')
        for space in REGIONS:
            key=distribution_key(bundle,space);data=s.get('spaces',{}).get(space,{})
            rows=data.get('hypotheses',[]);values={r['id']:r for r in rows};unknown=data.get('UNKNOWN')
            status='available' if header_ok and len(values)==len(rows) and all(r.get('space')==space and valid(r.get('C')) for r in rows) and (unknown is None or valid(unknown)) else 'invalid_reference'
            total=sum(r['C'] for r in rows) if status=='available' else 0
            if status=='available' and (total>1+1e-8 or unknown is not None and abs(total+unknown-1)>1e-8):status='invalid_reference'
            if key in distributions:status='invalid_reference'
            distributions[key]=dict(key=key,space=space,scope=bundle['scope'],status=status,UNKNOWN=unknown,B=1,
                hypotheses=deepcopy(values),snapshot_id=s.get('snapshot_id'),snapshot_token=stamp,input_cursor=s.get('input_cursor'),
                source_time=s.get('as_of_media_s'),view_cursor=view['cursor'],epoch=view['epoch'],field_rule_id=s.get('field_rule_id'),
                expires_at=view.get('expires_at'),normalization='space within this source reducer; no visible-subset normalization')
    expired=view.get('retention')=='expired'
    def resolve(ref):
        d=distributions.get(ref.get('distribution_key'));hid=ref.get('hypothesis_id')
        if not d:return dict(status='invalid_reference',value=None,reference=deepcopy(ref))
        status=d['status'];row=d['hypotheses'].get(hid) if hid is not None else None
        value=d['UNKNOWN'] if hid is None else (row or {}).get('C')
        if ref.get('snapshot_token')!=d['snapshot_token'] or hid is not None and row is None:status='invalid_reference'
        if expired:status='expired'
        if status=='available' and value is None:status='not_provided'
        return dict(status=status,value=value if status=='available' else None,B=1,reference=deepcopy(ref),
            snapshot_id=d['snapshot_id'],source_time=d['source_time'],input_cursor=d['input_cursor'],view_cursor=view['cursor'],
            source_hypothesis=deepcopy(row),scope=d['scope'],space=d['space'],expires_at=d['expires_at'])
    for n in view['nodes']:
        refs=n.get('field_refs',[])
        if len(refs)>1:n['mass']=dict(status='multiple_references',value=None,references=[resolve(r) for r in refs])
        elif refs:n['mass']=resolve(refs[0])
        else:n['mass']=dict(status='not_evaluated' if n.get('state') in ('not_evaluated','pending_evaluation') else 'not_provided',value=None)
        if n.get('availability') not in ('available','display_projection'):n['mass'].update(status='unavailable',value=None)
    for key,d in distributions.items():
        ident='@unknown:'+hashlib.sha256(key.encode()).hexdigest()[:24]
        ref=dict(distribution_key=key,hypothesis_id=None,snapshot_token=d['snapshot_token'])
        view['nodes'].append(dict(id=ident,canonical_id=None,display_only=True,revision=view['cursor'],kind='Unknown',region=d['space'],
            label=d['space']+' UNKNOWN ?',state='distribution_unknown',availability='display_projection',source_refs=[],field_refs=[ref],mass=resolve(ref)))
    view['mass_distributions']=list(distributions.values())
    view['mass_status']='expired' if expired else 'available' if distributions else 'not_provided'
    return view
