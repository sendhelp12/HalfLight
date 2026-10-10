"""Read-only enemy lookup in validated occupied CBS component slots.

Uses the verified component pool and RTTI, not a cached last-spawned AI pointer.
No health writes, spawning, damage calls or game-function invocations.
"""
import math, re, struct

class TargetLocator:

    def __init__(self, reader, game_base, engine_profile, world, receiver_system, receiver_table=39228920):
        self.reader = reader
        self.game = game_base
        self.world = world
        self.sid = receiver_system
        assert 0 < receiver_table < 67108864
        self.receiver_table = receiver_table
        creator = next((v for n, v in engine_profile['exports'].items() if 'CoMeshRender::Create(struct cbs::WorldIndex)' in n))
        loads = {}
        for i, ins in enumerate(creator['instructions'][:-1]):
            match = re.fullmatch('mov (rcx|r8), qword ptr \\[rip \\+ (0x[0-9a-f]+)\\]', ins['text'])
            if match:
                loads[match[1]] = creator['instructions'][i + 1]['rva'] + int(match[2], 16)
        assert set(loads) == {'rcx', 'r8'}
        assert reader.read(reader.engine + creator['rva'], 24) == bytes.fromhex(creator['prologue_hex'])
        self.pool = reader.number(reader.engine + loads['rcx'])
        self.arena = reader.number(self.pool)
        self.arena_size = reader.number(self.pool + 8)
        assert 0 <= world < 64 and 0 <= self.sid < 1024 and (16384 <= self.arena_size <= 4294967296)

    def typename(self, address):
        table = self.reader.number(address)
        locator = self.reader.number(table - 8)
        data = self.reader.read(locator, 24)
        if not data:
            return None
        fields = struct.unpack('<6I', data)
        base = locator - fields[5]
        if fields[0] != 1 or base not in (self.game, self.reader.engine):
            return None
        name = self.reader.read(base + fields[3] + 16, 200)
        return name.split(b'\x00')[0].decode(errors='replace') if name and name.startswith(b'.?A') else None

    def resolve(self, handle):
        address = self.arena + (handle << 4 & 4294967295)
        if not self.arena <= address < self.arena + self.arena_size or self.reader.number(address + 8) != handle:
            return None
        chunk = address & ~16383
        header = self.reader.read(chunk, 112)
        if not header or struct.unpack_from('<3I', header) != (2035499587, handle >> 28 & 63, handle >> 34 & 1023):
            return None
        multiplier, shift = struct.unpack_from('<II', header, 32)
        index = (address - chunk - 112) * multiplier >> (shift & 63)
        capacity = struct.unpack_from('<H', header, 46)[0]
        bit_offset = 48 + index // 64 * 8
        if index >= capacity or bit_offset + 8 > 112 or (not struct.unpack_from('<Q', header, bit_offset)[0] & 1 << index % 64):
            return None
        return address

    def locate(self, camera_position, max_distance=8, max_targets=16):
        assert len(camera_position) == 3 and all((math.isfinite(v) for v in camera_position)) and (0 < max_distance <= 30) and (0 < max_targets <= 32)
        arena = self.reader.number(self.pool)
        size = self.reader.number(self.pool + 8)
        if not 65536 <= arena < 140737488355328 or not 16384 <= size <= 4294967296:
            return []
        self.arena, self.arena_size = (arena, size)
        record = self.pool + 56 + (self.world * 1024 + self.sid) * 48
        count = self.reader.number(record, '<I')
        assert count < 100000
        if not count:
            return []
        pending = [self.reader.number(record + o) for o in (16, 32)]
        visited = set()
        receivers = []
        needle = struct.pack('<Q', self.game + self.receiver_table)
        while pending:
            chunk = pending.pop()
            if chunk in visited:
                continue
            assert len(visited) < min(self.arena_size // 16384, 4096)
            if not self.arena <= chunk <= self.arena + self.arena_size - 16384:
                continue
            raw = self.reader.read(chunk, 16384)
            if not raw or struct.unpack_from('<3I', raw) != (2035499587, self.world, self.sid):
                continue
            visited.add(chunk)
            pending.extend(struct.unpack_from('<QQ', raw, 16))
            cursor = 112
            while True:
                offset = raw.find(needle, cursor)
                if offset < 0:
                    break
                cursor = offset + 8
                if offset % 16 or offset + 24 > len(raw):
                    continue
                handle, entity = struct.unpack_from('<QQ', raw, offset + 8)
                receiver = chunk + offset
                if self.resolve(handle) != receiver or self.typename(entity) != '.?AVCEntity@cbs@@':
                    continue
                entity_handle = self.reader.number(entity + 8)
                if self.resolve(entity_handle) != entity:
                    continue
                root_handle = self.reader.number(entity + 88)
                xform = self.resolve(root_handle)
                if not xform or self.typename(xform) != '.?AVCoSkeleton@@':
                    continue
                packed = self.reader.number(entity + 120)
                data = packed & 281474976710655
                small = packed >> 56
                component_count = small - 1 if small else self.reader.number(entity + 128, '<I')
                if not 0 < component_count < 256:
                    continue
                human = None
                for i in range(component_count):
                    component = self.resolve(self.reader.number(data + i * 8))
                    if component and self.typename(component) == '.?AVCoAIObservableHumanAI@@':
                        ai = self.reader.number(component + 120)
                        if self.reader.number(component + 16) == entity and self.typename(ai) == '.?AVHumanAI@@':
                            human = ai
                            break
                if not human:
                    continue
                raw_matrix = self.reader.read(xform + 128, 48)
                if not raw_matrix:
                    continue
                matrix = struct.unpack('<12f', raw_matrix)
                if not all((math.isfinite(v) and abs(v) < 100000.0 for v in matrix)):
                    continue
                distance = math.sqrt(sum(((matrix[i * 4 + 3] - camera_position[i]) ** 2 for i in range(3))))
                if distance > max_distance:
                    continue
                receivers.append({'entity': hex(entity), 'entity_handle': hex(entity_handle), 'root_handle': hex(root_handle), 'xform': hex(xform), 'receiver': hex(receiver), 'receiver_handle': hex(handle), 'human_ai': hex(human), 'world_matrix': matrix, 'distance': distance})
        return sorted(receivers, key=lambda r: r['distance'])[:max_targets]
