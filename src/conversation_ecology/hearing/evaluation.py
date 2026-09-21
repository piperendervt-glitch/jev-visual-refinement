"""Choice/Score remain separate; values are supplied by a synthetic evaluation port."""
from itertools import combinations
from math import ceil
from ..contracts import number

AXES=('target','operation','references','deliverable')


def compare(previews,rows,projection_id):
    if not 2<=len(previews)<=3:raise ValueError('preview_limit')
    result=[]
    for a,b in combinations(previews,2):
        for axis in AXES:
            key=f"{a['id']}|{b['id']}|{axis}";raw=rows.get(key)
            status='VALID';relation=None;impact=None
            if not raw:status='not_evaluated'
            else:
                relation=raw.get('relation');impact=raw.get('impact')
                if relation in {'insufficient','ambiguous'}:status=relation;impact=None
                elif relation not in {'equivalent','materially_different'}:status='INVALID';impact=None
                else:
                    try:number(impact,0,4)
                    except ValueError:status='INVALID';impact=None
                    if status=='VALID' and ((relation=='equivalent' and impact>=2) or (relation=='materially_different' and impact==0)):status='evaluation_conflict'
            result.append(dict(pair=[a['id'],b['id']],axis=axis,relation=relation,impact=impact,status=status,raw=raw,
                               projection_id=projection_id,input_refs=[a['id'],b['id']],dependency_key=raw.get('dependency_key') if raw else None))
    units=len(result)
    return dict(axes=result,unit_count=units,primitive_questions=units*2,packet_count=ceil(units/8),http_sends=0,
                status='VALID' if all(r['status']=='VALID' for r in result) else 'PENDING',mode='FIXTURE')


def choose_goal(goals,seed=17):
    import random
    valid=[]
    for g in goals[:3]:
        if g.get('resolution_status')!='unresolved' or g.get('disposition')!='ask_now' or not g.get('user_gap'):continue
        try:
            for k in ('resolves_gap','task_fit','timing_fit','uncertainty_handling'):number(g[k],0,4)
        except (ValueError,KeyError):continue
        if not g.get('askable',False):continue
        valid.append(g)
    if not valid:return None
    top=max(tuple(g[k] for k in ('resolves_gap','task_fit','timing_fit')) for g in valid)
    tied=sorted((g for g in valid if tuple(g[k] for k in ('resolves_gap','task_fit','timing_fit'))==top),key=lambda g:g['id']);random.Random(seed).shuffle(tied)
    return tied[0]
