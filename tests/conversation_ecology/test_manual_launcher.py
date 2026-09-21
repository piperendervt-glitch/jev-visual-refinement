"""Real .cmd startup/HTTP/shutdown, no model start and no browser substitute."""
import http.cookiejar
import json
from pathlib import Path
import queue
import re
import subprocess
import threading
import unittest
import urllib.request
import urllib.error
from test_saved_video import ROOT


class LauncherTests(unittest.TestCase):
    def test_existing_cmd_mode_security_duplicate_and_cleanup(self):
        commands=['cmd.exe','/d','/c',str(ROOT/'Start-Viewer.cmd'),'--no-browser']
        child=subprocess.Popen(commands,cwd=ROOT.parent,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8')
        messages=queue.Queue();lines=[]
        def collect():
            for line in child.stdout:lines.append(line);messages.put(line)
            messages.put(None)
        reader=threading.Thread(target=collect);reader.start();area=None;url=None
        try:
            while url is None:
                line=messages.get(timeout=30)
                self.assertIsNotNone(line,''.join(lines))
                if line.startswith('終了記録: '):area=Path(line.split(': ',1)[1].strip())
                if line.startswith('Viewer URL: '):url=line.split(': ',1)[1].strip()
            origin=url.removesuffix('/map')
            client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
            with client.open(url,timeout=5) as r:html=r.read().decode()
            self.assertIn('通常利用・ローカル解析 / Jev OFF',html)
            self.assertNotIn('disabled id="sv-file"',html)
            owner=re.search('name="sv-owner" content="([^"]+)"',html).group(1)
            def get(path,headers=None):
                with client.open(urllib.request.Request(origin+path,headers=headers or {}),timeout=5) as r:return json.load(r)
            state=get('/api/state');sv=get('/api/sv/state',{'X-SV-Owner':owner})
            self.assertEqual(sv['mode'],'MANUAL_LOCAL_ANALYSIS');self.assertEqual(sv['budget']['model_loads'],0)
            self.assertEqual(get('/api/map')['view']['provider'],'saved_video')
            bad=urllib.request.Request(origin+'/api/sv/action',data=b'{}',headers={'Origin':origin})
            with self.assertRaises(urllib.error.HTTPError) as error:client.open(bad)
            self.assertEqual(error.exception.code,403)
            headers={'Origin':origin,'X-C0-Token':state['token'],'X-SV-Session':state['session_id'],'X-SV-Owner':owner,'Content-Type':'application/json'}
            bad=urllib.request.Request(origin+'/api/sv/action',data=b'{"action":"select","asset_id":"C:/Windows/not-a-video"}',headers=headers)
            with self.assertRaises(urllib.error.HTTPError) as error:client.open(bad)
            self.assertEqual(error.exception.code,400)
            duplicate=subprocess.run(commands,cwd=ROOT.parent,input='\n',capture_output=True,text=True,encoding='utf-8',timeout=15)
            self.assertEqual(duplicate.returncode,1);self.assertIn('既に起動中',duplicate.stdout)
        finally:
            child.stdin.write('\n');child.stdin.flush();child.stdin.close();child.wait(timeout=30);reader.join();child.stdout.close()
        self.assertEqual(child.returncode,0,''.join(lines))
        result=json.loads((area/'shutdown.json').read_text(encoding='utf-8'))
        self.assertTrue(result['success']);self.assertTrue(result['temporary_content_removed']);self.assertTrue(result['actual_pid_exited'])
        self.assertEqual(result['python_exit_code'],0);self.assertTrue(result['port_closed'])
        self.assertFalse((area/'content').exists())

if __name__=='__main__':unittest.main()
