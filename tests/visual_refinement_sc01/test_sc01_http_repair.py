from __future__ import annotations

from http.client import HTTPConnection
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest

from visual_refinement_sc01.repair import FixtureKernel, prepare_live_demo
from visual_refinement_sc01.server_v2 import FixtureServer


class RepairedHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); root=Path(self.temp.name)
        self.kernel=FixtureKernel(root/"state.sqlite3",root/"artifacts"); prepare_live_demo(self.kernel)
        self.server=FixtureServer(self.kernel); self.thread=threading.Thread(target=self.server.serve_forever); self.thread.start()
        self.port=self.server.server_port; self.origin=f"http://127.0.0.1:{self.port}"

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(3); self.kernel.close(); self.temp.cleanup()

    def request(self,method,path,body=None,headers=None):
        conn=HTTPConnection("127.0.0.1",self.port,timeout=3); conn.request(method,path,body=body,headers=headers or {}); response=conn.getresponse(); data=response.read(); status=response.status; conn.close(); return status,data

    def post(self,path,value,origin=None):
        body=json.dumps(value).encode(); return self.request("POST",path,body,{"Content-Type":"application/json","Origin":origin or self.origin,"Content-Length":str(len(body))})

    def test_fx01_live_control_updates_real_ledger(self):
        status,body=self.request("GET","/api/sc01/snapshot?frame=frame_k0"); self.assertEqual(status,200); self.assertEqual(json.loads(body)["queues"][0]["queued"],3)
        status,body=self.post("/api/sc01/fixture/release",{"action":"release_next"}); self.assertEqual(status,200); self.assertEqual(json.loads(body)["lane"],"A")
        _,body=self.request("GET","/api/sc01/snapshot?frame=frame_k0"); view=json.loads(body); self.assertEqual(view["selection"]["winner_id"],"cand_frame_k0_a"); self.assertEqual(view["queues"][0]["succeeded_total"],1)
        self.post("/api/sc01/fixture/release",{"action":"release_next"}); _,body=self.request("GET","/api/sc01/snapshot?frame=frame_k0"); self.assertEqual(json.loads(body)["selection"]["winner_id"],"cand_frame_k0_s")

    def test_fx11_non_object_bad_origin_host_and_query_are_rejected(self):
        self.assertEqual(self.request("POST","/api/sc01/fixture/release",b"[]",{"Content-Type":"application/json","Origin":self.origin,"Content-Length":"2"})[0],400)
        self.assertEqual(self.post("/api/sc01/fixture/release",{"action":"release_next"},"http://127.0.0.1:1")[0],403)
        self.assertEqual(self.request("GET","/api/sc01/snapshot?unknown=1")[0],400)
        self.assertEqual(self.request("GET","/api/sc01/snapshot",headers={"Host":"evil.example"})[0],403)

    def test_fx11_preview_scope_and_artifact_traversal_are_rejected(self):
        self.assertEqual(self.request("GET","/api/sc01/snapshot?preview=cand_other_a")[0],400)
        self.assertEqual(self.request("GET","/api/sc01/artifacts/..%2F.env")[0],400)

    def test_fx10_fixture_can_fail_one_registered_image_without_mutating_it(self):
        status,_=self.post("/api/sc01/fixture/artifact-failure",{"action":"fail_once","artifact_id":"art_frame_k0"}); self.assertEqual(status,200)
        self.assertEqual(self.request("GET","/api/sc01/artifacts/art_frame_k0")[0],503)
        self.assertEqual(self.request("GET","/api/sc01/artifacts/art_frame_k0")[0],200)

    def test_fx11_incomplete_body_does_not_prevent_finite_shutdown(self):
        sock=socket.create_connection(("127.0.0.1",self.port),timeout=2)
        request=(f"POST /api/sc01/fixture/release HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\nOrigin: {self.origin}\r\nContent-Type: application/json\r\nContent-Length: 100\r\n\r\n{{").encode(); sock.sendall(request)
        started=time.monotonic(); self.server.shutdown(); self.server.server_close(); self.thread.join(3); elapsed=time.monotonic()-started; sock.close()
        self.assertFalse(self.thread.is_alive()); self.assertLess(elapsed,3)
        self.server=FixtureServer(self.kernel); self.thread=threading.Thread(target=self.server.serve_forever); self.thread.start(); self.port=self.server.server_port; self.origin=f"http://127.0.0.1:{self.port}"


if __name__=="__main__": unittest.main()
