"""Fixed owned worker closure; no model objects or heavy lock in the control parent."""
import json
import ctypes
import os
import queue
from pathlib import Path
import subprocess
import sys
import threading
import time
from .resource_metrics import ram_sample,process_sample


class WorkerFailure(RuntimeError):
    def __init__(self,message,native=False):super().__init__(message);self.native=native


class RemoteLane:
    def __init__(self,manager,kind,index):
        self.manager=manager;self.kind=kind;self.ident=f'{kind}-{index}'
        ticket=manager.budget.load(kind,self.ident)
        spec=dict(lane=kind,worker_id=self.ident,load_ticket=ticket,candidate=manager.candidate,model_root=str(manager.model_root),cohort=manager.budget.data['cohort'])
        if manager.profile.get('manual_local'):
            spec['mode']='MANUAL_LOCAL_ANALYSIS'
            spec['settings_sha256']=manager.budget.settings_sha256
        path=manager.area/(self.ident+'.json');path.write_text(json.dumps(spec),encoding='utf-8')
        command=[sys.executable,'-B','-X','utf8',str(manager.root/'scripts/sv01_resource_worker.py'),'--spec',str(path)]
        manager.boundary.allowed_process_commands.add(tuple(command))
        manager.boundary.allowed_process_commands.add(subprocess.list2cmdline(command))
        self.errors=(manager.area/(self.ident+'-stderr.txt')).open('w',encoding='utf-8')
        self.child=subprocess.Popen(command,cwd=manager.root,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                                    stderr=self.errors,text=True,encoding='utf-8',bufsize=1)
        self.closed=False;self.process_handle=None;self.info=dict(worker=self.ident,launcher_pid=self.child.pid,load_ticket=ticket,command=command)
        self.inbox=None;self.pipe_eof=False
        if manager.profile.get('manual_local'):
            self.inbox=queue.Queue(maxsize=8)
            def read_lines():
                for line in iter(lambda:self.child.stdout.readline(262145),''):self.inbox.put(line)
                self.inbox.put(None)
            self.reader=threading.Thread(target=read_lines,name='manual-worker-pipe',daemon=False);self.reader.start()
        manager.executors.append(self)
        if hasattr(manager,'record_worker'):manager.record_worker(self.child.pid)
        try:
            ready=self.read()
            if ready.get('stage')=='booted' and manager.profile.get('manual_local'):
                manager.record_worker(ready['pid']);ready=self.read()
            if ready['stage']!='ready':raise WorkerFailure('worker_not_ready:'+str(ready)[:300])
            self.info.update(ready=ready,pid=ready['metrics']['pid'])
            if hasattr(manager,'record_worker'):manager.record_worker(self.info['pid'])
            if os.name=='nt':
                self.kernel=ctypes.WinDLL('kernel32',use_last_error=True)
                self.kernel.OpenProcess.restype=ctypes.c_void_p
                self.kernel.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_ulong]
                self.kernel.GetExitCodeProcess.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_ulong)]
                self.kernel.CloseHandle.argtypes=[ctypes.c_void_p]
                self.process_handle=self.kernel.OpenProcess(0x100000|0x1000,False,self.info['pid'])
                if not self.process_handle:raise WorkerFailure('owned_worker_handle_unavailable')
            manager.status[kind]=dict(state='ready',workers=[e.info for e in manager.executors if e.kind==kind])
        except Exception:
            self.close();raise

    def send(self,data):
        self.child.stdin.write(json.dumps(data,ensure_ascii=False,allow_nan=False)+'\n');self.child.stdin.flush()

    def read(self):
        try:raw=self.inbox.get(timeout=self.manager.profile['worker_io_timeout_seconds']) if self.inbox else self.child.stdout.readline(262145)
        except queue.Empty:raise WorkerFailure('worker_io_timeout; native cleanup still awaited')
        if not raw:
            self.pipe_eof=True
            code=self.child.wait();raise WorkerFailure('worker_exit:'+str(code),native=bool(code and code&0x80000000))
        if len(raw)>262144:raise WorkerFailure('worker_response_limit')
        data=json.loads(raw)
        if data.get('stage')=='failed':raise WorkerFailure('worker_failed:'+data['reason'])
        return data

    def decode(self,job):
        asset={**job['asset'],'path':str(job['asset']['path'])}
        self.send(dict(action='decode',asset=asset,interval=job['interval'],envelope=job['envelope']))
        value=self.read()
        if value['stage']!='decoded':raise WorkerFailure('decode_protocol')
        return value

    def infer(self,ticket):
        self.send(dict(action='infer',ticket=ticket));value=self.read()
        if value['stage']!='result' or value['ticket']!=ticket:raise WorkerFailure('result_ticket_mismatch')
        return value

    def cancel(self):self.send(dict(action='cancel'))

    def close(self):
        if self.closed:return
        self.closed=True
        if self.child.poll() is None:
            try:self.send(dict(action='stop'))
            except (BrokenPipeError,OSError):pass
        self.child.stdin.close()
        if self.inbox:
            lines=[]
            while not self.pipe_eof:
                line=self.inbox.get()
                if line is None:self.pipe_eof=True;break
                lines.append(line)
            self.reader.join();tail=''.join(lines)
        else:tail=self.child.stdout.read()
        code=self.child.wait();self.child.stdout.close();self.errors.close()
        self.info.update(exit_code=code,closed=True,closed_at=time.time(),final_messages=tail)
        if self.process_handle:
            value=ctypes.c_ulong()
            self.info['actual_pid_gone']=self.kernel.WaitForSingleObject(self.process_handle,0)==0
            self.info['actual_exit_code']=value.value if self.kernel.GetExitCodeProcess(self.process_handle,ctypes.byref(value)) else None
            self.kernel.CloseHandle(self.process_handle);self.process_handle=None
        if code:raise WorkerFailure('worker_exit:'+str(code),native=bool(code&0x80000000))


