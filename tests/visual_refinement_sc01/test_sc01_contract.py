from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from visual_refinement_sc01.core import (
    ArtifactRegistry, FixtureKernel, SCHEMA_VERSION, canonical_json,
    content_digest, normalize_decimal,
)


SCORES = {"Q": "3.2", "A": "1.2", "R": "1.8", "I": "3.5", "C": "3.5"}


class KernelCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.db = root / "state" / "fixture.sqlite3"
        self.artifacts = root / "runs" / "run_sc01" / "artifacts"
        self.kernel = FixtureKernel(self.db, self.artifacts)

    def tearDown(self):
        try:
            self.kernel.close()
        except (sqlite3.ProgrammingError, AttributeError):
            pass
        self.tmp.cleanup()

    def frame(self):
        self.kernel.publish_frame()
        for lane in "SABC":
            self.kernel.publish_candidate("frame_k0", lane)

    def evaluate(self, lane, q, version=0, **axes):
        values = dict(SCORES, Q=q, **axes)
        return self.kernel.accept_evaluation("frame_k0", lane, version, values,
            event_id=f"event_{lane.lower()}_e{version}_{q.replace('.', '_')}")


class SelectionContractTests(KernelCase):
    def test_cf01_cf02_fixed_rows_and_completion_order(self):
        self.frame()
        first = self.evaluate("A", "3.2")
        view = self.kernel.view("frame_k0")
        self.assertEqual([r["lane_id"] for r in view["rows"]], list("SABC"))
        self.assertEqual(first["reason_code"], "FIRST_ELIGIBLE")
        self.assertEqual(view["selection"]["winner_id"], "cand_frame_k0_a")

    def test_cf03_late_higher_revises_lower_is_decision_only(self):
        self.frame()
        self.evaluate("A", "3.2")
        higher = self.evaluate("S", "3.6")
        lower = self.evaluate("B", "3.4")
        self.assertEqual(higher["reason_code"], "HIGHER_Q")
        self.assertEqual(higher["delta_to_previous"], "0.4")
        self.assertEqual(lower["reason_code"], "LOWER_Q")
        self.assertIsNone(lower["revision_id"])
        self.assertEqual(self.kernel.view("frame_k0")["selection"]["winner_id"], "cand_frame_k0_s")

    def test_cf04_tie_keeps_current_and_rebuild_is_content_order(self):
        self.frame()
        self.evaluate("A", "3.2")
        tied = self.evaluate("S", "3.2")
        self.assertEqual(tied["reason_code"], "TIE_KEEP_CURRENT")
        expected = min(self.kernel._records("candidate"), key=lambda x: (x["content_digest"], x["ordinal"]))["candidate_id"]
        self.assertEqual(self.kernel.rebuild_tie("frame_k0"), expected)

    def test_cf05_cf06_only_q_controls_selection(self):
        self.frame()
        self.evaluate("A", "3.1", A="0", R="0", I="0", C="0")
        result = self.evaluate("S", "3.1", A="4", R="4", I="4", C="4")
        self.assertEqual(result["reason_code"], "TIE_KEEP_CURRENT")
        self.assertEqual(self.kernel.view("frame_k0")["selection"]["winner_id"], "cand_frame_k0_a")

    def test_cf07_cf08_zero_missing_and_partial_diagnostics(self):
        self.frame()
        zero = self.evaluate("A", "0")
        self.assertEqual(zero["reason_code"], "BELOW_Q_THRESHOLD")
        missing = self.kernel.accept_evaluation("frame_k0", "S", 0, {"Q": None, "A": "2"}, event_id="missing_q")
        self.assertEqual(missing["reason_code"], "EVALUATION_FAILED")
        partial = self.kernel.accept_evaluation("frame_k0", "B", 0, {"Q": "3.4", "A": None}, event_id="partial_q")
        self.assertEqual(partial["reason_code"], "FIRST_ELIGIBLE")
        before = len(self.kernel.view("frame_k0")["timeline_page"]["revisions"])
        self.assertEqual(before, 1)

    def test_cf09_to_cf13_evidence_revision_stale_and_refresh(self):
        self.frame()
        self.evaluate("S", "3.6")
        self.kernel.publish_evidence("frame_k0", 1)
        stale = self.evaluate("A", "3.9", version=0)
        self.assertEqual(stale["reason_code"], "OLD_EVIDENCE")
        first = self.evaluate("S", "3.3", version=1)
        self.assertEqual(first["reason_code"], "FIRST_ELIGIBLE_IN_NEW_EVIDENCE")
        view = self.kernel.view("frame_k0")
        self.assertIsNone(next(r for r in view["rows"] if r["lane_id"] == "A")["current_q_delta"])
        self.kernel.publish_evidence("frame_k0", 2)
        refreshed = self.evaluate("S", "3.8", version=2)
        self.assertEqual(refreshed["reason_code"], "FIRST_ELIGIBLE_IN_NEW_EVIDENCE")

    def test_cf14_duplicates_are_idempotent(self):
        self.frame()
        one = self.evaluate("A", "3.2")
        again = self.kernel.accept_evaluation("frame_k0", "A", 0, dict(SCORES, Q="4"), event_id="different_event")
        self.assertEqual(one["decision_id"], again["decision_id"])
        self.assertEqual(len(self.kernel.view("frame_k0")["timeline_page"]["decisions"]), 1)

    def test_cf15_invalid_envelope_and_decimal_are_rejected(self):
        self.frame()
        with self.assertRaisesRegex(ValueError, "envelope"):
            self.kernel.accept_evaluation("frame_k0", "A", 0, SCORES, event_id="bad_binding", returned_binding="live_unknown")
        for bad in ("NaN", "Infinity", "3e0", "+3", "04"):
            with self.assertRaises(ValueError):
                normalize_decimal(bad)

    def test_cf16_empty_candidate_is_not_failure(self):
        self.kernel.publish_frame()
        empty = self.kernel.publish_candidate("frame_k0", "C", empty=True)
        self.assertEqual(empty["output_status"], "SUCCEEDED_EMPTY")
        self.assertEqual(empty["mask_count"], 0)
        result = self.evaluate("C", "3.1")
        self.assertEqual(result["reason_code"], "FIRST_ELIGIBLE")


