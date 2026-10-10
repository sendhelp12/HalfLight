"""Drain the source's local pipe into RAM; disk diagnostics have their own thread."""
import ctypes as C,json,math,queue,struct,sys,threading,time
from ctypes import wintypes as W
from pathlib import Path
root=Path(__file__).resolve().parents[1];lab=root/'work/lab'
sys.path.insert(0,str(root/'outputs/HalfLightNext'))
from packet_stream import PacketStream
from guest_source_mailbox import open_mailbox
from weapon_profile import catalog
from halflight_runtime import read_lease_deadline
WEAPON_IDS={str(i) for i in range(len(catalog()))}

def run(session,pid):
    view=open_mailbox(session,True)
    packets=PacketStream(lab/f'guest-live-pose-{session}.csv',1024,stream=view,compatibility=False)
    k=C.WinDLL('kernel32',use_last_error=True)
    k.CreateNamedPipeW.argtypes=[W.LPCWSTR,W.DWORD,W.DWORD,W.DWORD,W.DWORD,W.DWORD,W.DWORD,C.c_void_p];k.CreateNamedPipeW.restype=W.HANDLE
    k.ConnectNamedPipe.argtypes=[W.HANDLE,C.c_void_p];k.ConnectNamedPipe.restype=W.BOOL
    k.ReadFile.argtypes=[W.HANDLE,C.c_void_p,W.DWORD,C.POINTER(W.DWORD),C.c_void_p];k.ReadFile.restype=W.BOOL
    k.WriteFile.argtypes=[W.HANDLE,C.c_void_p,W.DWORD,C.POINTER(W.DWORD),C.c_void_p];k.WriteFile.restype=W.BOOL
    k.DisconnectNamedPipe.argtypes=[W.HANDLE];k.CloseHandle.argtypes=[W.HANDLE]
    k.OpenThread.argtypes=[W.DWORD,W.BOOL,W.DWORD];k.OpenThread.restype=W.HANDLE
    k.CancelSynchronousIo.argtypes=[W.HANDLE];k.GetTickCount64.restype=C.c_uint64
    stopping=threading.Event();ready=threading.Event();errors=[];last_sequence=0;last_real=None;dropped=0;cancel_thread=[None]
    rows=queue.Queue(4096)
    state_path=lab/f'guest-source-pipe-{session}.json'
    pipe_name='\\\\.\\pipe\\HalfLightGuest-'+session
    def log_rows():
        # shortcut: bounded 4096-row diagnostic backlog; increase only if diagnostic loss matters; drop rows if disk
        # stalls for over a minute. The live RAM pose is independent of logging.
        first=None
        while first is None and not stopping.is_set():
            try:first=rows.get(timeout=.1)
            except queue.Empty:pass
        if first is None:return
        with (lab/f'guest-live-pose-{session}.csv').open('ab',buffering=0) as log:
            log.write(first)
            while not stopping.is_set() or not rows.empty():
                try:row=rows.get(timeout=.1)
                except queue.Empty:continue
                log.write(row)
    def serve():
        nonlocal last_sequence,last_real,dropped
        try:
            cancel_thread[0]=k.OpenThread(1,False,k.GetCurrentThreadId())
            if not cancel_thread[0]:raise C.WinError(C.get_last_error())
            while not stopping.is_set():
                # One local client, remote clients rejected, 64 KB pipe buffer.
                handle=k.CreateNamedPipeW(pipe_name,3,8,1,65536,65536,0,None)
                if handle==C.c_void_p(-1).value:raise C.WinError(C.get_last_error())
                try:
                    ready.set()
                    if not k.ConnectNamedPipe(handle,None) and C.get_last_error()!=535:
                        if stopping.is_set():break
                        raise C.WinError(C.get_last_error())
                    hello=f'{last_sequence}\n'.encode('ascii');sent=W.DWORD()
                    if not k.WriteFile(handle,hello,len(hello),C.byref(sent),None):
                        if stopping.is_set():break
                        continue
                    pending=b'';buffer=C.create_string_buffer(4096);got=W.DWORD()
                    while not stopping.is_set() and k.ReadFile(handle,buffer,len(buffer),C.byref(got),None) and got.value:
                        pending+=buffer.raw[:got.value]
                        if len(pending)>16384:raise ValueError('Oversize source pipe input')
                        lines=pending.split(b'\n');pending=lines.pop()
                        for row in lines:
                            parts=row.decode('ascii').split(',')
                            if len(parts) not in (19,20,32):raise ValueError('Expected synchronized weapon/camera row')
                            if len(parts)>=20 and parts[19] not in WEAPON_IDS:raise ValueError('Unsupported weapon index')
                            if len(parts)==32 and (parts[20] not in ('0','1') or parts[21] not in WEAPON_IDS|{'-1'} or (parts[21]!='-1' and parts[20]!='0')):raise ValueError('Invalid dual-wield hand assignment')
                            sequence=int(parts[0]);values=tuple(map(float,parts[1:]))
                            if not all(math.isfinite(v) and abs(v)<1e9 for v in values):raise ValueError('Invalid source row')
                            if sequence<=last_sequence or (last_real is not None and values[1]<=last_real):raise ValueError('Source clock/sequence regressed')
                            last_sequence=sequence;last_real=values[1]
                            packets.publish(row.decode('ascii'))
                            try:rows.put_nowait(row+b'\n')
                            except queue.Full:dropped+=1
                finally:k.DisconnectNamedPipe(handle);k.CloseHandle(handle)
        except Exception as exc:
            if not stopping.is_set():errors.append(str(exc));stopping.set()
    worker=threading.Thread(target=serve,daemon=True);logger=threading.Thread(target=log_rows,daemon=True)
    worker.start();logger.start()
    try:
        if not ready.wait(3) or errors:raise RuntimeError('Source pipe failed to start: '+str(errors))
        state_path.write_text(json.dumps({'state':'listening','session':session,'pid':pid,'pipe':pipe_name}))
        last_expiry=0
        while not stopping.wait(.2):
            last_expiry=read_lease_deadline(lab/f'native-axe-session-{pid}.lease',pid,int(session,16),k.GetTickCount64(),last_expiry)
            if not last_expiry or (lab/f'guest-stop-{session}.txt').exists():break
    finally:
        stopping.set()
        thread=cancel_thread[0]
        if thread:
            for _ in range(10):
                k.CancelSynchronousIo(thread);worker.join(.1)
                if not worker.is_alive():break
            k.CloseHandle(thread)
        logger.join(1)
        if not worker.is_alive():packets.close()
        state_path.write_text(json.dumps({'state':'stopped','session':session,'sequence':last_sequence,'dropped_log_rows':dropped,'unwritten_log_rows':rows.qsize(),'errors':errors}))
    if errors:raise RuntimeError('; '.join(errors))

if __name__=='__main__':run(sys.argv[1],int(sys.argv[2]))
