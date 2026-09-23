"""Cumulative SQLite reservations and atomic batch plans across SC03–SC07."""
from __future__ import annotations

from decimal import Decimal, ROUND_CEILING
from pathlib import Path
import sqlite3
import threading
import time

from .store import RUNS_ROOT

MAX_GPU_JOBS = 80
MAX_GPU_DURATION_MS = 2 * 60 * 60 * 1000
GPU_JOB_RESERVATION_MS = 120 * 1000
MAX_VALIDATION_GPU_JOBS = 64
MAX_SUITES = 128
MAX_VALIDATION_SUITES = 96
MAX_HTTP_ATTEMPTS = 192
MAX_QUESTIONS = 960
MAX_BODY_BYTES = 8 * 1024**2
MAX_REQUEST_BYTES = 32 * 1024
MAX_RESERVED_USD_MICRO = 1_000_000
INPUT_TOKEN_RESERVATION = 64_000
PRICE_USD_PER_MILLION_INPUT = Decimal("0.042")
RESERVED_MICRO_USD = int((Decimal(INPUT_TOKEN_RESERVATION) *
                          PRICE_USD_PER_MILLION_INPUT).to_integral_value(rounding=ROUND_CEILING))


class BudgetLedger:
    def __init__(self, path: Path | None = None):
        self.path = path or (RUNS_ROOT / "budget.sqlite3")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS reservations(
                id TEXT PRIMARY KEY, kind TEXT NOT NULL, bucket TEXT NOT NULL,
                run_id TEXT NOT NULL, frame_id TEXT, lane_id TEXT,
                body_bytes INTEGER NOT NULL DEFAULT 0, questions INTEGER NOT NULL DEFAULT 0,
                reserved_micro_usd INTEGER NOT NULL DEFAULT 0,
                at_ms INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'RESERVED',
                actual_input_tokens INTEGER, plan_id TEXT);
            CREATE TABLE IF NOT EXISTS plans(
                id TEXT PRIMARY KEY, definition_digest TEXT NOT NULL, bucket TEXT NOT NULL,
                remaining_gpu_jobs INTEGER NOT NULL, remaining_suites INTEGER NOT NULL,
                remaining_http_attempts INTEGER NOT NULL, remaining_questions INTEGER NOT NULL,
                remaining_body_bytes INTEGER NOT NULL, remaining_micro_usd INTEGER NOT NULL,
                status TEXT NOT NULL, at_ms INTEGER NOT NULL);
        """)
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(reservations)")}
        if "gpu_actual_ms" not in columns:
            self.db.execute("ALTER TABLE reservations ADD COLUMN gpu_actual_ms INTEGER")
            self.db.commit()

    def _gpu_duration_ms(self) -> int:
        return self.db.execute(
            "SELECT COALESCE(SUM(COALESCE(gpu_actual_ms,?)),0) FROM reservations WHERE kind='GPU_JOB'",
            (GPU_JOB_RESERVATION_MS,)).fetchone()[0]

    def _count(self, kind: str, bucket: str | None = None) -> int:
        if bucket:
            return self.db.execute("SELECT COUNT(*) FROM reservations WHERE kind=? AND bucket=?",
                                   (kind, bucket)).fetchone()[0]
        return self.db.execute("SELECT COUNT(*) FROM reservations WHERE kind=?",
                               (kind,)).fetchone()[0]

    def _sum(self, column: str, kind: str) -> int:
        if column not in {"body_bytes", "questions", "reserved_micro_usd"}:
            raise ValueError("ledger_column_invalid")
        return self.db.execute(f"SELECT COALESCE(SUM({column}),0) FROM reservations WHERE kind=?",
                               (kind,)).fetchone()[0]

    def _planned(self, column: str, bucket: str | None = None) -> int:
        if column not in {"remaining_gpu_jobs", "remaining_suites", "remaining_http_attempts",
                          "remaining_questions", "remaining_body_bytes", "remaining_micro_usd"}:
            raise ValueError("plan_column_invalid")
        if bucket:
            return self.db.execute(
                f"SELECT COALESCE(SUM({column}),0) FROM plans WHERE status='ACTIVE' AND bucket=?",
                (bucket,)).fetchone()[0]
        return self.db.execute(
            f"SELECT COALESCE(SUM({column}),0) FROM plans WHERE status='ACTIVE'").fetchone()[0]

    def reserve_plan(self, *, plan_id: str, definition_digest: str, bucket: str,
                     gpu_jobs: int, suites: int, http_attempts: int,
                     questions: int, body_bytes: int, cost_micro: int) -> None:
        if bucket not in {"VALIDATION", "NORMAL"}:
            raise ValueError("ledger_bucket_invalid")
        numbers = (gpu_jobs, suites, http_attempts, questions, body_bytes, cost_micro)
        if any(not isinstance(x, int) or x < 0 for x in numbers):
            raise ValueError("plan_quantity_invalid")
        with self.lock, self.db:
            row = self.db.execute("SELECT definition_digest,bucket,status FROM plans WHERE id=?",
                                  (plan_id,)).fetchone()
            if row:
                if row[:2] == (definition_digest, bucket) and row[2] == "ACTIVE":
                    return
                raise ValueError("plan_duplicate_conflict")
            if (self._count("GPU_JOB") + self._planned("remaining_gpu_jobs") + gpu_jobs > MAX_GPU_JOBS or
                self._count("SUITE") + self._planned("remaining_suites") + suites > MAX_SUITES or
                self._count("HTTP_ATTEMPT") + self._planned("remaining_http_attempts") + http_attempts > MAX_HTTP_ATTEMPTS or
                self._sum("questions", "HTTP_ATTEMPT") + self._planned("remaining_questions") + questions > MAX_QUESTIONS or
                self._sum("body_bytes", "HTTP_ATTEMPT") + self._planned("remaining_body_bytes") + body_bytes > MAX_BODY_BYTES or
                self._sum("reserved_micro_usd", "HTTP_ATTEMPT") + self._planned("remaining_micro_usd") + cost_micro > MAX_RESERVED_USD_MICRO):
                raise ValueError("plan_global_budget")
            if bucket == "VALIDATION":
                if (self._count("GPU_JOB", bucket) + self._planned("remaining_gpu_jobs", bucket) + gpu_jobs > MAX_VALIDATION_GPU_JOBS or
                    self._count("SUITE", bucket) + self._planned("remaining_suites", bucket) + suites > MAX_VALIDATION_SUITES):
                    raise ValueError("plan_validation_budget")
            else:
                if (self._count("GPU_JOB", bucket) + self._planned("remaining_gpu_jobs", bucket) + gpu_jobs > MAX_GPU_JOBS - MAX_VALIDATION_GPU_JOBS or
                    self._count("SUITE", bucket) + self._planned("remaining_suites", bucket) + suites > MAX_SUITES - MAX_VALIDATION_SUITES):
                    raise ValueError("plan_normal_budget")
            self.db.execute("INSERT INTO plans VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (plan_id, definition_digest, bucket, gpu_jobs, suites, http_attempts,
                 questions, body_bytes, cost_micro, "ACTIVE", int(time.time() * 1000)))

    def close_plan(self, plan_id: str) -> None:
        """Release only unsent/unstarted reservations; actual usage never resets."""
        with self.lock, self.db:
            if self.db.execute("UPDATE plans SET status='CLOSED',remaining_gpu_jobs=0,remaining_suites=0,remaining_http_attempts=0,remaining_questions=0,remaining_body_bytes=0,remaining_micro_usd=0 WHERE id=? AND status='ACTIVE'",
                               (plan_id,)).rowcount != 1:
                raise ValueError("active_plan_missing")

    def _reserve(self, ident: str, kind: str, bucket: str, run_id: str,
                 frame_id: str | None, lane_id: str | None,
                 body_bytes: int = 0, questions: int = 0,
                 cost_micro: int = 0, plan_id: str | None = None) -> None:
        if bucket not in {"VALIDATION", "NORMAL"}:
            raise ValueError("ledger_bucket_invalid")
        with self.lock, self.db:
            existing = self.db.execute(
                "SELECT kind,bucket,run_id,body_bytes,questions,reserved_micro_usd,plan_id FROM reservations WHERE id=?",
                (ident,)).fetchone()
            expected = (kind, bucket, run_id, body_bytes, questions, cost_micro, plan_id)
            if existing:
                if existing == expected:
                    return
                raise ValueError("ledger_duplicate_conflict")
            if kind == "GPU_JOB" and self._gpu_duration_ms() + GPU_JOB_RESERVATION_MS > MAX_GPU_DURATION_MS:
                raise ValueError("gpu_duration_budget")
            if kind == "HTTP_ATTEMPT" and (
                    questions < 1 or questions > 5 or body_bytes < 1 or
                    body_bytes > MAX_REQUEST_BYTES or cost_micro < 0):
                raise ValueError("http_budget")
            if plan_id:
                plan = self.db.execute(
                    "SELECT bucket,remaining_gpu_jobs,remaining_suites,remaining_http_attempts,remaining_questions,remaining_body_bytes,remaining_micro_usd,status FROM plans WHERE id=?",
                    (plan_id,)).fetchone()
                if plan is None or plan[0] != bucket or plan[7] != "ACTIVE":
                    raise ValueError("plan_not_active")
                need = {"GPU_JOB": (1, 0, 0, 0, 0, 0),
                        "SUITE": (0, 1, 0, 0, 0, 0),
                        "HTTP_ATTEMPT": (0, 0, 1, questions, body_bytes, cost_micro)}.get(kind)
                if need is None or any(plan[i + 1] < need[i] for i in range(6)):
                    raise ValueError("plan_capacity")
                self.db.execute("""UPDATE plans SET remaining_gpu_jobs=remaining_gpu_jobs-?,
                    remaining_suites=remaining_suites-?,remaining_http_attempts=remaining_http_attempts-?,
                    remaining_questions=remaining_questions-?,remaining_body_bytes=remaining_body_bytes-?,
                    remaining_micro_usd=remaining_micro_usd-? WHERE id=?""", (*need, plan_id))
            else:
                if kind == "GPU_JOB":
                    if (self._count(kind) + self._planned("remaining_gpu_jobs") >= MAX_GPU_JOBS or
                        self._count(kind, bucket) + self._planned("remaining_gpu_jobs", bucket) >=
                        (MAX_VALIDATION_GPU_JOBS if bucket == "VALIDATION" else MAX_GPU_JOBS - MAX_VALIDATION_GPU_JOBS)):
                        raise ValueError("gpu_job_budget")
                elif kind == "SUITE":
                    if (self._count(kind) + self._planned("remaining_suites") >= MAX_SUITES or
                        self._count(kind, bucket) + self._planned("remaining_suites", bucket) >=
                        (MAX_VALIDATION_SUITES if bucket == "VALIDATION" else MAX_SUITES - MAX_VALIDATION_SUITES)):
                        raise ValueError("suite_budget")
                elif kind == "HTTP_ATTEMPT":
                    if (self._count(kind) + self._planned("remaining_http_attempts") >= MAX_HTTP_ATTEMPTS or
                        self._sum("questions", kind) + self._planned("remaining_questions") + questions > MAX_QUESTIONS or
                        self._sum("body_bytes", kind) + self._planned("remaining_body_bytes") + body_bytes > MAX_BODY_BYTES or
                        self._sum("reserved_micro_usd", kind) + self._planned("remaining_micro_usd") + cost_micro > MAX_RESERVED_USD_MICRO):
                        raise ValueError("http_budget")
                else:
                    raise ValueError("ledger_kind_invalid")
            self.db.execute("""INSERT INTO reservations(id,kind,bucket,run_id,frame_id,lane_id,
                body_bytes,questions,reserved_micro_usd,at_ms,plan_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (ident, kind, bucket, run_id, frame_id, lane_id, body_bytes, questions,
                 cost_micro, int(time.time() * 1000), plan_id))

    def reserve_gpu_job(self, *, run_id: str, frame_id: str,
                        lane_id: str, bucket: str = "VALIDATION",
                        plan_id: str | None = None, job_id: str | None = None) -> None:
        ident = job_id or f"gpu_{run_id}_{frame_id}_{lane_id}"
        self._reserve(ident, "GPU_JOB", bucket, run_id, frame_id, lane_id, plan_id=plan_id)

    def mark_gpu_job(self, job_id: str, duration_ms: int) -> None:
        if not isinstance(duration_ms, int) or duration_ms < 0:
            raise ValueError("gpu_duration_invalid")
        with self.lock, self.db:
            if self.db.execute(
                    "UPDATE reservations SET gpu_actual_ms=?,status='COMPLETED' "
                    "WHERE id=? AND kind='GPU_JOB' AND gpu_actual_ms IS NULL",
                    (duration_ms, job_id)).rowcount != 1:
                raise ValueError("gpu_job_unknown_or_finished")

    def reserve_suite(self, *, run_id: str, frame_id: str, lane_id: str,
                      evidence_version: int, bucket: str = "VALIDATION",
                      plan_id: str | None = None) -> None:
        self._reserve(f"suite_{run_id}_{frame_id}_{lane_id}_e{evidence_version}",
                      "SUITE", bucket, run_id, frame_id, lane_id, plan_id=plan_id)

    def reserve_http_attempt(self, *, attempt_id: str, run_id: str, frame_id: str,
                             lane_id: str, body_bytes: int, questions: int,
                             bucket: str = "VALIDATION", plan_id: str | None = None) -> None:
        self._reserve(attempt_id, "HTTP_ATTEMPT", bucket, run_id, frame_id, lane_id,
                      body_bytes, questions, RESERVED_MICRO_USD, plan_id=plan_id)

    def mark_attempt(self, attempt_id: str, status: str,
                     actual_input_tokens: int | None = None) -> None:
        if status not in {"RESPONSE", "TIMEOUT_UNKNOWN", "HTTP_ERROR", "INVALID_RESPONSE"}:
            raise ValueError("attempt_status_invalid")
        if actual_input_tokens is not None and (not isinstance(actual_input_tokens, int) or
                                                actual_input_tokens < 0):
            raise ValueError("usage_invalid")
        with self.lock, self.db:
            if self.db.execute("UPDATE reservations SET status=?,actual_input_tokens=? WHERE id=? AND kind='HTTP_ATTEMPT'",
                               (status, actual_input_tokens, attempt_id)).rowcount != 1:
                raise ValueError("attempt_unknown")

    def snapshot(self) -> dict:
        with self.lock:
            return {"gpu_jobs": self._count("GPU_JOB"),
                    "gpu_duration_ms_reserved_or_actual": self._gpu_duration_ms(),
                    "max_gpu_duration_ms": MAX_GPU_DURATION_MS,
                    "validation_gpu_jobs": self._count("GPU_JOB", "VALIDATION"),
                    "suites": self._count("SUITE"), "validation_suites": self._count("SUITE", "VALIDATION"),
                    "http_attempts": self._count("HTTP_ATTEMPT"),
                    "questions": self._sum("questions", "HTTP_ATTEMPT"),
                    "body_bytes": self._sum("body_bytes", "HTTP_ATTEMPT"),
                    "reserved_micro_usd": self._sum("reserved_micro_usd", "HTTP_ATTEMPT"),
                    "planned_remaining": {
                        "gpu_jobs": self._planned("remaining_gpu_jobs"),
                        "suites": self._planned("remaining_suites"),
                        "http_attempts": self._planned("remaining_http_attempts"),
                        "questions": self._planned("remaining_questions"),
                        "body_bytes": self._planned("remaining_body_bytes"),
                        "reserved_micro_usd": self._planned("remaining_micro_usd")},
                    "max_gpu_jobs": MAX_GPU_JOBS, "max_suites": MAX_SUITES,
                    "max_http_attempts": MAX_HTTP_ATTEMPTS,
                    "max_reserved_micro_usd": MAX_RESERVED_USD_MICRO}

    def close(self) -> None:
        with self.lock:
            self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self.db.close()