class QueueProjectionTests(KernelCase):
    def test_cf17_cf18_queue_units_counts_and_freshness(self):
        q = self.kernel.queue_snapshot(queued=0, active=1, succeeded=2, longest_active_ms=9000, health="STALE_TELEMETRY")
        self.assertIsNone(q["oldest_queued_ms"])
        self.assertEqual(q["unit"], "EVALUATION_SUITE")
        self.assertEqual(q["accepted_total"], 3)
        self.assertEqual(q["health"], "STALE_TELEMETRY")
        with self.assertRaises(ValueError):
            self.kernel.queue_snapshot(queued=0, active=0, oldest_ms=1)

    def test_cf19_cf20_capacity_status_and_distinct_projection_fields(self):
        q = self.kernel.queue_snapshot(queued=4, active=2, capacity=4, oldest_ms=5000)
        self.assertEqual(q["congestion"], "SATURATED")
        self.frame(); self.evaluate("A", "3.2")
        row = self.kernel.view("frame_k0")["rows"][1]
        self.assertEqual(row["source_origin"], "FIXTURE")
        self.assertEqual(row["selection_status"], "CURRENT_PROVISIONAL")

    def test_cf21_cf22_historical_and_current_delta_manual_preview(self):
        self.frame(); first = self.evaluate("A", "3.2"); self.evaluate("S", "3.6")
        view = self.kernel.view("frame_k0", preview_candidate="cand_frame_k0_b")
        self.assertEqual(first["delta_to_previous"], None)
        self.assertEqual(next(r for r in view["rows"] if r["lane_id"] == "A")["current_q_delta"], "-0.4")
        self.assertEqual(view["preview"]["rendered_candidate_id"], "cand_frame_k0_b")
        self.assertEqual(view["selection"]["winner_id"], "cand_frame_k0_s")

    def test_cf23_cf24_cf25_receipt_is_separate_and_no_pulse_loop(self):
        self.frame(); self.evaluate("A", "3.2")
        before = len(self.kernel.event_page())
        view = self.kernel.view("frame_k0")
        receipt = {"receipt_id": "receipt_one", "view_session_id": "view_one",
            "source_revision_id": view["selection"]["display_revision_id"], "source_commit_seq": view["snapshot_seq"],
            "frame_id": "frame_k0", "display_mode": "FOLLOW_SELECTION",
            "rendered_candidate_id": "cand_frame_k0_a", "visible": False, "skipped_revision_ids": []}
        self.kernel.receipt(receipt); self.kernel.receipt(receipt)
        self.assertEqual(len(self.kernel.event_page()), before)
        self.assertEqual(self.kernel.db.execute("SELECT COUNT(*) FROM receipts").fetchone()[0], 1)
        self.assertEqual(view["flow_pulses"], [])


