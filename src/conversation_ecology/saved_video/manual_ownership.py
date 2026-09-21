"""Windows process handles and removal limited to owned manual-run content."""
import ctypes
import json
import os
import shutil
from .manual import AREA,MODE
from .media import plain_path


class ProcessHandle:
    def __init__(self,pid):
        self.pid=pid;self.kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        self.kernel.OpenProcess.restype=ctypes.c_void_p
        self.kernel.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_ulong]
        self.kernel.GetExitCodeProcess.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_ulong)]
        self.kernel.CloseHandle.argtypes=[ctypes.c_void_p]
        self.handle=self.kernel.OpenProcess(0x100000|0x1000,False,pid)
        if not self.handle:raise OSError(ctypes.get_last_error(),'process_status_unavailable')
    def exited(self):return self.kernel.WaitForSingleObject(self.handle,0)==0
    def code(self):
        value=ctypes.c_ulong()
        return value.value if self.kernel.GetExitCodeProcess(self.handle,ctypes.byref(value)) else None
    def close(self):self.kernel.CloseHandle(self.handle)


def pid_absent(pid):
    if pid==os.getpid():return False
    try:handle=ProcessHandle(pid)
    except OSError as error:return error.errno==87  # Invalid PID; permission errors are not absence.
    try:return handle.exited()
    finally:handle.close()


def purge_content(area):
    area=plain_path(area).resolve()
    if area.parent!=AREA.resolve():raise ValueError('manual_cleanup_boundary')
    manifest=json.loads((area/'owner.json').read_text(encoding='utf-8'))
    if manifest.get('mode')!=MODE or manifest.get('run')!=area.name:raise ValueError('manual_cleanup_owner')
    content=plain_path(area/'content')
    if not content.exists():return
    # Verify every resolved absolute target before a recursive Windows delete.
    for target in [content,*content.rglob('*')]:
        if not plain_path(target).resolve().is_relative_to(content.resolve()):raise ValueError('manual_cleanup_reparse')
    shutil.rmtree(content)


def recover_abandoned():
    for manifest in AREA.glob('*/owner.json'):
        area=manifest.parent
        if not (area/'content').exists():continue
        data=json.loads(manifest.read_text(encoding='utf-8'))
        if data.get('mode')!=MODE or data.get('run')!=area.name:raise ValueError('unknown_manual_manifest')
        pids=set(data.get('pids',[]))
        pids.update(json.loads(p.read_text())['pid'] for p in area.glob('worker-*.json'))
        if not pids or any(not pid_absent(pid) for pid in pids):raise ValueError('前回の通常モードのprocessが生存中、または終了を確認できません。既存runを終了してください。')
        purge_content(area)
        (area/'recovery.json').write_text(json.dumps(dict(content_removed=True,prior_pids=sorted(pids))),encoding='utf-8')
