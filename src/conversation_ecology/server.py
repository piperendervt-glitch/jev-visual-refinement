"""127.0.0.1専用。新しい依存、外部font、live adapterを使用しない。"""
import argparse
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import socket
import threading
from .demo import run_demo
from .engine import Engine
from .evaluation import FixtureEvaluator
from .isolation import Boundary
from .lifecycle import serve_controlled

ROOT = Path(__file__).resolve().parents[2]
UI = ROOT / "ui" / "conversation_ecology"


class App:
    def __init__(self, boundary=None):
        self.lock = threading.RLock()
        self.token = secrets.token_hex(24)
        self.serial = 0
        self.engine = Engine(FixtureEvaluator(), session_id="fixture-0")
        self.boundary = boundary or Boundary()

    def state(self):
        state = self.engine.view()
        state["token"] = self.token
        state["boundary"] = dict(self.boundary.denied)
        return state

    def action(self, command):
        with self.lock:
            name = command.get("action")
            operation = None
            if name in {"resend", "ack"} and "session_id" in command:
                if command["session_id"] != self.engine.session_id:
                    raise ValueError("stale_session")
            if name == "demo":
                self.serial += 1
                self.engine = run_demo(command.get("name"), f"fixture-{self.serial}")
            elif name == "utterance":
                self.engine.ingest(command.get("text"), revision=command.get("revision", False),
                                   phase=command.get("phase", "finalized"), source=command.get("source", "user_fixture"))
            elif name == "advance": self.engine.advance(command.get("ms"))
            elif name == "evaluate":
                e = self.engine.evaluate(profile=command.get("profile", "balanced"), overrides=command.get("scores"))
                self.engine.decide(e["id"])
            elif name == "ack":
                self.engine.acknowledge(command.get("commit_id"), command.get("evidence"), kind="browser_dom")
            elif name == "resend": operation = self.engine.resend()
            else: raise ValueError("unknown_action")
            # Delivery is an outbox send attempt, not a render acknowledgement.
            if name not in {"ack", "resend"}: self.engine.deliver()
            state = self.state()
            if operation is not None: state["operation"] = operation
            return state


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass

    def send(self, status, body, kind="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.end_headers()
        self.wfile.write(data)

    def allowed(self, mutation=False):
        origin = f"http://127.0.0.1:{self.server.server_port}"
        if self.headers.get("Host") != origin.removeprefix("http://"): return False
        if self.headers.get("Origin") not in (None, origin): return False
        if mutation:
            return self.headers.get("Origin") == origin and hmac.compare_digest(self.headers.get("X-C0-Token", ""), self.server.app.token)
        return True

    def do_GET(self):
        if not self.allowed(): return self.send(403, {"error": "origin_denied"})
        if self.path == "/api/state":
            with self.server.app.lock: return self.send(200, self.server.app.state())
        paths = {"/": ("index.html", "text/html; charset=utf-8"), "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                 "/style.css": ("style.css", "text/css; charset=utf-8"), "/favicon.ico": (None, None)}
        if self.path not in paths: return self.send(404, {"error": "not_found"})
        name, kind = paths[self.path]
        if name is None: return self.send(204, b"")
        return self.send(200, (UI/name).read_bytes(), kind)

    def do_POST(self):
        if self.path != "/api/action" or not self.allowed(True): return self.send(403, {"error": "origin_or_token_denied"})
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 32_000: raise ValueError("request_size")
            body = json.loads(self.rfile.read(size), parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite_json")))
            if not isinstance(body, dict): raise ValueError("request_object")
            return self.send(200, self.server.app.action(body))
        except (ValueError, TypeError, KeyError) as error:
            return self.send(400, {"error": str(error)})


class FixtureServer(ThreadingHTTPServer):
    # http.serverの既定daemon workerを終了の証拠にしない。
    daemon_threads = False
    block_on_close = True

    def __init__(self, *args, **kwargs):
        self.connections = set()
        self.connection_lock = threading.Lock()
        super().__init__(*args, **kwargs)

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(2)
        with self.connection_lock:
            self.connections.add(connection)
        return connection, address

    def shutdown_request(self, request):
        try:
            super().shutdown_request(request)
        finally:
            with self.connection_lock:
                self.connections.discard(request)

    def server_close(self):
        # loop停止後、未送信/途中のHTTP接続も解除してworker終了を待つ。
        with self.connection_lock:
            connections = tuple(self.connections)
        for connection in connections:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass  # 相手/workerが既に閉じたsocket。
        super().server_close()


def make_server(port=8890, boundary=None):
    server = FixtureServer(("127.0.0.1", port), Handler)
    server.app = App(boundary)
    return server


def main():
    parser = argparse.ArgumentParser(description="C0 FIXTURE専用。camera/mic/Jevは未接続。")
    parser.add_argument("--port", type=int, default=8890)
    parser.add_argument("--control-stdin", action="store_true",
                        help="起動端末に表示される stop <run_id> で正常終了する")
    args = parser.parse_args()
    boundary = Boundary()
    boundary.install()
    server = make_server(args.port, boundary)
    if args.control_stdin:
        serve_controlled(server)
        return
    print(f"C0 FIXTURE: http://127.0.0.1:{server.server_port}  "
          "Ctrl+C delivery is environment-dependent; prefer --control-stdin", flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()


if __name__ == "__main__": main()
