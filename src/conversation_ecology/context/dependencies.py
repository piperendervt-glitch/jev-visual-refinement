"""Bounded dependency planning, not an executor or semantic relevance classifier."""
from collections import Counter
import json
from .model import encoded


class DependencyIndex:
    def __init__(self,store):self.store=store
    def register(self,ident,session,scope,goal,refs,state='QUEUED'):
        with self.store.transaction():
            if self.store.db.execute('SELECT COUNT(*) FROM consumers').fetchone()[0]>=256:raise ValueError('descriptor_capacity')
            if state=='QUEUED' and self.store.db.execute("SELECT COUNT(*) FROM consumers WHERE state='QUEUED'").fetchone()[0]>=64:raise ValueError('queue_capacity')
            self.store.db.execute('INSERT INTO consumers VALUES (?,?,?,?,?,?)',(ident,session,scope,goal,encoded(refs),state))
    def affected(self,session,scope,keys):
        return [r['id'] for r in self.store.db.execute('SELECT * FROM consumers WHERE session=? AND scope=?',(session,scope)) if set(json.loads(r['refs']))&set(keys)]
    def rebuild(self):
        reverse={}
        for row in self.store.db.execute('SELECT * FROM consumers'):
            for key in json.loads(row['refs']):reverse.setdefault((row['session'],row['scope'],key),set()).add(row['id'])
        return reverse


class RecheckPlanner:
    CAPS={'control':16,'interactive':24,'background':16,'inspection':8}
    def __init__(self):
        self.descriptors={};self.queue=[];self.seen=set();self.skipped=Counter();self.stopped=False;self.dispatches=Counter()
    def add(self,ident,lane='background',now=0,protected=False):
        if self.stopped:return 'STOPPED'
        if ident in self.descriptors:return 'DUPLICATE'
        if len(self.descriptors)>=256:self.skipped['descriptor_capacity']+=1;return 'not_accepted_capacity'
        self.descriptors[ident]=dict(id=ident,lane=lane,expires=now+5,state='DESCRIBED',protected=protected,subscribers=set())
        if sum(self.descriptors[i]['lane']==lane for i in self.queue)>=self.CAPS[lane]:self.skipped['queue_capacity']+=1;return 'DESCRIBED'
        self.queue.append(ident);self.descriptors[ident]['state']='QUEUED';return 'QUEUED'
    def recheck(self,change,goals,session,scope,now=0):
        selected=[]
        eligible=[g for g in goals if g['session']==session and g['scope']==scope and g.get('active',True)]
        self.skipped['goal_limit']+=max(0,len(eligible)-4)
        for goal in eligible[:4]:
            consumers=goal['consumers'];self.skipped['consumer_limit']+=max(0,len(consumers)-8)
            for consumer in consumers[:8]:
                key=(change,goal['id'],consumer,'fixture-v1')
                if key in self.seen:continue
                if len(self.seen)>=256:self.skipped['recheck_key_capacity']+=1;continue
                self.seen.add(key);selected.append(key)
        for key in selected[:8]:self.add('|'.join(key),'inspection',now)
        self.skipped['dispatch_page_pending']+=max(0,len(selected)-8)
        # Descriptors retain the remainder; each dispatch moves at most eight references.
        for key in selected[8:]:self.add('|'.join(key),'inspection',now)
        return selected
    def dispatch(self,lane,now):
        if lane not in self.CAPS:raise ValueError('lane')
        available=self.CAPS[lane]-sum(self.descriptors[i]['lane']==lane for i in self.queue)
        for d in list(self.descriptors.values()):
            if available<=0:break
            if d['lane']==lane and d['state']=='DESCRIBED':
                if now>d['expires']:d['state']='EXPIRED';continue
                self.queue.append(d['id']);d['state']='QUEUED';available-=1
        candidates=[self.descriptors[i] for i in self.queue if self.descriptors[i]['lane']==lane]
        for d in list(candidates):
            if now>d['expires']:d['state']='EXPIRED';self.queue.remove(d['id']);candidates.remove(d)
        if self.stopped or not candidates:return None
        self.dispatches[lane]+=1
        protected=[d for d in candidates if d['protected']]
        chosen=protected[0] if self.dispatches[lane]%10==0 and protected else candidates[0]
        self.queue.remove(chosen['id']);chosen['state']='RUNNING';return chosen['id']
    def subscribe(self,child,parent):self.descriptors[child]['subscribers'].add(parent)
    def prune(self,child,parent):
        d=self.descriptors[child];d['subscribers'].discard(parent)
        if not d['subscribers'] and d['state']!='RUNNING':
            if child in self.queue:self.queue.remove(child)
            d['state']='cancelled_before_start'
        return d['state']
    def stop(self):
        self.stopped=True
        for ident in self.queue:self.descriptors[ident]['state']='cancelled_before_start'
        self.queue.clear()


def select_planned_job(candidates,evaluations):
    """Generic value selection from fixture scores; never starts real work."""
    from ..contracts import number
    valid=[]
    for candidate in candidates:
        score=evaluations.get(candidate['id'])
        if not score:continue
        try:
            values=[number(score[k],0,4)/4 for k in ('usefulness','incremental_value','resolves_gap')]
        except (ValueError,KeyError):continue
        value=sum(a*b for a,b in zip((.5,.3,.2),values))
        valid.append((value,candidate['id']))
    return max(valid)[1] if valid else None
