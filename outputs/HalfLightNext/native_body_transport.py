"""Fresh, identity-bound head/torso/limb shapes from the native update."""
import math, struct
from camera_pose_math import host_to_guest
HEADER = struct.Struct('<II3QII')
SHAPE = struct.Struct('<QQII8f')
IMPACT = struct.Struct('<3Q2I8f')

def impacts(raw, pid, session, tick, banks):
    if len(raw) != 4112 or struct.unpack_from('<IIQ', raw) != (843662920, pid, session):
        raise ValueError('Impact snapshot identity/size')
    rows = []
    seen = set()
    for i in range(64):
        seq, expiry, entity, bank, region, *v = IMPACT.unpack_from(raw, 16 + i * 64)
        if not seq or expiry <= tick:
            continue
        if seq in seen or not entity or expiry > tick + 1000 or (bank >= banks) or (region >= 14) or (not all((math.isfinite(n) for n in v))):
            raise ValueError('Invalid impact')
        if abs(sum((n * n for n in v[3:6])) - 1) > 0.01 or not 0.1 <= v[6] <= 3 or (not 0 <= v[7] <= 0.6):
            raise ValueError('Invalid impact response')
        seen.add(seq)
        rows.append((seq, entity, bank, region, tuple(v[:3]), tuple(v[3:6]), v[6], v[7]))
    return sorted(rows)

def decode(raw, pid, session, tick):
    if len(raw) not in (10792, 12584):
        raise ValueError('Body snapshot size')
    magic, owner, nonce, sequence, expiry, count, reserved = HEADER.unpack_from(raw)
    limit = 192 if magic == 893666888 and len(raw) == 10792 else 224 if magic == 910444104 and len(raw) == 12584 else 0
    if not limit or (owner, nonce) != (pid, session) or (not sequence) or reserved or (count > limit) or (not tick < expiry <= tick + 1000):
        raise ValueError('Stale or mismatched body snapshot')
    shapes = {}
    seen = set()
    for i in range(count):
        entity, root, region, padding, *values = SHAPE.unpack_from(raw, 40 + i * 56)
        centre, axis, radius, half = (tuple(values[:3]), tuple(values[3:6]), values[6], values[7])
        if not entity or not root or padding or (region >= (12 if limit == 192 else 14)) or ((entity, region) in seen) or (not all((math.isfinite(v) for v in values))) or (not (0.025 if region >= 12 else 0.04) <= radius <= 0.6) or (not radius < half <= 1.8) or (abs(sum((v * v for v in axis)) - 1) > 0.01):
            raise ValueError('Invalid animated body region')
        seen.add((entity, region))
        shapes.setdefault(entity, []).append({'root': root, 'region': region, 'centre': centre, 'axis': axis, 'radius': radius, 'half': half})
    return shapes

def capsule(shape, host, guest_position, guest_rotation):
    centre = host_to_guest(shape['centre'], host, guest_position, guest_rotation)
    tip = host_to_guest(tuple((shape['centre'][i] + shape['axis'][i] for i in range(3))), host, guest_position, guest_rotation)
    axis = tuple(((tip[i] - centre[i]) / 100 for i in range(3)))
    length = math.sqrt(sum((v * v for v in axis)))
    axis = tuple((v / length for v in axis))
    q = (-axis[1], axis[0], 0, 1 + axis[2]) if axis[2] > -0.999999 else (1, 0, 0, 0)
    norm = math.sqrt(sum((v * v for v in q)))
    q = tuple((v / norm for v in q))
    a = tuple((centre[i] + axis[i] * 200 for i in range(3)))
    b = tuple((centre[i] - axis[i] * 200 for i in range(3)))
    return (centre + q, a, b)
