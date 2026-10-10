"""External camera reads through the pinned, current native getter layout."""
import math, struct, time, importlib
from pathlib import Path
import camera_pose_math
import weapon_pose_math
from weapon_profile import selected, catalog

class CameraMapper:

    def __init__(self, reader, profile, camera_relative=False):
        self.reader = reader
        self.profile = profile
        self.latest = None
        self.camera_relative = camera_relative
        self.object = int(profile['address'], 16)
        self.table = int(profile['vtable'], 16)
        self.transform = int(profile['transform'], 16)
        self.transform_table = int(profile['transform_vtable'], 16)
        self.math_path = Path(camera_pose_math.__file__)
        self.math_mtime = self.math_path.stat().st_mtime_ns
        self.last_reload_check = 0
        self.weapon_profile = selected()

    def read(self):
        r = self.reader
        if r.number(self.object) != self.table or r.number(self.object + 56) != self.transform or r.number(self.transform) != self.transform_table:
            raise ValueError('Player camera identity changed; stop the link')
        raw = r.read(self.transform + 64, 48)
        if raw is None:
            raise ValueError('Camera matrix unavailable')
        matrix = struct.unpack('<12f', raw)
        if not all((math.isfinite(v) and abs(v) < 100000.0 for v in matrix)):
            raise ValueError('Invalid player camera matrix')
        projection = struct.unpack('<16f', r.read(self.transform + 128, 64))
        if abs(projection[14] + 1) > 0.001 or abs(projection[15]) > 0.001 or projection[0] <= 0 or (projection[5] <= 0):
            raise ValueError('Camera projection convention changed; stop the link')
        return matrix

    def __call__(self, line):
        parts = line.rstrip('\r\n').split(',')
        if len(parts) not in (19, 20, 32):
            raise ValueError('Synchronized guest weapon/camera row missing')
        offset = self.weapon_profile['pose_offset_cm']
        if len(parts) >= 20:
            profiles = catalog()
            if parts[19] not in {str(i) for i in range(len(profiles))}:
                raise ValueError('Unsupported weapon index')
            offset = profiles[int(parts[19])]['pose_offset_cm']
        values = list(map(float, parts[1:]))
        host = (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0) if self.camera_relative else self.read()
        guest_position = tuple(values[12:15])
        guest_rotation = tuple(values[15:18])
        if time.monotonic() - self.last_reload_check > 0.5:
            self.last_reload_check = time.monotonic()
            mtime = self.math_path.stat().st_mtime_ns
            if mtime != self.math_mtime:
                importlib.reload(weapon_pose_math)
                importlib.reload(camera_pose_math)
                self.math_mtime = mtime
        matrix = camera_pose_math.aligned_weapon(values[2:5], values[5:9], values[9:12], host, guest_position, guest_rotation, offset)
        self.latest = {'host': host, 'guest_position': guest_position, 'guest_rotation': guest_rotation, 'sequence': int(parts[0]), 'received': time.monotonic()}
        return matrix
