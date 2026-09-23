"""Same-origin loopback HTTP boundary for the approved SC02 run."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import socket
import threading
from urllib.parse import parse_qs, urlsplit

from .controller import RunController

UI_ROOT = Path(__file__).resolve().parents[2] / "ui" / "visual_refinement_sc01"
STATIC = {"/": ("sc02.html", "text/html; charset=utf-8"),
          "/sc02.js": ("sc02.js", "text/javascript; charset=utf-8"),
          "/style.css": ("style.css", "text/css; charset=utf-8"),
          "/sc02.css": ("sc02.css", "text/css; charset=utf-8")}
ARTIFACT_ID = re.compile(r"^[a-zA-Z0-9_-]{1,96}$")


class SC02Handler(BaseHTTPRequestHandler):
    server_version = "JevSC02/1"

    @property
    def controller(self) -> RunController:
        return self.server.controller  # type: ignore[attr-defined]

    def setup(self) -> None:
        self._slot = self.server.slots.acquire(timeout=2)  # type: ignore[attr-defined]
        if not self._slot:
            raise ConnectionAbortedError("connection_limit")
        super().setup()
        self.connection.settimeout(4)

    def finish(self) -> None:
        try:
            super().finish()
        finally:
            if getattr(self, "_slot", False):
                self.server.slots.release()  # type: ignore[attr-defined]

    def _headers(self, status: int, media: str, length: int, extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", media)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; img-src 'self'; media-src 'self'; script-src 'self'; "
                         "style-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()

    def _send(self, status: int, body: bytes, media: str = "application/json; charset=utf-8") -> None:
        try:
            self._headers(status, media, len(body))
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, OSError):
            return

    def _json(self, value: object, status: int = 200) -> None:
        self._send(status, json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))

    def _allowed(self, write: bool) -> bool:
        if self.client_address[0] not in {"127.0.0.1", "::1"} or self.server.stopping:  # type: ignore[attr-defined]
            return False
        host = self.headers.get("Host", "")
        if host not in {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}:
            return False
        origin = self.headers.get("Origin")
        if origin is None:
            return not write
        parsed = urlsplit(origin)
        return parsed.scheme == "http" and parsed.netloc in {
            f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}

    def _body(self) -> dict:
        if self.headers.get("Content-Type", "").split(";", 1)[0] != "application/json":
            raise ValueError("content_type")
        raw = self.headers.get("Content-Length", "")
        if not raw.isascii() or not raw.isdigit() or not 2 <= int(raw) <= 16384:
            raise ValueError("content_length")
        body = self.rfile.read(int(raw))
        if len(body) != int(raw):
            raise TimeoutError("incomplete_body")
        value = json.loads(body)
        if not isinstance(value, dict):
            raise ValueError("object_required")
        return value

    def _video(self) -> None:
        info = self.controller.video
        if info is None:
            return self._json({"error": "saved_view_has_no_source_stream"}, 404)
        size = info.byte_count
        start, end = 0, size - 1
        value = self.headers.get("Range")
        if value is not None:
            match = re.fullmatch(r"bytes=(\d+)-(\d*)", value)
            if not match:
                return self._json({"error": "invalid_range"}, 416)
            start = int(match.group(1))
            end = int(match.group(2)) if match.group(2) else size - 1
            if start >= size or end < start:
                return self._json({"error": "range_outside_video"}, 416)
            end = min(end, size - 1)
        length = end - start + 1
        extra = {"Accept-Ranges": "bytes"}
        if value is not None:
            extra["Content-Range"] = f"bytes {start}-{end}/{size}"
        try:
            self._headers(206 if value is not None else 200, "video/mp4", length, extra)
            with info.path.open("rb") as stream:
                stream.seek(start)
                remaining = length
                while remaining:
                    chunk = stream.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError, OSError):
            return

    def do_GET(self) -> None:  # noqa: N802
        if not self._allowed(write=False):
            return self._json({"error": "request_denied"}, 403)
        parsed = urlsplit(self.path)
        if parsed.path in STATIC:
            filename, media = STATIC[parsed.path]
            return self._send(200, (UI_ROOT / filename).read_bytes(), media)
        try:
            query = parse_qs(parsed.query, strict_parsing=bool(parsed.query), max_num_fields=4)
            if parsed.path == "/api/sc02/snapshot":
                if set(query) - {"cursor"}:
                    raise ValueError("query_field")
                cursor = int(query["cursor"][0]) if "cursor" in query else None
                return self._json(self.controller.snapshot(cursor))
            if parsed.path == "/api/sc02/video":
                if query:
                    raise ValueError("query_field")
                return self._video()
            if parsed.path.startswith("/api/sc02/artifacts/"):
                if set(query) - {"retry"} or ("retry" in query and (len(query["retry"]) != 1 or not query["retry"][0].isdigit())):
                    raise ValueError("query_field")
                ident = parsed.path.removeprefix("/api/sc02/artifacts/")
                if not ARTIFACT_ID.fullmatch(ident):
                    raise ValueError("artifact_id")
                media, data = self.controller.store.read_artifact(ident)
                return self._send(200, data, media)
        except (ValueError, TypeError, FileNotFoundError):
            return self._json({"error": "invalid_or_unavailable"}, 400)
        self._json({"error": "not_found"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        if not self._allowed(write=True):
            return self._json({"error": "request_denied"}, 403)
        try:
            payload = self._body()
            if self.path == "/api/sc02/select":
                if set(payload) != {"seconds"} or isinstance(payload["seconds"], bool):
                    raise ValueError("select_payload")
                ident = self.controller.select(float(payload["seconds"]))
                return self._json({"accepted": True, "frame_id": ident}, 202)
            if self.path == "/api/sc02/analysis-stop":
                if payload != {"action": "stop"}:
                    raise ValueError("stop_payload")
                self.controller.stop_analysis()
                return self._json({"accepted": True})
            if self.path == "/api/sc02/reset":
                if payload != {"action": "reset"}:
                    raise ValueError("reset_payload")
                self.controller.reset()
                return self._json({"accepted": True})
            if self.path == "/api/sc02/receipts":
                inserted = self.controller.store.receipt(payload)
                return self._json({"accepted": True, "inserted": inserted}, 201)
            if self.path == "/api/sc02/shutdown":
                if payload != {"action": "shutdown"}:
                    raise ValueError("shutdown_payload")
                self._json({"accepted": True})
                threading.Thread(target=self.server.shutdown, name="sc02-shutdown", daemon=True).start()
                return
        except (ValueError, TypeError, json.JSONDecodeError):
            return self._json({"error": "invalid_request"}, 400)
        except TimeoutError:
            return self._json({"error": "request_timeout"}, 408)
        self._json({"error": "not_found"}, 404)

    def log_message(self, format: str, *args: object) -> None:
        return


class SC02Server(ThreadingHTTPServer):
    daemon_threads = False
    block_on_close = True
    allow_reuse_address = False
    request_queue_size = 8

    def __init__(self, controller: RunController, address: tuple[str, int]):
        if address[0] != "127.0.0.1":
            raise ValueError("loopback_only")
        self.controller = controller
        self.stopping = False
        self.slots = threading.BoundedSemaphore(8)
        super().__init__(address, SC02Handler)

    def server_close(self) -> None:
        self.stopping = True
        super().server_close()
