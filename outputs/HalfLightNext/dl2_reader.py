"""Read-only external companion for runtime discovery; no injection or memory writes."""
import ctypes as C
from ctypes import wintypes as W
import json
import math
import struct
import time
from pathlib import Path
K = C.WinDLL('kernel32', use_last_error=True)

class MODULEENTRY32W(C.Structure):
    _fields_ = [('dwSize', W.DWORD), ('th32ModuleID', W.DWORD), ('th32ProcessID', W.DWORD), ('GlblcntUsage', W.DWORD), ('ProccntUsage', W.DWORD), ('modBaseAddr', C.c_void_p), ('modBaseSize', W.DWORD), ('hModule', W.HMODULE), ('szModule', W.WCHAR * 256), ('szExePath', W.WCHAR * 260)]

class PROCESSENTRY32W(C.Structure):
    _fields_ = [('dwSize', W.DWORD), ('cntUsage', W.DWORD), ('th32ProcessID', W.DWORD), ('th32DefaultHeapID', C.c_size_t), ('th32ModuleID', W.DWORD), ('cntThreads', W.DWORD), ('th32ParentProcessID', W.DWORD), ('pcPriClassBase', W.LONG), ('dwFlags', W.DWORD), ('szExeFile', W.WCHAR * 260)]
K.CreateToolhelp32Snapshot.argtypes = [W.DWORD, W.DWORD]
K.CreateToolhelp32Snapshot.restype = W.HANDLE
K.Module32FirstW.argtypes = [W.HANDLE, C.POINTER(MODULEENTRY32W)]
K.Module32FirstW.restype = W.BOOL
K.Module32NextW.argtypes = K.Module32FirstW.argtypes
K.Module32NextW.restype = W.BOOL
K.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
K.OpenProcess.restype = W.HANDLE
K.CloseHandle.argtypes = [W.HANDLE]
K.CloseHandle.restype = W.BOOL
K.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
K.ReadProcessMemory.restype = W.BOOL
K.QueryFullProcessImageNameW.argtypes = [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)]
K.QueryFullProcessImageNameW.restype = W.BOOL
K.Process32FirstW.argtypes = [W.HANDLE, C.POINTER(PROCESSENTRY32W)]
K.Process32FirstW.restype = W.BOOL
K.Process32NextW.argtypes = K.Process32FirstW.argtypes
K.Process32NextW.restype = W.BOOL
K.GetExitCodeProcess.argtypes = [W.HANDLE, C.POINTER(W.DWORD)]
K.GetExitCodeProcess.restype = W.BOOL

def find_game_pid():
    snapshot = K.CreateToolhelp32Snapshot(2, 0)
    if snapshot == C.c_void_p(-1).value:
        return None
    entry = PROCESSENTRY32W()
    entry.dwSize = C.sizeof(entry)
    try:
        ok = K.Process32FirstW(snapshot, C.byref(entry))
        while ok:
            if entry.szExeFile.lower() == 'dyinglightgame_x64_rwdi.exe':
                return entry.th32ProcessID
            ok = K.Process32NextW(snapshot, C.byref(entry))
    finally:
        K.CloseHandle(snapshot)
    return None

