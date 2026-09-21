"""Finite, versioned context records. Canonical JSON is also the immutable payload."""
from dataclasses import dataclass
import hashlib
import json
import math

KINDS={'entity','claim','source','fact','goal','question','evaluation','artifact','set'}
CLAIM_KINDS={'utterance_reference','acquired_value_reference','interpretation','preference','agreement_assertion'}


def encoded(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)


def hashed(value): return hashlib.sha256(encoded(value).encode()).hexdigest()


def validate_record(value):
    encoded(value)
    if value.get('kind') not in KINDS: raise ValueError('record_kind')
    if not isinstance(value.get('label'),str) or len(value['label'])>4000: raise ValueError('label')
    if value['kind']=='claim':
        if value.get('claim_kind') not in CLAIM_KINDS: raise ValueError('claim_kind')
        if value.get('evidence_state') not in {'not_evaluated','supported','contradicted','insufficient','contested'}:raise ValueError('evidence_state')
        if value.get('use_state') not in {'adopted','held','contested','superseded','unavailable','excluded'}:raise ValueError('use_state')
        if value.get('content_confirmation') not in {'unconfirmed','confirmed','denied','partial','disputed'}:raise ValueError('content_confirmation')
        if not value.get('entity_ref') or not isinstance(value.get('source_refs'),list):raise ValueError('claim_references')
    if value['kind']=='fact' and not {'value','unit','provider','acquired_at'}<=value.keys():raise ValueError('fact_provenance')
    if 'authority' in value and value['authority']!='denied':raise ValueError('authority_patch_denied')
    if any(k in value for k in ('authority_issued','real_work','raw_policy','workspace_write')):raise ValueError('authority_patch_denied')


@dataclass(frozen=True)
class LayerView:
    canonical: str
    @property
    def id(self): return 'projection:'+hashlib.sha256(self.canonical.encode()).hexdigest()
    def data(self): return json.loads(self.canonical)


@dataclass(frozen=True)
class ContextUpdateProposal:
    update_key: str
    session: str
    scope: str
    projection_id: str
    update_kind: str
    read_set: dict
    writes: dict
    expected: dict
    source_refs: tuple
    evaluation_id: str | None
    deadline: float
    def payload(self):
        from dataclasses import asdict
        value=asdict(self)
        # Deadline is delivery metadata, not a semantic idempotency-key payload.
        value.pop('deadline')
        return value
