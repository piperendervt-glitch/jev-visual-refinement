"""HTTP trust boundary with synthetic bytes, never a browser substitute."""
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from conversation_ecology.server import App
from conversation_ecology.saved_video.server import SVServer, SVHandler
from conversation_ecology.saved_video.media import Assets
from conversation_ecology.saved_video.budget import Budget
from conversation_ecology.saved_video.controller import Controller
from conversation_ecology.saved_video.models import LocalAnalyzers
PROFILE=json.loads((ROOT/'config/sv01.json').read_text())


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();root=Path(self.tmp.name)
        self.s=SVServer(('127.0.0.1',0),SVHandler);self.s.app=App();self.s.upload_lock=threading.Lock()
        self.s.sv=Controller(Assets(root/'media',PROFILE),Budget(root/'budget.json',PROFILE),LocalAnalyzers(),PROFILE)
        self.t=threading.Thread(target=self.s.serve_forever,kwargs={'poll_interval':.01});self.t.start()
        self.origin=f'http://127.0.0.1:{self.s.server_port}'
        self.headers={'Origin':self.origin,'X-C0-Token':self.s.app.token,'X-SV-Session':'fixture-0',
                      'Cookie':'SV01='+self.s.app.token,'X-SV-Suffix':'.mp4'}
    def tearDown(self):
        self.s.shutdown();self.t.join();self.s.server_close();self.tmp.cleanup()
    def req(self,path,body=None,headers=None):
        c=http.client.HTTPConnection('127.0.0.1',self.s.server_port,timeout=2)
        c.request('POST' if body is not None else 'GET',path,body, self.headers if headers is None else headers)
        r=c.getresponse();result=(r.status,dict(r.getheaders()),r.read());c.close();return result
    def upload(self):
        with patch('conversation_ecology.saved_video.media.probe',return_value={'decoder':'synthetic'}):
            status,_,data=self.req('/api/sv/upload',b'0123456789')
        self.assertEqual(status,200);return json.loads(data)['asset_id']
    def test_upload_auth_origin_session_and_path(self):
        for changes in ({'X-C0-Token':'bad'},{'Origin':'https://evil.invalid'},{'X-SV-Session':'old'}):
            headers={**self.headers,**changes}
            self.assertIn(self.req('/api/sv/upload',b'abc',headers)[0],(400,403))
        self.assertEqual(self.req('/media/../../.env?session=fixture-0')[0],400)
        self.assertEqual(self.req('/api/sv/state',headers={})[0],403)
    def test_registered_range_same_bytes_and_cookie(self):
        ident=self.upload();url='/media/'+ident+'?session=fixture-0'
        self.assertEqual(self.req(url,headers={})[0],403)
        status,headers,data=self.req(url,headers={**self.headers,'Range':'bytes=2-5'})
        self.assertEqual((status,data),(206,b'2345'));self.assertEqual(headers['Content-Range'],'bytes 2-5/10')
        self.assertEqual(self.req(url,headers={**self.headers,'Range':'bytes=50-'})[0],416)
    def test_session_change_revokes_asset_delivery_and_epoch(self):
        ident=self.upload()
        self.req('/api/sv/action',json.dumps({'action':'select','asset_id':ident}))
        old=self.s.sv.epoch
        self.req('/api/action',json.dumps({'action':'demo','name':'short'}))
        self.assertGreater(self.s.sv.epoch,old)
        self.assertIsNone(self.s.sv.asset_id)
        self.assertEqual(self.req('/media/'+ident+'?session=fixture-0')[0],400)
    def test_csp_and_device_permissions(self):
        status,headers,data=self.req('/')
        self.assertEqual(status,200)
        self.assertIn("media-src 'self'",headers['Content-Security-Policy'])
        self.assertIn('camera=()',headers['Permissions-Policy'])
        self.assertIn(b'saved-video.js',data)


if __name__=='__main__':unittest.main()