class PersistenceBoundaryTests(KernelCase):
    def test_cf26_replay_is_saved_order_without_network(self):
        self.frame(); self.evaluate("A", "3.2"); self.evaluate("S", "3.6")
        replay = self.kernel.replay("frame_k0")
        seqs = [e["commit_seq"] for e in replay["events"]]
        self.assertEqual(seqs, sorted(seqs))
        self.assertEqual(replay["network_calls"], 0)
        self.assertEqual(replay["clock"], "fixture_cursor_frozen")

    def test_cf27_restart_marks_unfinished_interrupted_without_retry(self):
        self.frame(); self.kernel.close()
        self.kernel = FixtureKernel(self.db, self.artifacts, create=False)
        self.assertEqual(self.kernel._meta("run_status"), "INTERRUPTED")
        self.assertEqual(self.kernel._meta("automatic_retries"), "0")
        self.assertEqual(self.kernel._meta("network_calls"), "0")

    def test_cf28_artifact_boundary_expiry_and_traversal(self):
        reg = ArtifactRegistry(Path(self.tmp.name) / "safe", "safe_run", now=10)
        with self.assertRaises(ValueError):
            reg.register("art_bad", "../secret", b"x", "text/plain")
        reg.register("art_ok", "one.txt", b"ok", "text/plain", expires_at=11)
        with self.assertRaises(FileNotFoundError):
            reg.resolve("art_ok", now=11)
        with self.assertRaises(FileNotFoundError):
            reg.resolve("env")

    def test_cf29_atomic_rollback_and_outbox_redelivery(self):
        self.frame(); self.kernel.inject_fault_once()
        with self.assertRaises(RuntimeError):
            self.evaluate("A", "3.2")
        self.assertIsNone(self.kernel.view("frame_k0")["selection"]["winner_id"])
        self.evaluate("A", "3.2")
        sent = self.kernel.deliver_outbox()
        self.assertGreater(len(sent), 0)
        self.assertEqual(self.kernel.deliver_outbox(), [])

    def test_cf30_cf31_reason_is_q_only_and_terminal_partial(self):
        self.frame(); low = self.evaluate("A", "2.9", C="4")
        self.assertEqual(low["reason_code"], "BELOW_Q_THRESHOLD")
        self.assertNotIn("C", low["reason_code"])
        self.kernel.finalize("frame_k0", partial=True)
        view = self.kernel.view("frame_k0")
        self.assertIsNone(view["selection"]["winner_id"])
        self.assertEqual(view["coverage_state"], "TERMINAL_PARTIAL")
        self.assertTrue(view["fixture"])

    def test_cf32_cf33_commit_order_and_scope_are_explicit(self):
        self.frame(); self.evaluate("S", "3.6"); self.kernel.publish_evidence("frame_k0", 1)
        self.evaluate("A", "3.9", version=0); self.evaluate("C", "3.3", version=1)
        events = self.kernel.event_page()
        self.assertEqual([e["commit_seq"] for e in events], list(range(1, len(events) + 1)))
        self.assertTrue(all(e["frame_id"] in {None, "frame_k0"} for e in events))

    def test_cf34_cf35_retention_schema_digest_and_raw(self):
        self.assertEqual(normalize_decimal("3.600"), "3.6")
        self.assertEqual(canonical_json({"b": 1, "a": 2}), '{"a":2,"b":1}')
        self.assertEqual(len(content_digest({"a": "3.6"})), 64)
        self.frame(); raw = b"3.600\x00raw"; self.kernel.accept_evaluation("frame_k0", "A", 0, SCORES, event_id="raw_one", raw=raw)
        digest = self.kernel.db.execute("SELECT raw_digest FROM evaluations").fetchone()[0]
        from hashlib import sha256
        self.assertEqual(digest, sha256(raw).hexdigest())
        self.kernel.close(); self.kernel = FixtureKernel(self.db, self.artifacts, create=False, now=1)
        self.kernel.close()
        conn = sqlite3.connect(self.db); conn.execute("UPDATE meta SET value='vr_sc02_v1' WHERE key='schema_version'"); conn.commit(); conn.close()
        with self.assertRaises(ValueError):
            FixtureKernel(self.db, self.artifacts, create=False, now=1)
        self.kernel = object()  # tearDown guard

    def test_cf36_fixture_kernel_has_no_vendor_or_dotenv_dependency(self):
        import visual_refinement_sc01.core as core
        source = Path(core.__file__).read_text(encoding="utf-8")
        self.assertNotIn("dotenv", source)
        self.assertNotIn("requests", source)
        self.assertEqual(SCHEMA_VERSION, "vr_sc01_v1")


if __name__ == "__main__":
    unittest.main()
