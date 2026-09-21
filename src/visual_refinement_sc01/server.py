"""Loopback-only HTTP boundary for the SC01 fixture UI."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .core import FixtureKernel


UI_ROOT = Path(__file__).resolve().parents[2] / "ui" / "visual_refinement_sc01"
STATIC = {"/": ("index.html", "text/html; charset=utf-8"),
          "/app.js": ("app.js", "text/javascript; charset=utf-8"),
          "/style.css": ("style.css", "text/css; charset=utf-8"),
          "/preview.css": ("preview.css", "text/css; charset=utf-8")}


class FixtureHandler(BaseHTTPRequestHandler):
    server_version = "JevFixtureSC01/1"

    @property
    def kernel(self) -> FixtureKernel:
        return self.server.kernel  # type: ignore[attr-defined]

    def _headers(self, status: int, media_type: str, length: int) -> None:
        self.send_response(status)
        self.send_header("Content-Type", media_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()

    def _send(self, status: int, body: bytes, media_type: str = "application/json; charset=utf-8") -> None:
        self._headers(status, media_type, len(body))
        self.wfile.write(body)

    def _json(self, value: object, status: int = 200) -> None:
        self._send(status, json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode())

    def _origin_ok(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        try:
            parsed = urlsplit(origin)
        except ValueError:
            return False
        return parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"} and parsed.port == self.server.server_port

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlsplit(self.path)
        if parsed.path in STATIC:
            name, media = STATIC[parsed.path]
            body = (UI_ROOT / name).read_bytes()
            return self._send(200, body, media)
        if parsed.path == "/api/sc01/snapshot":
            query = parse_qs(parsed.query)
            preview = query.get("preview", [None])[0]
            return self._json(self.kernel.view("frame_k0", preview_candidate=preview))
        if parsed.path == "/api/sc01/events":
            query = parse_qs(parsed.query)
            try:
                after = int(query.get("after", ["0"])[0])
                limit = int(query.get("limit", ["200"])[0])
                return self._json({"events": self.kernel.event_page(after, limit)})
            except (ValueError, TypeError):
                return self._json({"error": "invalid_cursor"}, 400)
        if parsed.path.startswith("/api/sc01/artifacts/"):
            artifact_id = parsed.path.removeprefix("/api/sc01/artifacts/")
            try:
                record, body = self.kernel.artifacts.resolve(artifact_id)
            except (ValueError, FileNotFoundError):
                return self._json({"error": "artifact_unavailable"}, 404)
            return self._send(200, body, record["media_type"])
        self._json({"error": "not_found"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/api/sc01/receipts":
            return self._json({"error": "not_found"}, 404)
        if not self._origin_ok():
            return self._json({"error": "origin_denied"}, 403)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 2 or length > 16384:
                raise ValueError("body_size")
            payload = json.loads(self.rfile.read(length))
            self.kernel.receipt(payload)
        except (ValueError, TypeError, json.JSONDecodeError):
            return self._json({"error": "invalid_receipt"}, 400)
        self._json({"accepted": True}, 201)

    def log_message(self, format: str, *args: object) -> None:
        return


class FixtureServer(ThreadingHTTPServer):
    daemon_threads = False
    allow_reuse_address = False

    def __init__(self, kernel: FixtureKernel, address: tuple[str, int] = ("127.0.0.1", 0)):
        if address[0] not in {"127.0.0.1", "localhost"}:
            raise ValueError("loopback_only")
        self.kernel = kernel
        super().__init__(address, FixtureHandler)
