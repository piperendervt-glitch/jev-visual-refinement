"""Finite context writes; response commits are a separate transaction and ID."""
import json
import sqlite3
import time
from .model import encoded, hashed, validate_record

ALLOWED={'entity_register','claim_add','claim_revise','relation_update','goal_binding_resolve','confirmation_transition'}


class ContextCommitter:
    def __init__(self,store,clock=time.monotonic):self.store=store;self.clock=clock

    def apply(self,p):
        s=self.store;payload=p.payload();canonical=encoded(payload)
        try:
            with s.transaction(control=s.stopped):
                old=s.db.execute('SELECT * FROM proposals WHERE update_key=?',(p.update_key,)).fetchone()
                if old:
                    if old['canonical']!=canonical:
                        s.event(p.session,p.scope,'key_conflict',{'key':p.update_key});return {'status':'KEY_CONFLICT'}
                    result=json.loads(old['result']);return dict(result,status='ALREADY_APPLIED') if result['status']=='APPLIED' else result
                result=self.validate(p)
                if result is None:
                    cursor=s.event(p.session,p.scope,'context_commit',{'key':p.update_key,'payload_hash':hashed(payload),'projection_id':p.projection_id})
                    changes=[]
                    projection=json.loads(s.db.execute('SELECT payload FROM projections WHERE id=?',(p.projection_id,)).fetchone()[0])
                    cutoff=max((v['source_cutoff'] for v in projection['items'].values()),default=0)
                    for ident,value in p.writes.items():
                        oldrev=s.version(p.session,p.scope,ident)
                        newrev=s.put(p.session,p.scope,ident,value,cutoff,cursor)
                        changes.append(dict(id=ident,before=oldrev,after=newrev,kind='changed' if oldrev else 'added'))
                    cid=f'{p.session}:context:{cursor}'
                    s.db.execute('INSERT INTO context_commits VALUES (?,?,?,?)',(cid,p.update_key,cursor,encoded(changes)))
                    # The inverse index is a projection; synchronous validation above is authoritative.
                    affected=[]
                    for c in s.db.execute('SELECT * FROM consumers WHERE session=? AND scope=?',(p.session,p.scope)).fetchall():
                        if set(json.loads(c['refs'])) & set(p.writes):
                            s.db.execute("UPDATE consumers SET state='STALE' WHERE id=?",(c['id'],));affected.append(c['id'])
                    result=dict(status='APPLIED',commit_id=cid,cursor=cursor,changeset=changes,affected=affected)
                    s.db.execute('UPDATE events SET payload=? WHERE cursor=?',(encoded(dict(result,projection_id=p.projection_id,source_refs=p.source_refs,evaluation_id=p.evaluation_id)),cursor))
                s.db.execute('INSERT INTO proposals VALUES (?,?,?)',(p.update_key,canonical,encoded(result)))
                if result['status']!='APPLIED':s.event(p.session,p.scope,'proposal_result',result)
            return result
        except sqlite3.Error as error:
            recorded=s.db.execute('SELECT 1 FROM proposals WHERE update_key=?',(p.update_key,)).fetchone()
            return dict(status='COMMIT_UNCERTAIN' if recorded else 'STORAGE_FAILED',reason=type(error).__name__)

    def validate(self,p):
        s=self.store
        def reject(reason):return dict(status='REJECTED',reason=reason)
        if s.stopped:return {'status':'STOPPED'}
        if self.clock()>p.deadline:return {'status':'EXPIRED'}
        if p.update_kind not in ALLOWED or not p.writes or len(p.writes)>32:return reject('finite_update_kind')
        if len(encoded(p.writes).encode())>64000:return reject('proposal_size')
        row=s.db.execute('SELECT * FROM projections WHERE id=?',(p.projection_id,)).fetchone()
        if not row or row['session']!=p.session or row['scope']!=p.scope:return reject('projection_scope')
        projection=json.loads(row['payload'])
        if any(v['availability']!='available' for v in projection['items'].values()):return reject('projection_unavailable')
        if projection['read_set']!=p.read_set:return reject('read_set_not_actual_projection')
        if set(p.expected)!=set(p.writes):return reject('expected_write_set')
        for ident,revision in {**p.read_set,**p.expected}.items():
            if s.version(p.session,p.scope,ident)!=revision:return dict(status='VERSION_CONFLICT',item=ident)
        if any(k in p.read_set and p.read_set[k]!=v for k,v in p.expected.items()):return reject('inconsistent_read_write_versions')
        for ident in p.source_refs:
            item=s.item(p.session,p.scope,ident)
            if not item or item['availability']!='available' or item['value']['kind'] not in {'source','fact'}:return reject('source_unavailable')
            if ident not in p.read_set:return reject('source_not_read')
        evaluation=s.item(p.session,p.scope,p.evaluation_id) if p.evaluation_id else None
        if not evaluation or evaluation['availability']!='available' or evaluation['value'].get('status')!='VALID':return {'status':'PENDING_EVALUATION'}
        if evaluation['value'].get('projection_id')!=p.projection_id:return reject('evaluation_binding')
        for ident,value in p.writes.items():
            try:validate_record(value)
            except ValueError as e:return reject(str(e))
            if ident.startswith(('L0','permission','work','raw')):return reject('protected_target')
            if value['kind'] not in {'entity','claim','goal','question'}:return reject('dedicated_ingress_required')
            if value['kind']=='claim':
                if not set(value['source_refs'])<=set(p.source_refs):return reject('uncited_claim')
                entity=p.writes.get(value['entity_ref']) or (s.item(p.session,p.scope,value['entity_ref']) or {}).get('value')
                if not entity or entity['kind']!='entity':return reject('entity_scope')
        if p.update_kind=='goal_binding_resolve':
            goals=[(i,v) for i,v in p.writes.items() if v['kind']=='goal']
            questions=[v for v in p.writes.values() if v['kind']=='question']
            if len(goals)!=1 or len(questions)!=1:return reject('atomic_binding_confirmation_required')
            gid,goal=goals[0];question=questions[0]
            if question.get('goal_id')!=gid or question.get('resolved_target')!=goal.get('target_binding'):return reject('binding_confirmation_mismatch')
            if not question.get('reply_ref') in p.source_refs:return reject('reply_reference')
            previous=s.item(p.session,p.scope,gid)
            if previous and any(goal.get(k)!=previous['value'].get(k) for k in ('budget','deadline','authority')):return reject('unanswered_branch_change')
        return None
