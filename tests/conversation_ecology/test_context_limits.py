"""Additional persistence/quota/output boundaries; no real inference or browser ack."""
from dataclasses import replace
import json
import sqlite3
from test_context import Base
from conversation_ecology.context.store import ContextStore
from conversation_ecology.context.commits import ContextCommitter
from conversation_ecology.context.output_adapter import OutputAdapter
from conversation_ecology.hearing.accounting import packets, FixtureAccounting


class Limits(Base):
    def test_reported_three_regions_then_preference_only_correction(self):
        self.assertEqual(self.c.reported_context()['status'],'APPLIED')
        person=self.c.item('claim:reported-person');place=self.c.item('claim:reported-place');source=self.c.item('reply:reported')
        self.assertEqual(place['value']['observation_status'],'not_observed')
        result=self.c.change_preference();self.assertEqual(result['status'],'APPLIED')
        self.assertEqual(self.c.item('goal:main')['value']['preference'],'speed')
        self.assertEqual(self.c.item('claim:reported-person'),person);self.assertEqual(self.c.item('claim:reported-place'),place);self.assertEqual(self.c.item('reply:reported'),source)
        self.assertEqual(self.c.item('claim:preference')['revision'],2)
    def test_deadline_metadata_does_not_break_idempotency(self):
        p=self.proposal();a=ContextCommitter(self.s).apply(p)
        b=ContextCommitter(self.s).apply(replace(p,deadline=p.deadline+1))
        self.assertEqual(b['status'],'ALREADY_APPLIED');self.assertEqual(a['commit_id'],b['commit_id'])

    def test_output_reference_respects_historical_cursor(self):
        self.assertEqual(self.s.snapshot('s','participant-a',cursor=1).data()['layers']['L5'],[])

    def test_required_missing_and_change_ports(self):
        from copy import deepcopy
        from conversation_ecology.hearing.coordinator import HearingCoordinator
        for kind in ('clarify_missing','clarify_change'):
            fixture=deepcopy(self.c.fixture);fixture['goals'][0]['confirmation_kind']=kind
            c=HearingCoordinator(self.s,kind,fixture=fixture);c.start()
            self.assertEqual(c.item('question:target')['value']['confirmation_kind'],kind)
    def test_single_owner_reopen_and_release(self):
        with self.assertRaises(FileExistsError):ContextStore(self.path,create=False)
        self.s.close();self.assertFalse(self.path.with_suffix('.owner.lock').exists())
        self.s=ContextStore(self.path,create=False)
        self.assertEqual(self.s.item('s','participant-a','utterance:1')['revision'],1)

    def test_unknown_schema_releases_owner(self):
        self.s.db.execute("UPDATE meta SET value='future' WHERE key='schema'");self.s.close()
        with self.assertRaises(ValueError):ContextStore(self.path,create=False)
        self.assertFalse(self.path.with_suffix('.owner.lock').exists())

    def test_packet_limits_chars_and_units(self):
        self.assertEqual([len(p) for p in packets([dict(questions=2)]*12)],[8,4])
        self.assertEqual([len(p) for p in packets([dict(questions=20)]*2)],[1,1])
        for unit in (dict(questions=0),dict(questions=33),dict(questions=True),dict(questions=2,text='a'*12000)):
            with self.assertRaises(ValueError):packets([unit])

    def test_accounting_no_reset_between_sessions_and_no_refund(self):
        unit=dict(questions=32,text='fixture')
        a=FixtureAccounting(self.s,'s','participant-a')
        for i in range(100):a.reserve('background',[unit],str(i))
        count=self.s.db.execute("SELECT COUNT(*) FROM events WHERE kind='fixture_packet_reservation'").fetchone()[0]
        a.reserve('background',[unit],'0')
        self.assertEqual(count,self.s.db.execute("SELECT COUNT(*) FROM events WHERE kind='fixture_packet_reservation'").fetchone()[0])
        b=FixtureAccounting(self.s,'new-session','participant-a')
        with self.assertRaises(ValueError):b.reserve('hearing',[unit]*30,'excess')
        self.s.close();self.s=ContextStore(self.path,create=False)
        with self.assertRaises(ValueError):FixtureAccounting(self.s,'third','other').reserve('hearing',[unit]*30,'excess')

    def test_capacity_preserves_control_stop(self):
        with self.s.transaction():
            for i in range(9000-self.s.db.execute('SELECT COUNT(*) FROM events').fetchone()[0]):self.s.event('s','participant-a','capacity_fixture',{})
        with self.assertRaisesRegex(ValueError,'capacity'):self.c.source('late','not accepted')
        self.s.stop();self.assertTrue(self.s.stopped)

    def test_checkpoint_rejects_regression_future(self):
        cursor=self.s.snapshot('s','participant-a').data()['available_cursor'];self.s.notify('ui',cursor)
        with self.assertRaisesRegex(ValueError,'regression'):self.s.notify('ui',cursor-1)
        with self.assertRaisesRegex(ValueError,'future'):self.s.notify('ui',cursor+100)

    def test_derived_cutoff_does_not_travel_backwards(self):
        self.s.ingress('s','participant-a','utterance:1',dict(kind='source',label='later revision'),cutoff=40)
        p=self.proposal();self.assertEqual(ContextCommitter(self.s).apply(p)['status'],'APPLIED')
        self.assertNotIn('entity:new',self.s.snapshot('s','participant-a',cutoff=39).data()['items'])

    def test_output_cannot_rebind_evaluation_or_candidate(self):
        response=OutputAdapter(self.s).deliver('s','participant-a')[0]
        args=['s','participant-a','new-turn','answer',response['text'],response['question_id'],response['projection_id'],response['Q'],response['evaluation_id'],response['read_set'],response['candidate_id']]
        args[4]='unevaluated replacement'
        with self.assertRaisesRegex(ValueError,'candidate_binding'):OutputAdapter(self.s).commit(*args)
        args[4]=response['text'];args[6]='invented projection'
        with self.assertRaisesRegex(ValueError,'projection_binding'):OutputAdapter(self.s).commit(*args)
        args[6]=response['projection_id'];args[9]={}
        with self.assertRaisesRegex(ValueError,'projection_binding'):OutputAdapter(self.s).commit(*args)

    def test_sqlite_writer_lock_is_not_success(self):
        p=self.proposal();other=sqlite3.connect(self.path,isolation_level=None)
        try:
            other.execute('BEGIN IMMEDIATE')
            self.assertEqual(ContextCommitter(self.s).apply(p)['status'],'STORAGE_FAILED')
            self.assertIsNone(self.s.item('s','participant-a','entity:new'))
        finally:other.execute('ROLLBACK');other.close()

    def test_queue_descriptor_and_expiry_edges(self):
        from conversation_ecology.context.dependencies import RecheckPlanner
        p=RecheckPlanner()
        for lane,cap in p.CAPS.items():
            for i in range(cap):self.assertEqual(p.add(lane+str(i),lane,now=10),'QUEUED')
        self.assertEqual(len(p.queue),64);self.assertEqual(p.add('65','background',now=10),'DESCRIBED')
        for i in range(191):p.add('rest'+str(i),'background',now=10)
        self.assertEqual(len(p.descriptors),256);self.assertEqual(p.add('257'),'not_accepted_capacity')
        self.assertIsNotNone(p.dispatch('control',15));self.assertIsNone(p.dispatch('control',15.001))

    def test_synthetic_ack_not_counted_as_browser(self):
        from conversation_ecology.context.provider import ContextProvider
        response=OutputAdapter(self.s).deliver('s','participant-a')[0]
        OutputAdapter(self.s).acknowledge('s','participant-a',response['id'],'test','synthetic_test')
        self.assertEqual(ContextProvider(self.c).snapshot()['acks'],[])

    def test_L5_references_durable_response(self):
        response=OutputAdapter(self.s).deliver('s','participant-a')[0]
        self.assertIn(response['id'],self.s.snapshot('s','participant-a').data()['layers']['L5'])

    def test_consumer_descriptor_bound(self):
        from conversation_ecology.context.dependencies import DependencyIndex
        index=DependencyIndex(self.s)
        for i in range(254):index.register(str(i),'s','participant-a','goal:main',{},'HELD')
        with self.assertRaisesRegex(ValueError,'descriptor_capacity'):index.register('excess','s','participant-a','goal:main',{},'HELD')

    def test_stop_cancels_pending_and_rejects_late_write(self):
        self.s.stop()
        states=dict(self.s.db.execute('SELECT id,state FROM consumers'))
        self.assertEqual(states['s:job:background'],'cancelled_before_start')
        with self.assertRaisesRegex(ValueError,'STOPPED'):self.c.source('late','late')

    def test_deletion_scrubs_reusable_derivations_but_preserves_consumption(self):
        self.c.reply('動画解析の方です','r')
        prior=[e for e in self.s.events('s','participant-a') if e['kind']=='fixture_packet_reservation']
        self.s.redact('s','participant-a','reply:r')
        self.assertEqual(OutputAdapter(self.s).deliver('s','participant-a'),[])
        self.assertEqual([e for e in self.s.events('s','participant-a') if e['kind']=='fixture_packet_reservation'],prior)
        self.assertEqual(self.s.replay('s','participant-a')['status'],'incomplete')
        for table,column in [('proposals','canonical'),('item_versions','payload'),('events','payload')]:
            values=' '.join(r[0] for r in self.s.db.execute(f'SELECT {column} FROM {table}'))
            self.assertNotIn('動画解析の方です',values)
