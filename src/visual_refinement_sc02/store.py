"""SC02-owned immutable artifacts, events, and replayable run records."""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any

SCHEMA = "vr_sc02_v1"
MAX_OUTPUT_BYTES = 1024**3
REPO = Path(__file__).resolve().parents[2]
RUNS_ROOT = REPO / "runs" / "sc02"


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


class RunStore:
    def __init__(self, root: Path, *, create: bool, source: dict | None = None):
        base = RUNS_ROOT.resolve()
        path = Path(root).resolve()
        if base not in path.parents:
            raise ValueError("run_outside_sc02_root")
        if path.exists() and (path.is_symlink() or path.is_junction()):
            raise ValueError("run_reparse_denied")
        self.root = path
        self.lock = threading.RLock()
        self.read_only = not create
        if create:
            if path.exists() and any(path.iterdir()):
                raise FileExistsError("run_already_exists")
            path.mkdir(parents=True, exist_ok=True)
            (path / "artifacts").mkdir()
            self.db = sqlite3.connect(path / "state.sqlite3", check_same_thread=False)
            self.db.execute("PRAGMA foreign_keys=ON")
            self.db.executescript("""
                CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE events(seq INTEGER PRIMARY KEY AUTOINCREMENT,kind TEXT NOT NULL,
                    frame_id TEXT,at_ms INTEGER NOT NULL,payload TEXT NOT NULL);
                CREATE TABLE frames(id TEXT PRIMARY KEY,seq INTEGER NOT NULL,data TEXT NOT NULL);
                CREATE TABLE candidates(id TEXT PRIMARY KEY,frame_id TEXT NOT NULL,
                    seq INTEGER NOT NULL,data TEXT NOT NULL);
                CREATE TABLE artifacts(id TEXT PRIMARY KEY,relative_path TEXT UNIQUE NOT NULL,
                    media_type TEXT NOT NULL,size INTEGER NOT NULL,sha256 TEXT NOT NULL);
                CREATE TABLE receipts(id TEXT PRIMARY KEY,session_id TEXT NOT NULL,
                    frame_id TEXT NOT NULL,candidate_id TEXT NOT NULL,mode TEXT NOT NULL,
                    source_seq INTEGER NOT NULL,at_ms INTEGER NOT NULL,
                    UNIQUE(session_id,candidate_id,mode,source_seq));
            """)
            self._meta("schema", SCHEMA)
            self._meta("source", source or {})
            self._meta("lifecycle", "RUNNING")
            self._meta("business", "PENDING")
            self.event("RunCreated", None, {"source_id": (source or {}).get("source_id")})
        else:
            if not (path / "state.sqlite3").is_file():
                raise FileNotFoundError("saved_run_missing")
            uri = (path / "state.sqlite3").as_uri() + "?mode=ro"
            self.db = sqlite3.connect(uri, uri=True, check_same_thread=False)
            if self.get_meta("schema") != SCHEMA:
                raise ValueError("run_schema_mismatch")

    def _meta(self, key: str, value: Any) -> None:
        self.db.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (key, _json(value)))
        self.db.commit()

    def get_meta(self, key: str) -> Any:
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def event(self, kind: str, frame_id: str | None, payload: dict) -> int:
        with self.lock:
            if self.read_only:
                raise ValueError("saved_run_read_only")
            cursor = self.db.execute("INSERT INTO events(kind,frame_id,at_ms,payload) VALUES(?,?,?,?)",
                                     (kind, frame_id, int(time.time() * 1000), _json(payload)))
            self.db.commit()
            return int(cursor.lastrowid)

    def put_artifact(self, ident: str, suffix: str, data: bytes, media_type: str) -> dict:
        if not ident.replace("_", "").replace("-", "").isalnum() or not data:
            raise ValueError("artifact_invalid")
        if suffix not in {".png", ".npz", ".json"}:
            raise ValueError("artifact_extension")
        if media_type not in {"image/png", "application/octet-stream", "application/json"}:
            raise ValueError("artifact_media_type")
        with self.lock:
            if self.read_only:
                raise ValueError("saved_run_read_only")
            used = self.db.execute("SELECT COALESCE(SUM(size),0) FROM artifacts").fetchone()[0]
            if used + len(data) > MAX_OUTPUT_BYTES:
                raise ValueError("output_capacity")
            relative = f"artifacts/{ident}{suffix}"
            target = self.root / relative
            if target.exists() or self.db.execute("SELECT 1 FROM artifacts WHERE id=?", (ident,)).fetchone():
                raise ValueError("artifact_collision")
            temporary = target.with_name(target.name + f".tmp-{os.getpid()}-{threading.get_ident()}")
            with temporary.open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.replace(temporary, target)
                digest = sha256(data).hexdigest()
                self.db.execute("INSERT INTO artifacts VALUES(?,?,?,?,?)",
                                (ident, relative, media_type, len(data), digest))
                self.db.commit()
            finally:
                temporary.unlink(missing_ok=True)
            return {"artifact_id": ident, "bytes": len(data), "sha256": digest,
                    "media_type": media_type, "relative_path": relative}

    def read_artifact(self, ident: str) -> tuple[str, bytes]:
        with self.lock:
            row = self.db.execute("SELECT relative_path,media_type,size,sha256 FROM artifacts WHERE id=?",
                                  (ident,)).fetchone()
            if row is None:
                raise FileNotFoundError("artifact_unknown")
            relative, media, size, digest = row
            target = (self.root / relative).resolve()
            if self.root not in target.parents or target.is_symlink():
                raise FileNotFoundError("artifact_outside_run")
            data = target.read_bytes()
            if len(data) != size or sha256(data).hexdigest() != digest:
                raise ValueError("artifact_integrity")
            return media, data

    def publish_frame(self, ident: str, data: dict) -> int:
        with self.lock:
            if self.db.execute("SELECT 1 FROM frames WHERE id=?", (ident,)).fetchone():
                raise ValueError("frame_collision")
            seq = self.event("KeyframePublished", ident, {"frame_id": ident, "pixel_sha256": data["pixel_sha256"]})
            self.db.execute("INSERT INTO frames VALUES(?,?,?)", (ident, seq, _json(data)))
            self.db.commit()
            return seq

    def publish_candidate(self, ident: str, frame_id: str, data: dict) -> int:
        with self.lock:
            if self.db.execute("SELECT 1 FROM candidates WHERE id=?", (ident,)).fetchone():
                raise ValueError("candidate_collision")
            seq = self.event("CandidatePublished", frame_id,
                             {"candidate_id": ident, "mask_count": data["mask_count"]})
            self.db.execute("INSERT INTO candidates VALUES(?,?,?,?)", (ident, frame_id, seq, _json(data)))
            self.db.commit()
            return seq

    def receipt(self, payload: dict) -> bool:
        required = {"id", "session_id", "frame_id", "candidate_id", "mode", "source_seq"}
        if set(payload) != required or payload["mode"] != "UNSCORED_PREVIEW":
            raise ValueError("receipt_invalid")
        with self.lock:
            if self.read_only:
                raise ValueError("saved_run_read_only")
            row = self.db.execute("SELECT frame_id,seq FROM candidates WHERE id=?",
                                  (payload["candidate_id"],)).fetchone()
            if row != (payload["frame_id"], payload["source_seq"]):
                raise ValueError("receipt_candidate_mismatch")
            try:
                self.db.execute("INSERT INTO receipts VALUES(?,?,?,?,?,?,?)",
                                (payload["id"], payload["session_id"], payload["frame_id"],
                                 payload["candidate_id"], payload["mode"], payload["source_seq"],
                                 int(time.time() * 1000)))
                self.db.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def snapshot(self, cursor: int | None = None) -> dict:
        with self.lock:
            limit = cursor if cursor is not None else self.db.execute("SELECT COALESCE(MAX(seq),0) FROM events").fetchone()[0]
            frames = [dict(json.loads(r[0]), seq=r[1]) for r in self.db.execute("SELECT data,seq FROM frames WHERE seq<=? ORDER BY seq", (limit,))]
            candidates = [dict(json.loads(r[0]), seq=r[1]) for r in self.db.execute("SELECT data,seq FROM candidates WHERE seq<=? ORDER BY seq", (limit,))]
            events = [{"seq": r[0], "kind": r[1], "frame_id": r[2], "at_ms": r[3], "payload": json.loads(r[4])}
                      for r in self.db.execute("SELECT seq,kind,frame_id,at_ms,payload FROM events WHERE seq<=? ORDER BY seq", (limit,))]
            return {"run_id": self.root.name, "schema": SCHEMA, "source": self.get_meta("source"),
                    "lifecycle": self.get_meta("lifecycle"), "business": self.get_meta("business"),
                    "snapshot_seq": limit, "frames": frames, "candidates": candidates,
                    "events": events, "output_bytes": self.db.execute("SELECT COALESCE(SUM(size),0) FROM artifacts").fetchone()[0]}

    def close_run(self, business: str, normal: bool = True) -> None:
        with self.lock:
            if self.read_only:
                return
            self.event("RunStopped", None, {"normal": normal, "business": business})
            self._meta("business", business)
            self._meta("lifecycle", "SERVICE_STOPPED_NORMAL" if normal else "SERVICE_INTERRUPTED")

    def close(self) -> None:
        with self.lock:
            self.db.close()
