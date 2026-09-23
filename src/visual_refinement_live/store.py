"""SC03–SC07 owned, append-only run store and replay projection."""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sqlite3
import threading
import time
from typing import Any

REPO = Path(__file__).resolve().parents[2]
RUNS_ROOT = REPO / "runs" / "sc03_sc07"
SCHEMA = "vr_live_v1"
MAX_RUN_BYTES = 2 * 1024**3
MAX_TOTAL_BYTES = 2 * 1024**3
ARTIFACT_WRITE_LOCK = threading.RLock()
_ID = re.compile(r"^[A-Za-z0-9_-]{1,96}$")


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


class LiveStore:
    def __init__(self, run_id: str, *, create: bool, source: dict | None = None,
                 experiment: dict | None = None):
        if not _ID.fullmatch(run_id):
            raise ValueError("run_id_invalid")
        base = RUNS_ROOT.resolve()
        root = (base / run_id).resolve()
        if base not in root.parents or root.is_symlink():
            raise ValueError("run_outside_owned_root")
        self.root = root
        self.read_only = not create
        self.lock = threading.RLock()
        if create:
            if root.exists() and any(root.iterdir()):
                raise FileExistsError("run_already_exists")
            root.mkdir(parents=True, exist_ok=True)
            (root / "artifacts").mkdir()
            self.db = sqlite3.connect(root / "state.sqlite3", check_same_thread=False)
            self.db.execute("PRAGMA foreign_keys=ON")
            self.db.executescript("""
                CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE events(seq INTEGER PRIMARY KEY AUTOINCREMENT,kind TEXT NOT NULL,
                    frame_id TEXT, lane_id TEXT, at_ms INTEGER NOT NULL,payload TEXT NOT NULL);
                CREATE TABLE frames(id TEXT PRIMARY KEY,seq INTEGER NOT NULL,data TEXT NOT NULL);
                CREATE TABLE candidates(id TEXT PRIMARY KEY,frame_id TEXT NOT NULL,lane_id TEXT NOT NULL,
                    seq INTEGER NOT NULL,data TEXT NOT NULL);
                CREATE TABLE measurements(id TEXT PRIMARY KEY,frame_id TEXT NOT NULL,
                    candidate_id TEXT,kind TEXT NOT NULL,seq INTEGER NOT NULL,data TEXT NOT NULL);
                CREATE TABLE evidence(id TEXT PRIMARY KEY,frame_id TEXT NOT NULL,version INTEGER NOT NULL,
                    seq INTEGER NOT NULL,data TEXT NOT NULL,UNIQUE(frame_id,version));
                CREATE TABLE evaluations(id TEXT PRIMARY KEY,candidate_id TEXT NOT NULL,frame_id TEXT NOT NULL,
                    evidence_version INTEGER NOT NULL,seq INTEGER NOT NULL,data TEXT NOT NULL,
                    UNIQUE(candidate_id,evidence_version));
                CREATE TABLE eval_tasks(id TEXT PRIMARY KEY,candidate_id TEXT NOT NULL,frame_id TEXT NOT NULL,
                    lane_id TEXT NOT NULL,evidence_version INTEGER NOT NULL,context_id TEXT NOT NULL,
                    input_digest TEXT NOT NULL,status TEXT NOT NULL,seq INTEGER NOT NULL,origin TEXT NOT NULL,UNIQUE(candidate_id,evidence_version));
                CREATE TABLE eval_attempts(id TEXT PRIMARY KEY,task_id TEXT NOT NULL,attempt_index INTEGER NOT NULL,
                    seq INTEGER NOT NULL,raw_artifact_id TEXT,status TEXT NOT NULL,error_code TEXT,
                    usage_tokens INTEGER);
                CREATE TABLE axis_results(task_id TEXT NOT NULL,axis_id TEXT NOT NULL,attempt_id TEXT NOT NULL,
                    seq INTEGER NOT NULL,data TEXT NOT NULL,PRIMARY KEY(task_id,axis_id));
                CREATE TABLE selection_state(frame_id TEXT PRIMARY KEY,evidence_version INTEGER NOT NULL,
                    winner_id TEXT,winner_q TEXT,selected_task_id TEXT,stale_fallback_id TEXT,latest_seq INTEGER NOT NULL);
                CREATE TABLE revisions(id TEXT PRIMARY KEY,frame_id TEXT NOT NULL,seq INTEGER NOT NULL,
                    from_candidate_id TEXT,to_candidate_id TEXT,kind TEXT NOT NULL,reason_code TEXT NOT NULL);
                CREATE TABLE decisions(id TEXT PRIMARY KEY,frame_id TEXT NOT NULL,seq INTEGER NOT NULL,
                    data TEXT NOT NULL);
                CREATE TABLE jobs(id TEXT PRIMARY KEY,frame_id TEXT,lane_id TEXT,stage TEXT NOT NULL,
                    unit TEXT NOT NULL,status TEXT NOT NULL,phase TEXT,queued_ms INTEGER,
                    started_ms INTEGER,finished_ms INTEGER,error_code TEXT);
                CREATE TABLE artifacts(id TEXT PRIMARY KEY,path TEXT UNIQUE NOT NULL,
                    media_type TEXT NOT NULL,size INTEGER NOT NULL,digest TEXT NOT NULL);
                CREATE TABLE receipts(id TEXT PRIMARY KEY,session_id TEXT NOT NULL,frame_id TEXT NOT NULL,
                    candidate_id TEXT NOT NULL,source_seq INTEGER NOT NULL,mode TEXT NOT NULL,
                    at_ms INTEGER NOT NULL,UNIQUE(session_id,candidate_id,source_seq,mode));
            """)
            self._meta("schema", SCHEMA)
            self._meta("lifecycle", "RUNNING")
            self._meta("business", "PENDING")
            self._meta("source", source or {})
            self._meta("experiment", experiment or {})
            self.event("RunCreated", None, None, {"source_id": (source or {}).get("source_id")})
        else:
            if not (root / "state.sqlite3").is_file():
                raise FileNotFoundError("saved_run_missing")
            self.db = sqlite3.connect((root / "state.sqlite3").as_uri() + "?mode=ro",
                                      uri=True, check_same_thread=False)
            if self.get_meta("schema") != SCHEMA:
                raise ValueError("run_schema_mismatch")

    def _meta(self, key: str, value: Any) -> None:
        self.db.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (key, canonical(value)))
        self.db.commit()

    def get_meta(self, key: str) -> Any:
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def _event_uncommitted(self, kind: str, frame_id: str | None, lane_id: str | None,
                           payload: dict) -> int:
        cursor = self.db.execute("INSERT INTO events(kind,frame_id,lane_id,at_ms,payload) VALUES(?,?,?,?,?)",
                                 (kind, frame_id, lane_id, int(time.time() * 1000), canonical(payload)))
        return int(cursor.lastrowid)

    def event(self, kind: str, frame_id: str | None, lane_id: str | None, payload: dict) -> int:
        with self.lock:
            if self.read_only:
                raise ValueError("saved_run_read_only")
            with self.db:
                return self._event_uncommitted(kind, frame_id, lane_id, payload)

    def _record(self, table: str, ident: str, frame_id: str, lane_id: str | None,
                kind: str, data: dict, *, candidate_id: str | None = None,
                version: int | None = None) -> int:
        if not _ID.fullmatch(ident):
            raise ValueError("record_id_invalid")
        with self.lock:
            if self.read_only:
                raise ValueError("saved_run_read_only")
            with self.db:
                seq = self._event_uncommitted(kind, frame_id, lane_id, {
                    "id": ident, "candidate_id": candidate_id, "version": version})
                if table == "frames":
                    self.db.execute("INSERT INTO frames VALUES(?,?,?)", (ident, seq, canonical(data)))
                elif table == "candidates":
                    self.db.execute("INSERT INTO candidates VALUES(?,?,?,?,?)",
                                    (ident, frame_id, lane_id, seq, canonical(data)))
                elif table == "measurements":
                    self.db.execute("INSERT INTO measurements VALUES(?,?,?,?,?,?)",
                                    (ident, frame_id, candidate_id, data["kind"], seq, canonical(data)))
                elif table == "evidence":
                    self.db.execute("INSERT INTO evidence VALUES(?,?,?,?,?)",
                                    (ident, frame_id, version, seq, canonical(data)))
                elif table == "evaluations":
                    self.db.execute("INSERT INTO evaluations VALUES(?,?,?,?,?,?)",
                                    (ident, candidate_id, frame_id, version, seq, canonical(data)))
                elif table == "decisions":
                    self.db.execute("INSERT INTO decisions VALUES(?,?,?,?)",
                                    (ident, frame_id, seq, canonical(data)))
                else:
                    raise ValueError("unknown_table")
                return seq

    def frame(self, ident: str, data: dict) -> int:
        return self._record("frames", ident, ident, None, "KeyframePublished", data)

    def candidate(self, ident: str, frame_id: str, lane_id: str, data: dict) -> int:
        return self._record("candidates", ident, frame_id, lane_id, "CandidatePublished", data)

    def measurement(self, ident: str, frame_id: str, candidate_id: str | None,
                    data: dict) -> int:
        return self._record("measurements", ident, frame_id, data.get("lane_id"),
                            "MeasurementsCommitted", data, candidate_id=candidate_id)

    def evidence(self, ident: str, frame_id: str, version: int, data: dict) -> int:
        if not _ID.fullmatch(ident) or version < 0:
            raise ValueError("evidence_invalid")
        with self.lock:
            if self.read_only:
                raise ValueError("saved_run_read_only")
            with self.db:
                current = self.db.execute("SELECT evidence_version,winner_id,stale_fallback_id FROM selection_state WHERE frame_id=?", (frame_id,)).fetchone()
                if (version == 0 and current is not None) or (version > 0 and (current is None or current[0] + 1 != version)):
                    raise ValueError("evidence_version_not_next")
                seq = self._event_uncommitted("EvidencePublished", frame_id, None,
                                               {"id": ident, "version": version})
                self.db.execute("INSERT INTO evidence VALUES(?,?,?,?,?)",
                                (ident, frame_id, version, seq, canonical(data)))
                if version == 0:
                    self.db.execute("INSERT INTO selection_state VALUES(?,?,?,?,?,?,?)",
                                    (frame_id, 0, None, None, None, None, seq))
                else:
                    old_winner = current[1]
                    fallback = old_winner or current[2]
                    self.db.execute("UPDATE selection_state SET evidence_version=?,winner_id=NULL,winner_q=NULL,selected_task_id=NULL,stale_fallback_id=?,latest_seq=? WHERE frame_id=?",
                                    (version, fallback, seq, frame_id))
                    self.db.execute("INSERT INTO revisions VALUES(?,?,?,?,?,?,?)",
                                    (f"rev_e_{seq}", frame_id, seq, old_winner, None,
                                     "EVIDENCE_INVALIDATED", "OLD_EVIDENCE"))
                return seq

    def evaluation(self, ident: str, candidate_id: str, frame_id: str, version: int,
                   data: dict) -> int:
        return self._record("evaluations", ident, frame_id, data["lane_id"],
                            "EvaluationCommitted", data, candidate_id=candidate_id,
                            version=version)

    def decision(self, ident: str, frame_id: str, data: dict) -> int:
        return self._record("decisions", ident, frame_id, data.get("lane_id"),
                            "DecisionCommitted", data)

    def job(self, ident: str, frame_id: str | None, lane_id: str | None,
            stage: str, unit: str, status: str = "QUEUED") -> None:
        if not _ID.fullmatch(ident) or status not in {"QUEUED", "WAITING_DEPENDENCY"}:
            raise ValueError("job_invalid")
        with self.lock:
            if self.read_only:
                raise ValueError("saved_run_read_only")
            with self.db:
                now = int(time.time() * 1000)
                self.db.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                                (ident, frame_id, lane_id, stage, unit, status, None,
                                 now if status == "QUEUED" else None, None, None, None))
                self._event_uncommitted("JobQueued" if status == "QUEUED" else "JobWaitingDependency",
                                        frame_id, lane_id, {"job_id": ident, "stage": stage, "unit": unit})

    def job_state(self, ident: str, status: str, *, phase: str | None = None,
                  error_code: str | None = None) -> None:
        if status not in {"QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED", "EXPIRED"}:
            raise ValueError("job_status_invalid")
        with self.lock:
            if self.read_only:
                raise ValueError("saved_run_read_only")
            row = self.db.execute("SELECT frame_id,lane_id,status FROM jobs WHERE id=?", (ident,)).fetchone()
            if row is None:
                raise ValueError("job_unknown")
            old = row[2]
            if (old, status) not in {("WAITING_DEPENDENCY", "QUEUED"), ("QUEUED", "RUNNING"),
                                     ("RUNNING", "SUCCEEDED"), ("RUNNING", "FAILED"),
                                     ("RUNNING", "CANCELLED"), ("QUEUED", "CANCELLED"),
                                     ("QUEUED", "EXPIRED"), ("RUNNING", "EXPIRED")}:
                raise ValueError("job_transition_invalid")
            now = int(time.time() * 1000)
            with self.db:
                self.db.execute("""UPDATE jobs SET status=?,phase=?,queued_ms=CASE WHEN ?='QUEUED' THEN ? ELSE queued_ms END,
                    started_ms=CASE WHEN ?='RUNNING' THEN ? ELSE started_ms END,
                    finished_ms=CASE WHEN ? IN ('SUCCEEDED','FAILED','CANCELLED','EXPIRED') THEN ? ELSE finished_ms END,
                    error_code=? WHERE id=?""",
                    (status, phase, status, now, status, now, status, now, error_code, ident))
                self._event_uncommitted("JobStarted" if status == "RUNNING" else
                                        "JobQueued" if status == "QUEUED" else "JobFinished",
                                        row[0], row[1], {"job_id": ident, "status": status,
                                                        "phase": phase, "error_code": error_code})

    def put_artifact(self, ident: str, suffix: str, content: bytes,
                     media_type: str) -> dict:
        if not _ID.fullmatch(ident) or suffix not in {".png", ".npz", ".json"} or not content:
            raise ValueError("artifact_invalid")
        with ARTIFACT_WRITE_LOCK, self.lock:
            if self.read_only:
                raise ValueError("saved_run_read_only")
            used = self.db.execute("SELECT COALESCE(SUM(size),0) FROM artifacts").fetchone()[0]
            if used + len(content) > MAX_RUN_BYTES:
                raise ValueError("run_output_capacity")
            total = sum(p.stat().st_size for run in RUNS_ROOT.iterdir()
                        if run.is_dir() and not run.is_symlink()
                        if (run / "artifacts").is_dir()
                        for p in (run / "artifacts").iterdir()
                        if p.is_file() and not p.is_symlink())
            if total + len(content) > MAX_TOTAL_BYTES:
                raise ValueError("total_output_capacity")
            relative = f"artifacts/{ident}{suffix}"
            target = self.root / relative
            if target.exists():
                raise ValueError("artifact_collision")
            temp = target.with_name(target.name + f".tmp-{os.getpid()}-{threading.get_ident()}")
            try:
                with temp.open("xb") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temp, target)
                digest = sha256(content).hexdigest()
                with self.db:
                    self.db.execute("INSERT INTO artifacts VALUES(?,?,?,?,?)",
                                    (ident, relative, media_type, len(content), digest))
            finally:
                temp.unlink(missing_ok=True)
            return {"artifact_id": ident, "bytes": len(content), "sha256": digest}

    def read_artifact(self, ident: str) -> tuple[str, bytes]:
        if not _ID.fullmatch(ident):
            raise ValueError("artifact_id_invalid")
        with self.lock:
            row = self.db.execute("SELECT path,media_type,size,digest FROM artifacts WHERE id=?",
                                  (ident,)).fetchone()
            if row is None:
                raise FileNotFoundError("artifact_unknown")
            path = (self.root / row[0]).resolve()
            if self.root not in path.parents or path.is_symlink():
                raise ValueError("artifact_outside_run")
            content = path.read_bytes()
            if len(content) != row[2] or sha256(content).hexdigest() != row[3]:
                raise ValueError("artifact_integrity")
            return row[1], content

    def snapshot(self, cursor: int | None = None) -> dict:
        with self.lock:
            latest = self.db.execute("SELECT COALESCE(MAX(seq),0) FROM events").fetchone()[0]
            seq = latest if cursor is None else min(max(0, cursor), latest)
            def records(table: str) -> list[dict]:
                return [dict(json.loads(data), seq=s) for data, s in self.db.execute(
                    f"SELECT data,seq FROM {table} WHERE seq<=? ORDER BY seq", (seq,))]
            events = [{"seq": s, "kind": kind, "frame_id": fid, "lane_id": lane,
                       "at_ms": at, "payload": json.loads(payload)}
                      for s, kind, fid, lane, at, payload in self.db.execute(
                          "SELECT seq,kind,frame_id,lane_id,at_ms,payload FROM events WHERE seq<=? ORDER BY seq",
                          (seq,))]
            job_meta = {r[0]: {"id": r[0], "frame_id": r[1], "lane_id": r[2],
                               "stage": r[3], "unit": r[4], "status": "WAITING_DEPENDENCY",
                               "phase": None, "queued_ms": None, "started_ms": None,
                               "finished_ms": None, "error_code": None}
                        for r in self.db.execute("SELECT * FROM jobs")}
            visible_jobs = {}
            for event in events:
                if event["kind"] not in {"JobWaitingDependency", "JobQueued", "JobStarted", "JobFinished"}:
                    continue
                ident = event["payload"].get("job_id")
                if ident not in job_meta:
                    continue
                job = visible_jobs.setdefault(ident, dict(job_meta[ident]))
                if event["kind"] == "JobWaitingDependency":
                    job["status"] = "WAITING_DEPENDENCY"
                elif event["kind"] == "JobQueued":
                    job["status"] = "QUEUED"
                    job["queued_ms"] = event["at_ms"]
                elif event["kind"] == "JobStarted":
                    job["status"] = "RUNNING"
                    job["phase"] = event["payload"].get("phase")
                    job["started_ms"] = event["at_ms"]
                else:
                    job["status"] = event["payload"]["status"]
                    job["error_code"] = event["payload"].get("error_code")
                    job["finished_ms"] = event["at_ms"]
            jobs = sorted(visible_jobs.values(), key=lambda x: (x["queued_ms"] or 0, x["id"]))
            evaluations = []
            for task in self.db.execute("SELECT id,candidate_id,frame_id,lane_id,evidence_version,context_id,status,seq,origin FROM eval_tasks WHERE seq<=? ORDER BY seq", (seq,)):
                axes = {axis: dict(json.loads(data), seq=axis_seq, attempt_id=attempt_id)
                        for axis, data, axis_seq, attempt_id in self.db.execute(
                    "SELECT axis_id,data,seq,attempt_id FROM axis_results WHERE task_id=? AND seq<=?",
                    (task[0], seq))}
                evaluations.append({"evaluation_id": task[0], "candidate_id": task[1],
                                    "frame_id": task[2], "lane_id": task[3],
                                    "evidence_version": task[4], "context_id": task[5],
                                    "status": "COMPLETE" if len(axes) == 5 else
                                              "PARTIAL_DIAGNOSTICS" if axes else
                                              task[6] if task[6] != "QUEUED" else "PENDING",
                                    "transport_status": task[6],
                                    "axes": axes, "origin": task[8], "seq": task[7]})
            attempts = [{"attempt_id": r[0], "evaluation_id": r[1], "index": r[2],
                         "seq": r[3], "raw_artifact_id": r[4], "status": r[5],
                         "error_code": r[6], "input_tokens": r[7]}
                        for r in self.db.execute("SELECT * FROM eval_attempts WHERE seq<=? ORDER BY seq", (seq,))]
            revisions = [{"revision_id": r[0], "frame_id": r[1], "seq": r[2],
                          "from_candidate_id": r[3], "to_candidate_id": r[4],
                          "kind": r[5], "reason_code": r[6]}
                         for r in self.db.execute("SELECT * FROM revisions WHERE seq<=? ORDER BY seq", (seq,))]
            decisions = records("decisions")
            evidence = records("evidence")
            selection = {}
            for frame in records("frames"):
                frame_id = frame["frame_id"]
                versions = [x["version"] for x in evidence if x["frame_id"] == frame_id]
                version = max(versions, default=0)
                current = [x for x in decisions if x["frame_id"] == frame_id and x["evidence_version"] == version]
                prior = [x for x in decisions if x["frame_id"] == frame_id and x["evidence_version"] < version]
                winner = current[-1]["winner_after_id"] if current else None
                selection[frame_id] = {"evidence_version": version, "winner_id": winner,
                                       "stale_fallback_id": None if winner else
                                            next((x["winner_after_id"] for x in reversed(prior)
                                                  if x.get("winner_after_id")), None),
                                       "latest_decision": current[-1] if current else None}
            source = dict(self.get_meta("source") or {})
            source.pop("path", None)
            return {"run_id": self.root.name, "schema": SCHEMA, "snapshot_seq": seq,
                    "lifecycle": self.get_meta("lifecycle"), "business": self.get_meta("business"),
                    "source": source, "experiment": self.get_meta("experiment"),
                    "frames": records("frames"), "candidates": records("candidates"),
                    "measurements": records("measurements"), "evidence": evidence,
                    "evaluations": evaluations, "eval_attempts": attempts,
                    "decisions": decisions, "revisions": revisions, "selection": selection,
                    "events": events, "jobs": jobs}

    def receipt(self, *, ident: str, session_id: str, frame_id: str,
                candidate_id: str, source_seq: int, mode: str) -> bool:
        if not all(_ID.fullmatch(x) for x in (ident, session_id, frame_id, candidate_id)):
            raise ValueError("receipt_id_invalid")
        if mode not in {"FOLLOW_SELECTION", "MANUAL_CANDIDATE", "UNSCORED_PREVIEW"}:
            raise ValueError("receipt_mode_invalid")
        with self.lock:
            if self.read_only:
                raise ValueError("saved_run_read_only")
            row = self.db.execute("SELECT frame_id,seq FROM candidates WHERE id=?",
                                  (candidate_id,)).fetchone()
            if row is None or row[0] != frame_id or source_seq < row[1]:
                raise ValueError("receipt_candidate_mismatch")
            if mode == "FOLLOW_SELECTION":
                decision = self.db.execute(
                    "SELECT data FROM decisions WHERE frame_id=? AND seq=?",
                    (frame_id, source_seq)).fetchone()
                if decision is None or json.loads(decision[0]).get("winner_after_id") != candidate_id:
                    raise ValueError("receipt_selection_source_mismatch")
            elif source_seq != row[1]:
                decision = self.db.execute(
                    "SELECT data FROM decisions WHERE frame_id=? AND seq=?",
                    (frame_id, source_seq)).fetchone()
                if decision is None or json.loads(decision[0]).get("candidate_id") != candidate_id:
                    raise ValueError("receipt_source_mismatch")
            try:
                with self.db:
                    self.db.execute("INSERT INTO receipts VALUES(?,?,?,?,?,?,?)",
                                    (ident, session_id, frame_id, candidate_id,
                                     source_seq, mode, int(time.time() * 1000)))
                return True
            except sqlite3.IntegrityError:
                return False

    def close_run(self, business: str, *, normal: bool = True) -> None:
        with self.lock:
            if self.read_only:
                return
            with self.db:
                self._event_uncommitted("RunStopped", None, None,
                                        {"business": business, "normal": normal})
                self.db.execute("INSERT OR REPLACE INTO meta VALUES(?,?)",
                                ("business", canonical(business)))
                self.db.execute("INSERT OR REPLACE INTO meta VALUES(?,?)",
                                ("lifecycle", canonical("SERVICE_STOPPED_NORMAL" if normal
                                                        else "SERVICE_INTERRUPTED")))
            self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def close(self) -> None:
        with self.lock:
            self.db.close()
