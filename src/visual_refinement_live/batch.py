"""Finite fixed-profile batch runner. Never starts without explicit server action."""
from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import shutil
import sqlite3
import threading
import time
import uuid

from .controller import LiveController, SHARED_GPU_PERMIT
from . import controller as controller_module
from .experiment import APPROVED_K_SECONDS, PROFILES, define_experiment, estimate
from .jev_client import JevEvaluator, load_dedicated_key
from .ledger import BudgetLedger, MAX_GPU_DURATION_MS
from .segmenters import MODEL_SPEC
from .preflight import verify_runtime
from .store import RUNS_ROOT, canonical

MAX_BATCH_SECONDS = 4 * 60 * 60
MAX_STORAGE_BYTES = 2 * 1024**3


class BatchManager:
    """One batch writer; all consumed work remains in a persistent global ledger."""

    def __init__(self, video: Path, ledger: BudgetLedger, *, main_controller: LiveController,
                 origin: str = "REAL", adapter_factory=None, fixture_transport=None):
        if origin not in {"REAL", "FIXTURE"}:
            raise ValueError("batch_origin_invalid")
        if origin == "FIXTURE" and (adapter_factory is None or fixture_transport is None):
            raise ValueError("fixture_injection_required")
        if origin == "REAL" and (adapter_factory is not None or fixture_transport is not None):
            raise ValueError("real_batch_cannot_inject_fixture")
        self.origin = origin
        self.adapter_factory = adapter_factory
        self.fixture_transport = fixture_transport
        self.video = video
        self.ledger = ledger
        self.main_controller = main_controller
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.batch_id: str | None = None
        self._k_cache: dict[float, dict] = {}
        self.current: LiveController | None = None
        self.path = RUNS_ROOT / "batches.sqlite3"
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS batches(
            id TEXT PRIMARY KEY, plan_digest TEXT NOT NULL, definition TEXT NOT NULL,
            bucket TEXT NOT NULL, status TEXT NOT NULL, started_ms INTEGER NOT NULL,
            finished_ms INTEGER, error_code TEXT)""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS batch_runs(
            batch_id TEXT NOT NULL, ordinal INTEGER NOT NULL, run_id TEXT NOT NULL,
            profile TEXT NOT NULL, repeat_index INTEGER NOT NULL,
            status TEXT NOT NULL, PRIMARY KEY(batch_id,ordinal))""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS k_sets(
            id TEXT PRIMARY KEY, seconds_json TEXT NOT NULL, updated_ms INTEGER NOT NULL)""")
        self.db.commit()
        self._recover_previous()

    def _recover_previous(self) -> None:
        """After the single-writer lease is acquired, close abandoned plans."""
        old = [row[0] for row in self.db.execute(
            "SELECT id FROM batches WHERE status='RUNNING'")]
        for ident in old:
            self.db.execute(
                "UPDATE batches SET status='INTERRUPTED',finished_ms=?,error_code=? WHERE id=?",
                (int(time.time() * 1000), "PROCESS_ENDED_WITHOUT_NORMAL_SHUTDOWN", ident))
            self.db.execute(
                "UPDATE batch_runs SET status='INTERRUPTED' WHERE batch_id=? AND status='RUNNING'",
                (ident,))
            try:
                self.ledger.close_plan(ident)
            except ValueError:
                pass
        self.db.commit()

    def k_set(self) -> dict:
        with self.lock:
            row = self.db.execute(
                "SELECT seconds_json,updated_ms FROM k_sets WHERE id='approved_video'").fetchone()
            seconds = json.loads(row[0]) if row else list(APPROVED_K_SECONDS)
            return {"seconds": seconds, "updated_ms": row[1] if row else None,
                    "allowed_seconds": list(APPROVED_K_SECONDS)}

    def save_k_set(self, seconds: tuple[float, ...]) -> dict:
        define_experiment(k_seconds=seconds)
        with self.lock:
            if self.worker and self.worker.is_alive():
                raise ValueError("batch_active")
            self.db.execute("INSERT OR REPLACE INTO k_sets VALUES(?,?,?)",
                            ("approved_video", canonical(seconds), int(time.time() * 1000)))
            self.db.commit()
        return self.k_set()

    def plan(self, *, profiles: tuple[str, ...], repeats: int,
             k_seconds: tuple[float, ...] = APPROVED_K_SECONDS,
             bucket: str = "VALIDATION") -> dict:
        if bucket not in {"VALIDATION", "NORMAL"}:
            raise ValueError("batch_bucket_invalid")
        if self.main_controller.video is None:
            raise ValueError("approved_video_required")
        fingerprints = []
        for seconds in k_seconds:
            if seconds not in APPROVED_K_SECONDS:
                raise ValueError("k_outside_approved_collection")
            if seconds not in self._k_cache:
                decoded = controller_module.decode_at(self.main_controller.video, seconds)
                self._k_cache[seconds] = {
                    "requested_seconds": seconds, "pts": decoded.pts,
                    "time_base": [decoded.time_base_num, decoded.time_base_den],
                    "pixel_sha256": decoded.pixel_sha256,
                    "sample_id": decoded.sample_id,
                    "width": decoded.width, "height": decoded.height}
            fingerprints.append(self._k_cache[seconds])
        definition = define_experiment(profiles=profiles, repeats=repeats,
                                       k_seconds=k_seconds,
                                       k_manifest=tuple(fingerprints),
                                       origin=self.origin)
        result = estimate(definition)
        used = self.ledger.snapshot()
        result["bucket"] = bucket
        result["ledger_before"] = used
        result["storage_limit_bytes"] = MAX_STORAGE_BYTES
        return result

    def _preflight(self, plan: dict) -> None:
        if self.origin == "REAL":
            lanes = tuple(sorted({lane for p in plan["definition"]["profiles"]
                                  for lane in PROFILES[p]}))
            plan["runtime_preflight"] = verify_runtime(lanes, jev=True)
            load_dedicated_key()
        # Only this owned run root is measured. The original video is never copied.
        used = sum(p.stat().st_size for p in RUNS_ROOT.rglob("*") if p.is_file())
        if used + plan["storage_reservation_bytes"] > MAX_STORAGE_BYTES:
            raise ValueError("batch_storage_capacity")
        if shutil.disk_usage(RUNS_ROOT).free < plan["storage_reservation_bytes"]:
            raise ValueError("batch_disk_free_insufficient")

    def start(self, *, profiles: tuple[str, ...], repeats: int,
              k_seconds: tuple[float, ...] = APPROVED_K_SECONDS,
              bucket: str = "VALIDATION") -> dict:
        plan = self.plan(profiles=profiles, repeats=repeats,
                         k_seconds=k_seconds, bucket=bucket)
        with self.lock:
            if self.worker is not None and self.worker.is_alive():
                raise ValueError("batch_already_running")
            if self.main_controller.worker and self.main_controller.worker.is_alive():
                raise ValueError("interactive_frame_active")
            if self.main_controller.evaluator and self.main_controller.evaluator.has_pending():
                raise ValueError("interactive_evaluation_active")
            self._preflight(plan)
            if (self.ledger.snapshot()["gpu_duration_ms_reserved_or_actual"] +
                    plan["worst_case_gpu_duration_ms"] > MAX_GPU_DURATION_MS):
                raise ValueError("batch_gpu_duration_capacity")
            ident = "batch_" + uuid.uuid4().hex[:20]
            self.ledger.reserve_plan(
                plan_id=ident, definition_digest=plan["definition_digest"],
                bucket=bucket, gpu_jobs=plan["segmentation_jobs"],
                suites=plan["logical_suites"],
                http_attempts=plan["max_http_attempts"],
                questions=plan["max_questions"],
                body_bytes=plan["max_body_bytes"],
                cost_micro=plan["max_reserved_micro_usd"])
            self.db.execute("INSERT INTO batches VALUES(?,?,?,?,?,?,?,?)",
                            (ident, plan["definition_digest"], canonical(plan["definition"]),
                             bucket, "RUNNING", int(time.time() * 1000), None, None))
            self.db.commit()
            self.batch_id = ident
            self.stop_event.clear()
            self.worker = threading.Thread(target=self._run,
                                           args=(ident, plan, bucket),
                                           name="fixed-batch", daemon=False)
            self.worker.start()
            return {"batch_id": ident, "plan": plan, "status": "RUNNING"}

    def _run(self, ident: str, plan: dict, bucket: str) -> None:
        definition = plan["definition"]
        began = time.monotonic()
        failure = None
        ordinal = 0
        try:
            for profile in definition["profiles"]:
                for repeat in range(1, definition["repeats"] + 1):
                    if self.stop_event.is_set() or time.monotonic() - began >= MAX_BATCH_SECONDS:
                        break
                    ordinal += 1
                    run_id = f"{ident}_{profile.lower()}_r{repeat}"
                    meta = {"batch_id": ident, "definition_digest": plan["definition_digest"],
                            "definition": definition, "profile": profile, "repeat": repeat,
                            "bucket": bucket, "plan_id": ident,
                            "weight_manifest": plan["weight_manifest"],
                            "runtime_preflight": plan.get("runtime_preflight"),
                            "planned_k_seconds": definition["k_seconds"],
                            "jev": self.origin == "REAL", "origin": self.origin}
                    with self.lock:
                        self.db.execute("INSERT INTO batch_runs VALUES(?,?,?,?,?,?)",
                                        (ident, ordinal, run_id, profile, repeat, "RUNNING"))
                        self.db.commit()
                    controller = None
                    try:
                        controller = LiveController(
                            video=self.video, run_id=run_id, lanes=PROFILES[profile],
                            experiment=meta, job_ledger=self.ledger, bucket=bucket,
                            plan_id=ident, gpu_permit=SHARED_GPU_PERMIT,
                            origin="REAL_MODEL" if self.origin == "REAL" else "FIXTURE",
                            **({"adapter_factory": self.adapter_factory}
                               if self.origin == "FIXTURE" else {}))
                        controller.evaluator = JevEvaluator(
                            controller.store, self.ledger, bucket=bucket, plan_id=ident,
                            origin="REAL_JEV" if self.origin == "REAL" else "FIXTURE",
                            **({"transport": self.fixture_transport}
                               if self.origin == "FIXTURE" else {}),
                            is_current=lambda fid, c=controller: c.accepting
                            and not c.cancel.is_set()
                            and c.frame_generations.get(fid) == c.generation)
                        with self.lock:
                            self.current = controller
                        for seconds in definition["k_seconds"]:
                            if self.stop_event.is_set() or time.monotonic() - began >= MAX_BATCH_SECONDS:
                                controller.stop_analysis()
                                break
                            controller.select(seconds)
                            stop_requested = False
                            while controller.snapshot()["worker_alive"]:
                                if (not stop_requested and
                                        (self.stop_event.is_set() or
                                         time.monotonic() - began >= MAX_BATCH_SECONDS)):
                                    controller.stop_analysis()
                                    stop_requested = True
                                time.sleep(0.05)
                        result = controller.close()
                        controller = None
                        run_status = result["business"]
                        if not result["normal"]:
                            run_status = "SERVICE_INTERRUPTED"
                        if run_status not in {"COMPLETE_NONEMPTY", "COMPLETE_EMPTY"}:
                            failure = run_status
                    except Exception as exc:
                        run_status = "FAILED"
                        failure = type(exc).__name__
                        if controller is not None:
                            try:
                                controller.stop_analysis()
                                controller.close()
                            except Exception:
                                pass
                    finally:
                        with self.lock:
                            self.current = None
                            self.db.execute(
                                "UPDATE batch_runs SET status=? WHERE batch_id=? AND ordinal=?",
                                (run_status, ident, ordinal))
                            self.db.commit()
                if self.stop_event.is_set() or time.monotonic() - began >= MAX_BATCH_SECONDS:
                    break
        except Exception as exc:
            failure = type(exc).__name__
        finally:
            status = ("STOPPED" if self.stop_event.is_set() else
                      "EXPIRED" if time.monotonic() - began >= MAX_BATCH_SECONDS else
                      "PARTIAL_FAILURE" if failure else "COMPLETE")
            with self.lock:
                self.db.execute("UPDATE batches SET status=?,finished_ms=?,error_code=? WHERE id=?",
                                (status, int(time.time() * 1000), failure, ident))
                self.db.commit()
            self.ledger.close_plan(ident)

    def stop(self) -> None:
        with self.lock:
            if self.worker is None or not self.worker.is_alive():
                raise ValueError("batch_not_running")
            self.stop_event.set()
            if self.current is not None:
                self.current.stop_analysis()

    def status(self) -> dict:
        with self.lock:
            rows = self.db.execute("""SELECT id,plan_digest,definition,bucket,status,started_ms,
                finished_ms,error_code FROM batches ORDER BY started_ms DESC LIMIT 25""").fetchall()
            runs = self.db.execute("""SELECT batch_id,ordinal,run_id,profile,
                repeat_index,status FROM batch_runs ORDER BY batch_id,ordinal""").fetchall()
            batches = []
            for row in rows:
                item = dict(zip(("batch_id", "plan_digest", "definition", "bucket",
                                 "status", "started_ms", "finished_ms", "error_code"), row))
                definition = json.loads(item.pop("definition"))
                item["planned_run_count"] = (
                    len(definition.get("profiles", ())) * definition.get("repeats", 0))
                batches.append(item)
            return {"active_batch_id": self.batch_id if self.worker and self.worker.is_alive() else None,
                    "batches": batches,
                    "runs": [dict(zip(("batch_id","ordinal","run_id","profile",
                                      "repeat_index","status"), r)) for r in runs],
                    "ledger": self.ledger.snapshot()}

    def close(self) -> None:
        self.stop_event.set()
        with self.lock:
            if self.current is not None:
                self.current.stop_analysis()
            worker = self.worker
        if worker:
            worker.join(timeout=MAX_BATCH_SECONDS + 180)
            if worker.is_alive():
                raise TimeoutError("batch_shutdown_timeout")
        self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.db.close()
