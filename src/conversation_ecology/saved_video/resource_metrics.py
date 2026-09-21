"""Content-free Windows process/RAM measurements, without model imports."""
import ctypes
import os
import time
from ctypes import wintypes as w


def process_sample():
    result=dict(pid=os.getpid(),monotonic=time.monotonic(),wall=time.time(),
                cpu_seconds=sum(os.times()[:2]),logical_cpus=os.cpu_count())
    if os.name!='nt':return result
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.GetCurrentProcess.restype=w.HANDLE
    handle=kernel.GetCurrentProcess()
    class Memory(ctypes.Structure):
        _fields_=[('cb',w.DWORD),('PageFaultCount',w.DWORD)]+[(n,ctypes.c_size_t) for n in
            ('PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage',
             'QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage','PrivateUsage')]
    m=Memory();m.cb=ctypes.sizeof(m)
    psapi=ctypes.WinDLL('psapi');psapi.GetProcessMemoryInfo.argtypes=[w.HANDLE,ctypes.c_void_p,w.DWORD]
    if psapi.GetProcessMemoryInfo(handle,ctypes.byref(m),m.cb):
        result.update(rss=m.WorkingSetSize,private_bytes=m.PrivateUsage,page_faults=m.PageFaultCount)
    mask=ctypes.c_size_t();system=ctypes.c_size_t()
    kernel.GetProcessAffinityMask.argtypes=[w.HANDLE,ctypes.c_void_p,ctypes.c_void_p]
    if kernel.GetProcessAffinityMask(handle,ctypes.byref(mask),ctypes.byref(system)):
        result.update(affinity_mask=mask.value,available_logical_cpus=mask.value.bit_count())
    class ThreadEntry(ctypes.Structure):
        _fields_=[('size',w.DWORD),('usage',w.DWORD),('id',w.DWORD),('owner',w.DWORD),('base',w.LONG),('delta',w.LONG),('flags',w.DWORD)]
    kernel.CreateToolhelp32Snapshot.restype=w.HANDLE
    snap=kernel.CreateToolhelp32Snapshot(4,0)
    kernel.Thread32First.argtypes=[w.HANDLE,ctypes.c_void_p];kernel.Thread32Next.argtypes=kernel.Thread32First.argtypes
    kernel.CloseHandle.argtypes=[w.HANDLE]
    if snap not in (None,ctypes.c_void_p(-1).value):
        e=ThreadEntry();e.size=ctypes.sizeof(e);ok=kernel.Thread32First(snap,ctypes.byref(e));count=0
        while ok:
            if e.owner==os.getpid():count+=1
            ok=kernel.Thread32Next(snap,ctypes.byref(e))
        result['os_threads']=count;kernel.CloseHandle(snap)
    return result


def ram_sample():
    if os.name!='nt':return {'available':None,'total':None}
    class Status(ctypes.Structure):
        _fields_=[('length',w.DWORD),('load',w.DWORD)]+[(n,ctypes.c_ulonglong) for n in
            ('total','available','page_total','page_available','virtual_total','virtual_available','extended')]
    s=Status();s.length=ctypes.sizeof(s)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s)):return {'available':None,'total':None}
    return dict(total=s.total,available=s.available,page_total=s.page_total,page_available=s.page_available,load=s.load)
