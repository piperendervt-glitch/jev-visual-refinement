"""unittest専用。旧pytest/conftestを収集しない。"""
import ast
from concurrent.futures import ThreadPoolExecutor
import copy
from dataclasses import FrozenInstanceError, replace
import http.client
import json
from pathlib import Path
import sys
import threading
import unittest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"src"))
from conversation_ecology.engine import Engine
from conversation_ecology.evaluation import FixtureEvaluator, validate
from conversation_ecology.templates import deduplicate
from conversation_ecology.demo import run_demo
from conversation_ecology.events import replay
from conversation_ecology.isolation import Boundary, FORBIDDEN_IMPORTS
from conversation_ecology.server import make_server

class Contracts(unittest.TestCase):
    def fresh(self,text="こんにちは。",**kwargs):
        e=Engine(FixtureEvaluator(),**kwargs);s=e.ingest(text);e.advance(25);return e,s

    def test_T01_generators_and_evaluation_required(self):
        e,s=self.fresh()
        calls=next(x["payload"]["calls"] for x in e.events if x["kind"]=="generators")
        self.assertEqual(len(calls),6);self.assertEqual({c["snapshot_id"] for c in calls},{s.snapshot_id})
        self.assertTrue(any(c["count"]==0 for c in calls))
        with self.assertRaises(ValueError):e.commit(e.candidates[s.snapshot_id][0].id,"absent")
        e.evaluator=None;r=e.evaluate()
        self.assertEqual(r["status"],"INVALID");self.assertIsNone(e.decide(r["id"]))

    def test_T02_score_only_intervention(self):
        winners=[];sets=[]
        for target in (0,1):
            e,s=self.fresh();cs=e.candidates[s.snapshot_id]
            scores={c.id:dict.fromkeys(("task_fit","context_fit","timing_fit"),4 if i==target else 1) for i,c in enumerate(cs)}
            winners.append(e.decide(e.evaluate(overrides=scores)["id"])["candidate_id"]);sets.append([c.id for c in cs])
        self.assertEqual(sets[0],sets[1]);self.assertNotEqual(*winners)

    def test_T03_hundred_duplicates_and_boundaries(self):
        e,s=self.fresh();cs=e.candidates[s.snapshot_id];one=cs[0]
        merged=deduplicate(cs+[replace(one,proposers=("duplicate",)) for _ in range(100)])
        self.assertEqual([c.id for c in merged],[c.id for c in cs])
        e.candidates[s.snapshot_id]=merged;chosen=e.decide(e.evaluate()["id"])
        other,_=self.fresh()
        self.assertEqual(chosen["candidate_id"],other.decide(other.evaluate()["id"])["candidate_id"])
        self.assertEqual(len(deduplicate([one,replace(one,turn_id="other"),replace(one,slot="backchannel"),replace(one,prerequisites=("other",))])),4)

    def test_T04_revision_and_old_arrival(self):
        e,s=self.fresh();e.ingest("訂正：こんにちは",revision=True);e.advance(25)
        old=e.evaluate(s.snapshot_id);self.assertEqual(old["status"],"STALE");self.assertIsNone(e.decide(old["id"]))
        e.advance(300);commit=e.decide(e.evaluate()["id"])
        self.assertEqual(commit["snapshot_id"],e.current.snapshot_id)

    def test_old_valid_evaluation_cannot_commit_to_new_turn(self):
        e,s=self.fresh();r=e.evaluate();e.ingest("別の発話")
        with self.assertRaises(ValueError):e.commit(e.candidates[s.snapshot_id][0].id,r["id"])

    def test_background_and_immutable_snapshot(self):
        e,s=self.fresh();e.background_update();self.assertEqual(e.current,s)
        self.assertEqual(s.context_snapshot_id,"context-0");self.assertIsNotNone(e.decide(e.evaluate()["id"]))
        with self.assertRaises(FrozenInstanceError):s.text="changed"

    def test_T05_compound_and_T06_authority_boundary(self):
        e=run_demo("work","test");self.assertTrue(e.main_pending);self.assertEqual(len(e.commits),1)
        for text,phase,source in [("はい","finalized","user_fixture"),("修正して","partial","user_fixture"),("修正して","finalized","external_fixture")]:
            e=Engine(FixtureEvaluator());e.ingest(text,phase=phase,source=source);e.advance(25);e.decide(e.evaluate()["id"])
            tasks=[x["payload"] for x in e.events if x["kind"]=="task"]
            self.assertTrue(all(x["simulated"] and not x["authority_issued"] and not x["real_work"] for x in tasks))
            self.assertFalse(any(x["kind"] in {"work_started","work_completed","authorization"} for x in e.events))
            if source=="external_fixture":self.assertFalse(e.commits)

    def test_T07_failures_do_not_force_answers(self):
        for profile in ("low","missing","timeout"):
            e,s=self.fresh("相談したい");r=e.evaluate(profile=profile)
            self.assertIsNone(e.decide(r["id"]));self.assertTrue(e.main_pending)
            if profile!="low":self.assertEqual(r["scores"],{})

    def test_invalid_type_range_and_binding(self):
        e,s=self.fresh();cs=e.candidates[s.snapshot_id];base=e.evaluator.evaluate(s,cs)
        for bad in (True,float("nan"),float("inf"),-1,4.1,"4"):
            payload=copy.deepcopy(base);payload["scores"][cs[0].id]["task_fit"]=bad
            with self.assertRaises(ValueError):validate(payload,s,cs)
        for field,value in [("candidate_ids",[]),("snapshot_id","future"),("mode","LIVE_JEV"),("revision",99)]:
            payload=copy.deepcopy(base);payload[field]=value
            with self.assertRaises(ValueError):validate(payload,s,cs)

    def test_invalid_numeric_response_remains_serializable(self):
        e,s=self.fresh();cs=e.candidates[s.snapshot_id]
        raw=e.evaluator.evaluate(s,cs);raw["scores"][cs[0].id]["task_fit"]=float("inf")
        result=e.evaluate(response=raw)
        self.assertEqual(result["status"],"INVALID")
        json.dumps(e.view(),allow_nan=False)
        raw=e.evaluator.evaluate(s,cs);raw["status"]="STREAMING"
        with self.assertRaises(ValueError):validate(raw,s,cs)

    def test_T08_atomic_competition_delivery_and_ack(self):
        e,s=self.fresh();r=e.evaluate();cs=e.candidates[s.snapshot_id]
        with ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(lambda i:e.commit(cs[i%2].id,r["id"]),range(32)))
        self.assertEqual(len(e.commits),1);cid=next(iter(e.commits));e.deliver();e.deliver()
        self.assertEqual(len(e.deliveries),1);self.assertFalse(e.acks)
        self.assertTrue(e.acknowledge(cid,"unit-test-only"));self.assertFalse(e.acknowledge(cid,"unit-test-only"))
        with self.assertRaises(ValueError):e.acknowledge("unknown","unit-test-only")

    def test_B01_final_response_group(self):
        e,s=self.fresh();c=e.candidates[s.snapshot_id][0]
        e.candidates[s.snapshot_id]=[replace(c,slot="final_micro"),replace(c,id="answer-candidate",slot="answer")]
        r=e.evaluate()
        with ThreadPoolExecutor(max_workers=2) as pool:values=list(pool.map(lambda c:e.commit(c.id,r["id"]),e.candidates[s.snapshot_id]))
        self.assertEqual(sum(v is not None for v in values),1)

    def test_B02_B03_outbox_ack_provenance(self):
        e,s=self.fresh();c=e.decide(e.evaluate()["id"])
        with self.assertRaises(ValueError):e.acknowledge(c["id"],"unit-test-only")
        self.assertEqual(e.deliver(),e.deliver());self.assertFalse(e.acks)
        e.acknowledge(c["id"],"unit-test-only")
        with self.assertRaises(ValueError):e.acknowledge(c["id"],"sent",kind="browser_dom")
        e.acknowledge(c["id"],"connected_dom_after_two_animation_frames",kind="browser_dom")
        self.assertEqual({x["kind"] for x in e.acks.values()},{"synthetic_test","browser_dom"})

    def test_generation_cannot_bypass_slot_and_history_retained(self):
        e,s=self.fresh();c=e.decide(e.evaluate()["id"]);e.advance(300)
        e.ingest("こんにちは、訂正です",revision=True);e.advance(25)
        self.assertIsNone(e.decide(e.evaluate()["id"]));self.assertEqual(list(e.commits),[c["id"]])
        self.assertTrue(any(x["kind"]=="correction" for x in e.events))

    def test_T09_double_asof_and_late_evaluation(self):
        e,s=self.fresh()
        materials=[{"capture_ms":s.source_cutoff,"available_cursor":s.available_cursor},{"capture_ms":s.source_cutoff+1,"available_cursor":s.available_cursor},{"capture_ms":s.source_cutoff,"available_cursor":s.available_cursor+1}]
        self.assertEqual(e.as_of_materials(materials,s),materials[:1])
        cursor=len(e.events);r=e.evaluate();self.assertIsNone(e.decide(r["id"],cursor=cursor))

    def test_B04_deadline_and_commit_recheck(self):
        e,s=self.fresh();e.advance(725);r=e.evaluate();self.assertEqual(r["status"],"VALID");e.advance(1)
        with self.assertRaises(ValueError):e.commit(e.candidates[s.snapshot_id][0].id,r["id"])
        self.assertIsNone(e.decide(r["id"]))
        e,s=self.fresh();e.advance(726);self.assertEqual(e.evaluate()["status"],"TIMEOUT")

    def test_collection_interval_cooldown(self):
        e=Engine(FixtureEvaluator());e.ingest("聞いて")
        with self.assertRaises(ValueError):e.evaluate()
        e.advance(25);self.assertEqual(e.decide(e.evaluate()["id"])["slot"],"backchannel")
        e.ingest("また聞いて");e.advance(25)
        with self.assertRaises(ValueError):e.evaluate()
        e.advance(275);self.assertIsNone(e.decide(e.evaluate()["id"]))
        e.advance(1200);e.ingest("もう一度聞いて");e.advance(25)
        self.assertEqual(e.decide(e.evaluate()["id"])["slot"],"backchannel")

    def test_silence_defer_do_not_complete_main(self):
        for act in ("silence","defer_to_main"):
            e,s=self.fresh("相談したい")
            scores={c.id:dict.fromkeys(("task_fit","context_fit","timing_fit"),4 if c.act==act else 0) for c in e.candidates[s.snapshot_id]}
            self.assertEqual(e.decide(e.evaluate(overrides=scores)["id"])["act"],act);self.assertTrue(e.main_pending)

    def test_seed_ties_are_not_fixed_by_generator(self):
        winners=set()
        for seed in range(10):
            e,s=self.fresh(seed=seed)
            scores={c.id:dict.fromkeys(("task_fit","context_fit","timing_fit"),4) for c in e.candidates[s.snapshot_id]}
            winners.add(e.decide(e.evaluate(overrides=scores)["id"])["candidate_id"])
        self.assertGreater(len(winners),1)

    def test_T10_fixture_replay_projection(self):
        for scenario in ("short","correction","unsuitable","work"):
            e=run_demo(scenario,"replay");e.deliver()
            for cid in e.commits:e.acknowledge(cid,"unit-test-only")
            saved=json.loads(json.dumps(e.events,ensure_ascii=False));p=replay(saved)
            self.assertEqual(p["commits"],list(e.commits.values()))
            self.assertEqual(p["evaluations"],list(e.evaluations.values()))
            self.assertEqual(p["threads"],e.threads);self.assertEqual(p["acks"],list(e.acks.values()))
            self.assertEqual(p["fixture_evaluation_attempts"],len(e.evaluations))
            self.assertTrue(all(x["snapshot_id"] in e.snapshots for x in p["evaluations"]))
        with self.assertRaises(ValueError):replay(saved[::-1])

    def test_T11_numeric_kinds(self):
        e=run_demo("short","view");v=e.view()
        self.assertEqual(v["stage"],"C0");self.assertEqual(v["mode"],"FIXTURE")
        self.assertTrue(all(x["UNKNOWN"]==1 for x in v["fields"].values()))
        for row in v["evaluations"][0]["scores"].values():
            self.assertIsNone(row["probability"]);self.assertIsNone(row["confidence"])
            self.assertGreaterEqual(row["Q"],0);self.assertLessEqual(row["Q"],1)

    def test_T12_imports_assets_and_guard(self):
        for p in (ROOT/"src/conversation_ecology").glob("*.py"):
            for x in ast.walk(ast.parse(p.read_text(encoding="utf8"))):
                if isinstance(x,ast.Import):names=[n.name for n in x.names]
                elif isinstance(x,ast.ImportFrom):names=[x.module or ""]
                else:continue
                self.assertFalse({n.split('.')[0] for n in names}&FORBIDDEN_IMPORTS,p)
        js=(ROOT/"ui/conversation_ecology/app.js").read_text(encoding="utf8")
        for token in ("getUserMedia","https://","http://","innerHTML","eval("):self.assertNotIn(token,js)
        b=Boundary()
        for kind,args in [("socket.connect",(None,("203.0.113.1",443))),("open",("C:/synthetic/.env-probe","r",0)),("import",("torch",)),("subprocess.Popen",("not-executed",))]:
            with self.assertRaises(PermissionError):b.guard(kind,args)
        self.assertEqual(b.denied,dict.fromkeys(b.denied,1))

