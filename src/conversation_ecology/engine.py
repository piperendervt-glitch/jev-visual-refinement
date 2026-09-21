"""C0 single-writer controller。live能力、モデル、秘密の探索を持たない。"""
import copy
import random
import threading
from .contracts import (TurnSnapshot, FixtureClock, DEADLINE_MS, EVALUATION_INTERVAL_MS,
                        COLLECTION_MS, BACKCHANNEL_COOLDOWN_MS, THRESHOLD)
from .templates import generate
from .evaluation import validate, audit_value
from .events import replay


class Engine:
    def __init__(self, evaluator, clock=None, session_id="fixture-session", seed=41):
        self.evaluator = evaluator
        self.clock = clock or FixtureClock()
        self.session_id, self.seed = session_id, seed
        self.lock = threading.RLock()
        self.events, self.snapshots, self.candidates, self.evaluations = [], {}, {}, {}
        self.commits, self.deliveries, self.acks, self.threads = {}, set(), {}, {}
        self.slots, self.groups = set(), set()
        self.current = None
        self.turn_serial = self.snapshot_serial = self.context_serial = 0
        self.last_evaluation_ms = self.last_backchannel_ms = float("-inf")
        self.main_pending = False
        self.status = "合成発話を待っています"

    def event(self, kind, payload):
        e = {"cursor": len(self.events)+1, "id": f"{self.session_id}:event-{len(self.events)+1}",
             "kind": kind, "mode": "FIXTURE", "fixture_monotonic_ms": self.clock.now_ms,
             "payload": copy.deepcopy(payload)}
        self.events.append(e)
        return e

    def thread(self, snapshot_id, state):
        self.threads[snapshot_id] = state
        self.event("thread", {"snapshot_id": snapshot_id, "state": state})

    def advance(self, milliseconds):
        with self.lock:
            self.clock.advance(milliseconds)
            self.event("clock_advanced", {"now_ms": self.clock.now_ms})

    def ingest(self, text, *, revision=False, phase="finalized", source="user_fixture", subject="anonymous-fixture"):
        with self.lock:
            if not isinstance(text, str) or not text.strip() or len(text) > 2000: raise ValueError("utterance_size")
            if phase not in {"partial", "finalized"} or source not in {"user_fixture", "external_fixture"}:
                raise ValueError("utterance_contract")
            if len(self.snapshots) >= 128: raise ValueError("fixture_capacity_reset_required")
            if type(revision) is not bool or not isinstance(subject, str) or not subject: raise ValueError("utterance_binding")
            if revision and (self.current is None or self.current.subject_scope != subject): raise ValueError("revision_without_turn")
            old = self.current
            if old:
                self.thread(old.snapshot_id, "SUPERSEDED")
                if revision: self.event("correction", {"old_snapshot_id": old.snapshot_id, "displayed_history_retained": True})
            if not revision: self.turn_serial += 1
            rev = old.utterance_revision+1 if revision else 1
            self.snapshot_serial += 1
            sid = f"{self.session_id}:snapshot-{self.snapshot_serial}"
            self.main_pending = any(w in text for w in ("修正", "調べ", "相談", "でも", "ところで", "作業"))
            work = ("simulated_approval_required",) if any(w in text for w in ("修正", "作業")) else ()
            transcript = self.event("transcript", {"text": text, "revision": rev, "phase": phase, "source": source,
                                                    "subject": subject, "capture_ms": self.clock.now_ms})
            snapshot = TurnSnapshot(self.session_id, subject, f"turn-{self.turn_serial}", rev,
                                    f"cycle-{self.snapshot_serial}", sid, f"context-{self.context_serial}",
                                    self.clock.now_ms, transcript["cursor"], self.clock.now_ms,
                                    self.clock.now_ms+DEADLINE_MS, text, phase, source,
                                    history_refs=tuple(self.commits), work_states=work)
            self.current = snapshot
            self.snapshots[sid] = snapshot
            self.event("snapshot", snapshot.data())
            candidates, calls, counts = generate(snapshot, self.main_pending)
            self.candidates[sid] = candidates
            self.event("generators", {"calls": calls, **counts})
            self.event("candidates", {"snapshot_id": sid, "items": [c.data() for c in candidates]})
            self.thread(sid, "WAITING_EVAL")
            self.status = "候補を生成しました。fixture評価待ち"
            if work:
                self.event("task", {"status": "approval_required", "simulated": True,
                                    "authority_issued": False, "real_work": False})
            return snapshot

    def background_update(self):
        with self.lock:
            self.context_serial += 1
            self.event("background", {"context_id": f"context-{self.context_serial}", "invalidates_turn": False})

    @staticmethod
    def as_of_materials(materials, snapshot):
        return [copy.deepcopy(m) for m in materials if m["capture_ms"] <= snapshot.source_cutoff
                and m["available_cursor"] <= snapshot.available_cursor]

    def evaluate(self, snapshot_id=None, profile="balanced", overrides=None, response=None):
        with self.lock:
            sid = snapshot_id or (self.current.snapshot_id if self.current else None)
            if sid not in self.snapshots: raise ValueError("unknown_snapshot")
            s = self.snapshots[sid]
            if self.clock.now_ms < s.created_ms+COLLECTION_MS: raise ValueError("collection_wait_25ms")
            if self.clock.now_ms-self.last_evaluation_ms < EVALUATION_INTERVAL_MS:
                raise ValueError("evaluation_interval_300ms")
            self.last_evaluation_ms = self.clock.now_ms
            eid = f"{self.session_id}:evaluation-{len(self.evaluations)+1}"
            raw = response
            try:
                if raw is None and self.evaluator is not None:
                    raw = self.evaluator.evaluate(s, self.candidates[sid], profile, overrides)
                status, scores = validate(raw, s, self.candidates[sid])
                reason = status.lower()
            except (ValueError, TypeError, KeyError) as error:
                status, scores, reason = "INVALID", {}, str(error)
            if self.current.snapshot_id != sid: status, scores, reason = "STALE", {}, "superseded_snapshot"
            elif self.clock.now_ms > s.deadline_ms: status, scores, reason = "TIMEOUT", {}, "deadline_750ms"
            record = {"id": eid, "snapshot_id": sid, "status": status, "reason": reason,
                      "scores": scores, "raw": audit_value(raw), "completed_ms": self.clock.now_ms,
                      "available_cursor": len(self.events)+1, "mode": "FIXTURE"}
            self.evaluations[eid] = record
            self.event("evaluation", record)
            if self.threads.get(sid) != "COMMITTED":
                self.thread(sid, "OUTPUT_READY" if status == "VALID" else status)
            return copy.deepcopy(record)

    def decide(self, evaluation_id, *, cursor=None):
        with self.lock:
            if evaluation_id not in self.evaluations: raise ValueError("evaluation_required")
            e = self.evaluations[evaluation_id]
            s = self.snapshots[e["snapshot_id"]]
            if cursor is None: cursor = len(self.events)
            if type(cursor) is not int or not 0 <= cursor <= len(self.events): raise ValueError("invalid_decision_cursor")
            reason, eligible = None, []
            if e["available_cursor"] > cursor: reason = "evaluation_not_available_as_of"
            elif self.current.snapshot_id != s.snapshot_id: reason = "superseded_snapshot"
            elif self.clock.now_ms > s.deadline_ms: reason = "deadline_750ms"
            elif e["status"] != "VALID": reason = e["status"].lower()
            else:
                eligible = [c for c in self.candidates[s.snapshot_id] if c.eligible
                            and e["scores"][c.id]["Q"] >= THRESHOLD
                            and (c.slot != "backchannel" or self.clock.now_ms-self.last_backchannel_ms >= BACKCHANNEL_COOLDOWN_MS)]
                if not eligible: reason = "no_eligible_candidate"
            if reason:
                self.status = "無応答／保留：" + reason
                self.event("decision", {"evaluation_id": evaluation_id, "snapshot_id": s.snapshot_id,
                                       "available_cursor": cursor, "reason": reason, "candidate_id": None})
                self.thread(s.snapshot_id, "HELD" if s == self.current else "SUPERSEDED")
                return None
            highest = max(e["scores"][c.id]["Q"] for c in eligible)
            tied = sorted((c for c in eligible if e["scores"][c.id]["Q"] == highest), key=lambda c: c.id)
            random.Random(self.seed).shuffle(tied)
            candidate = tied[0]
            self.event("decision", {"evaluation_id": evaluation_id, "snapshot_id": s.snapshot_id,
                                   "available_cursor": cursor, "reason": "highest_valid_Q", "Q": highest,
                                   "candidate_id": candidate.id, "seed": self.seed})
            return self.commit(candidate.id, evaluation_id)

    def commit(self, candidate_id, evaluation_id):
        with self.lock:
            e = self.evaluations.get(evaluation_id)
            if not e or e["status"] != "VALID": raise ValueError("valid_evaluation_required")
            s = self.snapshots[e["snapshot_id"]]
            if self.current != s or self.clock.now_ms > s.deadline_ms: raise ValueError("stale_commit")
            c = next((c for c in self.candidates[s.snapshot_id] if c.id == candidate_id), None)
            if not c or not c.eligible or e["scores"][c.id]["Q"] < THRESHOLD: raise ValueError("ineligible_commit")
            # No caller-supplied generation. The controller owns it; cycle/revision
            # changes cannot bypass an already-used slot or final response group.
            slot_key = (s.session_id, s.turn_id, c.slot)
            group = (s.session_id, s.turn_id, "main")
            if slot_key in self.slots or (c.slot in {"final_micro", "answer"} and group in self.groups): return None
            # One selected response per decision cycle even when slots differ.
            if any(x["snapshot_id"] == s.snapshot_id for x in self.commits.values()): return None
            if c.slot == "backchannel" and self.clock.now_ms-self.last_backchannel_ms < BACKCHANNEL_COOLDOWN_MS: return None
            cid = f"{self.session_id}:commit-{len(self.commits)+1}"
            record = {"id": cid, "key": [s.session_id, s.turn_id, c.slot, s.utterance_revision],
                      "snapshot_id": s.snapshot_id, "candidate_id": c.id, "evaluation_id": evaluation_id,
                      "text": c.text, "act": c.act, "slot": c.slot, "Q": e["scores"][c.id]["Q"],
                      "mode": "FIXTURE", "main_pending": self.main_pending}
            self.slots.add(slot_key)
            if c.slot in {"final_micro", "answer"}: self.groups.add(group)
            if c.slot == "backchannel": self.last_backchannel_ms = self.clock.now_ms
            self.commits[cid] = record  # commit and outbox share this transaction
            self.event("commit", record)
            self.thread(s.snapshot_id, "COMMITTED")
            self.status = "無応答を選択しました" if not c.text else "一つの反応を採用しました"
            return copy.deepcopy(record)

    def deliver(self):
        with self.lock:
            for cid in self.commits:
                if cid not in self.deliveries:
                    self.deliveries.add(cid)
                    self.event("delivery", {"commit_id": cid})
            return copy.deepcopy(list(self.commits.values()))

    def resend(self):
        """Prepare the same history, including acknowledged commits; never recommit."""
        with self.lock:
            records = self.deliver()
            payload = {
                "session_id": self.session_id,
                "result": "resent" if records else "no_commits",
                "commit_ids": [c["id"] for c in records],
                "browser_acked_commit_ids": [c["id"] for c in records if (c["id"], "browser_dom") in self.acks],
                "semantics": "response_prepared_not_browser_receipt",
            }
            event = self.event("resend", payload)
            return {"event_id": event["id"], **copy.deepcopy(payload)}

    def acknowledge(self, cid, evidence, *, kind="synthetic_test"):
        with self.lock:
            if cid not in self.deliveries: raise ValueError("unknown_or_unsent_commit")
            if kind not in {"browser_dom", "synthetic_test"}: raise ValueError("ack_kind")
            if evidence != "connected_dom_after_two_animation_frames" and kind == "browser_dom": raise ValueError("ack_evidence")
            key = (cid, kind)
            if key in self.acks: return False
            value = {"commit_id": cid, "kind": kind, "evidence": evidence, "human_read_proof": False}
            self.acks[key] = value
            self.event("ack", value)
            return True

    def projection(self):
        with self.lock: return replay(self.events)

    def view(self):
        with self.lock:
            current = self.current
            return {"mode": "FIXTURE", "stage": "C0", "session_id": self.session_id, "clock_ms": self.clock.now_ms,
                    "status": self.status, "snapshot": current.data() if current else None,
                    "candidates": [c.data() for c in self.candidates.get(current.snapshot_id, [])] if current else [],
                    "evaluations": copy.deepcopy(list(self.evaluations.values())),
                    "commits": copy.deepcopy(list(self.commits.values())), "acks": copy.deepcopy(list(self.acks.values())),
                    "threads": dict(self.threads), "events": copy.deepcopy(self.events), "main_pending": self.main_pending,
                    "fields": {space: {"UNKNOWN": 1.0, "kind": "synthetic_unobserved_concentration", "hypotheses": []}
                               for space in ("person", "place", "conversation")},
                    "capabilities": {"camera": "未接続", "microphone": "未接続", "Jev": "未接続",
                                     "local_models": "未接続", "work_adapter": "未接続",
                                     "C2_scheduler": "未実装", "MessageGate": "未実装"}}
