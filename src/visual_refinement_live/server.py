"""Loopback-only HTTP server for one SC03–SC07 owned run."""
from __future__ import annotations

from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import re
import threading
from urllib.parse import parse_qs, urlsplit

from src.visual_refinement_sc02.server import SC02Handler

from .controller import LiveController
from .analysis import analysis_snapshot, compare_runs
from .store import LiveStore
from .view_sessions import ViewSessionStore

UI_ROOT = Path(__file__).resolve().parents[2] / "ui" / "visual_refinement_sc01"
STATIC = {"/": ("live.html", "text/html; charset=utf-8"),
          "/live.js": ("live.js", "text/javascript; charset=utf-8"),
          "/live.css": ("live.css", "text/css; charset=utf-8"),
          "/style.css": ("style.css", "text/css; charset=utf-8"),
          "/sc02.css": ("sc02.css", "text/css; charset=utf-8")}
ARTIFACT_ID = re.compile(r"^[A-Za-z0-9_-]{1,96}$")


class LiveHandler(SC02Handler):
    server_version = "JevVisualRefinementLive/1"

    @property
    def controller(self) -> LiveController:
        return self.server.controller

    def do_GET(self) -> None:  # noqa: N802
        if not self._allowed(write=False):
            return self._json({"error": "request_denied"}, 403)
        parsed = urlsplit(self.path)
        if parsed.path in STATIC:
            filename, media_type = STATIC[parsed.path]
            return self._send(200, (UI_ROOT / filename).read_bytes(), media_type)
        try:
            query = parse_qs(parsed.query, strict_parsing=bool(parsed.query), max_num_fields=4)
            if parsed.path == "/api/live/snapshot":
                if set(query) - {"cursor"}:
                    raise ValueError("query_field")
                cursor = int(query["cursor"][0]) if "cursor" in query else None
                return self._json(self.controller.snapshot(cursor))
            if parsed.path == "/api/live/k-set":
                if query or self.server.batch_manager is None:
                    raise ValueError("k_set_unavailable")
                return self._json(self.server.batch_manager.k_set())
            if parsed.path == "/api/live/batches":
                if query:
                    raise ValueError("query_field")
                return self._json(self.server.batch_manager.status() if self.server.batch_manager else
                                  {"batches": [], "runs": [], "active_batch_id": None})
            if parsed.path == "/api/live/runs":
                if query:
                    raise ValueError("query_field")
                return self._json(analysis_snapshot())
            if parsed.path == "/api/live/compare":
                if query:
                    raise ValueError("query_field")
                return self._json(compare_runs())
            if parsed.path.startswith("/api/live/runs/"):
                parts = parsed.path.split("/")
                if len(parts) not in (6, 7) or not ARTIFACT_ID.fullmatch(parts[4]):
                    raise ValueError("saved_route")
                saved = LiveStore(parts[4], create=False)
                try:
                    if len(parts) == 6 and parts[5] == "snapshot":
                        if set(query) - {"cursor"}:
                            raise ValueError("query_field")
                        cursor = int(query["cursor"][0]) if "cursor" in query else None
                        view = saved.snapshot(cursor)
                        view.update({"accepting": False, "worker_alive": False,
                                     "selected_count": len(view["frames"]), "max_keyframes": 2,
                                     "active_phase": None, "failure": None})
                        return self._json(view)
                    if (len(parts) == 7 and parts[5] == "artifacts" and
                            ARTIFACT_ID.fullmatch(parts[6]) and set(query) <= {"retry"}):
                        media_type, content = saved.read_artifact(parts[6])
                        return self._send(200, content, media_type)
                    raise ValueError("saved_route")
                finally:
                    saved.close()
            if parsed.path == "/api/live/video":
                if query:
                    raise ValueError("query_field")
                return self._video()
            if parsed.path.startswith("/api/live/artifacts/"):
                if set(query) - {"retry"}:
                    raise ValueError("query_field")
                ident = parsed.path.removeprefix("/api/live/artifacts/")
                if not ARTIFACT_ID.fullmatch(ident):
                    raise ValueError("artifact_id")
                media_type, content = self.controller.store.read_artifact(ident)
                return self._send(200, content, media_type)
        except (ValueError, TypeError, FileNotFoundError):
            return self._json({"error": "invalid_or_unavailable"}, 400)
        return self._json({"error": "not_found"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        if not self._allowed(write=True):
            return self._json({"error": "request_denied"}, 403)
        try:
            payload = self._body()
            if self.path == "/api/live/k-set":
                if self.server.batch_manager is None or set(payload) != {"seconds"}:
                    raise ValueError("k_set_payload")
                return self._json(self.server.batch_manager.save_k_set(tuple(payload["seconds"])))
            if self.path == "/api/live/batch/plan":
                if self.server.batch_manager is None:
                    raise ValueError("batch_unavailable")
                profiles = tuple(payload.get("profiles", ()))
                repeats = payload.get("repeats")
                bucket = payload.get("bucket", "VALIDATION")
                k_seconds = payload.get("k_seconds")
                if (set(payload) - {"profiles", "repeats", "bucket", "k_seconds"} or
                        not isinstance(payload.get("profiles"), list) or
                        not isinstance(k_seconds, list) or
                        not isinstance(repeats, int) or isinstance(repeats, bool)):
                    raise ValueError("batch_plan_payload")
                return self._json(self.server.batch_manager.plan(
                    profiles=profiles, repeats=repeats,
                    k_seconds=tuple(k_seconds), bucket=bucket))
            if self.path == "/api/live/batch/start":
                if self.server.batch_manager is None:
                    raise ValueError("batch_unavailable")
                profiles = tuple(payload.get("profiles", ()))
                repeats = payload.get("repeats")
                bucket = payload.get("bucket", "VALIDATION")
                k_seconds = payload.get("k_seconds")
                if (set(payload) - {"profiles", "repeats", "bucket", "k_seconds"} or
                        not isinstance(payload.get("profiles"), list) or
                        not isinstance(k_seconds, list) or
                        not isinstance(repeats, int) or isinstance(repeats, bool)):
                    raise ValueError("batch_start_payload")
                with self.server.operation_lock:
                    started = self.server.batch_manager.start(
                        profiles=profiles, repeats=repeats,
                        k_seconds=tuple(k_seconds),
                        bucket=bucket)
                return self._json(started, 202)
            if self.path == "/api/live/batch/stop":
                if payload != {"action": "stop"} or self.server.batch_manager is None:
                    raise ValueError("batch_stop_payload")
                self.server.batch_manager.stop()
                return self._json({"accepted": True})
            if self.path == "/api/live/select":
                if set(payload) != {"seconds"} or isinstance(payload["seconds"], bool):
                    raise ValueError("select_payload")
                with self.server.operation_lock:
                    if (self.server.batch_manager and
                            self.server.batch_manager.status()["active_batch_id"]):
                        raise ValueError("batch_active")
                    frame_id = self.controller.select(float(payload["seconds"]))
                return self._json({"accepted": True, "frame_id": frame_id}, 202)
            if self.path == "/api/live/analysis-stop":
                if payload != {"action": "stop"}:
                    raise ValueError("stop_payload")
                self.controller.stop_analysis()
                return self._json({"accepted": True})
            if self.path == "/api/live/view-receipts":
                if set(payload) != {"id", "run_id", "session_id", "frame_id",
                                    "candidate_id", "source_seq", "mode"}:
                    raise ValueError("view_receipt_payload")
                inserted = self.server.view_sessions.record(
                    ident=payload["id"], run_id=payload["run_id"],
                    session_id=payload["session_id"], frame_id=payload["frame_id"],
                    candidate_id=payload["candidate_id"],
                    source_seq=payload["source_seq"], mode=payload["mode"])
                return self._json({"accepted": True, "inserted": inserted}, 201)
            if self.path == "/api/live/receipts":
                if set(payload) != {"id", "session_id", "frame_id", "candidate_id",
                                    "source_seq", "mode"}:
                    raise ValueError("receipt_payload")
                inserted = self.controller.store.receipt(
                    ident=payload["id"], session_id=payload["session_id"],
                    frame_id=payload["frame_id"], candidate_id=payload["candidate_id"],
                    source_seq=payload["source_seq"], mode=payload["mode"])
                return self._json({"accepted": True, "inserted": inserted}, 201)
            if self.path == "/api/live/shutdown":
                if payload != {"action": "shutdown"}:
                    raise ValueError("shutdown_payload")
                self._json({"accepted": True})
                threading.Thread(target=self.server.shutdown, name="live-shutdown",
                                 daemon=True).start()
                return
        except (ValueError, TypeError, json.JSONDecodeError):
            return self._json({"error": "invalid_request"}, 400)
        except TimeoutError:
            return self._json({"error": "request_timeout"}, 408)
        return self._json({"error": "not_found"}, 404)


class LiveServer(ThreadingHTTPServer):
    daemon_threads = False
    block_on_close = True
    allow_reuse_address = False
    request_queue_size = 8

    def __init__(self, controller: LiveController, address: tuple[str, int], batch_manager=None):
        if address[0] != "127.0.0.1":
            raise ValueError("loopback_only")
        self.controller = controller
        self.operation_lock = threading.RLock()
        self.batch_manager = batch_manager
        self.view_sessions = ViewSessionStore()
        self.stopping = False
        self.slots = threading.BoundedSemaphore(8)
        super().__init__(address, LiveHandler)

    def server_close(self) -> None:
        self.stopping = True
        super().server_close()
        self.view_sessions.close()
