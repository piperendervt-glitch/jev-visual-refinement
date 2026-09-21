"""Durable response slots using the existing C0 validated micro score contract."""
import json
import random
from .model import encoded


def choose(scores,eligible,seed=17):
    candidates=[k for k in eligible if k in scores and scores[k]['Q']>=.65]
    if not candidates:return None
    highest=max(scores[k]['Q'] for k in candidates)
    tied=sorted(k for k in candidates if scores[k]['Q']==highest);random.Random(seed).shuffle(tied)
    return tied[0]


class OutputAdapter:
    def __init__(self,store):self.store=store
    def commit(self,session,scope,turn,slot,text,question_id,projection_id,score,evaluation_id,read_set,candidate_id=None):
        s=self.store
        with s.transaction():
            if type(score) not in (int,float) or not .65<=score<=1:raise ValueError('ineligible_response')
            projection=s.db.execute('SELECT payload FROM projections WHERE id=? AND session=? AND scope=?',(projection_id,session,scope)).fetchone()
            if not projection or json.loads(projection[0])['read_set']!=read_set:raise ValueError('response_projection_binding')
            evaluation=s.item(session,scope,evaluation_id)
            if not evaluation or evaluation['availability']!='available' or evaluation['value'].get('status')!='VALID' or evaluation['value'].get('projection_id')!=projection_id:raise ValueError('response_evaluation_binding')
            if candidate_id:
                value=evaluation['value']
                if value.get('scores',{}).get(candidate_id,{}).get('Q')!=score or value.get('candidate_texts',{}).get(candidate_id)!=text:raise ValueError('response_candidate_binding')
            if any(s.version(session,scope,k)!=v for k,v in read_set.items()):raise ValueError('stale_output')
            if slot not in {'clarification','final_micro','answer','backchannel'}:raise ValueError('slot')
            old=s.db.execute('SELECT payload FROM response_commits WHERE session=? AND scope=? AND turn=? AND slot=?',(session,scope,turn,slot)).fetchone()
            if old:return json.loads(old[0])
            if slot=='clarification':
                question=s.item(session,scope,question_id)
                if not question or question['value'].get('branch_state')!='AWAITING_REPLY':raise ValueError('question_not_current')
                for row in s.db.execute('SELECT payload FROM response_commits WHERE session=? AND scope=? AND slot=?',(session,scope,slot)):
                    q=s.item(session,scope,json.loads(row[0])['question_id'])
                    if q and q['value']['branch_state']=='AWAITING_REPLY':raise ValueError('clarification_slot_occupied')
            group_id=turn+':main' if slot in {'final_micro','answer'} else None
            if group_id and s.db.execute('SELECT 1 FROM response_commits WHERE session=? AND scope=? AND group_id=?',(session,scope,group_id)).fetchone():return None
            cid=f'{session}:response:{turn}:{slot}'
            record=dict(id=cid,text=text,slot=slot,question_id=question_id,projection_id=projection_id,Q=score,evaluation_id=evaluation_id,candidate_id=candidate_id,mode='FIXTURE',read_set=read_set)
            s.db.execute('INSERT INTO response_commits VALUES (?,?,?,?,?,?,?)',(cid,session,scope,turn,slot,group_id,encoded(record)))
            s.event(session,scope,'response_commit',record)
        return record
    def deliver(self,session,scope):
        s=self.store
        with s.transaction():
            records=[json.loads(r[0]) for r in s.db.execute('SELECT payload FROM response_commits WHERE session=? AND scope=?',(session,scope)) if json.loads(r[0]).get('use_state')!='unavailable']
            for c in records:
                if not s.db.execute('SELECT 1 FROM deliveries WHERE commit_id=?',(c['id'],)).fetchone():
                    s.db.execute('INSERT INTO deliveries VALUES (?)',(c['id'],));s.event(session,scope,'delivery',{'commit_id':c['id']})
        return records
    def acknowledge(self,session,scope,cid,evidence,kind='browser_dom'):
        s=self.store
        with s.transaction():
            if not s.db.execute('SELECT 1 FROM response_commits r JOIN deliveries d ON r.id=d.commit_id WHERE r.id=? AND r.session=? AND r.scope=?',(cid,session,scope)).fetchone():raise ValueError('unknown_or_unsent_commit')
            if kind not in {'browser_dom','synthetic_test'}:raise ValueError('ack_kind')
            if kind=='browser_dom' and evidence!='visible_dom_after_two_animation_frames':raise ValueError('ack_evidence')
            value=dict(commit_id=cid,kind=kind,evidence=evidence,human_read_proof=False)
            if s.db.execute('SELECT 1 FROM acknowledgements WHERE commit_id=? AND kind=?',(cid,kind)).fetchone():return False
            s.db.execute('INSERT INTO acknowledgements VALUES (?,?,?)',(cid,kind,encoded(value)));s.event(session,scope,'ack',value)
        return True