class Reader:

    def __init__(self, pid, root):
        self.pid = pid
        self.seq = 0
        self.offsets = {}
        self.profile = json.loads((root / 'dl2_profile.json').read_text())
        self.handle = K.OpenProcess(16 | 4096, False, pid)
        if not self.handle:
            raise OSError(C.get_last_error(), 'Could not open Dying Light for read-only discovery')
        image = C.create_unicode_buffer(32768)
        size = W.DWORD(len(image))
        if not K.QueryFullProcessImageNameW(self.handle, 0, image, C.byref(size)) or Path(image.value).name.lower() != 'dyinglightgame_x64_rwdi.exe':
            self.close()
            raise ValueError('The requested PID is not Dying Light 2')
        snapshot = K.CreateToolhelp32Snapshot(8 | 16, pid)
        if snapshot == C.c_void_p(-1).value:
            self.close()
            raise OSError(C.get_last_error(), 'Module snapshot failed')
        self.modules = {}
        entry = MODULEENTRY32W()
        entry.dwSize = C.sizeof(entry)
        try:
            ok = K.Module32FirstW(snapshot, C.byref(entry))
            while ok:
                self.modules[entry.szModule.lower()] = (entry.modBaseAddr, entry.modBaseSize)
                ok = K.Module32NextW(snapshot, C.byref(entry))
        finally:
            K.CloseHandle(snapshot)
        self.engine = self.modules.get('engine_x64_rwdi.dll', (0, 0))[0]
        self.game = self.modules.get('gamedll_ph_x64_rwdi.dll', (0, 0))[0]
        self.profile_ok = self.matching(self.engine, 'ENGINE') and self.matching(self.game, 'GAME')

    def close(self):
        if self.handle:
            K.CloseHandle(self.handle)
            self.handle = None

    def alive(self):
        code = W.DWORD()
        return bool(self.handle and K.GetExitCodeProcess(self.handle, C.byref(code)) and (code.value == 259))

    def read(self, address, size):
        if not self.handle or not 65536 <= address <= 140737488355327:
            return None
        result = C.create_string_buffer(size)
        copied = C.c_size_t()
        return result.raw if K.ReadProcessMemory(self.handle, address, result, size, C.byref(copied)) and copied.value == size else None

    def number(self, address, format='<Q'):
        data = self.read(address, struct.calcsize(format))
        return struct.unpack(format, data)[0] if data else 0

    def matching(self, base, prefix):
        if not base:
            return False
        nt = self.number(base + 60, '<I')
        return self.read(base + nt, 4) == b'PE\x00\x00' and self.number(base + nt + 8, '<I') == self.profile[prefix + '_TIMESTAMP'] and (self.number(base + nt + 24 + 56, '<I') == self.profile[prefix + '_SIZE'])

    def typed(self, obj, base, key):
        return obj and self.number(obj) == base + self.profile['VT_' + key]

    def child(self, parent, base, key, hint, size):
        if not parent:
            return 0
        offset = self.offsets.get(key, hint)
        candidate = self.number(parent + offset)
        if self.typed(candidate, base, key):
            return candidate
        block = self.read(parent, size)
        if not block:
            return 0
        for offset in range(8, len(block) - 7, 8):
            candidate = struct.unpack_from('<Q', block, offset)[0]
            if self.typed(candidate, base, key):
                self.offsets[key] = offset
                return candidate
        return 0

    def is_camera(self, obj):
        table = self.number(obj)
        locator = self.number(table - 8)
        data = self.read(locator, 24)
        if not data:
            return False
        fields = struct.unpack('<6I', data)
        if fields[0] != 1 or not fields[5]:
            return False
        base = locator - fields[5]
        if base not in (self.engine, self.game):
            return False
        name = self.read(base + fields[3] + 16, 128)
        return name and b'Camera' in name.split(b'\x00')[0]

    def gameplay_level(self, game):
        if not game:
            return (0, 0)
        preferred = [self.offsets.get('LEVEL', 912), 912, 832]
        offsets = list(dict.fromkeys(preferred + list(range(8, 8192, 8))))
        block = None
        for offset in offsets:
            if offset in preferred:
                candidate = self.number(game + offset)
            else:
                if block is None:
                    block = self.read(game, 8192) or b''
                candidate = struct.unpack_from('<Q', block, offset)[0] if block else self.number(game + offset)
            if not self.typed(candidate, self.engine, 'LEVEL'):
                continue
            leveldi = self.child(candidate, self.game, 'LEVELDI', 32, 256)
            if leveldi:
                self.offsets['LEVEL'] = offset
                return (candidate, leveldi)
        return (0, 0)

    def snapshot(self, run_id, peer_ack=0):
        self.seq += 1
        p = self.profile
        state = dict(protocol='1', run_id=run_id, source='dying-light', seq=str(self.seq), pid=str(self.pid), reader='external-read-only', peer_ack=str(peer_ack), profile_ok=str(int(self.profile_ok)), lobby='0', game='0', level='0', leveldi='0', player='0', physics='0', camera='0', position_candidate='0', camera_valid='0')
        if self.profile_ok:
            lobby = self.number(self.engine + p['LOBBY_GLOBAL'])
            if not self.typed(lobby, self.engine, 'LOBBY'):
                lobby = 0
            game = 0
            gameph = 0
            if lobby:
                block = self.read(lobby, 768)
                offsets = [248] + [i for i in range(8, 768, 8) if i != 248]
                for offset in offsets:
                    candidate = struct.unpack_from('<Q', block, offset)[0] if block else 0
                    table = self.number(candidate)
                    if not self.engine <= table < self.engine + p['ENGINE_SIZE']:
                        continue
                    candidate_ph = self.child(candidate, self.game, 'GAMEPH', 8, 128)
                    if candidate_ph:
                        game = candidate
                        gameph = candidate_ph
                        self.offsets['GAME'] = offset
                        break
            level, leveldi = self.gameplay_level(game)
            session = self.child(gameph, self.game, 'SESSION', 304, 1536)
            client = self.child(session, self.game, 'CLIENT', 3592, 9216)
            player = self.child(client, self.game, 'PLAYER', 144, 1024)
            prop = self.number(player + 240) if player else 0
            physics = self.child(prop, self.engine, 'PHYSICS', 32, 256)
            owner = self.number(leveldi + 56) if leveldi else 0
            cameras = set()
            if owner:
                for slot in (5008, 5024):
                    component = self.number(owner + slot)
                    camera = self.number(component + 808) if component else 0
                    if self.is_camera(camera):
                        cameras.add(camera)
            camera = next(iter(cameras)) if len(cameras) == 1 else 0
            for key, value in [('lobby', lobby), ('game', game), ('gameph', gameph), ('level', level), ('leveldi', leveldi), ('session', session), ('client', client), ('player', player), ('physics', physics), ('camera', camera)]:
                state[key] = str(value)
            if physics:
                data = self.read(physics + p['POSITION_CANDIDATE_OFFSET'], 12)
                if data:
                    xyz = struct.unpack('<3f', data)
                    if all((math.isfinite(v) and abs(v) < 1000000.0 for v in xyz)):
                        state.update(zip(('x', 'y', 'z'), map(str, xyz)))
                        state['position_candidate'] = '1'
                        state['position_candidate_offset'] = str(p['POSITION_CANDIDATE_OFFSET'])
            if camera:
                transform = self.number(camera + 56)
                data = self.read(transform + 64, 48)
                if data:
                    matrix = struct.unpack('<12f', data)
                    if all((math.isfinite(v) for v in matrix)):
                        state['camera_valid'] = '1'
                        state.update(zip(('camera_x', 'camera_y', 'camera_z'), map(str, (matrix[3], matrix[7], matrix[11]))))
                        state.update(zip(('camera_forward_x', 'camera_forward_y', 'camera_forward_z'), map(str, (matrix[2], matrix[6], matrix[10]))))
                projection = self.read(transform + 128, 64)
                if projection:
                    values = struct.unpack('<16f', projection)
                    sx, sy = (abs(values[0]), abs(values[5]))
                    if math.isfinite(sx) and math.isfinite(sy) and (0.1 < sx < 10) and (0.1 < sy < 10):
                        state['camera_hfov'] = str(math.degrees(2 * math.atan(1 / sx)))
                        state['camera_vfov'] = str(math.degrees(2 * math.atan(1 / sy)))
                        state['camera_aspect'] = str(sy / sx)
            state['resolved_offsets'] = json.dumps(self.offsets, separators=(',', ':'))
        state['end_seq'] = str(self.seq)
        return state
