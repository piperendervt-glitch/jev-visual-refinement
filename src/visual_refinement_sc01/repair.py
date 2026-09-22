"""SC01 repair kernel: finite jobs, evidence-aware Q selection and replay."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation, localcontext
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sqlite3
import threading
from typing import Any

SCHEMA_VERSION = "vr_sc01_v1"
STORE_VERSION = "vr_sc01_store_v2"
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


def require_uint(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > 9_007_199_254_740_991:
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
    # normalize() is intentionally avoided: Decimal context can round long input.
    result = format(number, "f")
    return result.rstrip("0").rstrip(".") if "." in result else result


def decimal_delta(left: str, right: str) -> str:
    """Subtract without letting the process Decimal context erase input significance."""
    significant=max(sum(ch.isdigit() for ch in left),sum(ch.isdigit() for ch in right))+4
    with localcontext() as context:
        context.prec=significant
        value=Decimal(left)-Decimal(right)
    return normalize_decimal(format(value,"f"))


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_digest(value: object) -> str:
    return sha256(canonical_json(value).encode()).hexdigest()


def axis_result(value: object, axis_id: str) -> dict[str, Any]:
    if value is None:
        return {"axis_id": axis_id, "status": "MISSING", "score_decimal": None,
                "raw_score_text": None, "missing_reason": "FIXTURE_NOT_RETURNED"}
    if isinstance(value, dict):
        if set(value) - {"status", "score_decimal", "raw_score_text", "missing_reason"}:
            raise ValueError("unknown_axis_field")
        status = value.get("status")
        if status not in {"VALID", "MISSING", "INVALID", "NOT_APPLICABLE", "NOT_REQUESTED", "PENDING"}:
            raise ValueError("unknown_value_status")
        if status != "VALID":
            if value.get("score_decimal") is not None:
                raise ValueError("non_valid_axis_has_score")
            return {"axis_id": axis_id, "status": status, "score_decimal": None,
                    "raw_score_text": value.get("raw_score_text"),
                    "missing_reason": value.get("missing_reason") or status}
        value = value.get("score_decimal")
    score = normalize_decimal(value)
    if not Decimal("0") <= Decimal(score) <= Decimal("4"):
        raise ValueError("score_out_of_range")
    return {"axis_id": axis_id, "status": "VALID", "score_decimal": score,
            "raw_score_text": str(value), "missing_reason": None}


@dataclass(frozen=True)
class FixtureProfile:
    max_keyframes: int = 2
    max_lanes: int = 4
    max_masks: int = 8
    max_width: int = 640
    max_height: int = 360
    max_evidence_versions: int = 3
    max_evaluation_suites: int = 64
    max_events: int = 5000
    max_saved_runs: int = 20
    max_bytes: int = 256 * 1024 * 1024
    retention_seconds: int = 7 * 86400
    queue_capacity: int = 8
    evaluator_concurrency: int = 2
    request_timeout_seconds: float = 1.0
    max_http_connections: int = 8


class ArtifactRegistry:
    """Immutable registered files; collision checks precede all writes."""
    def __init__(self, root: Path, run_id: str, *, retention_now: int = 0,
                 max_bytes: int = 256 * 1024 * 1024):
        raw = Path(root)
        self._reject_links(raw)
        self.root = raw.resolve()
        self.run_id = require_id(run_id, "run_id")
        self.retention_now = retention_now
        self.max_bytes = max_bytes
        self.root.mkdir(parents=True, exist_ok=True)
        self._reject_links(self.root)
        self._records: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _reject_links(path: Path) -> None:
        current = path.absolute()
        while True:
            if current.exists() and (current.is_symlink() or current.is_junction()):
                raise ValueError("artifact_reparse_denied")
            if current.parent == current:
                return
            current = current.parent

    def total_bytes(self) -> int:
        return sum(r["bytes"] for r in self._records.values() if r["availability"] == "AVAILABLE")

    def register(self, artifact_id: str, relative: str, data: bytes, media_type: str,
                 expires_at: int | None = None) -> dict[str, Any]:
        require_id(artifact_id, "artifact_id")
        if not isinstance(data, bytes) or not data:
            raise ValueError("artifact_bytes_required")
        if media_type not in {"image/svg+xml", "application/octet-stream", "application/json"}:
            raise ValueError("artifact_media_type")
        rel = Path(relative)
        if rel.is_absolute() or ".." in rel.parts or rel.name.startswith("."):
            raise ValueError("artifact_locator_denied")
        target = (self.root / rel).resolve()
        if self.root not in target.parents:
            raise ValueError("artifact_locator_denied")
        digest = sha256(data).hexdigest()
        with self._lock:
            old = self._records.get(artifact_id)
            if old:
                if old["content_digest"] == digest and old["relative_locator"] == rel.as_posix():
                    return dict(old)
                raise ValueError("artifact_id_collision")
            if target.exists() and sha256(target.read_bytes()).hexdigest() != digest:
                raise ValueError("artifact_path_collision")
            if self.total_bytes() + len(data) > self.max_bytes:
                raise ValueError("artifact_capacity")
            target.parent.mkdir(parents=True, exist_ok=True)
            self._reject_links(target.parent)
            temp = target.with_name(target.name + f".tmp-{os.getpid()}-{threading.get_ident()}")
            try:
                with temp.open("xb") as stream:
                    stream.write(data); stream.flush(); os.fsync(stream.fileno())
                if target.exists():
                    raise ValueError("artifact_path_collision")
                os.replace(temp, target)
            finally:
                if temp.exists():
                    temp.unlink()
            record = {"schema_version": SCHEMA_VERSION, "artifact_id": artifact_id,
                "owner_run_id": self.run_id, "relative_locator": rel.as_posix(),
                "media_type": media_type, "bytes": len(data), "content_digest": digest,
                "availability": "AVAILABLE", "created_at": self.retention_now,
                "expires_at": expires_at}
            self._records[artifact_id] = record
            return dict(record)

    def import_record(self, value: dict[str, Any]) -> None:
        self._records[value["artifact_id"]] = dict(value)

    def resolve(self, artifact_id: str, now: int | None = None) -> tuple[dict[str, Any], bytes]:
        require_id(artifact_id, "artifact_id")
        with self._lock:
            record = self._records.get(artifact_id)
            if not record or record["availability"] != "AVAILABLE":
                raise FileNotFoundError("artifact_unavailable")
            current = self.retention_now if now is None else now
            if record["expires_at"] is not None and current >= record["expires_at"]:
                raise FileNotFoundError("artifact_expired")
            target = (self.root / record["relative_locator"]).resolve()
            self._reject_links(target)
            if self.root not in target.parents or not target.is_file():
                raise FileNotFoundError("artifact_unavailable")
            data = target.read_bytes()
            if len(data) != record["bytes"] or sha256(data).hexdigest() != record["content_digest"]:
                raise ValueError("artifact_digest_mismatch")
            return dict(record), data


class FixtureKernel:
    """Single writer with a lock-shared, commit-only HTTP read boundary."""
    def __init__(self, db_path: Path, artifact_root: Path, *, run_id: str = "run_sc01",
                 create: bool = True, retention_now: int = 0, fixture_now_ms: int = 0,
                 profile: FixtureProfile | None = None, session_root: Path | None = None):
        self.db_path = Path(db_path)
        self.run_id = require_id(run_id, "run_id")
        self.profile = profile or FixtureProfile()
        self.session_root=Path(session_root).resolve() if session_root is not None else None
        self.retention_now = retention_now
        self.fixture_now_ms = fixture_now_ms
        self._lock = threading.RLock()
        self._fault: str | None = None
        self.closed = False
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        existed = self.db_path.exists()
        if create and existed:
            raise ValueError("run_collision")
        if create and self.session_root is not None and len(list(self.session_root.glob("*/state.sqlite3")))>=self.profile.max_saved_runs:
            raise ValueError("saved_run_capacity")
        if create and self._session_bytes()>self.profile.max_bytes:
            raise ValueError("session_byte_capacity")
        self.db = sqlite3.connect(self.db_path, isolation_level=None, check_same_thread=False, timeout=2)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON"); self.db.execute("PRAGMA journal_mode=DELETE"); self.db.execute("PRAGMA synchronous=FULL")
        try:
            if create:
                self._schema()
                self.artifacts = ArtifactRegistry(artifact_root, run_id, retention_now=retention_now,
                                                  max_bytes=self.profile.max_bytes)
                self._bootstrap()
            else:
                self._validate_store()
                saved_capacity=self.db.execute("SELECT value FROM meta WHERE key='queue_capacity'").fetchone()
                if saved_capacity:
                    self.profile=replace(self.profile,queue_capacity=int(saved_capacity[0]))
                self.artifacts = ArtifactRegistry(Path(self._meta("artifact_root")), run_id,
                    retention_now=retention_now, max_bytes=self.profile.max_bytes)
                for item in self._records("artifact"):
                    self.artifacts.import_record(item)
                with self.transaction():
                    old = self._meta("run_status")
                    if old in {"CREATED", "RUNNING", "DRAINING"}:
                        self._set_meta("run_status", "INTERRUPTED")
                        _, seq = self._event("RunInterrupted", {"previous_status": old})
                        self._snapshot_all(seq)
        except BaseException:
            self.db.close(); raise

    def _schema(self) -> None:
        self.db.executescript("""
        CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE records(kind TEXT NOT NULL,id TEXT NOT NULL,payload TEXT NOT NULL,digest TEXT NOT NULL,PRIMARY KEY(kind,id));
        CREATE TABLE events(commit_seq INTEGER PRIMARY KEY AUTOINCREMENT,event_id TEXT UNIQUE NOT NULL,event_type TEXT NOT NULL,frame_id TEXT,lane_id TEXT,payload TEXT NOT NULL,origin TEXT NOT NULL);
        CREATE TABLE jobs(job_id TEXT PRIMARY KEY,frame_id TEXT,lane_id TEXT,stage TEXT NOT NULL,unit TEXT NOT NULL,status TEXT NOT NULL,phase TEXT,queued_ms INTEGER,started_ms INTEGER,finished_ms INTEGER,error_code TEXT,accepted INTEGER NOT NULL);
        CREATE TABLE eval_tasks(evaluation_id TEXT PRIMARY KEY,frame_id TEXT NOT NULL,lane_id TEXT NOT NULL,candidate_id TEXT NOT NULL,evidence_version INTEGER NOT NULL,context_id TEXT NOT NULL,status TEXT NOT NULL,input_digest TEXT NOT NULL);
        CREATE TABLE eval_attempts(attempt_id TEXT PRIMARY KEY,evaluation_id TEXT NOT NULL,attempt_index INTEGER NOT NULL,envelope_status TEXT NOT NULL,raw BLOB NOT NULL,raw_digest TEXT NOT NULL,event_id TEXT UNIQUE NOT NULL,commit_seq INTEGER NOT NULL);
        CREATE TABLE axis_results(evaluation_id TEXT NOT NULL,axis_id TEXT NOT NULL,attempt_id TEXT NOT NULL,payload TEXT NOT NULL,accepted_seq INTEGER NOT NULL,PRIMARY KEY(evaluation_id,axis_id));
        CREATE TABLE decisions(decision_id TEXT PRIMARY KEY,evaluation_id TEXT,frame_id TEXT NOT NULL,evidence_version INTEGER NOT NULL,previous_winner_id TEXT,winner_after_id TEXT,reason_code TEXT NOT NULL,candidate_q TEXT,previous_winner_q TEXT,delta_to_previous TEXT,commit_seq INTEGER NOT NULL);
        CREATE TABLE revisions(revision_id TEXT PRIMARY KEY,decision_id TEXT,frame_id TEXT NOT NULL,from_candidate_id TEXT,to_candidate_id TEXT,revision_kind TEXT NOT NULL,reason_code TEXT NOT NULL,commit_seq INTEGER NOT NULL);
        CREATE TABLE selection_state(frame_id TEXT PRIMARY KEY,generation INTEGER NOT NULL,evidence_version INTEGER NOT NULL,winner_id TEXT,selected_evaluation_id TEXT,display_revision_id TEXT,stale_fallback_id TEXT,latest_seq INTEGER NOT NULL,coverage_state TEXT NOT NULL,cancelled INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE view_history(frame_id TEXT NOT NULL,commit_seq INTEGER NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(frame_id,commit_seq));
        CREATE TABLE outbox(commit_seq INTEGER PRIMARY KEY,event_id TEXT UNIQUE NOT NULL,delivered INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE receipts(receipt_id TEXT PRIMARY KEY,view_session_id TEXT NOT NULL,source_revision_id TEXT NOT NULL,source_commit_seq INTEGER NOT NULL,run_id TEXT NOT NULL,frame_id TEXT NOT NULL,generation INTEGER NOT NULL,display_mode TEXT NOT NULL,rendered_candidate_id TEXT,visible INTEGER NOT NULL,skipped_revision_ids TEXT NOT NULL,classification TEXT NOT NULL);
        """)
        self.db.executemany("INSERT INTO meta VALUES (?,?)", [
            ("schema_version", SCHEMA_VERSION), ("store_version", STORE_VERSION),
            ("contract_version", CONTRACT_VERSION), ("run_id", self.run_id),
            ("run_status", "CREATED"), ("created_retention_time", str(self.retention_now)),
            ("expires_at", str(self.retention_now + self.profile.retention_seconds)),
            ("artifact_root", ""), ("fixture_now_ms", str(self.fixture_now_ms)),
            ("queue_capacity", str(self.profile.queue_capacity)),
            ("network_calls", "0"), ("automatic_retries", "0")])

    def _validate_store(self) -> None:
        if self._meta("schema_version") != SCHEMA_VERSION or self._meta("store_version") != STORE_VERSION:
            raise ValueError("unsupported_saved_run_schema")
        if self.retention_now >= int(self._meta("expires_at")):
            raise ValueError("retention_expired")
        if self._meta("run_id") != self.run_id:
            raise ValueError("run_mismatch")

    def _bootstrap(self) -> None:
        with self.transaction():
            self._set_meta("artifact_root", str(self.artifacts.root)); self._set_meta("run_status", "RUNNING")
            self._event("RunCreated", {"schema_version": SCHEMA_VERSION, "store_version": STORE_VERSION})
            for order, lane in enumerate(LANES):
                self._record("lane", lane, {"schema_version": SCHEMA_VERSION, "lane_id": lane,
                    "display_order": order, "architecture_label": f"Fixture lane {lane}",
                    "adapter_ref": "fixture_segmenter_v1", "weight_revision": None,
                    "expected_output_kind": "MASK_COLLECTION", "enabled": True})

    @contextmanager
    def transaction(self):
        with self._lock:
            if self.closed: raise ValueError("store_closed")
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield
                if self._fault == "before_commit":
                    self._fault = None; raise RuntimeError("injected_before_commit")
                if self.db.execute("SELECT COUNT(*) FROM events").fetchone()[0] > self.profile.max_events:
                    raise ValueError("event_capacity")
                if self.db_path.stat().st_size + self.artifacts.total_bytes() > self.profile.max_bytes: raise ValueError("run_capacity")
                if self._session_bytes()>self.profile.max_bytes: raise ValueError("session_byte_capacity")
                self.db.execute("COMMIT")
            except BaseException:
                if self.db.in_transaction: self.db.execute("ROLLBACK")
                raise

    def _session_bytes(self)->int:
        total=0
        if self.session_root is not None and self.session_root.exists():
            for path in self.session_root.glob("*/*"):
                if path.is_file():
                    try: total+=path.stat().st_size
                    except OSError: continue
            for path in self.session_root.glob("*/artifacts/**/*"):
                if path.is_file():
                    try: total+=path.stat().st_size
                    except OSError: continue
        return total

    def inject_fault_once(self) -> None: self._fault = "before_commit"
    def _meta(self, key: str) -> str:
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        if not row: raise ValueError("missing_meta")
        return row[0]
    def _set_meta(self, key: str, value: str) -> None:
        self.db.execute("INSERT INTO meta VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
    def _record(self, kind: str, ident: str, payload: dict[str, Any]) -> dict[str, str]:
        require_id(ident); digest = content_digest(payload)
        self.db.execute("INSERT INTO records VALUES (?,?,?,?)", (kind, ident, canonical_json(payload), digest))
        return {"record_id": ident, "digest": digest}
    def _records(self, kind: str) -> list[dict[str, Any]]:
        return [json.loads(r[0]) for r in self.db.execute("SELECT payload FROM records WHERE kind=? ORDER BY id", (kind,))]
    def _event(self, event_type: str, payload: dict[str, Any], frame_id: str | None = None,
               lane_id: str | None = None, event_id: str | None = None) -> tuple[str, int]:
        event_id = event_id or f"evt_{self.db.execute('SELECT COUNT(*) FROM events').fetchone()[0]+1}"
        require_id(event_id, "event_id")
        cur = self.db.execute("INSERT INTO events(event_id,event_type,frame_id,lane_id,payload,origin) VALUES (?,?,?,?,?,?)",
            (event_id, event_type, frame_id, lane_id, canonical_json(payload), "FIXTURE"))
        seq = int(cur.lastrowid); self.db.execute("INSERT INTO outbox(commit_seq,event_id) VALUES (?,?)", (seq,event_id))
        return event_id, seq

    def advance_fixture_clock(self, milliseconds: int) -> None:
        require_uint(milliseconds, "milliseconds"); self.fixture_now_ms += milliseconds
        with self.transaction(): self._set_meta("fixture_now_ms", str(self.fixture_now_ms))

    def publish_frame(self, frame_id: str = "frame_k0", width: int = 320, height: int = 180) -> dict[str, Any]:
        require_id(frame_id, "frame_id"); require_uint(width,"width"); require_uint(height,"height")
        if not (1 <= width <= self.profile.max_width and 1 <= height <= self.profile.max_height): raise ValueError("frame_dimensions")
        if self.db.execute("SELECT COUNT(*) FROM records WHERE kind='frame'").fetchone()[0] >= self.profile.max_keyframes: raise ValueError("keyframe_capacity")
        svg=(f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}"><rect width="100%" height="100%" fill="#071b2d"/><rect x="20" y="80" width="110" height="65" fill="#168aad"/><circle cx="235" cy="67" r="30" fill="#52b788"/><path d="M190 150 L235 88 L280 150Z" fill="#f4a261"/></svg>').encode()
        artifact=self.artifacts.register(f"art_{frame_id}",f"{frame_id}/keyframe.svg",svg,"image/svg+xml",int(self._meta("expires_at")))
        with self.transaction():
            self._record("artifact",artifact["artifact_id"],artifact)
            frame={"schema_version":SCHEMA_VERSION,"frame_id":frame_id,"run_id":self.run_id,"generation":0,
                "asset_id":"fixture_asset","asset_digest":artifact["content_digest"],"pixel_digest":artifact["content_digest"],
                "width":width,"height":height,"requested_time":"0","pts":"0","time_base_num":1,"time_base_den":1000,
                "sample_id":"fixture_k0","frame_artifact_ref":artifact["artifact_id"],"transform_ref":"identity","media_origin":"FIXTURE"}
            ref=self._record("frame",frame_id,frame); _,seq=self._event("KeyframePublished",{"frame_ref":ref},frame_id)
            self.db.execute("INSERT INTO selection_state VALUES (?,?,?,?,?,?,?,?,?,0)",(frame_id,0,0,None,None,None,None,seq,"OPEN")); self._snapshot(frame_id,seq)
        return frame

    def publish_candidate(self, frame_id: str, lane_id: str, *, mask_count: int = 1,
                          ordinal: int | None = None, empty: bool = False) -> dict[str, Any]:
        if lane_id not in LANES: raise ValueError("unknown_lane")
        require_uint(mask_count,"mask_count")
        if mask_count > self.profile.max_masks: raise ValueError("mask_capacity")
        row=self.db.execute("SELECT payload FROM records WHERE kind='frame' AND id=?",(frame_id,)).fetchone()
        if not row: raise ValueError("unknown_frame")
        frame=json.loads(row[0]); mask_count=0 if empty else mask_count
        color={"S":"#00d084","A":"#00a8ff","B":"#b65cff","C":"#f6bd60"}[lane_id]
        overlay="" if mask_count==0 else f'<path d="M35 150 L150 35 L285 150Z" fill="{color}" fill-opacity=".55"/>'
        svg=(f'<svg xmlns="http://www.w3.org/2000/svg" width="{frame["width"]}" height="{frame["height"]}" viewBox="0 0 {frame["width"]} {frame["height"]}"><rect width="100%" height="100%" fill="#071b2d"/><rect x="20" y="80" width="110" height="65" fill="#168aad"/><circle cx="235" cy="67" r="30" fill="#52b788"/><path d="M190 150 L235 88 L280 150Z" fill="#f4a261"/>{overlay}<text x="12" y="24" fill="white">FIXTURE {lane_id}</text></svg>').encode()
        aid=f"art_mask_{frame_id}_{lane_id.lower()}"; artifact=self.artifacts.register(aid,f"{frame_id}/{lane_id.lower()}-overlay.svg",svg,"image/svg+xml",int(self._meta("expires_at")))
        masks=[] if mask_count==0 else [{"mask_id":f"mask_{i}","binary_artifact_ref":aid,"bbox_xyxy":["0","0",str(frame["width"]),str(frame["height"])],"predicted_label":None,"label_schema_ref":None,"upstream_score":{"status":"NOT_REQUESTED","value":None}} for i in range(mask_count)]
        mid=f"masks_{frame_id}_{lane_id.lower()}"; collection={"schema_version":SCHEMA_VERSION,"mask_collection_id":mid,
            "frame_ref":frame_id,"output_kind":"MASK_COLLECTION","width":frame["width"],"height":frame["height"],"masks":masks,
            "background_policy":"NONE","source_transform_ref":"identity","pixel_digest":frame["pixel_digest"]}
        cid=f"cand_{frame_id}_{lane_id.lower()}"; candidate={"schema_version":SCHEMA_VERSION,"candidate_id":cid,"run_id":self.run_id,
            "generation":0,"frame_ref":frame_id,"lane_id":lane_id,"job_id":f"job_seg_{frame_id}_{lane_id.lower()}",
            "ordinal":LANES.index(lane_id) if ordinal is None else require_uint(ordinal,"ordinal"),"origin":"FIXTURE",
            "output_status":"SUCCEEDED_EMPTY" if empty else "SUCCEEDED_NONEMPTY","mask_count":mask_count,"mask_collection_ref":mid,
            "display_artifact_ref":aid,"raw_artifact_ref":None,"transform_ref":"identity","architecture_provenance":"fixture_segmenter_v1",
            "completed_at":str(self.fixture_now_ms),"content_digest":content_digest(collection)}
        with self.transaction():
            self._record("artifact",aid,artifact); self._record("mask_collection",mid,collection); ref=self._record("candidate",cid,candidate)
            _,seq=self._event("CandidatePublished",{"candidate_ref":ref},frame_id,lane_id); self._snapshot(frame_id,seq)
        return candidate

    def create_job(self, job_id: str, frame_id: str, lane_id: str | None, stage: str,
                   unit: str, *, status: str = "WAITING_DEPENDENCY") -> None:
        require_id(job_id,"job_id")
        if stage not in {"SEGMENTATION","MEASUREMENT","EVALUATION","SELECTION","ARTIFACT_WRITE"}: raise ValueError("unknown_stage")
        if status not in {"WAITING_DEPENDENCY","QUEUED"}: raise ValueError("invalid_initial_job_status")
        with self.transaction():
            queued=self.db.execute("SELECT COUNT(*) FROM jobs WHERE status='QUEUED' AND unit=?",(unit,)).fetchone()[0]
            accepted=not(status=="QUEUED" and queued>=self.profile.queue_capacity)
            actual=status if accepted else "FAILED"; error=None if accepted else "NOT_ACCEPTED_CAPACITY"
            _,seq=self._event("JobQueued" if accepted and status=="QUEUED" else ("JobWaitingDependency" if accepted else "JobRejected"),{"job_id":job_id,"stage":stage,"unit":unit,"error_code":error},frame_id,lane_id)
            self.db.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",(job_id,frame_id,lane_id,stage,unit,actual,None,
                self.fixture_now_ms if actual=="QUEUED" else None,None,self.fixture_now_ms if not accepted else None,error,1 if accepted else 0)); self._snapshot(frame_id,seq)

    def queue_job(self, job_id: str) -> None:
        with self.transaction():
            row=self.db.execute("SELECT * FROM jobs WHERE job_id=?",(job_id,)).fetchone()
            if not row or row["status"]!="WAITING_DEPENDENCY": raise ValueError("job_not_waiting_dependency")
            if self.db.execute("SELECT COUNT(*) FROM jobs WHERE status='QUEUED' AND unit=?",(row["unit"],)).fetchone()[0]>=self.profile.queue_capacity: raise ValueError("queue_capacity")
            _,seq=self._event("JobQueued",{"job_id":job_id},row["frame_id"],row["lane_id"]); self.db.execute("UPDATE jobs SET status='QUEUED',queued_ms=? WHERE job_id=?",(self.fixture_now_ms,job_id)); self._snapshot(row["frame_id"],seq)

    def start_job(self, job_id: str, phase: str = "fixture_callback") -> None:
        with self.transaction():
            row=self.db.execute("SELECT * FROM jobs WHERE job_id=?",(job_id,)).fetchone()
            if not row or row["status"]!="QUEUED": raise ValueError("job_not_queued")
            if row["unit"]=="EVALUATION_SUITE" and self.db.execute("SELECT COUNT(*) FROM jobs WHERE status='RUNNING' AND unit=?",(row["unit"],)).fetchone()[0]>=self.profile.evaluator_concurrency: raise ValueError("concurrency_limit")
            _,seq=self._event("JobStarted",{"job_id":job_id,"phase":phase},row["frame_id"],row["lane_id"]); self.db.execute("UPDATE jobs SET status='RUNNING',phase=?,started_ms=? WHERE job_id=?",(phase,self.fixture_now_ms,job_id)); self._snapshot(row["frame_id"],seq)

    def finish_job(self, job_id: str, status: str = "SUCCEEDED", error_code: str | None = None) -> None:
        if status not in {"SUCCEEDED","FAILED","CANCELLED","EXPIRED"}: raise ValueError("invalid_terminal_job_status")
        with self.transaction():
            row=self.db.execute("SELECT * FROM jobs WHERE job_id=?",(job_id,)).fetchone()
            if not row or row["status"]!="RUNNING": raise ValueError("job_not_running")
            _,seq=self._event("JobFinished",{"job_id":job_id,"status":status,"error_code":error_code},row["frame_id"],row["lane_id"]); self.db.execute("UPDATE jobs SET status=?,finished_ms=?,error_code=? WHERE job_id=?",(status,self.fixture_now_ms,error_code,job_id)); self._snapshot(row["frame_id"],seq)

    def publish_measurement(self, frame_id: str, lane_id: str, measurement_id: str,
                            *, kind: str = "INITIAL", value: str = "1") -> dict[str, Any]:
        if kind not in {"INITIAL","SUPPLEMENTARY","CORRECTION"}: raise ValueError("measurement_kind")
        payload={"schema_version":SCHEMA_VERSION,"measurement_id":measurement_id,"candidate_ref":f"cand_{frame_id}_{lane_id.lower()}",
            "profile_ref":"fixture_measurement_v1","kind":kind,"values":[{"metric_id":"fixture_metric","status":"VALID","value":normalize_decimal(value),"unit":"fixture"}],
            "measurement_origin":"FIXTURE_DECLARED","completed_at":str(self.fixture_now_ms)}
        with self.transaction(): ref=self._record("measurement",measurement_id,payload); _,seq=self._event("MeasurementsCommitted",{"measurement_ref":ref,"kind":kind},frame_id,lane_id); self._snapshot(frame_id,seq)
        return payload

    def publish_evidence(self, frame_id: str, version: int, *, measurement_refs: list[str] | None = None,
                         reevaluate_candidates: list[str] | None = None) -> dict[str, Any]:
        require_uint(version,"evidence_version")
        if version>=self.profile.max_evidence_versions: raise ValueError("evidence_version_capacity")
        refs=sorted(measurement_refs or []); targets=sorted(reevaluate_candidates or [])
        with self.transaction():
            state=self.db.execute("SELECT * FROM selection_state WHERE frame_id=?",(frame_id,)).fetchone()
            if not state or version!=state["evidence_version"]+1: raise ValueError("evidence_not_next")
            if any(not self.db.execute("SELECT 1 FROM records WHERE kind='measurement' AND id=?",(x,)).fetchone() for x in refs): raise ValueError("unknown_measurement")
            if any(not self.db.execute("SELECT 1 FROM records WHERE kind='candidate' AND id=?",(x,)).fetchone() for x in targets): raise ValueError("unknown_reevaluation_candidate")
            eid=f"evidence_{frame_id}_e{version}"; payload={"schema_version":SCHEMA_VERSION,"evidence_id":eid,"version":version,
                "frame_ref":frame_id,"task_ref":"fixture_task_v1","shared_base_refs":[],"supplementary_measurement_refs":refs,
                "comparison_set_refs":targets,"dependencies":refs,"previous_ref":f"evidence_{frame_id}_e{state['evidence_version']}","reevaluation_targets":targets}
            ref=self._record("evidence",eid,payload); _,seq=self._event("EvidencePublished",{"evidence_ref":ref,"previous_version":state["evidence_version"],"reevaluation_targets":targets,"coalesce_ms":0},frame_id)
            fallback=state["winner_id"] or state["stale_fallback_id"]; rid=f"rev_{seq}"
            self.db.execute("INSERT INTO revisions VALUES (?,?,?,?,?,?,?,?)",(rid,None,frame_id,state["winner_id"],None,"EVIDENCE_INVALIDATED","OLD_EVIDENCE",seq))
            self.db.execute("UPDATE selection_state SET evidence_version=?,winner_id=NULL,selected_evaluation_id=NULL,display_revision_id=?,stale_fallback_id=?,latest_seq=?,coverage_state='OPEN' WHERE frame_id=?",(version,rid,fallback,seq,frame_id)); self._snapshot(frame_id,seq)
        return payload

    def ensure_evaluation_task(self, frame_id: str, lane_id: str, evidence_version: int) -> str:
        cid=f"cand_{frame_id}_{lane_id.lower()}"; eid=f"eval_{frame_id}_{lane_id.lower()}_e{evidence_version}"
        with self.transaction():
            if self.db.execute("SELECT 1 FROM eval_tasks WHERE evaluation_id=?",(eid,)).fetchone(): return eid
            if self.db.execute("SELECT COUNT(*) FROM eval_tasks").fetchone()[0]>=self.profile.max_evaluation_suites: raise ValueError("evaluation_capacity")
            if not self.db.execute("SELECT 1 FROM records WHERE kind='candidate' AND id=?",(cid,)).fetchone(): raise ValueError("unknown_candidate")
            context=f"ctx_{frame_id}_e{evidence_version}"; digest=content_digest({"candidate":cid,"context":context,"rubric":"fixture_rubric_v1"})
            self.db.execute("INSERT INTO eval_tasks VALUES (?,?,?,?,?,?,?,?)",(eid,frame_id,lane_id,cid,evidence_version,context,"QUEUED",digest)); _,seq=self._event("EvaluationQueued",{"evaluation_id":eid,"context_id":context},frame_id,lane_id); self._snapshot(frame_id,seq)
        return eid

    def submit_attempt(self, evaluation_id: str, values: dict[str, object], *, attempt_id: str, event_id: str,
                       returned_binding: str = "fixture_evaluator_v1", rubric: str = "fixture_rubric_v1",
                       question_set: str = "fixture_questions_v1", raw: bytes = b"fixture") -> dict[str, Any]:
        if not isinstance(values,dict) or not values or set(values)-set(AXES): raise ValueError("invalid_axis_object")
        require_id(attempt_id,"attempt_id"); require_id(event_id,"event_id")
        if not isinstance(raw,bytes): raise ValueError("raw_bytes_required")
        task=self.db.execute("SELECT * FROM eval_tasks WHERE evaluation_id=?",(evaluation_id,)).fetchone()
        if not task: raise ValueError("unknown_evaluation")
        envelope=returned_binding=="fixture_evaluator_v1" and rubric=="fixture_rubric_v1" and question_set=="fixture_questions_v1"
        checked={}; errors={}
        if envelope:
            for axis,value in values.items():
                try: checked[axis]=axis_result(value,axis)
                except ValueError as exc: errors[axis]=str(exc)
        with self.transaction():
            if self.db.execute("SELECT 1 FROM eval_attempts WHERE attempt_id=? OR event_id=?",(attempt_id,event_id)).fetchone(): return {"duplicate":True,"evaluation_id":evaluation_id}
            state=self.db.execute("SELECT * FROM selection_state WHERE frame_id=?",(task["frame_id"],)).fetchone()
            if self._meta("run_status") not in {"RUNNING","DRAINING"} or state["cancelled"]: raise ValueError("run_or_generation_closed")
            _,seq=self._event("EvaluationAttemptFinished",{"evaluation_id":evaluation_id,"attempt_id":attempt_id,"envelope_status":"VALID" if envelope else "INVALID","axis_errors":errors},task["frame_id"],task["lane_id"],event_id)
            idx=self.db.execute("SELECT COUNT(*) FROM eval_attempts WHERE evaluation_id=?",(evaluation_id,)).fetchone()[0]
            self.db.execute("INSERT INTO eval_attempts VALUES (?,?,?,?,?,?,?,?)",(attempt_id,evaluation_id,idx,"VALID" if envelope else "INVALID",raw,sha256(raw).hexdigest(),event_id,seq))
            if not envelope:
                self.db.execute("UPDATE eval_tasks SET status='INVALID' WHERE evaluation_id=?",(evaluation_id,)); self._snapshot(task["frame_id"],seq)
                return {"evaluation_id":evaluation_id,"accepted_axes":[],"envelope_status":"INVALID","commit_seq":seq}
            accepted=[]
            for axis,result in checked.items():
                if result["status"]=="VALID" and not self.db.execute("SELECT 1 FROM axis_results WHERE evaluation_id=? AND axis_id=?",(evaluation_id,axis)).fetchone():
                    self.db.execute("INSERT INTO axis_results VALUES (?,?,?,?,?)",(evaluation_id,axis,attempt_id,canonical_json(result),seq)); accepted.append(axis)
            count=self.db.execute("SELECT COUNT(*) FROM axis_results WHERE evaluation_id=?",(evaluation_id,)).fetchone()[0]
            self.db.execute("UPDATE eval_tasks SET status=? WHERE evaluation_id=?",("COMPLETE" if count==5 else "PARTIAL_DIAGNOSTICS",evaluation_id))
            decision=self._select(task,seq) if "Q" in accepted else None; self._snapshot(task["frame_id"],seq)
            return {"evaluation_id":evaluation_id,"accepted_axes":accepted,"axis_errors":errors,"envelope_status":"VALID","commit_seq":seq,"decision":decision}

    def accept_evaluation(self, frame_id: str, lane_id: str, evidence_version: int, scores: dict[str,object], *, event_id: str,
                          returned_binding: str="fixture_evaluator_v1", rubric: str="fixture_rubric_v1", question: str="fixture_questions_v1",
                          raw: bytes=b"fixture", candidate_id: str|None=None) -> dict[str,Any]:
        expected=f"cand_{frame_id}_{lane_id.lower()}"
        if candidate_id is not None and candidate_id!=expected: raise ValueError("candidate_scope_mismatch")
        eid=self.ensure_evaluation_task(frame_id,lane_id,evidence_version)
        result=self.submit_attempt(eid,scores,attempt_id=f"attempt_{event_id}",event_id=event_id,returned_binding=returned_binding,rubric=rubric,question_set=question,raw=raw)
        return result.get("decision") or result

    def _axis(self,eid:str,axis:str)->dict[str,Any]|None:
        row=self.db.execute("SELECT payload FROM axis_results WHERE evaluation_id=? AND axis_id=?",(eid,axis)).fetchone(); return json.loads(row[0]) if row else None
    def _available(self,cid:str)->bool:
        row=self.db.execute("SELECT payload FROM records WHERE kind='candidate' AND id=?",(cid,)).fetchone()
        if not row:return False
        candidate=json.loads(row[0]); collection=self.db.execute("SELECT payload FROM records WHERE kind='mask_collection' AND id=?",(candidate["mask_collection_ref"],)).fetchone(); frame_row=self.db.execute("SELECT payload FROM records WHERE kind='frame' AND id=?",(candidate["frame_ref"],)).fetchone()
        if not collection or not frame_row:return False
        masks=json.loads(collection[0]);frame=json.loads(frame_row[0])
        if len(masks["masks"])!=candidate["mask_count"] or masks["width"]!=frame["width"] or masks["height"]!=frame["height"] or masks["pixel_digest"]!=frame["pixel_digest"]:return False
        for mask in masks["masks"]:
            try:
                x0,y0,x1,y1=(Decimal(x) for x in mask["bbox_xyxy"])
                if not (0<=x0<=x1<=frame["width"] and 0<=y0<=y1<=frame["height"]):return False
                self.artifacts.resolve(mask["binary_artifact_ref"],self.retention_now)
            except (KeyError,ValueError,FileNotFoundError,InvalidOperation):return False
        try:self.artifacts.resolve(candidate["display_artifact_ref"],self.retention_now)
        except (ValueError,FileNotFoundError):return False
        return True

    def _select(self,task:sqlite3.Row,seq:int)->dict[str,Any]:
        state=self.db.execute("SELECT * FROM selection_state WHERE frame_id=?",(task["frame_id"],)).fetchone(); q=self._axis(task["evaluation_id"],"Q"); previous=state["winner_id"]; winner=previous; pq=None; kind=None
        if task["evidence_version"]!=state["evidence_version"]:reason="OLD_EVIDENCE"
        elif not self._available(task["candidate_id"]):reason="ARTIFACT_UNAVAILABLE"
        elif Decimal(q["score_decimal"])<THRESHOLD:reason="BELOW_Q_THRESHOLD"
        elif previous is None:
            winner=task["candidate_id"]
            if state["stale_fallback_id"]==winner:reason="REFRESHED_SAME_CANDIDATE";kind="REFRESH_SAME"
            else:reason="FIRST_ELIGIBLE" if task["evidence_version"]==0 else "FIRST_ELIGIBLE_IN_NEW_EVIDENCE";kind="SELECT"
        else:
            pq=self._axis(state["selected_evaluation_id"],"Q")["score_decimal"]
            if Decimal(q["score_decimal"])>Decimal(pq):winner=task["candidate_id"];reason="HIGHER_Q";kind="REFRESH_SAME" if previous==winner else "REPLACE"
            elif Decimal(q["score_decimal"])==Decimal(pq):reason="TIE_KEEP_CURRENT"
            else:reason="LOWER_Q"
        delta=None if pq is None else decimal_delta(q["score_decimal"],pq); did=f"dec_{seq}"
        self.db.execute("INSERT INTO decisions VALUES (?,?,?,?,?,?,?,?,?,?,?)",(did,task["evaluation_id"],task["frame_id"],task["evidence_version"],previous,winner,reason,q["score_decimal"],pq,delta,seq)); rid=None
        if kind:
            rid=f"rev_{seq}"; self.db.execute("INSERT INTO revisions VALUES (?,?,?,?,?,?,?,?)",(rid,did,task["frame_id"],previous,winner,kind,reason,seq)); self.db.execute("UPDATE selection_state SET winner_id=?,selected_evaluation_id=?,display_revision_id=?,stale_fallback_id=NULL,latest_seq=? WHERE frame_id=?",(winner,task["evaluation_id"],rid,seq,task["frame_id"]))
        else:self.db.execute("UPDATE selection_state SET latest_seq=? WHERE frame_id=?",(seq,task["frame_id"]))
        return {"decision_id":did,"evaluation_id":task["evaluation_id"],"reason_code":reason,"winner_after_id":winner,"delta_to_previous":delta,"revision_id":rid,"commit_seq":seq}

    def cancel_generation(self,frame_id:str)->None:
        with self.transaction():
            state=self.db.execute("SELECT * FROM selection_state WHERE frame_id=?",(frame_id,)).fetchone()
            if not state:raise ValueError("unknown_frame")
            _,seq=self._event("GenerationCancelled",{"generation":state["generation"]},frame_id); self.db.execute("UPDATE selection_state SET cancelled=1,coverage_state='TERMINAL_PARTIAL',latest_seq=? WHERE frame_id=?",(seq,frame_id)); self.db.execute("UPDATE jobs SET status='CANCELLED',finished_ms=? WHERE frame_id=? AND status IN ('WAITING_DEPENDENCY','QUEUED','RUNNING')",(self.fixture_now_ms,frame_id)); self._snapshot(frame_id,seq)

    def rebuild_tie(self,frame_id:str)->str|None:
        with self._lock:
            state=self.db.execute("SELECT * FROM selection_state WHERE frame_id=?",(frame_id,)).fetchone(); rows=self.db.execute("SELECT t.*,r.payload candidate FROM eval_tasks t JOIN records r ON r.kind='candidate' AND r.id=t.candidate_id WHERE t.frame_id=? AND t.evidence_version=?",(frame_id,state["evidence_version"])).fetchall(); eligible=[]
            for row in rows:
                q=self._axis(row["evaluation_id"],"Q");cp=json.loads(row["candidate"])
                if q and Decimal(q["score_decimal"])>=THRESHOLD and self._available(row["candidate_id"]):eligible.append((-Decimal(q["score_decimal"]),cp["content_digest"],cp["ordinal"],row["candidate_id"]))
            return sorted(eligible)[0][3] if eligible else None

    def finalize(self,frame_id:str)->None:
        with self.transaction():
            state=self.db.execute("SELECT * FROM selection_state WHERE frame_id=?",(frame_id,)).fetchone(); jobs=self.db.execute("SELECT status FROM jobs WHERE frame_id=?",(frame_id,)).fetchall(); tasks=self.db.execute("SELECT status FROM eval_tasks WHERE frame_id=? AND evidence_version=?",(frame_id,state["evidence_version"])).fetchall()
            candidate_count=self.db.execute("SELECT COUNT(*) FROM records WHERE kind='candidate' AND json_extract(payload,'$.frame_ref')=?",(frame_id,)).fetchone()[0]
            partial=(state["cancelled"] or len(tasks)!=candidate_count or any(r[0]!="SUCCEEDED" for r in jobs)
                     or any(r[0]!="COMPLETE" for r in tasks));coverage="TERMINAL_PARTIAL" if partial else "COMPLETE";_,seq=self._event("CoverageFinalized",{"coverage_state":coverage,"candidate_count":candidate_count,"evaluation_count":len(tasks)},frame_id)
            if state["winner_id"] is None and state["stale_fallback_id"] is not None:
                rid=f"rev_{seq}";self.db.execute("INSERT INTO revisions VALUES (?,?,?,?,?,?,?,?)",(rid,None,frame_id,state["stale_fallback_id"],None,"CLEAR","NO_ELIGIBLE_RESULT",seq));self.db.execute("UPDATE selection_state SET display_revision_id=?,stale_fallback_id=NULL,latest_seq=?,coverage_state=? WHERE frame_id=?",(rid,seq,coverage,frame_id))
            else:self.db.execute("UPDATE selection_state SET latest_seq=?,coverage_state=? WHERE frame_id=?",(seq,coverage,frame_id))
            self._snapshot(frame_id,seq)

    def queue_snapshot(self,frame_id:str,unit:str="EVALUATION_SUITE")->dict[str,Any]:
        rows=self.db.execute("SELECT * FROM jobs WHERE frame_id=? AND unit=?",(frame_id,unit)).fetchall();count=lambda s:sum(r["status"]==s for r in rows);queued=count("QUEUED");active=count("RUNNING");qrows=[r for r in rows if r["status"]=="QUEUED"];arows=[r for r in rows if r["status"]=="RUNNING"];oldest=None if not qrows else self.fixture_now_ms-min(r["queued_ms"] for r in qrows);longest=None if not arows else self.fixture_now_ms-min(r["started_ms"] for r in arows);rejected=sum(not r["accepted"] for r in rows);congestion="NORMAL" if queued==0 else "ATTENTION"
        if queued and (queued/self.profile.queue_capacity>=.75 or (oldest or 0)>=5000):congestion="CONGESTED"
        if queued>=self.profile.queue_capacity:congestion="SATURATED"
        return {"queue_id":"fixture_eval","run_id":self.run_id,"frame_id":frame_id,"generation":0,"stage":"EVALUATION","lane_id":None,"unit":unit,"scope_kind":"FRAME","capacity":self.profile.queue_capacity,"concurrency_limit":self.profile.evaluator_concurrency,"not_ready":count("WAITING_DEPENDENCY"),"queued":queued,"active":active,"retry_delayed":count("RETRY_DELAY"),"succeeded_total":count("SUCCEEDED"),"failed_total":count("FAILED"),"cancelled_total":count("CANCELLED"),"expired_total":count("EXPIRED"),"rejected_total":rejected,"active_waiting_reason_counts":{},"oldest_queued_ms":oldest,"longest_active_ms":longest,"last_sampled_at":self.fixture_now_ms,"health":"OK","congestion":congestion,"threshold_profile_ref":"queue_visual_fixture_v1","accepted_total":sum(r["accepted"] for r in rows)}

    def _flow_pulses(self,frame_id:str)->list[dict[str,Any]]:
        """Bounded, event-bound visual transitions; never a synthetic running indicator."""
        edges={"CandidatePublished":("K_BRANCH","LANE_MASK"),
               "JobStarted":("EVALUATION_QUEUE","FIXTURE_EVALUATOR"),
               "MeasurementsCommitted":("LANE_MASK","COMMON_MEASUREMENT"),
               "EvaluationAttemptFinished":("FIXTURE_EVALUATOR","SELECTION")}
        rows=self.db.execute("SELECT event_id,event_type,lane_id FROM events WHERE frame_id=? AND lane_id IS NOT NULL AND event_type IN ('CandidatePublished','JobStarted','MeasurementsCommitted','EvaluationAttemptFinished') ORDER BY commit_seq DESC LIMIT 32",(frame_id,)).fetchall()
        return [{"pulse_id":f"pulse_{r['event_id']}","event_id":r["event_id"],
                 "edge_id":f"{r['lane_id']}_{r['event_type']}","source_node":edges[r["event_type"]][0],
                 "target_node":edges[r["event_type"]][1],"run_id":self.run_id,"frame_id":frame_id,
                 "candidate_id":f"cand_{frame_id}_{r['lane_id'].lower()}","lane_id":r["lane_id"],
                 "phase":r["event_type"],"duration_ms":500,"origin":"FIXTURE"}
                for r in reversed(rows)]

    def _build_view(self,frame_id:str,preview_candidate:str|None=None)->dict[str,Any]:
        state=self.db.execute("SELECT * FROM selection_state WHERE frame_id=?",(frame_id,)).fetchone();frow=self.db.execute("SELECT payload FROM records WHERE kind='frame' AND id=?",(frame_id,)).fetchone()
        if not state or not frow:raise ValueError("unknown_frame")
        frame=json.loads(frow[0]);candidates={r["lane_id"]:r for r in self._records("candidate") if r["frame_ref"]==frame_id}
        if preview_candidate is not None and not any(r["candidate_id"]==preview_candidate for r in candidates.values()):raise ValueError("preview_scope_mismatch")
        ever={r[0] for r in self.db.execute("SELECT to_candidate_id FROM revisions WHERE frame_id=? AND to_candidate_id IS NOT NULL",(frame_id,))};rows=[]
        selected_q=self._axis(state["selected_evaluation_id"],"Q") if state["selected_evaluation_id"] else None
        for lane in LANES:
            c=candidates.get(lane);task=self.db.execute("SELECT * FROM eval_tasks WHERE candidate_id=? AND evidence_version=?",(c["candidate_id"],state["evidence_version"])).fetchone() if c else None;axes={a:axis_result(None,a) for a in AXES}
            if task:
                for a in AXES:axes[a]=self._axis(task["evaluation_id"],a) or axes[a]
            q=axes["Q"] if axes["Q"]["status"]=="VALID" else None;delta=None
            if not c:selection,reason="NOT_READY","AWAITING_SEGMENTATION"
            elif c["candidate_id"]==state["winner_id"]:selection,reason,delta="CURRENT_PROVISIONAL","CURRENT_WINNER","0"
            elif not q:selection,reason="WAITING_EVALUATION","AWAITING_EVALUATION"
            elif Decimal(q["score_decimal"])<THRESHOLD:selection,reason="BELOW_THRESHOLD","BELOW_Q_THRESHOLD"
            elif selected_q:
                delta=decimal_delta(q["score_decimal"],selected_q["score_decimal"]);selection="ELIGIBLE_NOT_SELECTED";reason="TIE_KEEP_CURRENT" if delta=="0" else "LOWER_Q"
            else:selection,reason="ELIGIBLE_NOT_SELECTED","NO_CURRENT_WINNER"
            lane_jobs=self.db.execute("SELECT status FROM jobs WHERE frame_id=? AND lane_id=? AND unit='EVALUATION_SUITE'",(frame_id,lane)).fetchall()
            lane_queue={"stage":"EVALUATION","lane_id":lane,"unit":"EVALUATION_SUITE","queued":sum(j[0]=="QUEUED" for j in lane_jobs),"active":sum(j[0]=="RUNNING" for j in lane_jobs)}
            rows.append({"lane_id":lane,"architecture_label":f"Fixture lane {lane}","candidate_id":c["candidate_id"] if c else None,"generation_status":c["output_status"] if c else "NOT_STARTED","evaluation_status":task["status"] if task else "NOT_READY","selection_status":selection,"axis_results":axes,"current_q_delta":delta,"current_reason_code":reason,"ever_selected":bool(c and c["candidate_id"] in ever),"thumbnail_ref":c["display_artifact_ref"] if c else None,"mask_count":c["mask_count"] if c else None,"evidence_version":state["evidence_version"],"source_origin":"FIXTURE","queue":lane_queue})
        revisions=[dict(r) for r in self.db.execute("SELECT * FROM revisions WHERE frame_id=? ORDER BY commit_seq",(frame_id,))];decisions=[dict(r) for r in self.db.execute("SELECT * FROM decisions WHERE frame_id=? ORDER BY commit_seq",(frame_id,))];rendered=preview_candidate or state["winner_id"] or state["stale_fallback_id"];mode="MANUAL_CANDIDATE" if preview_candidate else "FOLLOW_SELECTION";rseq=None
        if state["display_revision_id"]:rseq=self.db.execute("SELECT commit_seq FROM revisions WHERE revision_id=?",(state["display_revision_id"],)).fetchone()[0]
        return {"view_id":f"view_{frame_id}","schema_version":SCHEMA_VERSION,"run_id":self.run_id,"run_status":self._meta("run_status"),"frame_id":frame_id,"generation":state["generation"],"current_comparison_ref":f"ctx_{frame_id}_e{state['evidence_version']}","evidence_version":state["evidence_version"],"snapshot_seq":state["latest_seq"],"delivery_mode":"ORIGINAL","rows":rows,"selection":{"winner_id":state["winner_id"],"stale_fallback_id":state["stale_fallback_id"],"display_revision_id":state["display_revision_id"],"display_revision_seq":rseq,"status":"STALE_EVIDENCE_PROVISIONAL" if state["winner_id"] is None and state["stale_fallback_id"] else ("CURRENT_PROVISIONAL" if state["winner_id"] else "NO_SELECTION")},"preview":{"display_mode":mode,"rendered_candidate_id":rendered,"manual_candidate_id":preview_candidate,"keyframe_artifact_ref":frame["frame_artifact_ref"]},"timeline_page":{"decisions":decisions,"revisions":revisions},"queues":[self.queue_snapshot(frame_id)],"flow_pulses":self._flow_pulses(frame_id),"coverage_state":state["coverage_state"],"unavailable_refs":[],"fixture":True,"network_calls":int(self._meta("network_calls"))}

    def view(self,frame_id:str,*,preview_candidate:str|None=None)->dict[str,Any]:
        with self._lock:
            if self.closed:raise ValueError("store_closed")
            return self._build_view(frame_id,preview_candidate)
    def _snapshot(self,frame_id:str,seq:int)->None:
        self.db.execute("UPDATE selection_state SET latest_seq=MAX(latest_seq,?) WHERE frame_id=?",(seq,frame_id))
        self.db.execute("INSERT OR REPLACE INTO view_history VALUES (?,?,?)",(frame_id,seq,canonical_json(self._build_view(frame_id))))
    def _snapshot_all(self,seq:int)->None:
        for row in self.db.execute("SELECT frame_id FROM selection_state"):self._snapshot(row[0],seq)

    def event_page(self,after:int=0,limit:int=200,until:int|None=None)->dict[str,Any]:
        require_uint(after,"after");require_uint(limit,"limit")
        if not 1<=limit<=200:raise ValueError("invalid_page_limit")
        if until is not None:require_uint(until,"until")
        with self._lock:
            ceiling=until if until is not None else self.db.execute("SELECT COALESCE(MAX(commit_seq),0) FROM events").fetchone()[0];rows=self.db.execute("SELECT * FROM events WHERE commit_seq>? AND commit_seq<=? ORDER BY commit_seq LIMIT ?",(after,ceiling,limit+1)).fetchall();more=len(rows)>limit;rows=rows[:limit]
            return {"events":[{**dict(r),"payload":json.loads(r["payload"])} for r in rows],"after":after,"until":ceiling,"next_after":rows[-1]["commit_seq"] if more and rows else None,"complete":not more}

    def replay(self,frame_id:str,cursor:int|None=None)->dict[str,Any]:
        with self._lock:
            latest=self.db.execute("SELECT COALESCE(MAX(commit_seq),0) FROM events").fetchone()[0];cursor=latest if cursor is None else require_uint(cursor,"cursor");row=self.db.execute("SELECT payload,commit_seq FROM view_history WHERE frame_id=? AND commit_seq<=? ORDER BY commit_seq DESC LIMIT 1",(frame_id,cursor)).fetchone()
            if not row:raise ValueError("cursor_before_frame")
            events=[];after=0
            while True:
                page=self.event_page(after,200,cursor);events.extend(page["events"])
                if page["complete"]:break
                after=page["next_after"]
            view=json.loads(row["payload"]);view["delivery_mode"]="RECORDED_REPLAY";view["snapshot_seq"]=row["commit_seq"]
            return {"delivery_mode":"RECORDED_REPLAY","cursor":cursor,"events":events,"view":view,"network_calls":0,"automatic_retries":0,"order":"commit_seq","clock":"fixture_cursor_frozen"}

    def receipt(self,value:object)->bool:
        if not isinstance(value,dict):raise ValueError("receipt_object_required")
        expected={"receipt_id","view_session_id","source_revision_id","source_commit_seq","run_id","frame_id","generation","display_mode","rendered_candidate_id","visible","skipped_revision_ids"}
        if set(value)!=expected:raise ValueError("receipt_fields")
        require_id(value["receipt_id"],"receipt_id");require_id(value["view_session_id"],"view_session_id");require_id(value["source_revision_id"],"source_revision_id");require_uint(value["source_commit_seq"],"source_commit_seq");require_uint(value["generation"],"generation")
        if value["run_id"]!=self.run_id:raise ValueError("receipt_run_mismatch")
        if type(value["visible"]) is not bool:raise ValueError("receipt_visible_type")
        if value["display_mode"] not in {"FOLLOW_SELECTION","MANUAL_CANDIDATE","HISTORICAL_REPLAY"}:raise ValueError("receipt_display_mode")
        if not isinstance(value["skipped_revision_ids"],list) or any(not isinstance(x,str) for x in value["skipped_revision_ids"]):raise ValueError("receipt_skipped_type")
        with self.transaction():
            state=self.db.execute("SELECT * FROM selection_state WHERE frame_id=?",(value["frame_id"],)).fetchone();revision=self.db.execute("SELECT * FROM revisions WHERE revision_id=? AND frame_id=?",(value["source_revision_id"],value["frame_id"])).fetchone()
            if not state or not revision or state["generation"]!=value["generation"] or revision["commit_seq"]!=value["source_commit_seq"]:raise ValueError("receipt_reference_mismatch")
            candidate=value["rendered_candidate_id"]
            if candidate is not None:
                row=self.db.execute("SELECT payload FROM records WHERE kind='candidate' AND id=?",(candidate,)).fetchone()
                if not row or json.loads(row[0])["frame_ref"]!=value["frame_id"]:raise ValueError("receipt_candidate_scope")
            if value["display_mode"]=="FOLLOW_SELECTION" and candidate not in {revision["to_candidate_id"],state["winner_id"],state["stale_fallback_id"]}:raise ValueError("receipt_render_mismatch")
            classification="PRIMARY_VISIBLE" if value["display_mode"]=="FOLLOW_SELECTION" and value["visible"] else "NON_PRIMARY"
            cur=self.db.execute("INSERT OR IGNORE INTO receipts VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",(value["receipt_id"],value["view_session_id"],value["source_revision_id"],value["source_commit_seq"],value["run_id"],value["frame_id"],value["generation"],value["display_mode"],candidate,1 if value["visible"] else 0,canonical_json(value["skipped_revision_ids"]),classification));return cur.rowcount==1

    def deliver_outbox(self)->list[str]:
        with self.transaction():ids=[r[0] for r in self.db.execute("SELECT event_id FROM outbox WHERE delivered=0 ORDER BY commit_seq")];self.db.execute("UPDATE outbox SET delivered=1");return ids
    def close_run(self)->str:
        with self.transaction():
            frames=self.db.execute("SELECT coverage_state FROM selection_state").fetchall();status="CLOSED_SUCCEEDED" if frames and all(r[0]=="COMPLETE" for r in frames) else "CLOSED_PARTIAL";self._set_meta("run_status",status);_,seq=self._event("RunClosed",{"status":status});self._snapshot_all(seq);return status
    def close(self)->None:
        with self._lock:
            if not self.closed:self.db.close();self.closed=True


DEMO_SCORES={"A":{"Q":"3.2","A":"1.2","R":"1.8","I":"3.5","C":"3.5"},"S":{"Q":"3.6","A":"1.7","R":"2.1","I":"3.5","C":"3.9"},"B":{"Q":"3.4","A":"1.4","R":"1.5","I":"3.6","C":"2.8"}}
def prepare_live_demo(kernel:FixtureKernel)->str:
    frame="frame_k0";kernel.publish_frame(frame)
    for lane in LANES:kernel.publish_candidate(frame,lane,empty=(lane=="C"))
    for lane in ("S","A","B"):
        kernel.ensure_evaluation_task(frame,lane,0);kernel.create_job(f"job_eval_{lane.lower()}_e0",frame,lane,"EVALUATION","EVALUATION_SUITE",status="QUEUED")
    return frame
def release_demo_step(kernel:FixtureKernel)->dict[str,Any]:
    with kernel._lock:
        completed={r[0] for r in kernel.db.execute("SELECT lane_id FROM jobs WHERE status='SUCCEEDED' AND job_id LIKE '%_e0'")};lane=next((x for x in ("A","S","B") if x not in completed),None)
        if lane is None:return {"done":True}
        job=f"job_eval_{lane.lower()}_e0";kernel.start_job(job);decision=kernel.accept_evaluation("frame_k0",lane,0,DEMO_SCORES[lane],event_id=f"evalevent_{lane.lower()}_e0");kernel.finish_job(job);return {"done":lane=="B","lane":lane,"decision":decision}

def publish_demo_evidence(kernel:FixtureKernel)->dict[str,Any]:
    """Publish E1 and leave the former winner visible only as a stale fallback."""
    with kernel._lock:
        state=kernel.db.execute("SELECT evidence_version FROM selection_state WHERE frame_id='frame_k0'").fetchone()
        if state[0]>=1:return {"published":False,"evidence_version":state[0]}
        measurement=kernel.publish_measurement("frame_k0","S","measurement_s_supplementary_e1",kind="SUPPLEMENTARY",value="1.25")
        targets=[f"cand_frame_k0_{lane.lower()}" for lane in ("S","A","B")]
        evidence=kernel.publish_evidence("frame_k0",1,measurement_refs=[measurement["measurement_id"]],reevaluate_candidates=targets)
        for lane in ("S","A","B"):
            kernel.ensure_evaluation_task("frame_k0",lane,1)
            kernel.create_job(f"job_eval_{lane.lower()}_e1","frame_k0",lane,"EVALUATION","EVALUATION_SUITE",status="QUEUED")
        return {"published":True,"evidence_version":evidence["version"]}

def release_demo_evidence_step(kernel:FixtureKernel)->dict[str,Any]:
    """Complete one E1 suite in deterministic S, A, B order."""
    scores={**DEMO_SCORES,"S":{**DEMO_SCORES["S"],"Q":"3.8"}}
    with kernel._lock:
        completed={r[0] for r in kernel.db.execute("SELECT lane_id FROM jobs WHERE status='SUCCEEDED' AND job_id LIKE '%_e1'")}
        lane=next((x for x in ("S","A","B") if x not in completed),None)
        if lane is None:return {"done":True}
        job=f"job_eval_{lane.lower()}_e1";kernel.start_job(job);decision=kernel.accept_evaluation("frame_k0",lane,1,scores[lane],event_id=f"evalevent_{lane.lower()}_e1");kernel.finish_job(job)
        return {"done":lane=="B","lane":lane,"decision":decision}
def build_demo(kernel:FixtureKernel)->str:
    frame=prepare_live_demo(kernel)
    while not release_demo_step(kernel)["done"]:pass
    return frame
