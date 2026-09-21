"""Fixed approved routes; a caller supplied grant string is not an approval."""
import hashlib
import json
import math
from pathlib import Path
from .media import plain_path

Q1 = 'SV01-SAMPLE-Q1'
M1 = 'SV01-MAP-M1'
L1 = 'SV01-LONG-L1'
R1 = 'SV01-RESOURCE-R1'
ROUTES = {'SV01-F1': ('sv01_f1.json', 'f1'), Q1: ('sv01_sample_q1.json', 'sample-q1'), M1: ('sv01_map_m1.json','map-m1'), L1: ('sv01_long_l1.json','long-l1')}
APPROVAL_SHA = '27b43957e00d2929a1641ecc1757c976d519013eb5ba9d9a75712d6fe5fa50e5'
PROFILE_SHA = 'a7520eea2f2f87a782df223e21135aaf635b0ee60259c176f5e43275bbbdb177'
PRIOR = {'artifacts\\sv01\\campaign.json': '3d6a3cafe0e7180c5e7485254f1cbaa72f6117da81d9310a929350c605a6d8c7',
         'artifacts\\sv01\\f1\\grant.json': '7d55bc54a309115e82ee775cdae8cfe458f98a47159b1c74eada28de157f372d'}
M1_PROFILE_SHA='a757c013a6cba7fbfbbf6fa9dd6026c69156ee8a42e8d480cae7d295ce3bfa67'
M1_APPROVAL_SHA='57bb87a5fbb831d0f5abfa261607da3c29d007813bf4b4ef1d9a9adb5ed1c418'
M1_PRIOR={**PRIOR,'artifacts\\sv01\\sample-q1\\grant.json':'be84e89b2058bc174a6f5b31a649d99f760c6f9ed533f92108415da73bf6409d'}
L1_PROFILE_SHA='608628f65d44771519d7306194a10f060cf94557c53521e5679c83ab39332c17'
L1_APPROVAL_SHA='a26f0b80e5d9accc87cc9465b4b271c8eff9114c791e8ae6975fc6e62548fe5f'
L1_PRIOR={**M1_PRIOR,'artifacts\\sv01\\map-m1\\grant.json':'9e4ededa1c108446042b80c05a784a2e01f2626547301686e976823698e5f7df'}
ROUTES[R1]=('sv01_resource_r1.json','resource-r1')
R1_PROFILE_SHA='251ea0b615a887f7721a7cd4a708f4ac06957e518c25c3162fb789954cb22979'
R1_APPROVAL_SHA='eae64464a72528aeb8f323fa34c145493deea460079cabcb78f447904e8cde37'
R1_PRIOR={**L1_PRIOR,'artifacts\\sv01\\long-l1\\grant.json':'b91ef2355b7bcaefe339a8df2b95c2e81f3a04a991a970a4ad6148cf531dbd32'}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve_route(root, grant=None, profile=None):
    root = Path(root)
    if grant is not None and grant not in ROUTES:
        raise ValueError('unknown_grant')
    name, area = ROUTES[grant] if grant else ('sv01.json', 'runtime')
    expected = plain_path(root/'config'/name)
    if profile is not None and plain_path(profile).resolve() != expected.resolve():
        raise ValueError('grant_profile_path_mismatch')
    if grant == Q1 and digest(expected) != PROFILE_SHA:
        raise ValueError('unapproved_profile')
    if grant == M1 and digest(expected) != M1_PROFILE_SHA:
        raise ValueError('unapproved_profile')
    if grant == L1 and digest(expected) != L1_PROFILE_SHA:
        raise ValueError('unapproved_profile')
    if grant == R1 and digest(expected) != R1_PROFILE_SHA:
        raise ValueError('unapproved_profile')
    parent = plain_path(root/'artifacts/sv01/campaign.json')
    ledger = plain_path(root/'artifacts/sv01'/area/'grant.json') if grant else parent
    if grant in (Q1,M1,L1,R1):
        for path, expected_hash in {Q1:PRIOR,M1:M1_PRIOR,L1:L1_PRIOR,R1:R1_PRIOR}[grant].items():
            if digest(plain_path(root/Path(path.replace('\\', '/')))) != expected_hash:
                raise ValueError('prior_ledger_changed')
    return dict(grant=grant, profile_path=expected, profile=json.loads(expected.read_text(encoding='utf-8')),
                ledger=ledger, parent=parent if grant else None, evidence=plain_path(root/'artifacts/sv01'/area))


def validate_q1(path, data, profile, grant=Q1):
    """Recognize the original approval once, then validate every restart."""
    prior={Q1:PRIOR,M1:M1_PRIOR,L1:L1_PRIOR,R1:R1_PRIOR}[grant]
    approval_sha={Q1:APPROVAL_SHA,M1:M1_APPROVAL_SHA,L1:L1_APPROVAL_SHA,R1:R1_APPROVAL_SHA}[grant]
    initial_state='AUTHORIZED_NOT_STARTED_BLOCKED_GRANT_ROUTING' if grant==Q1 else 'AUTHORIZED_NOT_STARTED'
    if data.get('grant') != grant or data.get('profile') != profile:
        raise ValueError('grant_profile_mismatch')
    if data.get('prior_ledgers') != prior or data.get('lease_required') != 'artifacts/sv01/campaign.lock':
        raise ValueError('grant_parent_mismatch')
    initial = data.get('state') == initial_state
    if initial:
        if digest(path) != approval_sha:
            raise ValueError('approval_bytes_changed')
    elif data.get('schema') != 1 or data.get('approval_sha256') != approval_sha:
        raise ValueError('unknown_grant_schema')
    elif data.get('state') not in ('READY', 'PAUSED'):
        raise ValueError('grant_not_reopenable')
    if data.get('native_failure_this_task') is not False or data.get('runtime_in_flight', False) or data.get('outer_verification_pending', False):
        raise ValueError('previous_runtime_incomplete')
    for key in ('media_seconds', 'asr_attempts', 'image_attempts', 'runtime_processes'):
        value = data.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= profile[key]:
            raise ValueError('invalid_grant_counter')
        if key != 'media_seconds' and not isinstance(value, int):
            raise ValueError('invalid_grant_counter')
    start = data.get('model_started_at')
    if grant==R1:
        loads=data.get('model_loads')
        if isinstance(loads,bool) or not isinstance(loads,int) or not 0<=loads<=profile['model_loads']:
            raise ValueError('invalid_model_load_counter')
        if any(data.get('active',{}).values()):raise ValueError('unfinished_resource_ticket')
        if len(data.get('candidates',[]))>profile['candidate_limit'] or any(c not in profile['candidates'] for c in data.get('candidates',[])):
            raise ValueError('invalid_candidate_history')
    if start is None:
        if any(data[k] for k in ('media_seconds', 'asr_attempts', 'image_attempts', 'runtime_processes')):
            raise ValueError('missing_grant_clock')
    elif isinstance(start, bool) or not isinstance(start, (int, float)) or not math.isfinite(start) or start <= 0 or not data['runtime_processes']:
        raise ValueError('invalid_grant_clock')
    if initial:
        data.update(schema=1, approval_sha256=approval_sha, state='READY',
                    routing_history=[{'from':data['state'], 'to':'READY', 'reason':{Q1:'Q1-ROUTING-01',M1:'SV-MAP-01',L1:'SV-LONG-01',R1:'AV-RESOURCE-01'}[grant]}])
