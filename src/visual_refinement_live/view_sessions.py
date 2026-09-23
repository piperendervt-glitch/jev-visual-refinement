"""Separate view-session receipts for saved, read-only run browsing."""
from __future__ import annotations

import re
import sqlite3
import threading
import time

from . import store as store_module

_ID = re.compile(r"^[A-Za-z0-9_-]{1,96}$")


class ViewSessionStore:
    def __init__(self):
        path = store_module.RUNS_ROOT / "view_sessions.sqlite3"
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS receipts(
            id TEXT PRIMARY KEY, source_run_id TEXT NOT NULL, session_id TEXT NOT NULL,
            frame_id TEXT NOT NULL, candidate_id TEXT NOT NULL, source_seq INTEGER NOT NULL,
            mode TEXT NOT NULL, at_ms INTEGER NOT NULL,
            UNIQUE(source_run_id,session_id,candidate_id,source_seq,mode))""")
        self.db.commit()
        self.lock = threading.RLock()

    def record(self, *, ident: str, run_id: str, session_id: str,
               frame_id: str, candidate_id: str, source_seq: int,
               mode: str) -> bool:
        if (not all(isinstance(x, str) and _ID.fullmatch(x)
                    for x in (ident, run_id, session_id, frame_id, candidate_id)) or
                not isinstance(source_seq, int) or source_seq < 1 or
                mode not in {"SAVED_REPLAY", "MANUAL_SAVED_CANDIDATE"}):
            raise ValueError("view_receipt_invalid")
        source = store_module.LiveStore(run_id, create=False)
        try:
            view = source.snapshot()
            if view["lifecycle"] != "SERVICE_STOPPED_NORMAL":
                raise ValueError("saved_run_not_normal")
            candidate = next((x for x in view["candidates"]
                              if x["candidate_id"] == candidate_id and
                              x["frame_id"] == frame_id), None)
            if candidate is None:
                raise ValueError("saved_candidate_missing")
            valid_seqs = {candidate["seq"]}
            valid_seqs.update(x["seq"] for x in view["decisions"]
                              if x["frame_id"] == frame_id and
                              (x["candidate_id"] == candidate_id or
                               x.get("winner_after_id") == candidate_id))
            if source_seq not in valid_seqs:
                raise ValueError("view_receipt_source_mismatch")
        finally:
            source.close()
        with self.lock, self.db:
            try:
                self.db.execute("INSERT INTO receipts VALUES(?,?,?,?,?,?,?,?)",
                                (ident, run_id, session_id, frame_id, candidate_id,
                                 source_seq, mode, int(time.time() * 1000)))
                return True
            except sqlite3.IntegrityError:
                return False

    def count(self, run_id: str) -> int:
        with self.lock:
            return self.db.execute("SELECT COUNT(*) FROM receipts WHERE source_run_id=?",
                                   (run_id,)).fetchone()[0]

    def close(self) -> None:
        with self.lock:
            self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self.db.close()
