from __future__ import annotations

from http.client import HTTPConnection
import json
from pathlib import Path
import tempfile
import threading
import unittest

from visual_refinement_sc01.core import FixtureKernel, build_demo
from visual_refinement_sc01.server import FixtureServer


class HTTPBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.kernel = FixtureKernel(root / "state.sqlite3", root / "artifacts")
        build_demo(self.kernel)
        self.server = FixtureServer(self.kernel)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.conn = HTTPConnection("127.0.0.1", self.server.server_port, timeout=2)

    def tearDown(self):
        self.conn.close(); self.server.shutdown(); self.server.server_close(); self.thread.join()
        self.kernel.close(); self.tmp.cleanup()

    def get(self, path):
        self.conn.request("GET", path); return self.conn.getresponse()

    def test_snapshot_static_and_registered_artifact_only(self):
        response = self.get("/"); self.assertEqual(response.status, 200); self.assertIn(b"FIXTURE", response.read())
        response = self.get("/api/sc01/snapshot"); self.assertEqual(response.status, 200)
        view = json.loads(response.read()); self.assertEqual(len(view["rows"]), 4)
        self.assertEqual(view["preview"]["keyframe_artifact_ref"], "art_frame_k0")
        response = self.get("/api/sc01/artifacts/art_mask_frame_k0_s"); self.assertEqual(response.status, 200); self.assertEqual(response.getheader("Content-Type"), "image/svg+xml"); response.read()
        response = self.get("/api/sc01/artifacts/..%2F.env"); self.assertEqual(response.status, 404); response.read()

    def test_event_page_is_finite_and_origin_is_rejected(self):
        response = self.get("/api/sc01/events?limit=201"); self.assertEqual(response.status, 400); response.read()
        body = json.dumps({"receipt_id":"receipt_http","view_session_id":"view_http","source_commit_seq":1,
            "frame_id":"frame_k0","display_mode":"FOLLOW_SELECTION","visible":True}).encode()
        self.conn.request("POST", "/api/sc01/receipts", body=body,
            headers={"Content-Type":"application/json","Origin":"https://evil.example","Content-Length":str(len(body))})
        response = self.conn.getresponse(); self.assertEqual(response.status, 403); response.read()

    def test_server_rejects_non_loopback_bind(self):
        with self.assertRaises(ValueError):
            FixtureServer(self.kernel, ("0.0.0.0", 0))


if __name__ == "__main__":
    unittest.main()
