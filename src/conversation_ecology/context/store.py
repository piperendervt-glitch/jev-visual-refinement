"""One SQLite canonical store, short single-writer transactions and durable outbox."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
from .model import encoded, LayerView, validate_record


class ContextStore:
    def __init__(self,path,*,create=True,clock=time.time,fault=None):
        self.path=Path(path);self.clock=clock;self.fault=fault or (lambda stage:None)
        self.lock=threading.RLock();self.stopped=False;self.closed=False
        if create and self.path.exists():raise ValueError('run_collision')
        if not create and not self.path.is_file():raise ValueError('missing_run')
        self.path.parent.mkdir(parents=True,exist_ok=True)
        if any(p.is_symlink() or p.is_junction() for p in (self.path,*self.path.parents)):raise ValueError('reparse_denied')
        self.lease=self.path.with_suffix('.owner.lock')
        self.lease_fd=os.open(self.lease,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        os.write(self.lease_fd,str(os.getpid()).encode())
        try:
            if not create:
                from contextlib import closing
                with closing(sqlite3.connect(f'file:{self.path.as_posix()}?mode=ro',uri=True)) as probe:
                    if probe.execute("SELECT value FROM meta WHERE key='schema'").fetchone()[0]!='context-store-v1':raise ValueError('unknown_schema')
                    if clock()>=float(probe.execute("SELECT value FROM meta WHERE key='expires'").fetchone()[0]):raise ValueError('retention_expired')
            self.db=sqlite3.connect(self.path,timeout=1,check_same_thread=False,isolation_level=None)
        except BaseException:
            os.close(self.lease_fd);self.lease.unlink();raise
        try:
            self.db.row_factory=sqlite3.Row
            self.db.execute('PRAGMA foreign_keys=ON');self.db.execute('PRAGMA journal_mode=DELETE');self.db.execute('PRAGMA synchronous=FULL')
            if create:
                self.db.executescript('''
                CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE events(cursor INTEGER PRIMARY KEY AUTOINCREMENT,session TEXT,scope TEXT,kind TEXT,payload TEXT);
                CREATE TABLE item_versions(session TEXT,scope TEXT,id TEXT,revision INTEGER,cursor INTEGER,cutoff REAL,payload TEXT,availability TEXT,PRIMARY KEY(session,scope,id,revision));
                CREATE TABLE current_items(session TEXT,scope TEXT,id TEXT,revision INTEGER,PRIMARY KEY(session,scope,id));
                CREATE TABLE proposals(update_key TEXT PRIMARY KEY,canonical TEXT,result TEXT);
                CREATE TABLE context_commits(id TEXT PRIMARY KEY,update_key TEXT UNIQUE,cursor INTEGER,changeset TEXT);
                CREATE TABLE notification_outbox(cursor INTEGER PRIMARY KEY REFERENCES events(cursor),delivered INTEGER DEFAULT 0);
                CREATE TABLE projection_checkpoints(consumer TEXT PRIMARY KEY,cursor INTEGER);
                CREATE TABLE projections(id TEXT PRIMARY KEY,session TEXT,scope TEXT,payload TEXT);
                CREATE TABLE consumers(id TEXT PRIMARY KEY,session TEXT,scope TEXT,goal TEXT,refs TEXT,state TEXT);
                CREATE TABLE response_commits(id TEXT PRIMARY KEY,session TEXT,scope TEXT,turn TEXT,slot TEXT,group_id TEXT,payload TEXT,UNIQUE(session,scope,turn,slot));
                CREATE UNIQUE INDEX final_group ON response_commits(session,scope,group_id) WHERE group_id IS NOT NULL;
                CREATE TABLE deliveries(commit_id TEXT PRIMARY KEY REFERENCES response_commits(id));
                CREATE TABLE acknowledgements(commit_id TEXT,kind TEXT,payload TEXT,PRIMARY KEY(commit_id,kind),FOREIGN KEY(commit_id) REFERENCES response_commits(id));
                ''')
                self.db.executemany('INSERT INTO meta VALUES (?,?)',[('schema','context-store-v1'),('created',str(clock())),('expires',str(clock()+7*86400))])
            if self.db.execute("SELECT value FROM meta WHERE key='schema'").fetchone()[0]!='context-store-v1':raise ValueError('unknown_schema')
            self.ensure_available()
            if not create:
                with self.transaction(control=True):self.db.execute("UPDATE consumers SET state='interrupted' WHERE state='RUNNING'")
        except BaseException:
            self.db.close();os.close(self.lease_fd);self.lease.unlink();raise

    def ensure_available(self):
        if self.closed:raise ValueError('store_closed')
        if self.clock()>=float(self.db.execute("SELECT value FROM meta WHERE key='expires'").fetchone()[0]):raise ValueError('retention_expired')

    @contextmanager
    def transaction(self,control=False):
        with self.lock:
            self.ensure_available()
            if self.stopped and not control:raise ValueError('STOPPED')
            self.db.execute('BEGIN IMMEDIATE')
            try:
                limit=10000 if control else 9000;byte_limit=(50 if control else 45)*1024*1024
                if self.db.execute('SELECT COUNT(*) FROM events').fetchone()[0]>=limit or self.path.stat().st_size>=byte_limit:raise ValueError('not_accepted_capacity')
                yield
                if self.db.execute('SELECT COUNT(*) FROM events').fetchone()[0]>limit or self.db.execute('PRAGMA page_count').fetchone()[0]*self.db.execute('PRAGMA page_size').fetchone()[0]>byte_limit:raise ValueError('not_accepted_capacity')
                self.fault('before_commit');self.db.execute('COMMIT')
            except BaseException:
                if self.db.in_transaction:self.db.execute('ROLLBACK')
                raise
            self.fault('after_commit_before_notify')

    def event(self,session,scope,kind,payload):
        cursor=self.db.execute('INSERT INTO events(session,scope,kind,payload) VALUES (?,?,?,?)',(session,scope,kind,encoded(payload))).lastrowid
        self.db.execute('INSERT INTO notification_outbox(cursor) VALUES (?)',(cursor,));return cursor

    def version(self,session,scope,ident):
        row=self.db.execute('SELECT revision FROM current_items WHERE session=? AND scope=? AND id=?',(session,scope,ident)).fetchone()
        return row[0] if row else 0

    def item(self,session,scope,ident):
        row=self.db.execute('SELECT v.* FROM item_versions v JOIN current_items c USING(session,scope,id,revision) WHERE session=? AND scope=? AND id=?',(session,scope,ident)).fetchone()
        return self.unpack(row) if row else None

    @staticmethod
    def unpack(row):
        return dict(id=row['id'],session_id=row['session'],subject_scope=row['scope'],schema_version='context-model-v1',mode='FIXTURE',revision=row['revision'],cursor=row['cursor'],source_cutoff=row['cutoff'],availability=row['availability'],value=json.loads(row['payload']))

    def put(self,session,scope,ident,value,cutoff,cursor,availability='available'):
        validate_record(value);revision=self.version(session,scope,ident)+1
        self.db.execute('INSERT INTO item_versions VALUES (?,?,?,?,?,?,?,?)',(session,scope,ident,revision,cursor,cutoff,encoded(value),availability))
        self.db.execute('INSERT INTO current_items VALUES (?,?,?,?) ON CONFLICT(session,scope,id) DO UPDATE SET revision=excluded.revision',(session,scope,ident,revision))
        return revision

    def ingress(self,session,scope,ident,value,cutoff=0):
        if len(encoded(value).encode())>64000:raise ValueError('record_size')
        if value['kind'] not in {'source','fact','evaluation','artifact','set'}:raise ValueError('dedicated_ingress_only')
        with self.transaction():
            validate_record(value);cursor=self.event(session,scope,value['kind'],{'id':ident})
            revision=self.put(session,scope,ident,value,cutoff,cursor)
        return revision

    def snapshot(self,session,scope,cutoff=1e12,cursor=None,refs=None):
        with self.lock:
            self.ensure_available()
            if cursor is None:cursor=self.db.execute('SELECT COALESCE(MAX(cursor),0) FROM events WHERE session=? AND scope=?',(session,scope)).fetchone()[0]
            rows=self.db.execute('SELECT * FROM item_versions WHERE session=? AND scope=? AND cursor<=? AND cutoff<=? ORDER BY revision',(session,scope,cursor,cutoff)).fetchall()
            items={r['id']:self.unpack(r) for r in rows}
            if refs is not None:items={k:v for k,v in items.items() if k in refs}
            read_set={k:v['revision'] for k,v in items.items()}
            for k in refs or []:read_set.setdefault(k,0)
            source_refs=[k for k,v in items.items() if v['value']['kind'] in {'source','fact'}]
            output_refs=[]
            for row in self.db.execute("SELECT payload FROM events WHERE session=? AND scope=? AND cursor<=? AND kind='response_commit'",(session,scope,cursor)):
                response=json.loads(row[0])
                if response.get('id') and all(k in items and items[k]['revision']==v for k,v in response['read_set'].items()):output_refs.append(response['id'])
            layers={'L0':{'work':'denied','models':'denied','scope':scope},'L1':list(items),'L2':[k for k,v in items.items() if v['value']['kind'] in {'goal','question'}],
                    'L3':{'read_set':read_set},'L4':source_refs,'L5':output_refs}
            return LayerView(encoded(dict(schema='context-readset-v1',session=session,scope=scope,source_cutoff=cutoff,available_cursor=cursor,items=items,read_set=read_set,layers=layers)))

    def register_projection(self,view):
        d=view.data()
        with self.transaction():self.db.execute('INSERT OR IGNORE INTO projections VALUES (?,?,?,?)',(view.id,d['session'],d['scope'],view.canonical))

    def events(self,session,scope):
        self.ensure_available()
        return [dict(cursor=r['cursor'],id=f"{session}:event:{r['cursor']}",kind=r['kind'],payload=json.loads(r['payload'])) for r in self.db.execute('SELECT * FROM events WHERE session=? AND scope=? ORDER BY cursor',(session,scope))]

    def replay(self,session,scope):
        view=self.snapshot(session,scope).data()
        missing=[k for k,v in view['items'].items() if v['availability']!='available']
        return dict(status='incomplete' if missing else 'complete_for_recorded_inputs',view=view,events=self.events(session,scope),missing=missing,network_calls=0)

    def rebuild(self):
        with self.transaction(control=True):
            self.db.execute('DELETE FROM current_items')
            self.db.execute('INSERT INTO current_items SELECT session,scope,id,MAX(revision) FROM item_versions GROUP BY session,scope,id')
            self.db.execute('DELETE FROM projection_checkpoints')
            self.db.execute('UPDATE notification_outbox SET delivered=0')

    def notify(self,consumer,cursor):
        with self.transaction():
            old=self.db.execute('SELECT cursor FROM projection_checkpoints WHERE consumer=?',(consumer,)).fetchone()
            if old and cursor<old[0]:raise ValueError('projection_regression')
            if cursor>self.db.execute('SELECT COALESCE(MAX(cursor),0) FROM events').fetchone()[0]:raise ValueError('future_cursor')
            self.db.execute('INSERT INTO projection_checkpoints VALUES (?,?) ON CONFLICT(consumer) DO UPDATE SET cursor=excluded.cursor',(consumer,cursor))
            self.db.execute('UPDATE notification_outbox SET delivered=1 WHERE cursor<=?',(cursor,))

    def redact(self,session,scope,ident):
        with self.transaction(control=True):
            item=self.item(session,scope,ident)
            if not item:raise ValueError('unknown_record')
            cursor=self.event(session,scope,'deleted',{'id':ident})
            # Payload-bearing projections and historical payloads cannot remain reusable.
            self.db.execute('UPDATE item_versions SET payload=?,availability=? WHERE session=? AND scope=? AND id=?',(encoded({'kind':item['value']['kind'],'label':'deleted'}),'deleted',session,scope,ident))
            self.db.execute('DELETE FROM projections WHERE session=? AND scope=?',(session,scope))
            for row in self.db.execute('SELECT * FROM consumers WHERE session=? AND scope=?',(session,scope)).fetchall():
                if ident in json.loads(row['refs']):self.db.execute("UPDATE consumers SET state='UNAVAILABLE' WHERE id=?",(row['id'],))
            for row in self.db.execute('SELECT v.* FROM item_versions v JOIN current_items c USING(session,scope,id,revision) WHERE session=? AND scope=?',(session,scope)).fetchall():
                value=json.loads(row['payload'])
                if ident in value.get('source_refs',[]):
                    value['use_state']='unavailable';self.put(session,scope,row['id'],value,row['cutoff'],cursor,'unavailable')
            # Deletion is conservative within this scope: derived payloads may quote
            # sources indirectly. Keep cursor/identity audit, invalidate all derived
            # reuse, preserve other raw source/fact records and unrelated scopes.
            for row in self.db.execute('SELECT * FROM item_versions WHERE session=? AND scope=?',(session,scope)).fetchall():
                value=json.loads(row['payload'])
                if value['kind'] not in {'source','fact','entity'}:
                    tombstone={'kind':value['kind'],'label':'unavailable after source deletion','source_refs':[],'use_state':'unavailable'}
                    self.db.execute('UPDATE item_versions SET payload=?,availability=? WHERE session=? AND scope=? AND id=? AND revision=?',(encoded(tombstone),'unavailable',session,scope,row['id'],row['revision']))
            self.db.execute("UPDATE consumers SET state='UNAVAILABLE' WHERE session=? AND scope=?",(session,scope))
            for row in self.db.execute('SELECT * FROM proposals').fetchall():
                value=json.loads(row['canonical'])
                if value.get('session')==session and value.get('scope')==scope:
                    self.db.execute('UPDATE proposals SET canonical=?,result=? WHERE update_key=?',(encoded({'session':session,'scope':scope,'unavailable':True}),encoded({'status':'UNAVAILABLE'}),row['update_key']))
            for row in self.db.execute('SELECT id,payload FROM response_commits WHERE session=? AND scope=?',(session,scope)).fetchall():
                value=json.loads(row['payload']);value.update(text='保存元削除により再利用不可',use_state='unavailable',read_set={})
                self.db.execute('UPDATE response_commits SET payload=? WHERE id=?',(encoded(value),row['id']))
            self.db.execute("UPDATE events SET payload=? WHERE session=? AND scope=? AND cursor<? AND kind!='fixture_packet_reservation'",(encoded({'unavailable_after_deletion':ident}),session,scope,cursor))
        # Logical erasure is not a claim of storage-device secure erase.

    def stop(self):
        with self.lock:
            self.stopped=True
            with self.transaction(control=True):
                self.db.execute("UPDATE consumers SET state='cancelled_before_start' WHERE state='QUEUED'")
                self.db.execute("UPDATE consumers SET state='interrupted' WHERE state='RUNNING'")
                self.event('_control','_control','stop',{'accepted':True})

    def close(self):
        with self.lock:
            if self.db.in_transaction:raise RuntimeError('active_transaction_on_close')
            self.db.close();self.closed=True
            os.close(self.lease_fd);self.lease.unlink()