class ResourceModels:
    def __init__(self,root,area,model_root,profile,candidate,budget,boundary):
        self.root,self.area,self.model_root=root,area,model_root
        self.profile,self.candidate,self.budget,self.boundary=profile,candidate,budget,boundary
        self.config=profile['candidates'][candidate];self.executors=[]
        self.status={kind:dict(state='loading') for kind in ('asr','image')}
        self.gpu=None;self.samples=[];self.done=threading.Event()
        self.gpu_command=['nvidia-smi','--query-gpu=memory.total,memory.free,utilization.gpu,temperature.gpu,clocks.current.graphics','--format=csv,noheader,nounits']
        boundary.allowed_process_commands.add(tuple(self.gpu_command))
        boundary.allowed_process_commands.add(subprocess.list2cmdline(self.gpu_command))
        self.monitor=threading.Thread(target=self.observe,name='resource-observer',daemon=False);self.monitor.start()

    def observe(self):
        with (self.area/'resource-usage.jsonl').open('w',encoding='utf-8') as stream:
            while not self.done.is_set():
                row=dict(at=time.monotonic(),ram=ram_sample(),parent=process_sample())
                try:
                    r=subprocess.run(self.gpu_command,capture_output=True,text=True,timeout=2)
                    values=r.stdout.strip().split(',') if r.returncode==0 else []
                    if len(values)==5:
                        self.gpu={key:float(value.strip()) if value.strip() not in ('N/A','[N/A]') else None for key,value in zip(('total_mib','free_mib','util_percent','temperature_c','graphics_mhz'),values)}
                    else:self.gpu=None
                except Exception:self.gpu=None
                row['gpu']=self.gpu;self.samples.append(row);stream.write(json.dumps(row)+'\n');stream.flush()
                if self.profile.get('manual_local'):
                    self.samples=self.samples[-128:]
                    if stream.tell()>1024*1024:stream.seek(0);stream.truncate()
                self.done.wait(2)

    def image_headroom(self):
        self.budget.check()
        ram=ram_sample();gpu=self.gpu
        return bool(ram['available'] is not None and ram['available']>=max(4*1024**3,ram['total']*.15)
                    and gpu and gpu['free_mib'] is not None and gpu['free_mib']>=max(2048,gpu['total_mib']*.10))

    def open(self,kind,index):return RemoteLane(self,kind,index)
    def close(self):
        errors=[]
        try:
            for executor in self.executors:
                try:executor.close()
                except Exception as error:errors.append(error)
        finally:
            self.done.set();self.monitor.join()
            (self.area/'workers.json').write_text(json.dumps([e.info for e in self.executors],indent=2),encoding='utf-8')
        if errors:raise errors[0]
