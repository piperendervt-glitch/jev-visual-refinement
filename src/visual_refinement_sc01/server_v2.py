"""Strict loopback HTTP boundary for the repaired SC01 fixture UI."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import threading
from urllib.parse import parse_qs, urlsplit

from .repair import FixtureKernel, publish_demo_evidence, release_demo_evidence_step, release_demo_step

UI_ROOT = Path(__file__).resolve().parents[2] / "ui" / "visual_refinement_sc01"
STATIC = {"/": ("index.html", "text/html; charset=utf-8"), "/app.js": ("app.js", "text/javascript; charset=utf-8"),
          "/style.css": ("style.css", "text/css; charset=utf-8"), "/preview.css": ("preview.css", "text/css; charset=utf-8")}


class FixtureHandler(BaseHTTPRequestHandler):
    server_version = "JevFixtureSC01/2"

    @property
    def kernel(self) -> FixtureKernel:
        return self.server.kernel  # type: ignore[attr-defined]

    def setup(self) -> None:
        self._slot = self.server.connection_slots.acquire(timeout=self.server.request_timeout)  # type: ignore[attr-defined]
        if not self._slot:
            raise ConnectionAbortedError("connection_limit")
        super().setup()
        self.connection.settimeout(self.server.request_timeout)  # type: ignore[attr-defined]

    def finish(self) -> None:
        try:
            super().finish()
        finally:
            if getattr(self, "_slot", False):
                self.server.connection_slots.release()  # type: ignore[attr-defined]

    def _headers(self, status: int, media_type: str, length: int) -> None:
        self.send_response(status); self.send_header("Content-Type", media_type); self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store"); self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()

    def _send(self, status: int, body: bytes, media: str = "application/json; charset=utf-8") -> None:
        try:
            self._headers(status, media, len(body)); self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, OSError):
            return

    def _json(self, value: object, status: int = 200) -> None:
        self._send(status, json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode())

    def _authority(self) -> str | None:
        host = self.headers.get("Host")
        if not host or host.count(":") != 1:
            return None
        name, port_text = host.rsplit(":", 1)
        try:
            port = int(port_text)
        except ValueError:
            return None
        if name not in {"127.0.0.1", "localhost"} or port != self.server.server_port:
            return None
        return f"{name}:{port}"

    def _request_allowed(self, *, write: bool) -> bool:
        if self.client_address[0] not in {"127.0.0.1", "::1"} or self.server.stopping:  # type: ignore[attr-defined]
            return False
        authority = self._authority()
        if authority is None:
            return False
        origin = self.headers.get("Origin")
        if origin is None:
            return not write
        try:
            parsed = urlsplit(origin)
            origin_port = parsed.port
        except (ValueError, TypeError):
            return False
        return parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"} and origin_port == self.server.server_port

    def _object_body(self) -> dict:
        media=self.headers.get("Content-Type","").split(";",1)[0].strip().lower()
        if media!="application/json": raise ValueError("content_type")
        raw_length = self.headers.get("Content-Length")
        if raw_length is None or not raw_length.isascii() or not raw_length.isdigit():
            raise ValueError("content_length")
        length = int(raw_length)
        if not 2 <= length <= 16384:
            raise ValueError("body_size")
        try:
            body = self.rfile.read(length)
        except (TimeoutError, socket.timeout) as exc:
            raise TimeoutError("body_timeout") from exc
        if len(body) != length:
            raise TimeoutError("incomplete_body")
        value = json.loads(body)
        if not isinstance(value, dict):
            raise ValueError("object_required")
        return value

    def do_GET(self) -> None:  # noqa: N802
        if not self._request_allowed(write=False):
            return self._json({"error": "request_denied"}, 403)
        parsed = urlsplit(self.path)
        if parsed.path in STATIC:
            name, media = STATIC[parsed.path]; return self._send(200, (UI_ROOT / name).read_bytes(), media)
        try:
            query = parse_qs(parsed.query, strict_parsing=bool(parsed.query), max_num_fields=8)
            if any(len(values)!=1 for values in query.values()): raise ValueError("duplicate_query_field")
            if parsed.path == "/api/sc01/snapshot":
                if set(query) - {"frame", "preview"}: raise ValueError("query_field")
                frame = query.get("frame", ["frame_k0"])[0]; preview = query.get("preview", [None])[0]
                return self._json(self.kernel.view(frame, preview_candidate=preview))
            if parsed.path == "/api/sc01/events":
                if set(query) - {"after", "limit", "until"}: raise ValueError("query_field")
                after = int(query.get("after", ["0"])[0]); limit = int(query.get("limit", ["200"])[0])
                until = int(query["until"][0]) if "until" in query else None
                return self._json(self.kernel.event_page(after, limit, until))
            if parsed.path == "/api/sc01/replay":
                if set(query) - {"frame", "cursor"}: raise ValueError("query_field")
                frame = query.get("frame", ["frame_k0"])[0]; cursor = int(query["cursor"][0]) if "cursor" in query else None
                return self._json(self.kernel.replay(frame, cursor))
            if parsed.path.startswith("/api/sc01/artifacts/"):
                artifact_id = parsed.path.removeprefix("/api/sc01/artifacts/")
                with self.server._connections_lock:
                    if artifact_id in self.server.fail_once_artifacts:
                        self.server.fail_once_artifacts.remove(artifact_id)
                        return self._json({"error": "fixture_artifact_failure"}, 503)
                record, body = self.kernel.artifacts.resolve(artifact_id)
                return self._send(200, body, record["media_type"])
        except (ValueError, TypeError, FileNotFoundError):
            return self._json({"error": "invalid_or_unavailable"}, 400)
        self._json({"error": "not_found"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        if not self._request_allowed(write=True):
            return self._json({"error": "request_denied"}, 403)
        try:
            payload = self._object_body()
            if self.path == "/api/sc01/receipts":
                inserted = self.kernel.receipt(payload); return self._json({"accepted": True, "inserted": inserted}, 201)
            if self.path == "/api/sc01/fixture/release":
                if payload != {"action": "release_next"}: raise ValueError("control_payload")
                return self._json(release_demo_step(self.kernel), 200)
            if self.path == "/api/sc01/fixture/evidence":
                if payload == {"action": "publish_e1"}: return self._json(publish_demo_evidence(self.kernel), 200)
                if payload == {"action": "release_next_e1"}: return self._json(release_demo_evidence_step(self.kernel), 200)
                raise ValueError("control_payload")
            if self.path == "/api/sc01/fixture/artifact-failure":
                if set(payload)!={"action","artifact_id"} or payload["action"]!="fail_once": raise ValueError("control_payload")
                artifact_id=payload["artifact_id"]
                if not isinstance(artifact_id,str) or not self.kernel.db.execute("SELECT 1 FROM records WHERE kind='artifact' AND id=?",(artifact_id,)).fetchone(): raise ValueError("unknown_artifact")
                with self.server._connections_lock: self.server.fail_once_artifacts.add(artifact_id)
                return self._json({"armed": True, "artifact_id": artifact_id}, 200)
        except TimeoutError:
            return self._json({"error": "request_timeout"}, 408)
        except (ValueError, TypeError, json.JSONDecodeError):
            return self._json({"error": "invalid_request"}, 400)
        self._json({"error": "not_found"}, 404)

    def log_message(self, format: str, *args: object) -> None:
        return


class FixtureServer(ThreadingHTTPServer):
    daemon_threads = False
    block_on_close = True
    allow_reuse_address = False
    request_queue_size = 8

    def __init__(self, kernel: FixtureKernel, address: tuple[str, int] = ("127.0.0.1", 0)):
        if address[0] not in {"127.0.0.1", "localhost"}: raise ValueError("loopback_only")
        self.kernel = kernel; self.stopping = False
        self.request_timeout = kernel.profile.request_timeout_seconds
        self.connection_slots = threading.BoundedSemaphore(kernel.profile.max_http_connections)
        self.fail_once_artifacts: set[str] = set()
        self._connections: set[socket.socket] = set(); self._connections_lock = threading.Lock()
        super().__init__(address, FixtureHandler)

    def get_request(self):
        request, address = super().get_request(); request.settimeout(self.request_timeout)
        with self._connections_lock: self._connections.add(request)
        return request, address

    def close_request(self, request):
        with self._connections_lock: self._connections.discard(request)
        super().close_request(request)

    def handle_error(self, request, client_address) -> None:
        # Socket closure during bounded shutdown is an expected control path.
        return

    def server_close(self) -> None:
        self.stopping = True
        with self._connections_lock: connections = list(self._connections)
        for connection in connections:
            try: connection.shutdown(socket.SHUT_RDWR)
            except OSError: pass
            try: connection.close()
            except OSError: pass
        super().server_close()
