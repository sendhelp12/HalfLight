"""Verify retail damage registration and owners through external reads only."""
import json, struct
from retail_bridge import ROOT, OUT, attach_reader
from pe_tools import PE, inspect
from native_target_locator import TargetLocator

def run():
    reader, loaded, state = attach_reader()
    try:
        profile = json.loads((ROOT / 'work/lab/retail-bridge-profile.json').read_text())['modules']
        game_pe = PE(loaded['gamedll_ph_x64_rwdi.dll']['path'])
        engine_pe = PE(loaded['engine_x64_rwdi.dll']['path'])
        bindings = profile['gamedll_ph_x64_rwdi.dll']['bindings']
        receiver_table = bindings['0x25695f8']['retail_rva']
        getter = game_pe.u64(game_pe.offset(receiver_table) + 16) - game_pe.base
        code = reader.read(reader.game + getter, 14)
        assert code[:3] == bytes.fromhex('488b0d') and code[7:10] == bytes.fromhex('48ff25')
        global_address = reader.game + getter + 7 + struct.unpack_from('<i', code, 3)[0]
        rt = reader.number(reader.number(global_address))
        packed = reader.number(rt + 288)
        data = packed & 281474976710655
        count = (packed >> 56) - 1 if packed >> 56 else reader.number(rt + 296, '<I')
        assert 0 < count < 128
        matches = []
        for index in range(count):
            pipe, dispatcher = struct.unpack('<QQ', reader.read(data + index * 16, 16))
            if pipe != 128:
                continue
            variants = reader.number(dispatcher + 8)
            rows = variants & 281474976710655
            n = (variants >> 56) - 1 if variants >> 56 else reader.number(dispatcher + 16, '<I')
            assert 0 < n < 128
            for j in range(n):
                for offset in (0, 8, 16):
                    slot = rows + j * 24 + offset
                    if reader.number(slot) == reader.game + 34896512:
                        matches.append(slot)
        assert len(matches) == 1, 'Damage receiver registration is ambiguous'
        wrapper = inspect(game_pe, 34896512, {})
        jump = next((i for i in wrapper['instructions'] if i['text'].startswith('jmp ')))
        assert int(jump['text'].split()[1], 16) == game_pe.base + 35128352
        wrapper['instructions'] = wrapper['instructions'][:wrapper['instructions'].index(jump) + 1]
        creator = engine_pe.exports()['?Create@CEntity@cbs@@SAPEAV12@UWorldIndex@2@@Z']
        raw = engine_pe.data[engine_pe.offset(creator + 15):engine_pe.offset(creator + 15) + 7]
        assert raw[:3] == bytes.fromhex('488b0d')
        pool = reader.number(reader.engine + creator + 22 + struct.unpack('<i', raw[3:])[0])
        arena, size = (reader.number(pool), reader.number(pool + 8))
        assert 16384 <= size <= 4294967296
        world = int(state['cbs_world_index'])
        needle = struct.pack('<Q', reader.game + receiver_table)
        systems = []
        for sid in range(1024):
            record = pool + 56 + (world * 1024 + sid) * 48
            for offset in (16, 32):
                chunk = reader.number(record + offset)
                if not arena <= chunk <= arena + size - 16384:
                    continue
                header = reader.read(chunk, 112)
                if not header or struct.unpack_from('<3I', header) != (2035499587, world, sid):
                    continue
                contents = reader.read(chunk, 16384)
                if contents and needle in contents[112:]:
                    systems.append(sid)
                    break
        systems = sorted(set(systems))
        assert len(systems) <= 1
        targets = []
        receiver_examples = []
        if systems:
            mesh_creator = next((v for n, v in engine_pe.exports().items() if n.startswith('?Create@CoMeshRender@@')))
            engine_profile = {'exports': {'CoMeshRender::Create(struct cbs::WorldIndex)': inspect(engine_pe, mesh_creator, {})}}
            locator = TargetLocator(reader, reader.game, engine_profile, world, systems[0], receiver_table)
            position = tuple((float(state['camera_' + axis]) for axis in 'xyz'))
            targets = locator.locate(position, max_distance=30, max_targets=32)
            record = pool + 56 + (world * 1024 + systems[0]) * 48
            pending = [reader.number(record + offset) for offset in (16, 32)]
            seen = set()
            while pending and len(receiver_examples) < 16:
                chunk = pending.pop()
                if chunk in seen or not arena <= chunk <= arena + size - 16384:
                    continue
                seen.add(chunk)
                assert len(seen) < 4096
                contents = reader.read(chunk, 16384)
                if not contents or struct.unpack_from('<3I', contents) != (2035499587, world, systems[0]):
                    continue
                pending.extend(struct.unpack_from('<QQ', contents, 16))
                cursor = 112
                while len(receiver_examples) < 16:
                    offset = contents.find(needle, cursor)
                    if offset < 0:
                        break
                    cursor = offset + 8
                    receiver = chunk + offset
                    handle = reader.number(receiver + 8)
                    if locator.resolve(handle) != receiver:
                        continue
                    entity = reader.number(receiver + 16)
                    eh = reader.number(entity + 8)
                    if locator.resolve(eh) != entity:
                        continue
                    packed = reader.number(entity + 120)
                    span = packed & 281474976710655
                    n = (packed >> 56) - 1 if packed >> 56 else reader.number(entity + 128, '<I')
                    assert 0 < n < 256
                    components = []
                    for i in range(n):
                        component = locator.resolve(reader.number(span + i * 8))
                        name = locator.typename(component) if component else None
                        if name and 'AI' in name:
                            children = [{'offset': o, 'type': locator.typename(reader.number(component + o))} for o in (104, 112, 120, 128, 136)]
                            item = {'type': name, 'address': component, 'children': children}
                            if name == '.?AVCoAIObservableHumanAI@@':
                                human = reader.number(component + 120)
                                registry = reader.number(human + 1544)
                                module = reader.number(registry + 112)
                                item.update(human=human, registry=registry, health_module=module, health_type=locator.typename(module), health_layout_matches_lab=locator.typename(module) == '.?AVHumanHealthModule@@' and reader.number(module + 8) & 2305843009213693951 == human + 128 and bool(reader.number(reader.number(module + 24))))
                            components.append(item)
                    root = locator.resolve(reader.number(entity + 88))
                    receiver_examples.append({'entity': entity, 'receiver': receiver, 'root_type': locator.typename(root) if root else None, 'components': components})
            for target in targets:
                human = int(target['human_ai'], 16)
                registry = reader.number(human + 1544)
                module = reader.number(registry + 112)
                valid = locator.typename(module) == '.?AVHumanHealthModule@@' and reader.number(module + 8) & 2305843009213693951 == human + 128 and bool(reader.number(reader.number(module + 24)))
                target.update(registry=registry, health_module=module, health_layout_matches_lab=valid)
        result = {'pid': reader.pid, 'receiver_table': receiver_table, 'receiver_getter': getter, 'receiver_rtti': rt, 'hit_slot': matches[0], 'hit_original': reader.game + 34896512, 'wrapper': wrapper, 'handler': 35128352, 'pool': pool, 'arena': arena, 'arena_size': size, 'world': world, 'receiver_systems': systems, 'health_getter': 18038432, 'targets': targets, 'receiver_examples': receiver_examples, 'scope': 'external registration and CBS reads; no native damage calls'}
        (OUT / 'native-damage-registration-verification.json').write_text(json.dumps(result, indent=2) + '\n')
        print('PASS retail native damage registration: one exact receiver callback;', len(systems), 'occupied receiver systems')
        print('Nearby human targets:', len(targets), '; verified health layouts:', sum((t['health_layout_matches_lab'] for t in targets)))
    finally:
        reader.close()
if __name__ == '__main__':
    run()
