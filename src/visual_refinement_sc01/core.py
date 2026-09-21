"""SC01 fixture-only records, selection state, persistence, and projection.

This module intentionally imports no model, media, environment-file loader, or vendor SDK code.
All ordering decisions are made from the SQLite writer's commit sequence.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sqlite3
import threading
from typing import Any, Iterable


SCHEMA_VERSION = "vr_sc01_v1"
CONTRACT_VERSION = "0.5"
LANES = ("S", "A", "B", "C")
AXES = ("Q", "A", "R", "I", "C")
THRESHOLD = Decimal("3")
ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,95}$")
DECIMAL_RE = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")


def require_id(value: object, name: str = "id") -> str:
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise ValueError(f"invalid_{name}")
    return value


def normalize_decimal(value: object) -> str:
    if not isinstance(value, str) or not DECIMAL_RE.fullmatch(value):
        raise ValueError("invalid_decimal")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("invalid_decimal") from exc
    if not number.is_finite():
        raise ValueError("invalid_decimal")
    if number == 0:
        return "0"
    result = format(number.normalize(), "f")
    return result.rstrip("0").rstrip(".") if "." in result else result


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_digest(value: object) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _axis(value: object, axis_id: str) -> dict[str, Any]:
    if value is None:
        return {"axis_id": axis_id, "status": "MISSING", "score_decimal": None,
                "missing_reason": "FIXTURE_NOT_RETURNED"}
    if isinstance(value, dict):
        status = value.get("status")
        if status not in {"VALID", "MISSING", "INVALID", "NOT_APPLICABLE", "NOT_REQUESTED", "PENDING"}:
            raise ValueError("unknown_value_status")
        raw = value.get("score_decimal")
        reason = value.get("missing_reason")
        if status != "VALID":
            if raw is not None:
                raise ValueError("non_valid_axis_has_score")
            return {"axis_id": axis_id, "status": status, "score_decimal": None,
                    "missing_reason": reason or status}
        value = raw
    score = normalize_decimal(value)
    if not Decimal("0") <= Decimal(score) <= Decimal("4"):
        raise ValueError("score_out_of_range")
    return {"axis_id": axis_id, "status": "VALID", "score_decimal": score,
            "missing_reason": None}


@dataclass(frozen=True)
class FixtureProfile:
    max_keyframes: int = 2
    max_lanes: int = 4
    max_masks: int = 8
    max_evidence_versions: int = 3
    max_evaluation_suites: int = 64
    max_events: int = 5000
    max_saved_runs: int = 20
    max_bytes: int = 256 * 1024 * 1024
    retention_seconds: int = 7 * 86400


class ArtifactRegistry:
    """Owned artifact root; clients resolve only registered IDs."""

    def __init__(self, root: Path, run_id: str, now: int = 0):
        self.root = Path(root).resolve()
        self.run_id = require_id(run_id, "run_id")
        self.now = now
        self.root.mkdir(parents=True, exist_ok=True)
        if self.root.is_symlink() or self.root.is_junction():
            raise ValueError("artifact_root_reparse_denied")
        self._records: dict[str, dict[str, Any]] = {}

    def register(self, artifact_id: str, relative: str, data: bytes, media_type: str,
                 expires_at: int | None = None) -> dict[str, Any]:
        require_id(artifact_id, "artifact_id")
        rel = Path(relative)
        if rel.is_absolute() or ".." in rel.parts or rel.name.startswith("."):
            raise ValueError("artifact_locator_denied")
        target = (self.root / rel).resolve()
        if self.root not in target.parents:
            raise ValueError("artifact_locator_denied")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        record = {
            "artifact_id": artifact_id, "owner_run_id": self.run_id,
            "relative_locator": rel.as_posix(), "media_type": media_type,
            "bytes": len(data), "content_digest": sha256(data).hexdigest(),
            "availability": "AVAILABLE", "created_at": self.now,
            "expires_at": expires_at,
        }
        self._records[artifact_id] = record
        return dict(record)

    def import_record(self, record: dict[str, Any]) -> None:
        self._records[record["artifact_id"]] = dict(record)

    def resolve(self, artifact_id: str, now: int | None = None) -> tuple[dict[str, Any], bytes]:
        require_id(artifact_id, "artifact_id")
        record = self._records.get(artifact_id)
        if not record or record["availability"] != "AVAILABLE":
            raise FileNotFoundError("artifact_unavailable")
        current = self.now if now is None else now
        if record["expires_at"] is not None and current >= record["expires_at"]:
            raise FileNotFoundError("artifact_expired")
        target = (self.root / record["relative_locator"]).resolve()
        if self.root not in target.parents or not target.is_file() or target.is_symlink():
            raise FileNotFoundError("artifact_unavailable")
        data = target.read_bytes()
        if sha256(data).hexdigest() != record["content_digest"]:
            raise ValueError("artifact_digest_mismatch")
        return dict(record), data


class FixtureKernel:
    """A deterministic fixture kernel with a single SQLite writer."""

    def __init__(self, db_path: Path, artifact_root: Path, *, run_id: str = "run_sc01",
                 create: bool = True, now: int = 0, profile: FixtureProfile | None = None):
        self.db_path = Path(db_path)
        self.run_id = require_id(run_id, "run_id")
        self.profile = profile or FixtureProfile()
        self.now = now
        self._lock = threading.RLock()
        self._fault: str | None = None
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.db_path, isolation_level=None, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=DELETE")
        self.db.execute("PRAGMA synchronous=FULL")
        if create:
            self._create_schema()
            self.artifacts = ArtifactRegistry(Path(artifact_root), self.run_id, now)
            self._bootstrap()
        else:
            try:
                self._validate_schema()
            except BaseException:
                self.db.close()
                raise
            row = self.db.execute("SELECT value FROM meta WHERE key='artifact_root'").fetchone()
            self.artifacts = ArtifactRegistry(Path(row[0]), self.run_id, now)
            for item in self._records("artifact"):
                self.artifacts.import_record(item)
            with self.transaction():
                status = self._meta("run_status")
                if status in {"CREATED", "RUNNING", "DRAINING"}:
                    self._set_meta("run_status", "INTERRUPTED")
                    self._event("RunInterrupted", {"previous_status": status})

    def _create_schema(self) -> None:
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS records(kind TEXT NOT NULL,id TEXT NOT NULL,payload TEXT NOT NULL,digest TEXT NOT NULL,PRIMARY KEY(kind,id));
        CREATE TABLE IF NOT EXISTS events(commit_seq INTEGER PRIMARY KEY AUTOINCREMENT,event_id TEXT UNIQUE NOT NULL,event_type TEXT NOT NULL,frame_id TEXT,lane_id TEXT,payload TEXT NOT NULL,origin TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS evaluations(evaluation_id TEXT PRIMARY KEY,event_id TEXT UNIQUE NOT NULL,frame_id TEXT NOT NULL,lane_id TEXT NOT NULL,candidate_id TEXT NOT NULL,evidence_version INTEGER NOT NULL,context_id TEXT NOT NULL,axes TEXT NOT NULL,suite_state TEXT NOT NULL,raw_digest TEXT,commit_seq INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS decisions(decision_id TEXT PRIMARY KEY,evaluation_id TEXT,frame_id TEXT NOT NULL,evidence_version INTEGER NOT NULL,previous_winner_id TEXT,winner_after_id TEXT,reason_code TEXT NOT NULL,candidate_q TEXT,previous_winner_q TEXT,delta_to_previous TEXT,commit_seq INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS revisions(revision_id TEXT PRIMARY KEY,decision_id TEXT,frame_id TEXT NOT NULL,from_candidate_id TEXT,to_candidate_id TEXT,revision_kind TEXT NOT NULL,reason_code TEXT NOT NULL,commit_seq INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS selection_state(frame_id TEXT PRIMARY KEY,evidence_version INTEGER NOT NULL,winner_id TEXT,selected_evaluation_id TEXT,display_revision_id TEXT,stale_fallback_id TEXT,latest_seq INTEGER NOT NULL,phase TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS outbox(commit_seq INTEGER PRIMARY KEY,event_id TEXT UNIQUE NOT NULL,delivered INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS receipts(receipt_id TEXT PRIMARY KEY,view_session_id TEXT NOT NULL,source_revision_id TEXT,source_commit_seq INTEGER NOT NULL,frame_id TEXT NOT NULL,display_mode TEXT NOT NULL,rendered_candidate_id TEXT,visible INTEGER NOT NULL,skipped_revision_ids TEXT NOT NULL);
        """)
        if not self.db.execute("SELECT 1 FROM meta WHERE key='schema_version'").fetchone():
            self.db.executemany("INSERT INTO meta VALUES (?,?)", [
                ("schema_version", SCHEMA_VERSION), ("contract_version", CONTRACT_VERSION),
                ("run_id", self.run_id), ("run_status", "CREATED"),
                ("created_at", str(self.now)), ("expires_at", str(self.now + self.profile.retention_seconds)),
                ("artifact_root", str(Path(self.db_path.parent.parent / "runs" / self.run_id / "artifacts").resolve())),
                ("network_calls", "0"), ("automatic_retries", "0")])

    def _validate_schema(self) -> None:
        try:
            version = self._meta("schema_version")
        except sqlite3.Error as exc:
            raise ValueError("unknown_schema") from exc
        if version != SCHEMA_VERSION:
            raise ValueError("unknown_schema")
        if self.now >= int(self._meta("expires_at")):
            raise ValueError("retention_expired")
        if self._meta("run_id") != self.run_id:
            raise ValueError("run_mismatch")

    def _bootstrap(self) -> None:
        with self.transaction():
            self._set_meta("artifact_root", str(self.artifacts.root))
            self._set_meta("run_status", "RUNNING")
            self._event("RunCreated", {"schema_version": SCHEMA_VERSION, "origin": "FIXTURE"})
            for order, lane in enumerate(LANES):
                self._record("lane", lane, {"schema_version": SCHEMA_VERSION, "lane_id": lane,
                    "display_order": order, "architecture_label": f"Fixture lane {lane}",
                    "adapter_ref": "fixture_segmenter_v1", "weight_revision": None,
                    "expected_output_kind": "MASK_COLLECTION", "enabled": True})

    @contextmanager
    def transaction(self):
        with self._lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield
                if self._fault == "before_commit":
                    self._fault = None
                    raise RuntimeError("injected_before_commit")
                if self.db.execute("SELECT COUNT(*) FROM events").fetchone()[0] > self.profile.max_events:
                    raise ValueError("event_capacity")
                self.db.execute("COMMIT")
            except BaseException:
                if self.db.in_transaction:
                    self.db.execute("ROLLBACK")
                raise

    def inject_fault_once(self) -> None:
        self._fault = "before_commit"

    def _meta(self, key: str) -> str:
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        if not row:
            raise ValueError("missing_meta")
        return row[0]

    def _set_meta(self, key: str, value: str) -> None:
        self.db.execute("INSERT INTO meta VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    def _record(self, kind: str, ident: str, payload: dict[str, Any]) -> dict[str, Any]:
        require_id(ident)
        digest = content_digest(payload)
        self.db.execute("INSERT INTO records VALUES (?,?,?,?)", (kind, ident, canonical_json(payload), digest))
        return {"record_id": ident, "digest": digest}

    def _records(self, kind: str) -> list[dict[str, Any]]:
        return [json.loads(row[0]) for row in self.db.execute("SELECT payload FROM records WHERE kind=? ORDER BY id", (kind,))]

    def _event(self, event_type: str, payload: dict[str, Any], frame_id: str | None = None,
               lane_id: str | None = None, event_id: str | None = None) -> tuple[str, int]:
        event_id = event_id or f"evt_{self.db.execute('SELECT COUNT(*) FROM events').fetchone()[0] + 1}"
        require_id(event_id, "event_id")
        cur = self.db.execute("INSERT INTO events(event_id,event_type,frame_id,lane_id,payload,origin) VALUES (?,?,?,?,?,?)",
                              (event_id, event_type, frame_id, lane_id, canonical_json(payload), "FIXTURE"))
        seq = cur.lastrowid
        self.db.execute("INSERT INTO outbox(commit_seq,event_id) VALUES (?,?)", (seq, event_id))
        return event_id, seq

    def publish_frame(self, frame_id: str = "frame_k0", width: int = 320, height: int = 180) -> dict[str, Any]:
        require_id(frame_id, "frame_id")
        if self.db.execute("SELECT COUNT(*) FROM records WHERE kind='frame'").fetchone()[0] >= self.profile.max_keyframes:
            raise ValueError("keyframe_capacity")
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
               '<rect width="100%" height="100%" fill="#071b2d"/><rect x="20" y="80" width="110" height="65" fill="#168aad"/>'
               '<circle cx="235" cy="67" r="30" fill="#52b788"/><path d="M190 150 L235 88 L280 150Z" fill="#f4a261"/></svg>').encode()
        artifact = self.artifacts.register(f"art_{frame_id}", f"{frame_id}/keyframe.svg", svg, "image/svg+xml",
                                           self.now + self.profile.retention_seconds)
        with self.transaction():
            self._record("artifact", artifact["artifact_id"], artifact)
            frame = {"schema_version": SCHEMA_VERSION, "frame_id": frame_id, "run_id": self.run_id,
                     "generation": 0, "asset_id": "fixture_asset", "asset_digest": artifact["content_digest"],
                     "pixel_digest": artifact["content_digest"], "width": width, "height": height,
                     "requested_time": "0", "pts": "0", "time_base_num": 1, "time_base_den": 1000,
                     "sample_id": "fixture_k0", "frame_artifact_ref": artifact["artifact_id"],
                     "transform_ref": "identity", "media_origin": "FIXTURE"}
            ref = self._record("frame", frame_id, frame)
            event_id, seq = self._event("KeyframePublished", {"frame_ref": ref}, frame_id)
            self.db.execute("INSERT INTO selection_state VALUES (?,?,?,?,?,?,?,?)",
                            (frame_id, 0, None, None, None, None, seq, "OPEN"))
        return frame

    def publish_candidate(self, frame_id: str, lane_id: str, *, mask_count: int = 1,
                          ordinal: int | None = None, empty: bool = False) -> dict[str, Any]:
        if lane_id not in LANES:
            raise ValueError("unknown_lane")
        if not 0 <= mask_count <= self.profile.max_masks:
            raise ValueError("mask_capacity")
        if empty:
            mask_count = 0
        candidate_id = f"cand_{frame_id}_{lane_id.lower()}"
        color = {"S": "#00d084", "A": "#00a8ff", "B": "#b65cff", "C": "#f6bd60"}[lane_id]
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="320" height="180" viewBox="0 0 320 180">'
               f'<rect width="320" height="180" fill="#071b2d"/><path d="M{25 + 12*LANES.index(lane_id)} 145 L150 35 L285 145Z" fill="{color}" fill-opacity=".68"/>'
               f'<text x="12" y="24" fill="white" font-family="sans-serif">FIXTURE {lane_id}</text></svg>').encode()
        artifact = self.artifacts.register(f"art_mask_{frame_id}_{lane_id.lower()}",
            f"{frame_id}/{lane_id.lower()}-mask.svg", svg, "image/svg+xml", self.now + self.profile.retention_seconds)
        candidate = {"schema_version": SCHEMA_VERSION, "candidate_id": candidate_id,
            "run_id": self.run_id, "generation": 0, "frame_ref": frame_id, "lane_id": lane_id,
            "job_id": f"job_{frame_id}_{lane_id.lower()}", "ordinal": LANES.index(lane_id) if ordinal is None else ordinal,
            "origin": "FIXTURE", "output_status": "SUCCEEDED_EMPTY" if empty else "SUCCEEDED_NONEMPTY",
            "mask_count": mask_count, "mask_collection_ref": artifact["artifact_id"],
            "raw_artifact_ref": None, "transform_ref": "identity",
            "architecture_provenance": "fixture_segmenter_v1", "completed_at": str(self.now),
            "content_digest": sha256(svg).hexdigest()}
        with self.transaction():
            self._record("artifact", artifact["artifact_id"], artifact)
            ref = self._record("candidate", candidate_id, candidate)
            self._event("CandidatePublished", {"candidate_ref": ref}, frame_id, lane_id)
        return candidate

    def publish_evidence(self, frame_id: str, version: int) -> None:
        if version < 0 or version >= self.profile.max_evidence_versions:
            raise ValueError("evidence_version_capacity")
        with self.transaction():
            state = self.db.execute("SELECT * FROM selection_state WHERE frame_id=?", (frame_id,)).fetchone()
            if not state or version <= state["evidence_version"]:
                raise ValueError("evidence_not_newer")
            event_id, seq = self._event("EvidencePublished", {"version": version,
                "previous_version": state["evidence_version"], "coalesce_ms": 0}, frame_id)
            revision_id = f"rev_{seq}"
            self.db.execute("INSERT INTO revisions VALUES (?,?,?,?,?,?,?,?)",
                (revision_id, None, frame_id, state["winner_id"], None, "EVIDENCE_INVALIDATED", "OLD_EVIDENCE", seq))
            self.db.execute("UPDATE selection_state SET evidence_version=?,winner_id=NULL,selected_evaluation_id=NULL,display_revision_id=?,stale_fallback_id=?,latest_seq=?,phase='OPEN' WHERE frame_id=?",
                (version, revision_id, state["winner_id"], seq, frame_id))

    def accept_evaluation(self, frame_id: str, lane_id: str, evidence_version: int,
                          scores: dict[str, object], *, event_id: str,
                          returned_binding: str = "fixture_evaluator_v1",
                          rubric: str = "fixture_rubric_v1", question: str = "fixture_questions_v1",
                          raw: bytes = b"fixture", candidate_id: str | None = None) -> dict[str, Any]:
        require_id(event_id, "event_id")
        if returned_binding != "fixture_evaluator_v1" or rubric != "fixture_rubric_v1" or question != "fixture_questions_v1":
            raise ValueError("evaluation_envelope_mismatch")
        candidate_id = candidate_id or f"cand_{frame_id}_{lane_id.lower()}"
        candidate = self.db.execute("SELECT payload FROM records WHERE kind='candidate' AND id=?", (candidate_id,)).fetchone()
        if not candidate:
            raise ValueError("unknown_candidate")
        candidate_payload = json.loads(candidate[0])
        if candidate_payload["frame_ref"] != frame_id or candidate_payload["lane_id"] != lane_id:
            raise ValueError("candidate_scope_mismatch")
        axes = {axis: _axis(scores.get(axis), axis) for axis in AXES}
        q = axes["Q"]
        suite_state = "COMPLETE" if all(v["status"] == "VALID" for v in axes.values()) else "PARTIAL_DIAGNOSTICS"
        raw_digest = sha256(raw).hexdigest()
        context_id = f"ctx_{frame_id}_e{evidence_version}"
        evaluation_id = f"eval_{frame_id}_{lane_id.lower()}_e{evidence_version}"
        with self.transaction():
            duplicate = self.db.execute("SELECT decision_id FROM decisions WHERE evaluation_id=?", (evaluation_id,)).fetchone()
            event_duplicate = self.db.execute("SELECT 1 FROM events WHERE event_id=?", (event_id,)).fetchone()
            if duplicate or event_duplicate:
                row = self.db.execute("SELECT * FROM decisions WHERE evaluation_id=?", (evaluation_id,)).fetchone()
                return dict(row) if row else {"duplicate": True}
            if self.db.execute("SELECT COUNT(*) FROM evaluations").fetchone()[0] >= self.profile.max_evaluation_suites:
                raise ValueError("evaluation_capacity")
            _, seq = self._event("EvaluationAccepted", {"evaluation_id": evaluation_id,
                "evidence_version": evidence_version, "accepted_axes": [a for a, v in axes.items() if v["status"] == "VALID"]},
                frame_id, lane_id, event_id)
            self.db.execute("INSERT INTO evaluations VALUES (?,?,?,?,?,?,?,?,?,?,?)", (
                evaluation_id, event_id, frame_id, lane_id, candidate_id, evidence_version,
                context_id, canonical_json(axes), suite_state, raw_digest, seq))
            state = self.db.execute("SELECT * FROM selection_state WHERE frame_id=?", (frame_id,)).fetchone()
            previous = state["winner_id"]
            previous_q: str | None = None
            winner = previous
            reason = "AWAITING_EVALUATION"
            revision_kind: str | None = None
            if evidence_version != state["evidence_version"]:
                reason = "OLD_EVIDENCE"
            elif q["status"] != "VALID":
                reason = "INVALID_EVALUATION" if q["status"] == "INVALID" else "EVALUATION_FAILED"
            elif Decimal(q["score_decimal"]) < THRESHOLD:
                reason = "BELOW_Q_THRESHOLD"
            elif previous is None:
                winner = candidate_id
                reason = "FIRST_ELIGIBLE" if evidence_version == 0 else "FIRST_ELIGIBLE_IN_NEW_EVIDENCE"
                revision_kind = "SELECT"
            else:
                prow = self.db.execute("SELECT axes FROM evaluations WHERE evaluation_id=(SELECT selected_evaluation_id FROM selection_state WHERE frame_id=?)", (frame_id,)).fetchone()
                previous_q = json.loads(prow[0])["Q"]["score_decimal"]
                if Decimal(q["score_decimal"]) > Decimal(previous_q):
                    winner = candidate_id
                    reason = "HIGHER_Q"
                    revision_kind = "REFRESH_SAME" if previous == candidate_id else "REPLACE"
                elif Decimal(q["score_decimal"]) == Decimal(previous_q):
                    reason = "TIE_KEEP_CURRENT"
                else:
                    reason = "LOWER_Q"
            delta = None
            if previous_q is not None and q["status"] == "VALID" and evidence_version == state["evidence_version"]:
                delta = normalize_decimal(str(Decimal(q["score_decimal"]) - Decimal(previous_q)))
            decision_id = f"dec_{seq}"
            self.db.execute("INSERT INTO decisions VALUES (?,?,?,?,?,?,?,?,?,?,?)", (
                decision_id, evaluation_id, frame_id, evidence_version, previous, winner, reason,
                q["score_decimal"] if q["status"] == "VALID" else None, previous_q, delta, seq))
            revision_id = None
            if revision_kind:
                revision_id = f"rev_{seq}"
                self.db.execute("INSERT INTO revisions VALUES (?,?,?,?,?,?,?,?)",
                    (revision_id, decision_id, frame_id, previous, winner, revision_kind, reason, seq))
                self.db.execute("UPDATE selection_state SET winner_id=?,selected_evaluation_id=?,display_revision_id=?,stale_fallback_id=NULL,latest_seq=? WHERE frame_id=?",
                    (winner, evaluation_id, revision_id, seq, frame_id))
            else:
                self.db.execute("UPDATE selection_state SET latest_seq=? WHERE frame_id=?", (seq, frame_id))
            return {"decision_id": decision_id, "evaluation_id": evaluation_id,
                    "reason_code": reason, "winner_after_id": winner, "delta_to_previous": delta,
                    "revision_id": revision_id, "commit_seq": seq}

    def rebuild_tie(self, frame_id: str) -> str | None:
        state = self.db.execute("SELECT * FROM selection_state WHERE frame_id=?", (frame_id,)).fetchone()
        rows = self.db.execute("SELECT e.*,r.payload candidate FROM evaluations e JOIN records r ON r.kind='candidate' AND r.id=e.candidate_id WHERE e.frame_id=? AND e.evidence_version=?",
                               (frame_id, state["evidence_version"])).fetchall()
        eligible = []
        for row in rows:
            q = json.loads(row["axes"])["Q"]
            if q["status"] == "VALID" and Decimal(q["score_decimal"]) >= THRESHOLD:
                cp = json.loads(row["candidate"])
                eligible.append((-Decimal(q["score_decimal"]), cp["content_digest"], cp["ordinal"], row["candidate_id"]))
        return sorted(eligible)[0][3] if eligible else None

    def finalize(self, frame_id: str, *, partial: bool = False) -> None:
        with self.transaction():
            state = self.db.execute("SELECT * FROM selection_state WHERE frame_id=?", (frame_id,)).fetchone()
            winner = state["winner_id"]
            seq = self._event("CoverageFinalized", {"coverage_state": "TERMINAL_PARTIAL" if partial else "COMPLETE"}, frame_id)[1]
            if winner is None and state["stale_fallback_id"] is not None:
                revision_id = f"rev_{seq}"
                self.db.execute("INSERT INTO revisions VALUES (?,?,?,?,?,?,?,?)",
                    (revision_id, None, frame_id, state["stale_fallback_id"], None, "CLEAR", "NO_ELIGIBLE_RESULT", seq))
                self.db.execute("UPDATE selection_state SET display_revision_id=?,stale_fallback_id=NULL,latest_seq=?,phase=? WHERE frame_id=?",
                    (revision_id, seq, "TERMINAL_PARTIAL" if partial else "COMPLETE", frame_id))
            else:
                self.db.execute("UPDATE selection_state SET latest_seq=?,phase=? WHERE frame_id=?",
                    (seq, "TERMINAL_PARTIAL" if partial else "COMPLETE", frame_id))

    @staticmethod
    def queue_snapshot(*, queue_id: str = "fixture_eval", queued: int, active: int,
                       retry_delayed: int = 0, succeeded: int = 0, failed: int = 0,
                       cancelled: int = 0, expired: int = 0, rejected: int = 0,
                       capacity: int = 8, concurrency: int = 2, oldest_ms: int | None = None,
                       longest_active_ms: int | None = None, health: str = "OK") -> dict[str, Any]:
        for value in (queued, active, retry_delayed, succeeded, failed, cancelled, expired, rejected):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError("invalid_queue_count")
        if queued == 0 and oldest_ms is not None:
            raise ValueError("oldest_requires_queued")
        if health not in {"OK", "PAUSED", "ERROR", "UNKNOWN", "STALE_TELEMETRY"}:
            raise ValueError("unknown_health")
        congestion = "NORMAL"
        if queued > 0:
            congestion = "ATTENTION"
        if queued and ((capacity > 0 and queued / capacity >= .75) or (oldest_ms or 0) >= 5000):
            congestion = "CONGESTED"
        if (capacity > 0 and queued >= capacity) or rejected > 0:
            congestion = "SATURATED"
        return {"queue_id": queue_id, "unit": "EVALUATION_SUITE", "scope_kind": "RUN",
            "capacity": capacity, "concurrency_limit": concurrency, "queued": queued, "active": active,
            "retry_delayed": retry_delayed, "succeeded_total": succeeded, "failed_total": failed,
            "cancelled_total": cancelled, "expired_total": expired, "rejected_total": rejected,
            "oldest_queued_ms": oldest_ms, "longest_active_ms": longest_active_ms,
            "health": health, "congestion": congestion,
            "accepted_total": queued + active + retry_delayed + succeeded + failed + cancelled + expired}

    def view(self, frame_id: str, *, preview_candidate: str | None = None) -> dict[str, Any]:
        state = self.db.execute("SELECT * FROM selection_state WHERE frame_id=?", (frame_id,)).fetchone()
        frame_row = self.db.execute("SELECT payload FROM records WHERE kind='frame' AND id=?", (frame_id,)).fetchone()
        if not state or not frame_row:
            raise ValueError("unknown_frame")
        frame = json.loads(frame_row[0])
        candidates = {row["lane_id"]: row for row in self._records("candidate") if row["frame_ref"] == frame_id}
        rows = []
        selected_eval = None
        if state["selected_evaluation_id"]:
            selected_eval = self.db.execute("SELECT axes FROM evaluations WHERE evaluation_id=?", (state["selected_evaluation_id"],)).fetchone()
        selected_q = json.loads(selected_eval[0])["Q"]["score_decimal"] if selected_eval else None
        ever = {r[0] for r in self.db.execute("SELECT to_candidate_id FROM revisions WHERE frame_id=? AND to_candidate_id IS NOT NULL", (frame_id,))}
        for lane in LANES:
            candidate = candidates.get(lane)
            evaluation = None
            if candidate:
                evaluation = self.db.execute("SELECT * FROM evaluations WHERE candidate_id=? AND evidence_version=? ORDER BY commit_seq LIMIT 1",
                    (candidate["candidate_id"], state["evidence_version"])).fetchone()
            axes = json.loads(evaluation["axes"]) if evaluation else {a: _axis(None, a) for a in AXES}
            q = axes["Q"]
            delta = None
            if selected_q is not None and q["status"] == "VALID":
                delta = normalize_decimal(str(Decimal(q["score_decimal"]) - Decimal(selected_q)))
            decision = self.db.execute("SELECT * FROM decisions WHERE evaluation_id=?", (evaluation["evaluation_id"],)).fetchone() if evaluation else None
            is_winner = candidate is not None and candidate["candidate_id"] == state["winner_id"]
            rows.append({"lane_id": lane, "architecture_label": f"Fixture lane {lane}",
                "candidate_id": candidate["candidate_id"] if candidate else None,
                "generation_status": candidate["output_status"] if candidate else "RUNNING",
                "evaluation_status": evaluation["suite_state"] if evaluation else "NOT_READY",
                "selection_status": "CURRENT_PROVISIONAL" if is_winner else ("ELIGIBLE_NOT_SELECTED" if evaluation else "NOT_READY"),
                "axis_results": axes, "current_q_delta": delta,
                "current_reason_code": decision["reason_code"] if decision else ("AWAITING_EVALUATION" if candidate else "AWAITING_SEGMENTATION"),
                "decision_ref": decision["decision_id"] if decision else None,
                "ever_selected": candidate is not None and candidate["candidate_id"] in ever,
                "thumbnail_ref": candidate["mask_collection_ref"] if candidate else None,
                "mask_count": candidate["mask_count"] if candidate else None,
                "evidence_version": state["evidence_version"], "source_origin": "FIXTURE"})
        revisions = [dict(r) for r in self.db.execute("SELECT * FROM revisions WHERE frame_id=? ORDER BY commit_seq", (frame_id,))]
        decisions = [dict(r) for r in self.db.execute("SELECT * FROM decisions WHERE frame_id=? ORDER BY commit_seq", (frame_id,))]
        winner = state["winner_id"]
        rendered = preview_candidate or winner or state["stale_fallback_id"]
        display_mode = "MANUAL_CANDIDATE" if preview_candidate else "FOLLOW_SELECTION"
        return {"view_id": f"view_{frame_id}", "schema_version": SCHEMA_VERSION, "run_id": self.run_id,
            "frame_id": frame_id, "generation": 0, "current_comparison_ref": f"ctx_{frame_id}_e{state['evidence_version']}",
            "snapshot_seq": state["latest_seq"], "delivery_mode": "ORIGINAL", "rows": rows,
            "selection": {"winner_id": winner, "stale_fallback_id": state["stale_fallback_id"],
                "display_revision_id": state["display_revision_id"]},
            "preview": {"display_mode": display_mode, "rendered_candidate_id": rendered,
                "manual_candidate_id": preview_candidate, "keyframe_artifact_ref": frame["frame_artifact_ref"]},
            "timeline_page": {"decisions": decisions, "revisions": revisions},
            "queues": [self.queue_snapshot(queued=0, active=0, succeeded=len(decisions))],
            "flow_pulses": [], "coverage_state": state["phase"], "unavailable_refs": [],
            "fixture": True, "network_calls": int(self._meta("network_calls"))}

    def event_page(self, after: int = 0, limit: int = 200) -> list[dict[str, Any]]:
        if limit < 1 or limit > 200:
            raise ValueError("invalid_page_limit")
        return [{**dict(row), "payload": json.loads(row["payload"])} for row in self.db.execute(
            "SELECT * FROM events WHERE commit_seq>? ORDER BY commit_seq LIMIT ?", (after, limit))]

    def receipt(self, value: dict[str, Any]) -> None:
        required = {"receipt_id", "view_session_id", "source_commit_seq", "frame_id", "display_mode", "visible"}
        if not required <= value.keys() or value["display_mode"] not in {"FOLLOW_SELECTION", "MANUAL_CANDIDATE", "HISTORICAL_REPLAY"}:
            raise ValueError("invalid_receipt")
        with self.transaction():
            self.db.execute("INSERT OR IGNORE INTO receipts VALUES (?,?,?,?,?,?,?,?,?)", (
                require_id(value["receipt_id"], "receipt_id"), require_id(value["view_session_id"], "view_session_id"),
                value.get("source_revision_id"), value["source_commit_seq"], value["frame_id"], value["display_mode"],
                value.get("rendered_candidate_id"), 1 if value["visible"] else 0,
                canonical_json(value.get("skipped_revision_ids", []))))

    def deliver_outbox(self) -> list[str]:
        with self.transaction():
            ids = [row[0] for row in self.db.execute("SELECT event_id FROM outbox WHERE delivered=0 ORDER BY commit_seq")]
            self.db.execute("UPDATE outbox SET delivered=1")
        return ids

    def replay(self, frame_id: str) -> dict[str, Any]:
        return {"delivery_mode": "RECORDED_REPLAY", "events": self.event_page(),
                "view": self.view(frame_id), "network_calls": 0, "automatic_retries": 0,
                "order": "commit_seq", "clock": "fixture_cursor_frozen"}

    def close_run(self, *, partial: bool = False) -> None:
        with self.transaction():
            self._set_meta("run_status", "CLOSED_PARTIAL" if partial else "CLOSED_SUCCEEDED")
            self._event("RunClosed", {"status": self._meta("run_status")})

    def close(self) -> None:
        self.db.close()


def build_demo(kernel: FixtureKernel) -> str:
    """Build the contractual E0 sample without sleeping or external work."""
    frame = "frame_k0"
    kernel.publish_frame(frame)
    for lane in LANES:
        kernel.publish_candidate(frame, lane, empty=(lane == "C"))
    values = {
        "A": {"Q": "3.2", "A": "1.2", "R": "1.8", "I": "3.5", "C": "3.5"},
        "S": {"Q": "3.6", "A": "1.7", "R": "2.1", "I": "3.5", "C": "3.9"},
        "B": {"Q": "3.4", "A": "1.4", "R": "1.5", "I": "3.6", "C": "2.8"},
    }
    for lane in ("A", "S", "B"):
        kernel.accept_evaluation(frame, lane, 0, values[lane], event_id=f"evalevent_{lane.lower()}_e0")
    return frame

# SC01 repair implementation. The original v1 remains in Git history and above
# for review provenance; public imports use the repaired store and validators.
from .repair import (  # noqa: E402,F401
    ArtifactRegistry, FixtureKernel, FixtureProfile, SCHEMA_VERSION,
    build_demo, canonical_json, content_digest, normalize_decimal,
    prepare_live_demo, release_demo_step,
)