class HttpBoundary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=make_server(0);cls.worker=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.worker.start()
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.worker.join()
    def call(self,path="/api/state",body=None,headers=None):
        conn=http.client.HTTPConnection("127.0.0.1",self.server.server_port,timeout=3)
        conn.request("GET" if body is None else "POST",path,body=json.dumps(body) if body is not None else None,headers=headers or {})
        r=conn.getresponse();data=r.read();status=r.status;hdr=dict(r.getheaders());conn.close();return status,data,hdr
    def test_http_origin_csp_routes(self):
        status,data,h=self.call("/");self.assertEqual(status,200);self.assertIn(b"C0 / FIXTURE",data)
        self.assertIn("camera=()",h["Permissions-Policy"]);self.assertIn("connect-src 'self'",h["Content-Security-Policy"])
        self.assertEqual(self.call("/.env")[0],404);self.assertEqual(self.call("/../.env")[0],404)
        self.assertEqual(self.call(headers={"Host":"evil.invalid"})[0],403)
        self.assertEqual(self.call("/api/action",{"action":"demo","name":"short"})[0],403)
    def test_http_commit_does_not_fabricate_browser_ack(self):
        _,data,_=self.call();token=json.loads(data)["token"]
        h={"Origin":f"http://127.0.0.1:{self.server.server_port}","X-C0-Token":token}
        status,data,_=self.call("/api/action",{"action":"demo","name":"short"},h)
        state=json.loads(data);self.assertEqual(status,200);self.assertEqual(len(state["commits"]),1);self.assertFalse(state["acks"])
        self.assertEqual(self.call("/api/action",{"action":"work_execute"},h)[0],400)

if __name__=="__main__":unittest.main()
