"""Bounded, completion-ordered TypeSafe Jev transport.

No SDK import, key read, or network call occurs unless a live evaluator is
explicitly constructed and a committed candidate is enqueued.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import logging
import threading
import time

from .evaluation import SelectionEngine
from .jev_wire import AXES, MODEL_ID, build_state, request_body
from .ledger import BudgetLedger, MAX_REQUEST_BYTES
from .secret_store import SecretProvider, WindowsCredentialManager
from .store import LiveStore

def classify_transport_error(exc: Exception) -> str:
    """Use the SDK's documented status and exception families without logging bodies."""
    status = getattr(exc, "status", None)
    cause = getattr(exc, "__cause__", None)
    names = type(exc).__name__ + " " + (type(cause).__name__ if cause else "")
    if "ResponseValidation" in names:
        return "INVALID_RESPONSE"
    if status in (401, 403):
        return "AUTH"
    if status in (429, 529):
        return "RATE_LIMIT"
    if isinstance(exc, TimeoutError) or "Timeout" in names:
        return "TIMEOUT_UNKNOWN"
    if isinstance(status, int) and status >= 500:
        return "SERVER_ERROR"
    if isinstance(exc, ConnectionError) or "Connection" in names:
        return "CONNECTION_ERROR"
    return "HTTP_ERROR"


class SDKTransport:
    def __init__(self, key: str):
        self._key = key
        logging.getLogger("typesafe_sdk").disabled = True

    def send(self, state: dict, axes: tuple[str, ...]) -> bytes:
        from typesafe_sdk import RetryPolicy, TypeSafeClient
        from .jev_wire import QUESTIONS

        with TypeSafeClient(api_key=self._key, model=MODEL_ID,
                            base_url="https://api.typesafe.ai",
                            retry=RetryPolicy(max_retries=0), timeout=20.0) as client:
            response = client.system_one(state=state,
                                         questions={axis: QUESTIONS[axis] for axis in axes},
                                         model=MODEL_ID)
            return bytes(response.raw_http_response.content)


