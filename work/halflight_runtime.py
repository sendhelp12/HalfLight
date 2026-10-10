"""Small, read-only status and retry policy shared by the lab launcher."""
import ctypes, json, os, struct, time
from pathlib import Path

def read_lease_deadline(path, pid, nonce, now, previous=0):
    try:
        packet = struct.unpack('<IIQQ', Path(path).read_bytes())
    except OSError:
        return previous if now < previous <= now + 10000 else 0
    except struct.error:
        return 0
    return packet[3] if packet[:3] == (827541064, pid, nonce) and now < packet[3] <= now + 10000 else 0

class RetryBudget:

    def __init__(self, limit=3):
        self.limit = limit
        self.key = None
        self.count = 0

    def fail(self, key):
        if key != self.key:
            self.key = key
            self.count = 0
        self.count += 1
        return self.count < self.limit

    def clear(self):
        self.key = None
        self.count = 0

def read_json(path, default=None):
    try:
        raw = Path(path).read_bytes()
        if len(raw) > 65536:
            return default
        return json.loads(raw)
    except (OSError, ValueError):
        return default

def atomic_json(path, data):
    path = Path(path)
    temporary = path.with_suffix('.' + str(os.getpid()) + '.tmp')
    try:
        temporary.write_text(json.dumps(data, indent=2), encoding='utf-8')
        temporary.replace(path)
        return True
    except PermissionError:
        return False

def processes():
    from ctypes import wintypes as W

    class Entry(ctypes.Structure):
        _fields_ = [('size', W.DWORD), ('usage', W.DWORD), ('pid', W.DWORD), ('heap', ctypes.c_size_t), ('module', W.DWORD), ('threads', W.DWORD), ('parent', W.DWORD), ('priority', W.LONG), ('flags', W.DWORD), ('name', W.WCHAR * 260)]
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.CreateToolhelp32Snapshot.argtypes = [W.DWORD, W.DWORD]
    k.CreateToolhelp32Snapshot.restype = W.HANDLE
    k.Process32FirstW.argtypes = [W.HANDLE, ctypes.POINTER(Entry)]
    k.Process32FirstW.restype = W.BOOL
    k.Process32NextW.argtypes = [W.HANDLE, ctypes.POINTER(Entry)]
    k.Process32NextW.restype = W.BOOL
    k.CloseHandle.argtypes = [W.HANDLE]
    k.CloseHandle.restype = W.BOOL
    snapshot = k.CreateToolhelp32Snapshot(2, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        raise OSError(ctypes.get_last_error(), 'Process inventory failed')
    result = {}
    entry = Entry()
    entry.size = ctypes.sizeof(entry)
    try:
        found = k.Process32FirstW(snapshot, ctypes.byref(entry))
        while found:
            result[entry.pid] = entry.name.lower()
            found = k.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        k.CloseHandle(snapshot)
    return result

def telemetry(path, max_age=2):
    try:
        path = Path(path)
        if time.time() - path.stat().st_mtime > max_age:
            return {}
        raw = path.read_bytes()
        if len(raw) > 16384:
            return {}
        result = {}
        for line in raw.decode(errors='replace').splitlines():
            if ',' in line:
                key, value = line.split(',', 1)
                result[key] = value
        return result
    except OSError:
        return {}

def restoration_error(lab, active, inventory):
    """Never rebind over a surviving callback or an unrestored valid weapon."""
    if inventory.get(active['target_pid']) != 'dyinglightgame_x64_rwe.exe':
        return None
    lab = Path(lab)
    pid = active['target_pid']
    result = read_json(lab / 'native-axe-session-result.json', {})
    if result.get('pid') != pid or result.get('session') != active['session'] or result.get('controller_pid') != active['controller_pid']:
        return 'movement callback restoration is unverified'
    no_load = result.get('native_load_started') is False
    for name, keys in (('damage', ('hit_callback_restored', 'movement_callback_restored')), ('camera-lock', ('hooks_restored',))):
        path = lab / f'native-axe-{name}-{pid}.log' if name == 'damage' else lab / f'native-{name}-{pid}.log'
        startup = read_json(lab / 'active-axe-damage.json', {}) if name == 'damage' else {}
        untouched = startup.get('callbacks_not_installed') is True and startup.get('pid') == pid and (startup.get('session') == active['session'])
        if path.exists() and (not no_load) and (not untouched):
            rows = telemetry(path, float('inf'))
            if any((rows.get(key) != '1' for key in keys)):
                return name + ' callbacks have not restored'
    if not no_load and (not result.get('slot_restored_external')):
        return 'movement callback restoration is unverified'
    for bank in result.get('weapon_restoration', []):
        if bank['identity_valid'] and (not bank['pose_restored']):
            return 'surviving weapon pose has not restored'
    path = lab / f"guest-background-rendering-{active['session']}.txt"
    if path.exists():
        rows = dict((line.split('=', 1) for line in path.read_text().splitlines() if '=' in line))
        if rows.get('Session') != active['session'] or rows.get('world_rendering') != '1' or rows.get('mesh_settings_restored') != '1':
            return 'guest rendering or mesh settings have not restored'
    return None

def details(lab, active):
    if not active:
        return {}
    pid = active['target_pid']
    session = active['session']
    lab = Path(lab)
    stats = telemetry(lab / f'native-axe-damage-{pid}.log')
    result = {'damage_state': stats.get('status', 'unavailable'), 'forwarding': stats.get('input_armed') == '1', 'targets': stats.get('nearby_targets', '0'), 'hits': stats.get('native_damage_calls', '0'), 'hand_applications': stats.get('hand_applications', '0'), 'hand_outliers': stats.get('hand_reach_refusals', '0'), 'projection_ratio': stats.get('hand_projection_ratio', '1'), 'two_hand_mode': stats.get('two_hand_mode') == '1', 'left_hand_enabled': stats.get('left_hand_enabled') == '1', 'left_hand_applications': stats.get('left_hand_applications', '0'), 'left_hand_outliers': stats.get('left_hand_reach_refusals', '0')}
    result.update(measured_health_loss=stats.get('measured_health_loss', '0'), dead_target_frames=stats.get('dead_target_frames', '0'), unknown_health_frames=stats.get('unknown_health_frames', '0'))
    try:
        result['source_age_seconds'] = round(time.time() - Path(active['source_path']).stat().st_mtime, 2)
    except OSError:
        result['source_age_seconds'] = None
    try:
        path = lab / f'guest-camera-follow-{session}.status'
        rows = dict((line.split('=', 1) for line in path.read_text().splitlines() if '=' in line))
        fresh = time.time() - float(rows.get('updated_unix', '0')) < 3
        result['camera_follow'] = 'following' if fresh and result['forwarding'] else 'control off' if not result['forwarding'] else 'awaiting guest update'
        if fresh:
            result['camera_pitch_error'] = rows.get('pitch_error')
            result['camera_yaw_error'] = rows.get('yaw_error')
    except (OSError, ValueError):
        result['camera_follow'] = 'awaiting guest update' if result['forwarding'] else 'control off'
    return result
