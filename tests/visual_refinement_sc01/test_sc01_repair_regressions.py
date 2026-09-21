from __future__ import annotations

from decimal import Decimal
from hashlib import sha256
from pathlib import Path
import tempfile
import threading
import unittest

from visual_refinement_sc01.repair import ArtifactRegistry, FixtureKernel, FixtureProfile, normalize_decimal


FULL={"Q":"3.2","A":"1","R":"2","I":"3","C":"4"}


class RepairRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); root=Path(self.temp.name)
        self.kernel=FixtureKernel(root/"state.sqlite3",root/"artifacts")
        self.kernel.publish_frame()
        for lane in "SABC": self.kernel.publish_candidate("frame_k0",lane,empty=lane=="C")

    def tearDown(self):
        self.kernel.close(); self.temp.cleanup()

    def task(self,lane="A",version=0): return self.kernel.ensure_evaluation_task("frame_k0",lane,version)

    def attempt(self,lane,values,suffix,version=0,**kwargs):
        return self.kernel.submit_attempt(self.task(lane,version),values,attempt_id=f"attempt_{suffix}",event_id=f"event_{suffix}",raw=f"raw-{suffix}".encode(),**kwargs)

    def test_fx02_q_first_selects_and_late_diagnostics_do_not_revise(self):
        first=self.attempt("A",{"Q":"3.2"},"q")
        self.assertEqual(first["decision"]["reason_code"],"FIRST_ELIGIBLE")
        revisions=len(self.kernel.view("frame_k0")["timeline_page"]["revisions"])
        late=self.attempt("A",{"A":"2","R":"bad","I":"3","C":"1"},"diag")
        self.assertEqual(late["accepted_axes"],["A","I","C"]); self.assertIn("R",late["axis_errors"])
        self.assertEqual(len(self.kernel.view("frame_k0")["timeline_page"]["revisions"]),revisions)

    def test_fx02_first_valid_axis_is_immutable_and_invalid_raw_is_saved(self):
        self.attempt("A",{"Q":None,"A":"1"},"missing")
        valid=self.attempt("A",{"Q":"3.2","A":"4"},"valid")
        self.assertEqual(valid["accepted_axes"],["Q"])
        isolated=self.attempt("B",FULL,"bad_env",returned_binding="wrong")
        self.assertEqual(isolated["envelope_status"],"INVALID")
        row=self.kernel.db.execute("SELECT raw,raw_digest FROM eval_attempts WHERE attempt_id='attempt_bad_env'").fetchone()
        self.assertEqual(row[0],b"raw-bad_env"); self.assertEqual(row[1],sha256(row[0]).hexdigest())

    def test_fx03_high_precision_is_not_rounded(self):
        low="3.60000000000000000000000000001"; high="3.60000000000000000000000000002"
        self.assertEqual(normalize_decimal(low),low); self.assertGreater(Decimal(high),Decimal(low))
        self.attempt("A",dict(FULL,Q=low),"prec_low"); result=self.attempt("S",dict(FULL,Q=high),"prec_high")
        self.assertEqual(result["decision"]["reason_code"],"HIGHER_Q")
        self.assertEqual(result["decision"]["delta_to_previous"],"0.00000000000000000000000000001")

    def test_fx04_e2_preserves_fallback_and_terminal_clear(self):
        self.attempt("S",dict(FULL,Q="3.6"),"s0")
        self.kernel.publish_evidence("frame_k0",1,reevaluate_candidates=["cand_frame_k0_s"])
        self.kernel.publish_evidence("frame_k0",2,reevaluate_candidates=["cand_frame_k0_s"])
        view=self.kernel.view("frame_k0"); self.assertIsNone(view["selection"]["winner_id"]); self.assertEqual(view["selection"]["stale_fallback_id"],"cand_frame_k0_s")
        self.kernel.finalize("frame_k0"); view=self.kernel.view("frame_k0")
        self.assertIsNone(view["selection"]["stale_fallback_id"]); self.assertEqual(view["coverage_state"],"TERMINAL_PARTIAL")

    def test_fx05_cancel_and_close_block_late_winner(self):
        eid=self.task("A"); self.kernel.cancel_generation("frame_k0")
        with self.assertRaisesRegex(ValueError,"closed"):
            self.kernel.submit_attempt(eid,FULL,attempt_id="attempt_late",event_id="event_late")
        self.assertIsNone(self.kernel.view("frame_k0")["selection"]["winner_id"])

    def test_fx05_unplanned_c_keeps_coverage_partial(self):
        for lane in "SAB": self.attempt(lane,FULL,f"complete_{lane}")
        self.kernel.finalize("frame_k0")
        self.assertEqual(self.kernel.view("frame_k0")["coverage_state"],"TERMINAL_PARTIAL")

    def test_fx05_job_commit_advances_public_snapshot_seq(self):
        before=self.kernel.view("frame_k0")["snapshot_seq"]
        self.kernel.create_job("job_seq","frame_k0","A","EVALUATION","EVALUATION_SUITE",status="QUEUED")
        self.assertGreater(self.kernel.view("frame_k0")["snapshot_seq"],before)

    def test_fx06_rollback_is_not_observable(self):
        eid=self.task("A"); before=self.kernel.view("frame_k0")["snapshot_seq"]; self.kernel.inject_fault_once()
        with self.assertRaises(RuntimeError): self.kernel.submit_attempt(eid,FULL,attempt_id="attempt_rollback",event_id="event_rollback")
        after=self.kernel.view("frame_k0"); self.assertEqual(after["snapshot_seq"],before); self.assertIsNone(after["selection"]["winner_id"])

    def test_fx06_reads_wait_for_commit_boundary(self):
        eid=self.task("A"); entered=threading.Event(); release=threading.Event(); original=self.kernel._snapshot
        def paused(frame,seq): entered.set(); release.wait(1); original(frame,seq)
        self.kernel._snapshot=paused
        writer=threading.Thread(target=lambda:self.kernel.submit_attempt(eid,FULL,attempt_id="attempt_commit",event_id="event_commit")); writer.start(); self.assertTrue(entered.wait(1))
        observed=[]; reader=threading.Thread(target=lambda:observed.append(self.kernel.view("frame_k0"))); reader.start(); self.assertTrue(reader.is_alive()); release.set(); writer.join(2); reader.join(2)
        self.assertEqual(observed[0]["selection"]["winner_id"],"cand_frame_k0_a")

    def test_fx07_artifact_collision_does_not_overwrite(self):
        root=Path(self.temp.name)/"immutable"; registry=ArtifactRegistry(root,"safe_run")
        registry.register("artifact_one","same.bin",b"one","application/octet-stream")
        with self.assertRaises(ValueError): registry.register("artifact_two","same.bin",b"two","application/octet-stream")
        self.assertEqual((root/"same.bin").read_bytes(),b"one")

    def test_fx07_empty_and_multiple_masks_match_collection(self):
        empty=next(x for x in self.kernel._records("candidate") if x["lane_id"]=="C")
        collection=next(x for x in self.kernel._records("mask_collection") if x["mask_collection_id"]==empty["mask_collection_ref"])
        self.assertEqual(collection["masks"],[]); self.assertEqual(empty["mask_count"],0)
        with self.assertRaises(ValueError): self.kernel.publish_candidate("frame_k0","S",mask_count=9)

    def test_fx07_session_run_and_byte_caps_are_enforced(self):
        session=Path(self.temp.name)/"session"; prior=session/"prior"; prior.mkdir(parents=True); (prior/"state.sqlite3").write_bytes(b"xx")
        with self.assertRaisesRegex(ValueError,"saved_run_capacity"):
            FixtureKernel(session/"new"/"state.sqlite3",session/"new"/"artifacts",profile=FixtureProfile(max_saved_runs=1),session_root=session)
        with self.assertRaisesRegex(ValueError,"session_byte_capacity"):
            FixtureKernel(session/"bytes"/"state.sqlite3",session/"bytes"/"artifacts",profile=FixtureProfile(max_bytes=1),session_root=session)

    def test_fx08_event_pages_and_historical_cursor_are_complete(self):
        first=self.attempt("A",FULL,"cursor_a")["commit_seq"]
        self.attempt("S",dict(FULL,Q="3.6"),"cursor_s")
        for i in range(205):
            with self.kernel.transaction(): self.kernel._event("Probe",{"i":i},"frame_k0")
        replay=self.kernel.replay("frame_k0"); self.assertGreater(len(replay["events"]),200)
        historical=self.kernel.replay("frame_k0",first)["view"]; self.assertEqual(historical["selection"]["winner_id"],"cand_frame_k0_a")

    def test_fx10_receipt_strict_types_revision_seq_and_idempotence(self):
        self.attempt("A",FULL,"receipt"); view=self.kernel.view("frame_k0")
        value={"receipt_id":"receipt_valid","view_session_id":"view_valid","source_revision_id":view["selection"]["display_revision_id"],"source_commit_seq":view["selection"]["display_revision_seq"],"run_id":view["run_id"],"frame_id":"frame_k0","generation":0,"display_mode":"FOLLOW_SELECTION","rendered_candidate_id":"cand_frame_k0_a","visible":True,"skipped_revision_ids":[]}
        self.assertTrue(self.kernel.receipt(value)); self.assertFalse(self.kernel.receipt(value))
        bad=dict(value,receipt_id="receipt_bad",visible="false")
        with self.assertRaises(ValueError): self.kernel.receipt(bad)
        wrong=dict(value,receipt_id="receipt_wrong",source_commit_seq=view["snapshot_seq"]+1)
        with self.assertRaises(ValueError): self.kernel.receipt(wrong)

    def test_fx11_preview_is_frame_scoped(self):
        with self.assertRaisesRegex(ValueError,"scope"): self.kernel.view("frame_k0",preview_candidate="cand_other_a")


if __name__=="__main__": unittest.main()
