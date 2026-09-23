"""Transactional acceptance of Jev attempts and Q-only selection."""
from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
import json

from .jev_wire import AXES, validate_response
from .selection import SelectionState, decide
from .store import LiveStore, canonical


class SelectionEngine:
    def __init__(self, store: LiveStore):
        self.store = store

    def ensure_task(self, frame_id: str, candidate_id: str, lane_id: str,
                    evidence_version: int, input_digest: str,
                    *, origin: str = "REAL_JEV") -> str:
        if origin not in {"REAL_JEV", "FIXTURE"}:
            raise ValueError("evaluation_origin_invalid")
        task_id = f"eval_{candidate_id}_e{evidence_version}"
        with self.store.lock:
            if self.store.read_only:
                raise ValueError("saved_run_read_only")
            row = self.store.db.execute("SELECT input_digest FROM eval_tasks WHERE id=?",
                                        (task_id,)).fetchone()
            if row:
                if row[0] != input_digest:
                    raise ValueError("evaluation_input_changed")
                return task_id
            candidate = self.store.db.execute("SELECT frame_id,lane_id FROM candidates WHERE id=?",
                                               (candidate_id,)).fetchone()
            evidence = self.store.db.execute("SELECT 1 FROM evidence WHERE frame_id=? AND version=?",
                                              (frame_id, evidence_version)).fetchone()
            if candidate != (frame_id, lane_id) or not evidence:
                raise ValueError("evaluation_dependencies_missing")
            with self.store.db:
                seq = self.store._event_uncommitted(
                    "EvaluationQueued", frame_id, lane_id,
                    {"task_id": task_id, "candidate_id": candidate_id,
                     "evidence_version": evidence_version, "origin": origin})
                self.store.db.execute("INSERT INTO eval_tasks VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (task_id, candidate_id, frame_id, lane_id, evidence_version,
                     f"ctx_{frame_id}_e{evidence_version}", input_digest, "QUEUED", seq, origin))
            return task_id

    def missing_axes(self, task_id: str) -> tuple[str, ...]:
        with self.store.lock:
            existing = {row[0] for row in self.store.db.execute(
                "SELECT axis_id FROM axis_results WHERE task_id=?", (task_id,))}
            return tuple(axis for axis in AXES if axis not in existing)

    def _candidate_available(self, candidate_id: str, frame_id: str) -> bool:
        row = self.store.db.execute("SELECT data FROM candidates WHERE id=? AND frame_id=?",
                                    (candidate_id, frame_id)).fetchone()
        frame = self.store.db.execute("SELECT data FROM frames WHERE id=?", (frame_id,)).fetchone()
        if row is None or frame is None:
            return False
        candidate = json.loads(row[0])
        source = json.loads(frame[0])
        if candidate.get("segmentation_status") not in {"SUCCEEDED_NONEMPTY", "SUCCEEDED_EMPTY"}:
            return False
        if candidate.get("source_pixel_sha256") != source.get("pixel_sha256"):
            return False
        if candidate.get("mask_count") != len(candidate.get("masks", [])):
            return False
        try:
            self.store.read_artifact(candidate["preview_artifact_id"])
            for mask in candidate["masks"]:
                self.store.read_artifact(mask["artifact_id"])
        except (KeyError, FileNotFoundError, ValueError):
            return False
        return True

    def accept_attempt(self, task_id: str, attempt_id: str, raw: bytes,
                       *, origin: str, apply_selection: bool = True) -> dict:
        if origin not in {"REAL_JEV", "FIXTURE"}:
            raise ValueError("attempt_origin_invalid")
        with self.store.lock:
            task = self.store.db.execute("SELECT * FROM eval_tasks WHERE id=?", (task_id,)).fetchone()
            if task is None or task[9] != origin:
                raise ValueError("task_origin_mismatch")
            if self.store.db.execute("SELECT 1 FROM eval_attempts WHERE id=?", (attempt_id,)).fetchone():
                return {"duplicate": True, "task_id": task_id}
            attempt_index = self.store.db.execute(
                "SELECT COUNT(*) FROM eval_attempts WHERE task_id=?", (task_id,)).fetchone()[0]
            if attempt_index >= 2:
                raise ValueError("attempt_limit")
        artifact = self.store.put_artifact(f"raw_{attempt_id}", ".json", raw, "application/json")
        try:
            checked = validate_response(raw)
            envelope_status = "VALID"
            error = None
        except ValueError as exc:
            checked = None
            envelope_status = "INVALID"
            error = str(exc)
        candidate_id, frame_id, lane_id, version = task[1], task[2], task[3], task[4]
        with self.store.lock, self.store.db:
            if self.store.read_only or self.store.get_meta("lifecycle") != "RUNNING":
                raise ValueError("run_closed")
            seq = self.store._event_uncommitted("EvaluationAttemptFinished", frame_id, lane_id,
                {"task_id": task_id, "attempt_id": attempt_id,
                 "origin": origin, "envelope_status": envelope_status,
                 "error_code": error})
            usage = checked["usage"]["input_tokens"] if checked else None
            self.store.db.execute("INSERT INTO eval_attempts VALUES(?,?,?,?,?,?,?,?)",
                (attempt_id, task_id, attempt_index, seq, artifact["artifact_id"],
                 envelope_status, error, usage))
            accepted = []
            decision_data = None
            if checked:
                for axis in AXES:
                    result = checked["axes"][axis]
                    if result["status"] != "VALID":
                        continue
                    already = self.store.db.execute(
                        "SELECT 1 FROM axis_results WHERE task_id=? AND axis_id=?",
                        (task_id, axis)).fetchone()
                    if already:
                        continue
                    self.store.db.execute("INSERT INTO axis_results VALUES(?,?,?,?,?)",
                        (task_id, axis, attempt_id, seq, canonical(result)))
                    accepted.append(axis)
                if "Q" in accepted and apply_selection:
                    row = self.store.db.execute(
                        "SELECT evidence_version,winner_id,winner_q,stale_fallback_id FROM selection_state WHERE frame_id=?",
                        (frame_id,)).fetchone()
                    state = SelectionState(frame_id, row[0], row[1], row[2], row[3])
                    next_state, outcome = decide(
                        state, candidate_id=candidate_id, evidence_version=version,
                        q_status="VALID", q_decimal=checked["axes"]["Q"]["score_decimal"],
                        available=self._candidate_available(candidate_id, frame_id))
                    decision_data = asdict(outcome)
                    decision_data.update({"frame_id": frame_id, "lane_id": lane_id,
                                          "task_id": task_id, "context_id": task[5],
                                          "origin": origin, "received_attempt_id": attempt_id})
                    decision_seq = self.store._event_uncommitted(
                        "DecisionCommitted", frame_id, lane_id, decision_data)
                    decision_id = f"dec_{decision_seq}"
                    decision_data["decision_id"] = decision_id
                    self.store.db.execute("INSERT INTO decisions VALUES(?,?,?,?)",
                        (decision_id, frame_id, decision_seq, canonical(decision_data)))
                    if outcome.revision_kind:
                        self.store.db.execute("INSERT INTO revisions VALUES(?,?,?,?,?,?,?)",
                            (f"rev_{decision_seq}", frame_id, decision_seq,
                             outcome.previous_winner_id, outcome.winner_after_id,
                             outcome.revision_kind, outcome.reason_code))
                    self.store.db.execute(
                        "UPDATE selection_state SET winner_id=?,winner_q=?,selected_task_id=CASE WHEN ? THEN ? ELSE selected_task_id END,stale_fallback_id=?,latest_seq=? WHERE frame_id=?",
                        (next_state.winner_id, next_state.winner_q,
                         bool(outcome.revision_kind), task_id, next_state.stale_fallback_id,
                         decision_seq, frame_id))
            count = self.store.db.execute(
                "SELECT COUNT(*) FROM axis_results WHERE task_id=?", (task_id,)).fetchone()[0]
            status = "COMPLETE" if count == 5 else "PARTIAL_DIAGNOSTICS" if count else (
                "INVALID" if checked is None else "MISSING")
            self.store.db.execute("UPDATE eval_tasks SET status=? WHERE id=?", (status, task_id))
            return {"task_id": task_id, "accepted_axes": accepted,
                    "envelope_status": envelope_status, "error_code": error,
                    "decision": decision_data, "attempt_seq": seq, "status": status}
