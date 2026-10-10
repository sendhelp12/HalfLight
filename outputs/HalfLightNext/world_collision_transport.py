"""Original lab-floor back-channel, derived from the user's local map source.

This handles the verified axis/scale mapping; no native memory access.
It does not discover arbitrary campaign geometry.
"""
import math
from camera_pose_math import alignment, host_to_guest

def rigid_floor_transform(host_camera, guest_camera_position, guest_camera_rotation, host_centre):
    """Rigid inverse of the same frame used for the rendered weapon.

    The local floor geometry is already converted (X,Y,Z)->(X,Z,Y).
    Applying this proper rotation preserves collision without mesh recooking.
    """
    rotation, _ = alignment(host_camera, guest_camera_position, guest_camera_rotation)
    order = (0, 2, 1)
    r = tuple((tuple((rotation[order[j]][order[i]] for j in range(3))) for i in range(3)))
    trace = sum((r[i][i] for i in range(3)))
    if trace > 0:
        s = math.sqrt(trace + 1) * 2
        q = ((r[2][1] - r[1][2]) / s, (r[0][2] - r[2][0]) / s, (r[1][0] - r[0][1]) / s, 0.25 * s)
    else:
        i = max(range(3), key=lambda index: r[index][index])
        j = (i + 1) % 3
        k = (i + 2) % 3
        s = math.sqrt(1 + r[i][i] - r[j][j] - r[k][k]) * 2
        q = [0, 0, 0, 0]
        q[i] = 0.25 * s
        q[j] = (r[j][i] + r[i][j]) / s
        q[k] = (r[k][i] + r[i][k]) / s
        q[3] = (r[k][j] - r[j][k]) / s
    norm = math.sqrt(sum((v * v for v in q)))
    q = tuple((v / norm for v in q))
    position = host_to_guest(host_centre, host_camera, guest_camera_position, guest_camera_rotation)
    return (position, q, r)

def guest_point(host_point, guest_origin, host_anchor):
    if any((len(value) != 3 for value in (host_point, guest_origin, host_anchor))):
        raise ValueError('Expected three-component positions')
    if not all((math.isfinite(float(n)) for value in (host_point, guest_origin, host_anchor) for n in value)):
        raise ValueError('Non-finite world coordinate')
    return tuple((float(guest_origin[i]) + 100 * (float(host_point[j]) - float(host_anchor[j])) for i, j in enumerate((0, 2, 1))))

def floor_patch(centre, half_extents, anchor, radius=2):
    if radius <= 0 or radius > 3 or half_extents[1] <= 0:
        raise ValueError('Invalid local floor patch')
    left = max(centre[0] - half_extents[0], anchor[0] - radius)
    right = min(centre[0] + half_extents[0], anchor[0] + radius)
    near = max(centre[2] - half_extents[2], anchor[2] - radius)
    far = min(centre[2] + half_extents[2], anchor[2] + radius)
    if left >= right or near >= far:
        raise ValueError('Anchor outside floor')
    y = centre[1] + half_extents[1]
    a, b, c, d = ((left, y, near), (right, y, near), (right, y, far), (left, y, far))
    return ((a, b, c), (a, c, d))
