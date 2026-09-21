"""Loopback fixture HTTP contract; no browser acknowledgements are submitted."""
import json
import threading
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from test_context import ROOT
from conversation_ecology.map_server import make_map_server


class HttpContracts(unittest.TestCase):
    def setUp(self):
        self.server=make_map_server();self.thread=threading.Thread(target=self.server.serve_forever)
        self.thread.start();self.base='http://127.0.0.1:'+str(self.server.server_port)
    def tearDown(self):
        self.server.shutdown();self.thread.join(2);self.server.server_close()
        self.assertFalse(self.thread.is_alive())
    def get(self,path):
        with urlopen(self.base+path,timeout=2) as response:return response.read()
    def test_new_and_old_routes_one_c0_state(self):
        self.assertIn(b'map.js',self.get('/map'));self.assertIn(b'app.js',self.get('/c0'))
        self.assertIn(b'app.js',self.get('/'));self.assertIn(b'href="/map"',self.get('/'))
        self.assertEqual(json.loads(self.get('/api/state'))['session_id'],json.loads(self.get('/api/map'))['c0']['session_id'])
    def test_mutations_require_origin_and_token(self):
        before=self.server.app.map_state()
        request=Request(self.base+'/api/map/action',data=b'{"action":"demo"}',headers={'Content-Type':'application/json'},method='POST')
        with self.assertRaises(HTTPError) as failure:urlopen(request,timeout=2)
        self.assertEqual(failure.exception.code,403);failure.exception.close()
        self.assertEqual(before,self.server.app.map_state())
    def test_sv_is_zero_stub_and_stop_gate_rejects_all_input(self):
        self.assertEqual(json.loads(self.get('/api/sv/state'))['released_position'],0)
        self.server.app.accepting=False
        request=Request(self.base+'/api/action',data=b'{"action":"demo","name":"short"}',headers={'Origin':self.base,'X-C0-Token':self.server.app.token},method='POST')
        with self.assertRaises(HTTPError) as failure:urlopen(request,timeout=2)
        self.assertEqual(failure.exception.code,503);failure.exception.close()


if __name__=='__main__':unittest.main()
