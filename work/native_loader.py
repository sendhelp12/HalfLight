"""Validated Windows loader shared by campaign adapters; no gameplay input."""
import ctypes as C
import struct
from ctypes import wintypes as W
from pathlib import Path
from dl2_reader import K


def load_native(reader,loaded,dll,slot,original,modules):
    pid=reader.pid
    # Resolve LoadLibraryW in its actual local owner module, then compare remote bytes.
    K.LoadLibraryW.argtypes=[W.LPCWSTR];K.LoadLibraryW.restype=W.HMODULE
    local_function=C.cast(K.LoadLibraryW,C.c_void_p).value
    K.GetModuleHandleExW.argtypes=[W.DWORD,W.LPCWSTR,C.POINTER(W.HMODULE)];K.GetModuleHandleExW.restype=W.BOOL
    owner=W.HMODULE()
    assert K.GetModuleHandleExW(4|2,C.cast(local_function,W.LPCWSTR),C.byref(owner))
    K.GetModuleFileNameW.argtypes=[W.HMODULE,W.LPWSTR,W.DWORD];K.GetModuleFileNameW.restype=W.DWORD
    path=C.create_unicode_buffer(32768);assert K.GetModuleFileNameW(owner,path,len(path))
    remote_owner=loaded[Path(path.value).name.lower()]
    assert remote_owner['path']==Path(path.value)
    remote_function=remote_owner['base']+local_function-owner.value
    remote_bytes=reader.read(remote_function,32);local_bytes=C.string_at(local_function,32)
    if remote_bytes and remote_bytes[:16]!=local_bytes[:16]:
        # KERNEL32's import jump can already be patched by the game's tooling.
        # Validate its unmodified local forwarding target; do not change that patch.
        assert local_bytes[:3]==b'\x48\xff\x25','Unexpected local loader forwarding stub'
        import_pointer=local_function+7+struct.unpack_from('<i',local_bytes,3)[0]
        forwarded=C.c_void_p.from_address(import_pointer).value
        kernelbase=C.WinDLL('KernelBase',use_last_error=True)
        direct_function=C.cast(kernelbase.LoadLibraryW,C.c_void_p).value
        assert forwarded==direct_function,'Local forwarder differs from KernelBase export'
        local_function=direct_function
        assert K.GetModuleHandleExW(4|2,C.cast(local_function,W.LPCWSTR),C.byref(owner))
        assert K.GetModuleFileNameW(owner,path,len(path))
        assert Path(path.value).name.lower()=='kernelbase.dll'
        remote_owner=loaded['kernelbase.dll'];assert remote_owner['path']==Path(path.value)
        remote_function=remote_owner['base']+local_function-owner.value
        remote_bytes=reader.read(remote_function,32);local_bytes=C.string_at(local_function,32)
    assert remote_bytes and remote_bytes[:16]==local_bytes[:16],'Remote LoadLibraryW bytes differ; no load was attempted'
    K.VirtualAllocEx.argtypes=[W.HANDLE,C.c_void_p,C.c_size_t,W.DWORD,W.DWORD];K.VirtualAllocEx.restype=C.c_void_p
    K.VirtualFreeEx.argtypes=[W.HANDLE,C.c_void_p,C.c_size_t,W.DWORD];K.VirtualFreeEx.restype=W.BOOL
    K.WriteProcessMemory.argtypes=[W.HANDLE,C.c_void_p,C.c_void_p,C.c_size_t,C.POINTER(C.c_size_t)];K.WriteProcessMemory.restype=W.BOOL
    K.CreateRemoteThread.argtypes=[W.HANDLE,C.c_void_p,C.c_size_t,C.c_void_p,C.c_void_p,W.DWORD,C.POINTER(W.DWORD)];K.CreateRemoteThread.restype=W.HANDLE
    K.WaitForSingleObject.argtypes=[W.HANDLE,W.DWORD];K.WaitForSingleObject.restype=W.DWORD
    process=K.OpenProcess(0x43a,False,pid);assert process,'Cannot open approved loader handle'
    remote=None;thread=None;finished=False
    try:
        assert reader.alive() and reader.number(slot)==original,'Native callback changed before loading'
        payload=(str(dll.resolve())+'\0').encode('utf-16-le')
        remote=K.VirtualAllocEx(process,None,len(payload),0x1000|0x2000,0x04);assert remote
        copied=C.c_size_t();buffer=C.create_string_buffer(payload)
        assert K.WriteProcessMemory(process,remote,buffer,len(payload),C.byref(copied)) and copied.value==len(payload)
        thread=K.CreateRemoteThread(process,None,0,remote_function,remote,0,None);assert thread
        finished=K.WaitForSingleObject(thread,10000)==0
        assert finished,'Loader did not finish in ten seconds; allocation kept for pending thread'
        after=modules();assert dll.name.lower() in after and after[dll.name.lower()]['path']==dll.resolve()
    finally:
        if remote and (not thread or finished):K.VirtualFreeEx(process,remote,0,0x8000)
        if thread:K.CloseHandle(thread)
        K.CloseHandle(process)
