"""Half Sword root pose -> native axe affine matrix, without game access.

The mesh converter bakes its visible component's +8 cm local Z offset.
Never add that offset again to a root pose. A shared world/camera anchor
must be supplied by the caller; this module does not establish one.
"""
import math
import struct

def native_matrix(position_cm, quaternion_xyzw, scale_xyz=(1, 1, 1), guest_origin_cm=(0, 0, 0), host_origin_m=(0, 0, 0)):
    """Return 12 row-major float values for mtx34 (translation at 3/7/11).

    Global basis D maps guest (X,Y,Z) to native (X,Z,Y). The world anchor
    here is translation only; a later calibrated heading can left-multiply
    this result. Inputs are actual source root transforms, not visible-part
    transforms. No interpolation or stale-packet policy is hidden here.
    """
    groups = (position_cm, quaternion_xyzw, scale_xyz, guest_origin_cm, host_origin_m)
    if tuple(map(len, groups)) != (3, 4, 3, 3, 3):
        raise ValueError('Expected position3, quaternion4, scale3 and two origin3 values')
    if not all((math.isfinite(float(x)) for group in groups for x in group)):
        raise ValueError('Non-finite pose or anchor')
    norm = math.sqrt(sum((float(v) ** 2 for v in quaternion_xyzw)))
    if abs(norm - 1) > 0.01:
        raise ValueError('Quaternion must have unit length')
    if not all((0 < float(v) <= 100 for v in scale_xyz)):
        raise ValueError('Unsupported weapon scale')
    x, y, z, w = (float(v) / norm for v in quaternion_xyzw)
    rotation = ((1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)), (2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)), (2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)))
    order = (0, 2, 1)
    matrix = []
    for i, guest_i in enumerate(order):
        for guest_j in order:
            matrix.append(rotation[guest_i][guest_j] * float(scale_xyz[guest_j]))
        matrix.append(float(host_origin_m[i]) + 0.01 * (float(position_cm[guest_i]) - float(guest_origin_cm[guest_i])))
    return tuple(matrix)

def packed_native_matrix(*args, **kwargs):
    """Serialize the observed 48-byte affine layout; makes no native call."""
    return struct.pack('<12f', *native_matrix(*args, **kwargs))

def visible_component_matrix(position_cm, quaternion_xyzw, scale_xyz=(1, 1, 1), guest_origin_cm=(0, 0, 0), host_origin_m=(0, 0, 0), component_offset_cm=8):
    """Use the actual simulated visible mesh pose with the existing asset.

    The imported geometry includes its old +8 cm component offset. Undo
    that baked offset in mesh-local space when using the component pose,
    rather than assuming the separately simulated grip follows the blade.
    """
    matrix = list(native_matrix(position_cm, quaternion_xyzw, scale_xyz, guest_origin_cm, host_origin_m))
    if component_offset_cm not in (0, 5, 8):
        raise ValueError('Unsupported imported weapon pivot')
    for row in range(3):
        matrix[row * 4 + 3] -= component_offset_cm * 0.01 * matrix[row * 4 + 1]
    return tuple(matrix)
