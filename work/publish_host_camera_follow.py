"""Renewable camera synchronization for the already-running offline link."""
import ast, ctypes, json, math, os, struct, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from retail_session import root, pid, engine_profile, EditorReader
sys.path.insert(0, str(root / 'outputs/HalfLightNext'))
from native_camera_reader import CameraMapper
from live_pose_transport import replace_packet
from packet_stream import PacketStream
from look_lock import LookLock
from halflight_runtime import read_lease_deadline
active = json.loads((root / 'work/lab/active-axe-session.json').read_text())
assert active['state'] == 'running' and active['target_pid'] == pid
session = active['session']
nonce = int(session, 16)
reader = EditorReader(pid)
camera = CameraMapper(reader, json.loads((root / 'work/lab/host-camera-profile.json').read_text()))
guest = dict((line.split('=', 1) for line in (root / f'work/lab/guest-camera-alignment-{session}.txt').read_text().splitlines()))
assert guest['Session'] == session and time.time() - int(guest['unix_seconds']) < 3

def heading(matrix):
    return math.degrees(math.atan2(-matrix[10], -matrix[2]))
initial_host = heading(camera.read())
initial_guest = float(guest['camera_yaw'])
sequence = time.time_ns() // 1000
kernel = ctypes.WinDLL('kernel32')
kernel.GetTickCount64.restype = ctypes.c_uint64
output = root / f'work/lab/host-camera-follow-{session}.txt'
temporary = output.with_suffix('.tmp')
stop = root / f'work/lab/camera-follow-stop-{session}.txt'
packets = PacketStream(output, 4096)
look = LookLock(session)
state = {'pid': os.getpid(), 'target_pid': pid, 'session': session, 'state': 'running', 'stop_path': str(stop), 'initial_host_yaw': initial_host, 'initial_guest_yaw': initial_guest, 'scope': 'Actual camera pitch and relative yaw, F8 gated; reflected guest FOV if supported.'}
state_path = root / 'work/lab/active-camera-follow.json'
state_path.write_text(json.dumps(state, indent=2))
print(json.dumps(state), flush=True)
try:
    last_expiry = 0
    while not stop.exists() and reader.alive():
        now = kernel.GetTickCount64()
        last_expiry = read_lease_deadline(active['lease_path'], pid, nonce, now, last_expiry)
        if not last_expiry:
            break
        m = camera.read()
        projection = struct.unpack('<16f', reader.read(camera.transform + 128, 64))
        pitch = math.degrees(math.atan2(-m[6], math.hypot(m[2], m[10])))
        yaw = initial_guest + ((heading(m) - initial_host + 180) % 360 - 180)
        fov = math.degrees(2 * math.atan(1 / projection[0]))
        try:
            controls = dict((line.split('=', 1) for line in (root / f'work/lab/guest-input-{session}.txt').read_text().splitlines()))
        except (OSError, ValueError):
            controls = {}
        enabled, held = look.update(controls, time.monotonic(), int(time.time()))
        pitch, yaw = look.direction(pitch, yaw)
        sequence += 1
        try:
            packets.publish(f'Session={session}\nsequence={sequence}\nexpires_at={int(time.time()) + 1}\nenabled={int(enabled)}\nleft_click_lock={int(held)}\npitch={pitch:.8f}\nyaw={yaw:.8f}\nfov={fov:.8f}\nend_sequence={sequence}\n')
        except PermissionError:
            pass
        time.sleep(1 / 30)
finally:
    packets.close()
    try:
        temporary.write_text(f'Session={session}\nexpires_at=0\nenabled=0\n')
        replace_packet(temporary, output)
    except PermissionError:
        pass
    reader.close()
    state['state'] = 'stopped'
    state_path.write_text(json.dumps(state, indent=2))
