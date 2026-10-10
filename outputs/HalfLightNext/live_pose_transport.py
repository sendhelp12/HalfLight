"""Bounded source CSV -> atomic native pose packets. No game-memory access."""
import ctypes
import math
import os
import struct
import threading
import time
from pathlib import Path
from functools import lru_cache
from weapon_pose_math import native_matrix
import camera_pose_math
from weapon_profile import catalog
PACKET = struct.Struct('<IIQQQ12f')
assert PACKET.size == 80
IDENTITY = (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0)
@lru_cache(maxsize=1)
def weapon_ids():
    return {str(i) for i in range(len(catalog()))}

class SharedPosePublisher:
    """One writer, aligned sequence lock, read-only native consumer."""

    def __init__(self, pid, nonce, suffix=''):
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        k = self.kernel
        k.CreateFileMappingW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_wchar_p]
        k.CreateFileMappingW.restype = ctypes.c_void_p
        k.MapViewOfFile.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_size_t]
        k.MapViewOfFile.restype = ctypes.c_void_p
        k.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
        k.UnmapViewOfFile.restype = ctypes.c_int
        k.CloseHandle.argtypes = [ctypes.c_void_p]
        k.CloseHandle.restype = ctypes.c_int
        self.publisher = ctypes.WinDLL(str(Path(__file__).resolve().parents[2] / 'work/lab/native_pose_publish.dll'))
        self.publisher.HLF_Publish.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int32]
        self.publisher.HLF_Publish.restype = None
        assert suffix in ('', '-offhand', '-free', '-offhand-free')
        self.name = f'Local\\HalfLightAxe-{pid}-{nonce:016x}' + suffix
        self.handle = k.CreateFileMappingW(ctypes.c_void_p(-1), None, 4, 0, 128, self.name)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        if ctypes.get_last_error() == 183:
            k.CloseHandle(self.handle)
            self.handle = None
            raise RuntimeError('Shared pose session already exists')
        self.view = k.MapViewOfFile(self.handle, 983071, 0, 0, 128)
        if not self.view:
            k.CloseHandle(self.handle)
            self.handle = None
            raise ctypes.WinError(ctypes.get_last_error())
        self.stamp = 0

    def publish(self, payload):
        assert len(payload) == 80
        self.stamp = self.stamp + 2 & 2147483646
        if not self.stamp:
            self.stamp = 2
        buffer = ctypes.create_string_buffer(payload)
        self.publisher.HLF_Publish(self.view, buffer, self.stamp)

    def close(self):
        if self.view:
            self.kernel.UnmapViewOfFile(self.view)
            self.view = None
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None

def replace_packet(temporary, destination):
    deadline = time.monotonic() + 0.2
    while True:
        try:
            os.replace(temporary, destination)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.005)

def convert_row(line, origin, anchor):
    parts = line.rstrip('\r\n').split(',')
    if len(parts) not in (13, 19, 20, 32):
        raise ValueError('Expected weapon pose with optional synchronized camera')
    if len(parts) >= 20 and parts[19] not in weapon_ids():
        raise ValueError('Unsupported weapon index')
    if len(parts) == 32 and (parts[20] not in ('0', '1') or parts[21] not in weapon_ids() | {'-1'} or (parts[21] != '-1' and parts[20] != '0')):
        raise ValueError('Invalid dual-wield hand assignment')
    sequence = int(parts[0])
    numbers = tuple(map(float, parts[1:]))
    if sequence <= 0 or not all((math.isfinite(n) for n in numbers)):
        raise ValueError('Invalid pose row')
    position = numbers[2:5]
    origin = position if origin is None else origin
    matrix = native_matrix(position, numbers[5:9], numbers[9:12], origin, anchor)
    return (sequence, numbers[1], origin, matrix)