class JevEvaluator:
    def __init__(self, store: LiveStore, ledger: BudgetLedger, *,
                 secret_provider: SecretProvider | None = None, transport=None,
                 bucket: str = "VALIDATION",
                 is_current=None, origin: str = "REAL_JEV",
                 plan_id: str | None = None):
        if origin not in {"REAL_JEV", "FIXTURE"}:
            raise ValueError("evaluator_origin_invalid")
        self.origin = origin
        self.store = store
        self.ledger = ledger
        self.engine = SelectionEngine(store)
        self.bucket = bucket
        self.plan_id = plan_id
        self.is_current = is_current or (lambda frame_id: True)
        if transport is None:
            if origin != "REAL_JEV":
                raise ValueError("fixture_transport_required")
            key = (secret_provider or WindowsCredentialManager()).get_secret()
            self.transport = SDKTransport(key)
            key = None
        else:
            self.transport = transport
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="jev-eval")
        self.lock = threading.RLock()
        self.circuit_open = False
        self.futures = []

    def enqueue(self, frame_id: str, candidate: dict, measurement: dict,
                *, evidence_version: int, supplementary: dict | None = None) -> str:
        if self.origin == "REAL_JEV" and (
                candidate.get("origin") != "REAL_MODEL" or
                measurement.get("origin") != "REAL_LOCAL_MEASUREMENT" or
                (supplementary is not None and supplementary.get("origin") != "REAL_LOCAL_SUPPLEMENTARY_MEASUREMENT")):
            raise ValueError("real_evaluation_requires_real_measurements")
        state = build_state(candidate["candidate_id"], measurement, supplementary=supplementary)
        body = request_body(state)
        digest = sha256(body).hexdigest()
        lane_id = candidate["lane_id"]
        self.ledger.reserve_suite(run_id=self.store.root.name, frame_id=frame_id,
                                  lane_id=lane_id, evidence_version=evidence_version,
                                  bucket=self.bucket, plan_id=self.plan_id)
        task_id = self.engine.ensure_task(frame_id, candidate["candidate_id"], lane_id,
                                          evidence_version, digest, origin=self.origin)
        job_id = f"job_{task_id}"
        self.store.job(job_id, frame_id, lane_id, "EVALUATION", "EVALUATION_SUITE")
        with self.lock:
            if self.circuit_open:
                self._set_task_status(task_id, "AUTH_CIRCUIT_OPEN")
                self.store.job_state(job_id, "CANCELLED", error_code="AUTH_CIRCUIT_OPEN")
                return task_id
            future = self.executor.submit(self._run_task, task_id, job_id,
                                          frame_id, lane_id, state)
            self.futures.append(future)
        return task_id

    def _set_task_status(self, task_id: str, status: str) -> None:
        with self.store.lock, self.store.db:
            self.store.db.execute("UPDATE eval_tasks SET status=? WHERE id=?",
                                  (status, task_id))

    def _transport_failure(self, task_id: str, attempt_id: str, frame_id: str,
                           lane_id: str, status: str) -> None:
        with self.store.lock, self.store.db:
            seq = self.store._event_uncommitted(
                "EvaluationTransportFailed", frame_id, lane_id,
                {"task_id": task_id, "attempt_id": attempt_id, "status": status})
            index = self.store.db.execute(
                "SELECT COUNT(*) FROM eval_attempts WHERE task_id=?", (task_id,)).fetchone()[0]
            self.store.db.execute("INSERT INTO eval_attempts VALUES(?,?,?,?,?,?,?,?)",
                                  (attempt_id, task_id, index, seq, None, status, status, None))
            self.store.db.execute("UPDATE eval_tasks SET status=? WHERE id=?",
                                  (status, task_id))

    def _run_task(self, task_id: str, job_id: str, frame_id: str,
                  lane_id: str, state: dict) -> None:
        self.store.job_state(job_id, "RUNNING", phase="JEV_HTTP")
        try:
            for index in range(2):
                if not self.is_current(frame_id):
                    self._set_task_status(task_id, "STALE_GENERATION")
                    self.store.job_state(job_id, "CANCELLED", error_code="GENERATION_CLOSED")
                    return
                with self.lock:
                    if self.circuit_open:
                        self._set_task_status(task_id, "AUTH_CIRCUIT_OPEN")
                        self.store.job_state(job_id, "CANCELLED", error_code="AUTH_CIRCUIT_OPEN")
                        return
                missing = self.engine.missing_axes(task_id)
                if not missing:
                    break
                body = request_body(state, missing)
                attempt_id = f"att_{task_id}_{index}"
                self.ledger.reserve_http_attempt(
                    attempt_id=attempt_id, run_id=self.store.root.name,
                    frame_id=frame_id, lane_id=lane_id, body_bytes=MAX_REQUEST_BYTES,
                    questions=len(missing), bucket=self.bucket,
                    plan_id=self.plan_id)
                self.store.event("EvaluationAttemptReserved", frame_id, lane_id,
                                 {"task_id": task_id, "attempt_id": attempt_id,
                                  "questions": list(missing), "body_bytes": len(body)})
                try:
                    raw = self.transport.send(state, missing)
                except Exception as exc:
                    category = classify_transport_error(exc)
                    self.ledger.mark_attempt(
                        attempt_id, category if category in {"TIMEOUT_UNKNOWN", "INVALID_RESPONSE"}
                        else "HTTP_ERROR")
                    self._transport_failure(task_id, attempt_id, frame_id, lane_id, category)
                    if category == "AUTH":
                        with self.lock:
                            self.circuit_open = True
                    if index == 0 and category in {"RATE_LIMIT", "TIMEOUT_UNKNOWN", "SERVER_ERROR", "CONNECTION_ERROR"}:
                        wait = getattr(exc, "retry_after_ms", None)
                        delay = max(0.5, min(5.0, wait / 1000)) if isinstance(wait, int) else 0.5
                        time.sleep(delay)
                        continue
                    self.store.job_state(job_id, "FAILED", error_code=category)
                    return
                outcome = self.engine.accept_attempt(
                    task_id, attempt_id, raw, origin=self.origin,
                    apply_selection=self.is_current(frame_id))
                self.ledger.mark_attempt(attempt_id,
                                         "RESPONSE" if outcome["envelope_status"] == "VALID"
                                         else "INVALID_RESPONSE",
                                         self._usage_from_attempt(attempt_id))
                if outcome["status"] == "COMPLETE":
                    break
            remaining = self.engine.missing_axes(task_id)
            self.store.job_state(job_id, "SUCCEEDED" if not remaining else "FAILED",
                                 error_code=None if not remaining else "PARTIAL_OR_MISSING")
        except Exception as exc:
            code = str(exc)
            category = "BUDGET_STOP" if any(x in code for x in
                ("budget", "plan_capacity", "capacity")) else "WORKER_ERROR"
            self._set_task_status(task_id, category)
            self.store.event("EvaluationWorkerFailed", frame_id, lane_id,
                             {"task_id": task_id, "error_type": type(exc).__name__,
                              "category": category})
            try:
                self.store.job_state(job_id, "FAILED", error_code=type(exc).__name__)
            except ValueError:
                pass

    def _usage_from_attempt(self, attempt_id: str) -> int | None:
        row = self.store.db.execute("SELECT usage_tokens FROM eval_attempts WHERE id=?",
                                    (attempt_id,)).fetchone()
        return row[0] if row else None

    def has_pending(self) -> bool:
        with self.lock:
            return any(not future.done() for future in self.futures)

    def close(self) -> None:
        self.executor.shutdown(wait=True)
        self.transport = None
