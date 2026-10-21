"""User entry point: start/reuse native HOI4, wait for campaign, run bridge."""
import hashlib
import os
import subprocess,hashlib,os
import time
from pathlib import Path
from .core import ROOT,BridgeError,config,read_json
from .native import NativeHOI


def process_ids(executable):
    # Toolhelp only reads process names; tasklist uses WMI, unavailable on some
    # hosts. No window inspection, input injection or process-memory access.
    import ctypes
    from ctypes import wintypes as w
    class Entry(ctypes.Structure):
        _fields_=[('size',w.DWORD),('usage',w.DWORD),('pid',w.DWORD),('heap',ctypes.c_size_t),
            ('module',w.DWORD),('threads',w.DWORD),('parent',w.DWORD),('priority',w.LONG),
            ('flags',w.DWORD),('name',w.WCHAR*260)]
    api=ctypes.WinDLL('kernel32',use_last_error=True)
    api.CreateToolhelp32Snapshot.argtypes=[w.DWORD,w.DWORD];api.CreateToolhelp32Snapshot.restype=w.HANDLE
    for name in ('Process32FirstW','Process32NextW'):
        getattr(api,name).argtypes=[w.HANDLE,ctypes.POINTER(Entry)];getattr(api,name).restype=w.BOOL
    api.CloseHandle.argtypes=[w.HANDLE];api.CloseHandle.restype=w.BOOL
    handle=api.CreateToolhelp32Snapshot(2,0)
    if handle==ctypes.c_void_p(-1).value:raise BridgeError('Could not inspect running game processes')
    try:
        entry=Entry();entry.size=ctypes.sizeof(entry)
        more=api.Process32FirstW(handle,ctypes.byref(entry));found=[]
        while more:
            if entry.name.casefold()==executable.casefold():found.append(entry.pid)
            more=api.Process32NextW(handle,ctypes.byref(entry))
        if ctypes.get_last_error() not in (0,18):raise BridgeError('Process enumeration did not complete')
        return sorted(found)
    finally:api.CloseHandle(handle)


def running(executable):return bool(process_ids(executable))


def process_started_at_ns(pid):
    """Read-only process creation time, independent of foreground focus."""
    import ctypes
    from ctypes import wintypes as w
    api=ctypes.WinDLL('kernel32',use_last_error=True)
    api.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];api.OpenProcess.restype=w.HANDLE
    api.GetProcessTimes.argtypes=[w.HANDLE]+[ctypes.POINTER(w.FILETIME)]*4;api.GetProcessTimes.restype=w.BOOL
    api.CloseHandle.argtypes=[w.HANDLE]
    handle=api.OpenProcess(0x1000,False,pid)
    if not handle:raise BridgeError('Could not read MoW creation time')
    try:
        times=[w.FILETIME() for _ in range(4)]
        if not api.GetProcessTimes(handle,*[ctypes.byref(t) for t in times]):raise BridgeError('Could not read MoW creation time')
        ticks=(times[0].dwHighDateTime<<32)|times[0].dwLowDateTime
        return (ticks-116444736000000000)*100
    finally:api.CloseHandle(handle)


def connect():
    cfg=config();client=NativeHOI(cfg.get('hoi4_native_port',17389));folder=ROOT/'native_trial'
    if not running('hoi4.exe'):
        from native_trial.probe import signature,SIGNATURE
        exe=Path(cfg['hoi4'])/'hoi4.exe'
        if signature(exe)!=SIGNATURE:raise BridgeError('This HOI4 version is unsupported; no game launched')
        manifest=read_json(folder/'manifest.json')
        for name,expected in manifest['binaries'].items():
            if hashlib.sha256((folder/name).read_bytes()).hexdigest()!=expected:
                raise BridgeError('Native runtime hash mismatch: '+name)
        enabled=read_json(Path(cfg['hoi4_user'])/'dlc_load.json').get('enabled_mods',[])
        if enabled!=['mod/hoi4_mow_bridge.mod']:
            raise BridgeError('Enable only the HOI4 Men of War Bridge mod before native launch')
        logs=ROOT/'runtime';logs.mkdir(exist_ok=True)
        with (logs/'native-launcher.log').open('wb') as stream:
            subprocess.Popen([str(folder/'hoi4_launcher.exe'),'--exe='+str(exe),'--no-mod-sync',
                '-http='+str(cfg.get('hoi4_native_port',17389))],cwd=folder,
                env={**os.environ,'HOI4_DLL_DEBUG':'1'},
                stdout=stream,stderr=subprocess.STDOUT,creationflags=0x08000000)
        print('HOI4 launched with the native bridge. Load your campaign and leave this window open.',flush=True)
    else:
        print('Connecting to running HOI4. It must have been started with the native extension.',flush=True)
    deadline=time.monotonic()+600
    while time.monotonic()<deadline:
        try:
            state=client.request('/health')
        except BridgeError:
            time.sleep(2);continue
        if state.get('version')!=client.VERSION:raise BridgeError('Unsupported native bridge version')
        if state.get('session_active') is True:break
        time.sleep(1)
    else:raise BridgeError('No native campaign connected. Close ordinary HOI4 and start this launcher again.')
    return cfg,client


def main(retry_mow=False):
    cfg,client=connect()
    from .transition import AutomaticTransfer,worker_lock,_watch,release_completed
    root=ROOT/'sessions/automatic'
    with worker_lock(root):
        transfer=AutomaticTransfer(cfg,root)
        from .snapshot_cleanup import automatic_cleanup
        automatic_cleanup(cfg,root)
        if transfer.pending and transfer.pending.get('strategic_result_applied') and transfer.pending['status']=='result_ready':
            release_completed(transfer,cfg,allow_menu=cfg.get('mow_auto_load',False))
            if transfer.pending:raise BridgeError('Leave the completed MoW mission before starting another transfer')
            print('Previous completed tactical session released; scene exit verified.',flush=True)
        if retry_mow:
            from .mow_launch import retry
            retry(transfer,cfg,ROOT)
        _watch(cfg,root,install=True,native=True)


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--retry-mow',action='store_true');args=parser.parse_args()
    try:main(args.retry_mow)
    except (BridgeError,OSError) as error:raise SystemExit('Bridge stopped: '+str(error))