class PoseFeed:

    def __init__(self, source, destination, pid, nonce, anchor, continuous=False, pose_mapper=None, source_mailbox=None):
        self.source = Path(source)
        self.destination = Path(destination)
        self.pid = pid
        self.nonce = nonce
        self.anchor = anchor
        self.continuous = continuous
        self.pose_mapper = pose_mapper
        self.source_mailbox = source_mailbox
        self.stop_event = threading.Event()
        self.ready = threading.Event()
        self.count = 0
        self.error = None
        self.last_sequence = 0
        self.max_gap_seconds = 0
        self.recovered_stalls = 0
        from host_weapon_bite import HostWeaponBite
        from look_lock import LookLock
        self.host_bites = HostWeaponBite()
        self.input_lock = LookLock(f'{nonce:016x}')
        self.thread = threading.Thread(target=self.run, daemon=True)

    def start(self):
        self.thread.start()

    def close(self):
        self.stop_event.set()
        self.thread.join(2)

    def feedback(self, tick):
        from native_body_transport import impacts, decode
        base = self.destination.parent
        controls = {}
        try:
            text = (base / f'guest-input-{self.nonce:016x}.txt').read_text()
            if len(text) <= 1024:
                for line in text.splitlines():
                    if '=' in line:
                        key, value = line.split('=', 1)
                        if key in controls:
                            raise ValueError('Duplicate input field')
                        controls[key] = value
        except (OSError, ValueError):
            controls = {}
        armed, _ = self.input_lock.update(controls, time.monotonic(), int(time.time()))
        try:
            events = impacts((base / f'native-combat-impacts-{self.pid}.snapshot').read_bytes(), self.pid, self.nonce, tick, len(weapon_ids()) * 2)
            shapes = decode((base / f'native-axe-bodies-{self.pid}.snapshot').read_bytes(), self.pid, self.nonce, tick)
        except (OSError, ValueError):
            events = []
            shapes = {}
        return (armed, events, shapes)

    def run(self):
        kernel = ctypes.WinDLL('kernel32')
        kernel.GetTickCount64.restype = ctypes.c_uint64
        offset = 0
        buffer = ''
        origin = None
        last_real = None
        began = time.monotonic()
        last_fresh = began
        shared = None
        secondary_shared = None
        free_shared = None
        secondary_free = None
        source_view = None
        try:
            if self.continuous:
                shared = SharedPosePublisher(self.pid, self.nonce)
            if self.source_mailbox:
                from guest_source_mailbox import open_mailbox, read_mailbox
                source_view = open_mailbox(self.source_mailbox)
            while not self.stop_event.is_set() and (self.continuous or time.monotonic() - began < 40):
                if source_view is not None or self.source.exists():
                    if source_view is not None:
                        row = read_mailbox(source_view)
                        lines = [row] if row and int(row.split(',', 1)[0]) > self.last_sequence else []
                    else:
                        with self.source.open('rb') as stream:
                            stream.seek(offset)
                            chunk = stream.read()
                            offset = stream.tell()
                        buffer += chunk.decode('ascii')
                        lines = buffer.split('\n')
                        buffer = lines.pop()
                    newest = None
                    newest_weapon = None
                    secondary = None
                    secondary_weapon = None
                    primary_valid = True
                    for line in lines:
                        if not line or line.startswith('sequence,'):
                            continue
                        line = line.rstrip('\r\n')
                        seq, real, origin, matrix = convert_row(line, origin, self.anchor)
                        parts = line.split(',')
                        primary_valid = True
                        if self.pose_mapper:
                            try:
                                matrix = self.pose_mapper(line)
                            except camera_pose_math.WeaponOutOfReach:
                                if len(parts) != 32:
                                    raise
                                matrix = IDENTITY
                                primary_valid = False
                        if seq <= self.last_sequence or (last_real is not None and real <= last_real):
                            raise ValueError('Source sequence or clock stopped advancing')
                        self.last_sequence = seq
                        last_real = real
                        newest = matrix
                        newest_weapon = parts[19] if len(parts) >= 20 else None
                        if len(parts) == 32:
                            secondary_weapon = parts[21]
                            second_row = ','.join(parts[:3] + parts[22:32] + parts[13:19] + ['0' if secondary_weapon == '-1' else secondary_weapon])
                            try:
                                secondary = self.pose_mapper(second_row) if secondary_weapon != '-1' else IDENTITY
                            except camera_pose_math.WeaponOutOfReach:
                                secondary = IDENTITY
                                secondary_weapon = '-1'
                    if newest is not None:
                        gap = time.monotonic() - last_fresh
                        self.max_gap_seconds = max(self.max_gap_seconds, gap)
                        if self.ready.is_set() and gap > 0.5:
                            self.recovered_stalls += 1
                        tick = kernel.GetTickCount64()
                        free_primary, free_secondary = (newest, secondary)
                        if self.continuous and getattr(self.pose_mapper, 'camera_relative', False):
                            armed, events, shapes = self.feedback(tick)
                            camera = self.pose_mapper.read()
                            selected_banks = set()
                            if primary_valid and newest_weapon is not None:
                                bank = int(newest_weapon)
                                selected_banks.add(bank)
                                newest = self.host_bites.apply(bank, newest, camera, events, shapes, tick, armed)
                            if secondary_weapon not in (None, '-1'):
                                bank = len(weapon_ids()) + int(secondary_weapon)
                                selected_banks.add(bank)
                                secondary = self.host_bites.apply(bank, secondary, camera, events, shapes, tick, armed)
                            for bank in set(self.host_bites.bites) - selected_banks:
                                self.host_bites.bites.pop(bank, None)
                        magic = 843859528 if getattr(self.pose_mapper, 'camera_relative', False) else 827082312
                        if newest_weapon is not None:
                            if not getattr(self.pose_mapper, 'camera_relative', False):
                                raise ValueError('Weapon switching requires camera-relative transport')
                            magic = 860636744 + (int(newest_weapon) << 24)
                            if not primary_valid:
                                magic = 1934378568 + (int(newest_weapon) << 24)
                        payload = PACKET.pack(magic, self.pid, self.nonce, self.last_sequence, tick, *newest)
                        if shared and newest_weapon is not None:
                            if free_shared is None:
                                free_shared = SharedPosePublisher(self.pid, self.nonce, '-free')
                            free_shared.publish(PACKET.pack(magic, self.pid, self.nonce, self.last_sequence, tick, *free_primary))
                        if shared:
                            shared.publish(payload)
                        else:
                            temporary = self.destination.with_suffix('.tmp')
                            temporary.write_bytes(payload)
                            replace_packet(temporary, self.destination)
                        if secondary_weapon is not None:
                            if not shared:
                                raise ValueError('Dual wield requires continuous transport')
                            if secondary_shared is None:
                                secondary_shared = SharedPosePublisher(self.pid, self.nonce, '-offhand')
                            second_index = 0 if secondary_weapon == '-1' else int(secondary_weapon)
                            second_magic = (1934378568 if secondary_weapon == '-1' else 860636744) + (second_index << 24)
                            if secondary_free is None:
                                secondary_free = SharedPosePublisher(self.pid, self.nonce, '-offhand-free')
                            secondary_free.publish(PACKET.pack(second_magic, self.pid, self.nonce, self.last_sequence, tick, *free_secondary))
                            secondary_shared.publish(PACKET.pack(second_magic, self.pid, self.nonce, self.last_sequence, tick, *secondary))
                        self.count += 1
                        last_fresh = time.monotonic()
                        self.ready.set()
                if not self.continuous and self.ready.is_set() and (time.monotonic() - last_fresh > 2):
                    raise TimeoutError('Half Sword source stopped; no stale poses republished')
                self.stop_event.wait(0.005)
        except Exception as exc:
            self.error = str(exc)
        finally:
            if shared:
                shared.close()
            if secondary_shared:
                secondary_shared.close()
            if free_shared:
                free_shared.close()
            if secondary_free:
                secondary_free.close()
            if source_view is not None:
                source_view.close()
