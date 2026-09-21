"""Finite synthetic packet accounting. HTTP transmissions remain zero."""
from ..context.model import encoded


def packets(units):
    result=[];current=[]
    for unit in units:
        if len(encoded([unit]))>12000 or type(unit.get('questions')) is not int or not 1<=unit['questions']<=32:raise ValueError('unit_too_large')
        candidate=current+[unit]
        if len(candidate)>8 or sum(u['questions'] for u in candidate)>32 or len(encoded(candidate))>12000:
            result.append(current);current=[]
        current.append(unit)
    if current:result.append(current)
    return result


class FixtureAccounting:
    """One durable event stream for all synthetic roles; failures are not refunded."""
    def __init__(self,store,session,scope):self.store=store;self.session=session;self.scope=scope
    def reserve(self,role,units,key):
        s=self.store
        batch=packets(units)
        with s.transaction():
            import json
            previous=[json.loads(r[0]) for r in s.db.execute("SELECT payload FROM events WHERE kind='fixture_packet_reservation'")]
            old=next((e for e in previous if e['key']==key and e['session']==self.session and e['scope']==self.scope),None)
            if old:
                if old['units']!=units or old['role']!=role:raise ValueError('reservation_key_conflict')
                return old
            totals=dict(packets=sum(x['packet_count'] for x in previous),units=sum(len(x['units']) for x in previous),questions=sum(x['questions'] for x in previous),chars=sum(x['chars'] for x in previous))
            record=dict(session=self.session,scope=self.scope,role=role,key=key,units=units,packet_count=len(batch),questions=sum(u['questions'] for u in units),chars=sum(len(encoded(p)) for p in batch),http_sends=0,mode='FIXTURE')
            if totals['packets']+len(batch)>300 or totals['units']+len(units)>1000 or totals['questions']+record['questions']>4000 or totals['chars']+record['chars']>1200000:raise ValueError('shared_fixture_quota')
            if role=='background' and totals['packets']+len(batch)>240:raise ValueError('dialogue_reserve')
            s.event(self.session,self.scope,'fixture_packet_reservation',record)
        return record
