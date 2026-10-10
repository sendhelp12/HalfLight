"""Keep a leased native target binding and the guest capsule in the same frame."""
import ast, ctypes, json, math, os, struct, sys, time, importlib
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from retail_session import root, pid, engine_profile, EditorReader
sys.path.insert(0, str(root / 'outputs/HalfLightNext'))
from native_target_locator import TargetLocator
from native_camera_reader import CameraMapper
import native_body_transport
import camera_pose_math, weapon_pose_math, world_collision_transport
from live_pose_transport import replace_packet
from packet_stream import PacketStream
from halflight_runtime import read_lease_deadline
from guest_source_mailbox import GuestPoseRows
from weapon_profile import catalog
active = json.loads((root / 'work/lab/active-axe-session.json').read_text())
assert active['state'] == 'running' and active['target_pid'] == pid
graph = json.loads((root / 'work/lab/target-damage-graph.json').read_text())
body = graph['spatial'][0]
receiver = next((c for c in body['components'] if c['type'] == '.?AVCoDamageReceiver@@'))
alignment = json.loads((root / 'work/lab/host-alignment-graph.json').read_text())
assert alignment['pid'] == pid
levels = [int(a, 16) for a, n in alignment['graph'].items() if n['type'] == '.?AVLevelDI@@']
assert len(levels) == 1
session = active['session']
nonce = int(session, 16)
reader = EditorReader(pid)
camera = CameraMapper(reader, json.loads((root / 'work/lab/host-camera-profile.json').read_text()))
hands = json.loads((root / 'work/lab/native-player-hands.json').read_text())
assert hands['pid'] == pid
player = int(hands['player'], 16)
player_entity = reader.number(reader.number(player + 56) + 16)
locator = TargetLocator(reader, int(alignment['game'], 16), engine_profile, reader.number(player_entity + 8) >> 28 & 63, 205, receiver_table=38179184)
kernel = ctypes.WinDLL('kernel32')
kernel.GetTickCount64.restype = ctypes.c_uint64
output = root / f'work/lab/guest-target-{session}.txt'
binding_output = root / f'work/lab/native-axe-target-{pid}.binding'
packets = PacketStream(output, 98304)
stop = root / f'work/lab/target-publisher-stop-{session}.txt'
source_rows = GuestPoseRows(active)
newest = None
fresh = 0
last_sequence = 0
sequence = int(time.time() * 1000000)
last_scan = 0
selected = None
rows = []
last_expiry = 0
state = {'pid': os.getpid(), 'target_pid': pid, 'session': session, 'state': 'running', 'stop_path': str(stop), 'scope': 'Up to sixteen occupied enemy receivers within eight metres. Discovery is independent of guest pose freshness; physics requires a fresh pose and native body snapshot. Native body expiry is 500ms, guest proxy lease is 2s. Presence is not a health check.'}
(root / 'work/lab/active-target-publisher.json').write_text(json.dumps(state, indent=2))
print(json.dumps(state), flush=True)
try:
    while not stop.exists():
        try:
            now = kernel.GetTickCount64()
            last_expiry = read_lease_deadline(active['lease_path'], pid, nonce, now, last_expiry)
            if not last_expiry:
                break
            for line in source_rows.read():
                if not line or line.startswith('sequence,'):
                    continue
                parts = line.split(',')
                assert len(parts) in (19, 20, 32)
                if int(parts[0]) > last_sequence:
                    last_sequence = int(parts[0])
                    newest = list(map(float, parts[1:]))
                    fresh = time.monotonic()
            source_fresh = newest is not None and time.monotonic() - fresh <= 0.5
            host = camera.read()
            if time.monotonic() - last_scan > 0.5:
                rows = locator.locate(tuple((host[i * 4 + 3] for i in range(3))))
                cached = 0
                preferred = next((r for r in rows if int(r['human_ai'], 16) == cached), None)
                current = next((r for r in rows if selected and r['entity_handle'] == selected['entity_handle']), None)
                selected = preferred or current or (rows[0] if rows else None)
                last_scan = time.monotonic()
                (root / 'work/lab/nearby-native-targets.json').write_text(json.dumps({'pid': pid, 'targets': rows, 'selected': selected, 'scope': state['scope']}, indent=2))
            sequence += 1
            binary = struct.pack('<II3QII', 860112456, pid, nonce, sequence, kernel.GetTickCount64() + 2000, len(rows), 0)
            for row in rows:
                binary += struct.pack('<6Q', int(row['entity'], 16), int(row['receiver'], 16), int(row['receiver_handle'], 16), int(row['xform'], 16), int(row['root_handle'], 16), int(row['entity_handle'], 16))
            binary += bytes((16 - len(rows)) * 48)
            assert len(binary) == 808
            temporary = binding_output.with_suffix('.tmp')
            temporary.write_bytes(binary)
            replace_packet(temporary, binding_output)
            mtime = camera.math_path.stat().st_mtime_ns
            if mtime != camera.math_mtime:
                importlib.reload(weapon_pose_math)
                importlib.reload(camera_pose_math)
                importlib.reload(world_collision_transport)
                camera.math_mtime = mtime
        except PermissionError:
            pass
        time.sleep(1 / 60)
finally:
    source_rows.close()
    packets.close()
    reader.close()
    state['state'] = 'stopped'
    (root / 'work/lab/active-target-publisher.json').write_text(json.dumps(state, indent=2))
    print('Target publisher stopped; binding and capsule expire.', flush=True)
