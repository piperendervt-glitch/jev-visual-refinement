"""An isolated existing reducer for each as-of query; never rewind a mutable ledger."""
from context_fields.clock import MediaClock
from context_fields.fields import FieldReducer, Hypothesis
from context_fields.ledger import Ledger


def field_snapshot(records=(),hypotheses=(),*,cutoff=0,cursor=0,session='context-fixture'):
    ledger=Ledger(session=session,media_id='synthetic',path=None)
    clock=MediaClock(media_s=cutoff,released={'video':[(0,cutoff)],'audio':[(0,cutoff)]})
    reducer=FieldReducer(ledger)
    for h in hypotheses:reducer.register(Hypothesis(**h))
    for entry in records:
        if entry['available_cursor']>cursor or entry['source_cutoff']>cutoff:continue
        record=entry['record']
        if record['kind'] not in {'observation','evidence_evaluation'}:raise ValueError('non_evidence_root_denied')
        ledger.add(record,clock)
        if record['kind']=='evidence_evaluation':reducer.contribute(record['id'],record['hypothesis_id'],entry.get('accepted_media_s',entry['source_cutoff']))
    return reducer.snapshot(cutoff).data()
