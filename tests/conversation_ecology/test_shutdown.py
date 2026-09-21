"""C0停止専用。実Python子のexit codeとloopback資源を外側で検証する。"""
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import queue
import socket
import subprocess
import sys
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from conversation_ecology.lifecycle import StopRequest, serve_controlled


class ManagedFixture:
    """試験ハーネス側のみ。アプリの能力guard内では子processを作らない。"""
    def __init__(self):
        self.spawned_utc = datetime.now(timezone.utc).isoformat()
        self.command = [sys.executable, "-B", "-X", "utf8",
                        str(ROOT / "scripts/c0_fixture.py"), "--port", "0", "--control-stdin"]
        self.process = subprocess.Popen(self.command, cwd=ROOT, stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        text=True, encoding="utf-8", bufsize=1)
        self.events = []
        self.messages = queue.Queue()
        self.forced = False

        def collect():
            for line in self.process.stdout:
                event = json.loads(line)
                self.events.append(event)
                self.messages.put(event)

        self.reader = threading.Thread(target=collect, name="c0-test-output", daemon=False)
        self.reader.start()
        try:
            self.ready = self.messages.get(timeout=10)
            assert self.ready["stage"] == "ready"
            assert self.ready["pid"] == self.process.pid
        except BaseException:
            self.recover()
            raise

    def send(self, line):
        self.process.stdin.write(line + "\n")
        self.process.stdin.flush()

    def finish(self, line=None):
        requested = time.monotonic()
        if line is not None:
            self.send(line)
        self.process.stdin.close()
        self.process.stdin = None
        try:
            code = self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.recover()
            raise
        self.reader.join(timeout=2)
        if self.reader.is_alive():
            raise RuntimeError("test_output_reader_not_closed")
        stderr = self.process.stderr.read()
        self.process.stdout.close()
        self.process.stderr.close()
        with socket.socket() as probe:
            probe.settimeout(1)
            port_closed = probe.connect_ex(("127.0.0.1", self.ready["port"])) != 0
        return dict(spawned_utc=self.spawned_utc, parent_pid=os.getpid(),
                    pid=self.process.pid, command=self.command, ready=self.ready,
                    events=self.events, python_exit_code=code,
                    owned_process_handle_exited=self.process.poll() is not None,
                    loopback_connect_refused=port_closed,
                    stop_elapsed_seconds=time.monotonic()-requested,
                    forced_cleanup=self.forced, stderr=stderr)

    def recover(self):
        # Popenが保持する当該子のOS handleに限定。名前検索・PID再利用なし。
        if self.process.poll() is None:
            self.forced = True
            self.process.kill()
        self.process.wait(timeout=10)
        if self.process.stdin is not None:
            self.process.stdin.close()
        self.reader.join(timeout=2)
        self.process.stdout.close()
        self.process.stderr.close()


class ShutdownContracts(unittest.TestCase):
    def test_run_binding_rejection_and_duplicate(self):
        request = StopRequest("current")
        for invalid in ("stop old", "stop", "GET /", "stop current extra"):
            self.assertFalse(request.accept(invalid))
        self.assertTrue(request.accept("stop current\n"))
        self.assertFalse(request.accept("stop current"))

    def test_cleanup_failure_propagates_without_completion_record(self):
        class BrokenClose:
            server_port = 0
            def __init__(self): self.stopped = threading.Event()
            def serve_forever(self, **kwargs): self.stopped.wait(2)
            def shutdown(self): self.stopped.set()
            def server_close(self): raise OSError("test_cleanup_failure")
        output = io.StringIO()
        with self.assertRaisesRegex(OSError, "test_cleanup_failure"):
            serve_controlled(BrokenClose(), io.StringIO(""), output)
        self.assertNotIn("cleanup_completed", output.getvalue())

    def test_loop_failure_propagates_after_cleanup(self):
        class BrokenLoop:
            server_port = 0
            closed = False
            def serve_forever(self, **kwargs): raise ValueError("test_loop_failure")
            def shutdown(self): pass
            def server_close(self): self.closed = True
        server = BrokenLoop()
        with self.assertRaisesRegex(RuntimeError, "C0_serve_loop_failed"):
            serve_controlled(server, io.StringIO(""), io.StringIO())
        self.assertTrue(server.closed)


class ShutdownProcesses(unittest.TestCase):
    def assert_clean(self, result):
        self.assertEqual(result["python_exit_code"], 0, result)
        self.assertFalse(result["forced_cleanup"])
        self.assertTrue(result["owned_process_handle_exited"])
        self.assertTrue(result["loopback_connect_refused"])
        self.assertLess(result["stop_elapsed_seconds"], 10)
        stages = [e["stage"] for e in result["events"]]
        self.assertEqual(stages.count("stop_accepted"), 1)
        self.assertLess(stages.index("stop_accepted"), stages.index("loop_ended"))
        self.assertLess(stages.index("loop_ended"), stages.index("cleanup_completed"))
        self.assertFalse(result["events"][-1]["loop_thread_alive"])

    def test_S01_idle_stop(self):
        child = ManagedFixture()
        try: self.assert_clean(child.finish(child.ready["stop_command"]))
        finally: child.recover()

    def test_wrong_run_rejected_before_valid_stop(self):
        child = ManagedFixture()
        try:
            child.send("stop old-run")
            self.assertEqual(child.messages.get(timeout=3)["stage"], "stop_rejected")
            self.assertIsNone(child.process.poll())
            self.assert_clean(child.finish(child.ready["stop_command"]))
        finally: child.recover()

    def test_duplicate_stop_accepted_once(self):
        child = ManagedFixture()
        try:
            command = child.ready["stop_command"]
            self.assert_clean(child.finish(command + "\n" + command))
        finally: child.recover()

    def test_idle_http_connection_is_closed_and_joined(self):
        child = ManagedFixture()
        try:
            with socket.create_connection(("127.0.0.1", child.ready["port"]), timeout=2) as conn:
                conn.sendall(b"GET / HTTP/1.1\r\n")  # 未完のrequest worker。
                self.assert_clean(child.finish(child.ready["stop_command"]))
                try:
                    self.assertEqual(conn.recv(1), b"")
                except ConnectionResetError:
                    # Windows may return RST for an incomplete HTTP request.
                    # Process code, joined workers and cleanup were checked above.
                    pass
        finally: child.recover()

    def test_stdin_eof_uses_cleanup(self):
        child = ManagedFixture()
        try: self.assert_clean(child.finish())
        finally: child.recover()

    def test_invalid_control_is_not_success_exit(self):
        child = ManagedFixture()
        try:
            result = child.finish("x" * 128)
            self.assertNotEqual(result["python_exit_code"], 0)
            self.assertFalse(result["forced_cleanup"])
            self.assertTrue(result["loopback_connect_refused"])
            self.assertIn("cleanup_completed", [e["stage"] for e in result["events"]])
            self.assertNotIn("stop_accepted", [e["stage"] for e in result["events"]])
        finally: child.recover()


if __name__ == "__main__":
    unittest.main()
