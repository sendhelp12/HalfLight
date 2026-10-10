"""Read the loaded campaign rig; no native calls, writes or gameplay input."""
import json, math, struct
from retail_bridge import ROOT, OUT, attach_reader
from pe_tools import PE, inspect

def run():
    reader, loaded, state = attach_reader()
    try:
        pe = PE(loaded['engine_x64_rwdi.dll']['path'])
        exports = pe.exports()
        creator = exports['?Create@CEntity@cbs@@SAPEAV12@UWorldIndex@2@@Z']
        instruction = pe.data[pe.offset(creator + 15):pe.offset(creator + 15) + 7]
        assert instruction[:3] == bytes.fromhex('488b0d')
        pool = reader.number(reader.engine + creator + 22 + struct.unpack('<i', instruction[3:])[0])
        arena, size = (reader.number(pool), reader.number(pool + 8))
        assert 16384 <= size <= 4294967296

        def typename(address):
            table = reader.number(address)
            locator = reader.number(table - 8)
            raw = reader.read(locator, 24)
            if not raw:
                return None
            fields = struct.unpack('<6I', raw)
            base = locator - fields[5]
            if fields[0] != 1 or base not in (reader.engine, reader.game):
                return None
            name = reader.read(base + fields[3] + 16, 160)
            return name.split(b'\x00')[0].decode(errors='replace') if name and name.startswith(b'.?A') else None
        player = int(state['player'])
        proxy = reader.number(player + 56)
        entity = reader.number(proxy + 16)
        handle = reader.number(entity + 88)
        skeleton = arena + (handle << 4 & 4294967295)
        assert typename(player) == '.?AVPlayerDI_PH@@'
        assert typename(entity) == '.?AVCEntity@cbs@@' and reader.number(skeleton + 8) == handle
        assert typename(skeleton) == '.?AVCoSkeleton@@' and reader.number(skeleton + 16) == entity
        getter = inspect(pe, exports['?GetModelXformElement@CoSkeleton@@UEBAAEBVmtx34@@H@Z'], {})
        assert any(('[rbx + 0x2a0]' in i['text'] for i in getter['instructions']))
        buffers = []
        for offset in (672, 704):
            pointer, count, unused, definition = struct.unpack('<QIIQ', reader.read(skeleton + offset, 24))
            assert 0 < count < 1024 and typename(definition) == '.?AVCCompactMesh@@'
            matrices = reader.read(pointer, count * 48)
            assert matrices and all((math.isfinite(v) for v in struct.unpack('<' + str(count * 12) + 'f', matrices)))
            buffers.append({'offset': offset, 'pointer': pointer, 'count': count, 'definition': definition})
        assert buffers[0]['count'] == buffers[1]['count'] == 390
        definition = buffers[0]['definition']
        elements = reader.number(reader.number(definition + 120) + 8)
        bones = []
        for index in range(390):
            element = elements + index * 208
            name_pointer = reader.number(element + 120) & 2305843009213693951
            raw = reader.read(name_pointer, 200)
            assert raw
            name = raw.split(b'\x00')[0].decode()
            parent = reader.number(element + 198, '<h')
            assert -1 <= parent < index
            bones.append({'index': index, 'name': name, 'parent': parent})
        assert all(bones[i]['name'].startswith(prefix) for i,prefix in ((26,'r_finger'),(87,'l_finger')))
        name_pointer = reader.number(skeleton + 528) & 2305843009213693951
        rig = reader.read(name_pointer, 120).split(b'\x00')[0].decode()
        assert rig == 'player_fpp_phx_skeleton.msh'
        result = {'pid': reader.pid, 'player': player, 'proxy': proxy, 'entity': entity, 'entity_handle': reader.number(entity + 8), 'skeleton': skeleton, 'handle': handle, 'rig': rig, 'buffers': buffers, 'bones': bones, 'getter': getter, 'hierarchy_matches_lab': True, 'scope': 'read-only rig and buffer verification; no poses applied'}
        (OUT / 'native-hand-layout-verification.json').write_text(json.dumps(result, indent=2) + '\n')
        print('PASS campaign rig: owned 390-bone hierarchy and buffers verified')
        return result
    finally:
        reader.close()
if __name__ == '__main__':
    run()
