"""Camera-relative placement of an actual simulated guest weapon."""
import math
from weapon_pose_math import visible_component_matrix
FIRST_PERSON_OFFSET = (0, 0, 0.25)

class WeaponOutOfReach(ValueError):
    pass

def alignment(host_camera, guest_camera_position, guest_camera_rotation):
    if len(host_camera) != 12 or len(guest_camera_position) != 3 or len(guest_camera_rotation) != 3:
        raise ValueError('Invalid camera dimensions')
    if not all((math.isfinite(float(v)) for values in (host_camera, guest_camera_position, guest_camera_rotation) for v in values)):
        raise ValueError('Non-finite camera')
    pitch, yaw, roll = map(math.radians, guest_camera_rotation)
    cp, sp, cy, sy, cr, sr = (math.cos(pitch), math.sin(pitch), math.cos(yaw), math.sin(yaw), math.cos(roll), math.sin(roll))
    forward = (cp * cy, cp * sy, sp)
    right = (sr * sp * cy - cr * sy, sr * sp * sy + cr * cy, -sr * cp)
    up = (-(cr * sp * cy + sr * sy), sr * cy - cr * sp * sy, cr * cp)
    guest_axes = [tuple((axis[i] for i in (0, 2, 1))) for axis in (right, up, forward)]
    host_axes = [tuple((host_camera[row * 4 + col] for row in range(3))) for col in range(3)]
    host_axes[2] = tuple((-value for value in host_axes[2]))
    for axis in host_axes:
        if abs(sum((v * v for v in axis)) - 1) > 0.05:
            raise ValueError('Host camera basis is not unit length')
    for i in range(3):
        for j in range(i):
            if abs(sum((a * b for a, b in zip(host_axes[i], host_axes[j])))) > 0.05:
                raise ValueError('Host camera basis is not orthogonal')
    rotation = tuple((tuple((sum((host_axes[k][i] * guest_axes[k][j] for k in range(3))) for j in range(3))) for i in range(3)))
    anchor = tuple((host_camera[i * 4 + 3] + sum((host_axes[k][i] * FIRST_PERSON_OFFSET[k] for k in range(3))) for i in range(3)))
    return (rotation, anchor)

def aligned_weapon(position, quaternion, scale, host_camera, guest_camera_position, guest_camera_rotation, component_offset_cm=8):
    rotation, anchor = alignment(host_camera, guest_camera_position, guest_camera_rotation)
    base = visible_component_matrix(position, quaternion, scale, guest_camera_position, (0, 0, 0), component_offset_cm)
    result = []
    for row in range(3):
        for col in range(3):
            result.append(sum((rotation[row][k] * base[k * 4 + col] for k in range(3))))
        result.append(anchor[row] + sum((rotation[row][k] * base[k * 4 + 3] for k in range(3))))
    eye = tuple((host_camera[i * 4 + 3] for i in range(3)))
    if any((sum(((result[i * 4 + 3] - origin[i]) ** 2 for i in range(3))) > 9 for origin in (anchor, eye))):
        raise WeaponOutOfReach('Guest weapon is more than three metres from its camera')
    return tuple(result)

def host_to_guest(point, host_camera, guest_camera_position, guest_camera_rotation):
    rotation, anchor = alignment(host_camera, guest_camera_position, guest_camera_rotation)
    converted = tuple((sum((rotation[k][i] * (point[k] - anchor[k]) * 100 for k in range(3))) for i in range(3)))
    return tuple((guest_camera_position[i] + converted[j] for i, j in enumerate((0, 2, 1))))
