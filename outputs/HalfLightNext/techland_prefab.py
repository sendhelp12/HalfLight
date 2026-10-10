"""Read the observed JSON or MsgP/MessagePack prefab, with bounded decoding."""
import json, struct

def decode(raw):
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError('Prefab exceeds reader bound')
    if not raw.startswith(b'MsgP'):
        return json.loads(raw)
    cursor = 4
    nodes = 0

    def take(size):
        nonlocal cursor
        if size < 0 or cursor + size > len(raw):
            raise ValueError('Truncated MsgP prefab')
        result = raw[cursor:cursor + size]
        cursor += size
        return result

    def number(fmt):
        return struct.unpack(fmt, take(struct.calcsize(fmt)))[0]

    def value(depth=0):
        nonlocal nodes
        nodes += 1
        if depth > 64 or nodes > 100000:
            raise ValueError('Prefab nesting/node bound exceeded')
        tag = number('B')
        if tag < 128:
            return tag
        if tag >= 224:
            return tag - 256
        if 160 <= tag <= 191:
            return take(tag & 31).decode('utf-8')
        if tag == 192:
            return None
        if tag in (194, 195):
            return tag == 195
        formats = {202: '>f', 203: '>d', 204: '>B', 205: '>H', 206: '>I', 207: '>Q', 208: '>b', 209: '>h', 210: '>i', 211: '>q'}
        if tag in formats:
            return number(formats[tag])
        if tag in (217, 218, 219):
            return take(number({217: '>B', 218: '>H', 219: '>I'}[tag])).decode('utf-8')
        if tag in (196, 197, 198):
            return take(number({196: '>B', 197: '>H', 198: '>I'}[tag]))
        if 144 <= tag <= 159 or tag in (220, 221):
            count = tag & 15 if tag < 160 else number('>H' if tag == 220 else '>I')
            if count > 100000:
                raise ValueError('Array bound exceeded')
            return [value(depth + 1) for _ in range(count)]
        if 128 <= tag <= 143 or tag in (222, 223):
            count = tag & 15 if tag < 144 else number('>H' if tag == 222 else '>I')
            if count > 100000:
                raise ValueError('Map bound exceeded')
            result = {}
            for _ in range(count):
                key = value(depth + 1)
                if not isinstance(key, (str, int)) or key in result:
                    raise ValueError('Invalid or duplicate prefab key')
                result[key] = value(depth + 1)
            return result
        raise ValueError(f'Unobserved MessagePack tag: {tag:#x}')
    result = value()
    if cursor != len(raw) and raw[cursor:] != b'\x00':
        raise ValueError('Trailing prefab bytes')
    if not isinstance(result, dict) or '__filename__' not in result:
        raise ValueError('Unexpected prefab structure')
    return result
