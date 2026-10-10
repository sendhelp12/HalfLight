import argparse, ctypes as C, hashlib, json, os, re, struct, subprocess, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'work/retail'
sys.path.insert(0, str(ROOT / 'outputs/HalfLightNext'))
from dl2_reader import Reader, find_game_pid, K, W, MODULEENTRY32W

def weapon_prefab(mesh):
    assert re.fullmatch('halflight_guest_[a-z0-9_]+\\.msh', mesh), 'Unexpected custom mesh'
    return {'__filename__': {'Version': 4, 'RuntimeData': {'Components': [{'Class': 'CoWorldXform', 'PrefabFields': {'m_PcId': '1', 'm_RootXform': '1'}}, {'Class': 'CoMeshRender', 'PrefabFields': {'m_PcId': '2', 'm_XformComponent': '1'}, 'Fields': {'m_MeshName': mesh, 'm_SkinName': 'Default'}}]}}}

def modules(pid):
    snapshot = K.CreateToolhelp32Snapshot(8 | 16, pid)
    assert snapshot != C.c_void_p(-1).value, 'Cannot enumerate retail modules'
    entry = MODULEENTRY32W()
    entry.dwSize = C.sizeof(entry)
    result = {}
    try:
        ok = K.Module32FirstW(snapshot, C.byref(entry))
        while ok:
            result[entry.szModule.lower()] = {'base': entry.modBaseAddr, 'path': Path(entry.szExePath)}
            ok = K.Module32NextW(snapshot, C.byref(entry))
    finally:
        K.CloseHandle(snapshot)
    return result

def attach_reader():
    pid = find_game_pid()
    assert pid, 'Retail DL2 is not running'
    reader = Reader(pid, ROOT / 'outputs/HalfLightNext')
    try:
        assert reader.profile_ok, 'Retail PE identity changed'
        loaded = modules(pid)
        profile = json.loads((ROOT / 'work/lab/retail-bridge-profile.json').read_text())
        for name, entry in profile['modules'].items():
            assert loaded[name]['path'] == Path(entry['path'])
            assert hashlib.sha256(loaded[name]['path'].read_bytes()).hexdigest() == entry['sha256']
        assert not any((n.startswith(('halflightbridge.', 'halflightrenderprobe.', 'halflightframeprobe.', 'halflightframepacer.')) for n in loaded)), 'Legacy probes loaded; restart retail DL2'
        state = reader.snapshot('retail-preparation')
        assert state['camera_valid'] == '1' and int(state['player']) and int(state['level']), 'Load a campaign save first'
        world = reader.number(int(state['leveldi']) + 56)
        world_index = reader.number(world + 184, '<I') if world else 64
        assert world and world_index < 64, 'Campaign ILevel has no valid CBS world'
        state['cbs_world'] = str(world)
        state['cbs_world_index'] = str(world_index)
        return (reader, loaded, state)
    except BaseException:
        reader.close()
        raise

def load_native(reader, loaded, dll, slot, original):
    from native_loader import load_native as load
    load(reader,loaded,dll,slot,original,lambda:modules(reader.pid))

def observe(spawn=False, create=False, bank=False):
    OUT.mkdir(exist_ok=True)
    reader, loaded, state = attach_reader()
    pid = reader.pid
    try:
        profiles = json.loads((ROOT / 'outputs/HalfLightNext/Native-Update-Profiles.json').read_text())['installed_builds']
        profile = profiles['gamedll_ph_x64_rwdi.dll']
        callback = next((v for v in profile['callbacks'] if v['import'].startswith('?OnPostUpdate@')))
        game = loaded['gamedll_ph_x64_rwdi.dll']['base']
        table = int(profile['secondary_vtable_rva_hex'], 16)
        slot_offset = int(callback['slot_hex'], 16)
        thunk = int(callback['thunk_rva_hex'], 16)
        slot, original = (game + table + slot_offset, game + thunk)
        assert reader.number(int(state['gameph']) + 48) == game + table, 'Game callback receiver identity differs'
        assert reader.number(slot) == original and reader.read(original, 2) == b'\xff%', 'Callback already owned or changed'
        text = (ROOT / 'outputs/HalfLightNext/src/native_update_observer.cpp').read_text()
        text = text.replace('0x250aec8', hex(table)).replace('0x878', hex(slot_offset)).replace('0x1d76348', hex(thunk)).replace('_rwe', '_rwdi')
        hashes = json.loads((ROOT / 'work/lab/retail-bridge-profile.json').read_text())['modules']
        for variable, name in (('expected_game', 'gamedll_ph_x64_rwdi.dll'), ('expected_engine', 'engine_x64_rwdi.dll')):
            import re
            literal = ','.join(('0x' + hashes[name]['sha256'][i:i + 2] for i in range(0, 64, 2)))
            text, count = re.subn('(const unsigned char ' + variable + '\\[32\\]=)\\{[^}]+\\}', '\\g<1>{' + literal + '}', text)
            assert count == 1
        if spawn:
            prefab = weapon_prefab('halflight_guest_longsword.msh')
            payload = json.dumps(json.dumps(prefab, separators=(',', ':')))
            code = '\nstd::atomic<bool> spawn_attempted{false};\nstd::uintptr_t asset_entity=0,asset_mesh=0,asset_xform=0;\nbool prefab_loaded=false,root_verified=false,mesh_loaded=false,asset_hidden=false;\nstd::uint64_t asset_handle=0;\nbool prefab_lookup_matches=false;\nbool mesh_load_result=false;\nchar registered_name[256]{};\nbool safe_read(std::uintptr_t p,void* out,std::size_t size){\n    MEMORY_BASIC_INFORMATION r{};\n    if(!p || !VirtualQuery(reinterpret_cast<void*>(p),&r,sizeof(r)) || r.State!=MEM_COMMIT ||\n       (r.Protect&(PAGE_GUARD|PAGE_NOACCESS)) || p+size<p || p+size>reinterpret_cast<std::uintptr_t>(r.BaseAddress)+r.RegionSize)return false;\n    std::memcpy(out,reinterpret_cast<void*>(p),size);return true;\n}\ntemplate<class T> bool value(std::uintptr_t p,T& out){return safe_read(p,&out,sizeof(out));}\nvoid prepare_asset(void* self){\n    const auto engine=reinterpret_cast<std::uintptr_t>(GetModuleHandleW(L"engine_x64_rwdi.dll"));\n    const auto game=reinterpret_cast<std::uintptr_t>(GetModuleHandleW(L"gamedll_ph_x64_rwdi.dll"));\n    std::uintptr_t table=0,owner=0,manager=0,lane_owner=0;DWORD mode_key=0,lane_key=0;\n    if(!value(reinterpret_cast<std::uintptr_t>(self),table) || table!=game+0x241eba8 ||\n       !value(engine+0x180c6f0,owner) || !value(owner,manager) || !value(manager+8,mode_key) ||\n       !value(engine+0x180c6f8,lane_owner) || !value(lane_owner,lane_key) || mode_key>=1088 || lane_key>=1088)return;\n    const auto mode=reinterpret_cast<std::uintptr_t>(TlsGetValue(mode_key));\n    const auto lane=reinterpret_cast<std::uintptr_t>(TlsGetValue(lane_key));\n    if(mode>=2 || !lane || lane>128 || spawn_attempted.exchange(true))return;\n    // ILevel is the campaign LevelDI object, not its framework CLevel wrapper.\n    // CreateEntityObject dereferences ILevel+0x38 -> CBS world before it creates\n    // components; refuse a missing world rather than entering that native call.\n    const auto level=std::uintptr_t(LEVEL_ADDRESS);\n    std::uintptr_t world=0;unsigned world_index=64;\n    if(!value(level,table) || table!=game+LEVEL_TABLE || !value(level+0x38,world) || !world ||\n       !value(world+0xb8,world_index) || world_index>=64)return;\n    using GetManager=void*(*)();using Load=void*(*)(void*,std::uintptr_t,const char*);\n    const char* name="ASSET_CHECK_NAME";\n    auto* prefabs=reinterpret_cast<GetManager>(engine+0x620910)();\n    void* loaded=prefabs?reinterpret_cast<Load>(engine+0x161b80)(prefabs,reinterpret_cast<std::uintptr_t>(name),PREFAB_TEXT):nullptr;\n    prefab_loaded=loaded!=nullptr;\n    if(!prefab_loaded)return;\n    std::uintptr_t name_storage=0,name_data=0;\n    if(value(reinterpret_cast<std::uintptr_t>(loaded)+0x10,name_storage) && value(name_storage,name_data)){\n        name_data&=0x1fffffffffffffffull;\n        safe_read(name_data,registered_name,sizeof(registered_name));registered_name[255]=0;\n    }\n    using GetRoot=const void*(*)(const void*);using IsRoot=bool(*)(const void*);\n    const auto* root=reinterpret_cast<GetRoot>(engine+0x561390)(loaded);\n    root_verified=root && reinterpret_cast<IsRoot>(engine+0x566f30)(root);\n    if(!root_verified)return;\n    using Find=void*(*)(void*,std::uintptr_t);\n    prefab_lookup_matches=reinterpret_cast<Find>(engine+0x615030)(prefabs,reinterpret_cast<std::uintptr_t>(name))==loaded;\n    if(!prefab_lookup_matches)return;\n    CREATE_ASSET\n\n}\n'
            level_table = reader.number(int(state['leveldi'])) - reader.game
            code = code.replace('LEVEL_ADDRESS', state['leveldi']).replace('LEVEL_TABLE', hex(level_table)).replace('PREFAB_TEXT', payload).replace('ASSET_CHECK_NAME', 'halflight_retail_asset_check_' + str(time.time_ns()))
            creation = '\n    alignas(16) float matrix[12]={CAMERA_MATRIX};\n    matrix[3]+=matrix[2];matrix[7]+=matrix[6];matrix[11]+=matrix[10];\n    alignas(16) unsigned char options[56]{};\n    if(!safe_read(engine+0x27f6720,options,sizeof(options)))return;\n    using Create=void*(*)(std::uint64_t*,std::uintptr_t,void*,const float*,std::uintptr_t,void*,bool,bool);\n    std::uint64_t handle=0;\n    reinterpret_cast<Create>(engine+0x6028b0)(&handle,reinterpret_cast<std::uintptr_t>(name),reinterpret_cast<void*>(level),matrix,0,options,false,false);\n    asset_handle=handle;\n    if(!handle)return;\n    // CPointer carries a CBS handle; CEntityPointer::read_ptr expects a GUID.\n    // Use the arena referenced by the exported CEntity::Create function.\n    std::uintptr_t pool=0,arena_base=0;std::uint64_t arena_size=0;\n    const auto offset=(handle<<4)&0xffffffffull;\n    if(!value(engine+ENTITY_POOL_RVA,pool) || !value(pool,arena_base) || !value(pool+8,arena_size) ||\n       arena_size<16384 || arena_size>0x100000000ull || offset+0x100>arena_size)return;\n    asset_entity=arena_base+offset;\n    std::uint64_t found=0,packed=0;unsigned count=0;\n    if(!value(asset_entity+8,found) || found!=handle || !value(asset_entity+0x78,packed))return;\n    unsigned char stage=0;\n    if(!value(asset_entity+0x4a,stage))return;\n    if(stage<5){\n        // Prefab allocation leaves stage zero; render registration needs native creation.\n        using Initialize=void(*)(void*,bool);\n        reinterpret_cast<Initialize>(engine+0x489c30)(reinterpret_cast<void*>(asset_entity),false);\n    }\n    if(!value(asset_entity+0x4a,stage) || stage<5)return;\n    if(!value(asset_entity+0x78,packed))return;\n    if(packed>>56)count=unsigned(packed>>56)-1;else if(!value(asset_entity+0x80,count))return;\n    if(!count || count>64)return;\n    const auto arena=asset_entity-((handle<<4)&0xffffffffull);\n    for(unsigned i=0;i<count;++i){\n        std::uint64_t component_handle=0;std::uintptr_t component_table=0;\n        if(!value((packed&0xffffffffffffull)+i*8,component_handle))return;\n        const auto component=arena+((component_handle<<4)&0xffffffffull);\n        if(!value(component,component_table) || component_table!=engine+0x18ca5d8)continue;\n        if(!value(component+8,found) || found!=component_handle || !value(component+0x98,asset_xform))return;\n        asset_mesh=component;\n        const bool hidden=false;using Active=bool(*)(void*,const bool&);\n        const bool shown=true;\n        reinterpret_cast<Active>(engine+0x4a3ad0)(reinterpret_cast<void*>(component),shown);\n        using Activate=void(*)(void*);\n        reinterpret_cast<Activate>(engine+0x46cdc0)(reinterpret_cast<void*>(asset_entity));\n        using LoadMesh=bool(*)(void*,const char*);\n        mesh_load_result=reinterpret_cast<LoadMesh>(engine+0x4e3fd0)(reinterpret_cast<void*>(component),"halflight_guest_longsword.msh");\n        asset_hidden=reinterpret_cast<Active>(engine+0x4a3ad0)(reinterpret_cast<void*>(component),hidden);\n        const unsigned resource_offsets[2]={0xb0u,0x1e0u};\n        for(unsigned offset:resource_offsets){\n            std::uintptr_t resource=0,storage=0,filename=0;char resource_name[256]{};\n            if(value(component+offset,resource) && resource && value(resource+0x78,storage) && value(storage,filename) &&\n               safe_read(filename,resource_name,sizeof(resource_name))){\n                resource_name[255]=0;\n                if(std::strstr(resource_name,"halflight_guest_longsword"))mesh_loaded=true;\n            }\n        }\n        return;\n    }\n'
            if create:
                sys.path.insert(0, str(ROOT / 'work'))
                from pe_tools import PE
                pe = PE(loaded['engine_x64_rwdi.dll']['path'])
                creator = pe.exports()['?Create@CEntity@cbs@@SAPEAV12@UWorldIndex@2@@Z']
                instruction = pe.data[pe.offset(creator + 15):pe.offset(creator + 15) + 7]
                assert instruction[:3] == b'H\x8b\r', 'CBS creator arena instruction changed'
                pool_rva = creator + 22 + struct.unpack('<i', instruction[3:])[0]
                creation = creation.replace('ENTITY_POOL_RVA', hex(pool_rva))
                previous_path = OUT / 'native-asset-verification.json'
                if previous_path.exists() and (not bank):
                    previous = json.loads(previous_path.read_text())
                    if previous['pid'] == pid:
                        handles = [line.split(',')[1] for line in previous['output'].splitlines() if line.startswith('asset_handle,')]
                        if handles and int(handles[0], 16):
                            handle = int(handles[0], 16)
                            pool = reader.number(reader.engine + pool_rva)
                            arena = reader.number(pool)
                            size = reader.number(pool + 8)
                            offset = handle << 4 & 4294967295
                            if offset + 256 <= size and reader.number(arena + offset + 8) == handle:
                                creation = creation.replace('std::uint64_t handle=0;', f'std::uint64_t handle={handle}ull;')
                                creation = re.sub('    reinterpret_cast<Create>\\(engine\\+0x6028b0\\)\\([^\\n]+;', '    // Reuse the verified instance from the preceding check.', creation)
                                creation = creation.replace('    using Create=void*(*)(std::uint64_t*,std::uintptr_t,void*,const float*,std::uintptr_t,void*,bool,bool);', '').replace('    alignas(16) float matrix[12]={CAMERA_MATRIX};\n    matrix[3]+=matrix[2];matrix[7]+=matrix[6];matrix[11]+=matrix[10];', '')
                camera = reader.number(int(state['camera']) + 56)
                matrix = struct.unpack('<12f', reader.read(camera + 64, 48))
                values = []
                for v in matrix:
                    token = format(v, '.9g')
                    values.append(token + 'f' if '.' in token or 'e' in token else token + '.0f')
                creation = creation.replace('CAMERA_MATRIX', ','.join(values))
            code = code.replace('CREATE_ASSET', creation if create else 'return;')
            if bank:
                weapons = json.loads((ROOT / '.local/catalog.json').read_text())['weapons']
                meshes = [Path(w['native_mesh']).stem + suffix + '.msh' for suffix in ('', '_offhand') for w in weapons]
                count = len(meshes)
                arrays = 'const char* bank_meshes[]={' + ','.join((json.dumps(m) for m in meshes)) + '};\n'
                arrays += 'const char* bank_prefabs[]={' + ','.join((json.dumps(json.dumps(weapon_prefab(m), separators=(',', ':'))) for m in meshes)) + '};\n'
                prior_bank = OUT / 'native-bank-verification.json'
                if prior_bank.exists():
                    prior = json.loads(prior_bank.read_text())
                    records = [line.split(',') for line in prior['output'].splitlines() if line.startswith('bank,')]
                    if prior['pid'] == pid and len(records) == count and all((reader.number(int(row[3], 16) + 8) == int(row[2], 16) for row in records)):
                        arrays += 'const std::uint64_t bank_handles[]={' + ','.join((row[2] + 'ull' for row in records)) + '};\n'
                        code = code.replace('std::uint64_t handle=0;', 'std::uint64_t handle=bank_handles[bank_index];')
                        code = re.sub('    reinterpret_cast<Create>\\(engine\\+0x6028b0\\)\\([^\\n]+;', '    // Reuse the verified bank instances.', code)
                        code = re.sub('    using Create=[^\\n]+;\\n', '', code)
                        code = re.sub('    alignas\\(16\\) float matrix\\[12\\]=\\{[^\\n]+;\\n    matrix\\[3\\][^\\n]+;\\n', '', code)
                arrays += f'unsigned bank_index=0;std::atomic_flag bank_lock=ATOMIC_FLAG_INIT;int pack_results[{count}]{{}};std::uintptr_t pack_addresses[{count}]{{}};\nstruct BankRecord{{std::uint64_t handle,entity,mesh,xform;bool loaded,hidden;}};BankRecord bank_records[{count}]{{}};\n'
                arrays += f'bool bank_activated[{count}]{{}};unsigned char bank_stages[{count}]{{}};\n'
                code = re.sub('const char\\* name="halflight_retail_asset_check_[0-9]+";', f'char name[128]{{}};std::snprintf(name,sizeof(name),"halflight_retail_bank_{time.time_ns()}_%u",bank_index);', code)
                code = code.replace(payload, 'bank_prefabs[bank_index]').replace('"halflight_guest_longsword.msh"', 'bank_meshes[bank_index]')
                code = code.replace('        asset_hidden=reinterpret_cast<Active>', '        using IsActive=bool(*)(const void*);\n        bank_activated[bank_index]=reinterpret_cast<IsActive>(engine+0x15d200)(reinterpret_cast<void*>(component));\n        value(asset_entity+0x4a,bank_stages[bank_index]);\n        asset_hidden=reinterpret_cast<Active>')
                code = code.replace('        mesh_load_result=', '        char resource_path[160]{};std::snprintf(resource_path,sizeof(resource_path),"meshes/%s",bank_meshes[bank_index]);\n        mesh_load_result=')
                code = code.replace('(reinterpret_cast<void*>(component),bank_meshes[bank_index]);', '(reinterpret_cast<void*>(component),resource_path);')
                code = code.replace('        char resource_path[160]{};', '        using GetRuntime=void*(*)();using LoadPack=int(*)(void*,const char*,void**,unsigned,const char*);\n        void* pack=nullptr;char pack_path[256]{};\n        std::snprintf(pack_path,sizeof(pack_path),"HALFLIGHT_ASSET_ROOT/meshes/%s_obj",bank_meshes[bank_index]);\n        auto* runtime=reinterpret_cast<GetRuntime>(engine+0x14d760)();\n        if(runtime)pack_results[bank_index]=reinterpret_cast<LoadPack>(engine+0xc32060)(runtime,pack_path,&pack,0,nullptr);\n        pack_addresses[bank_index]=reinterpret_cast<std::uintptr_t>(pack);\n        char resource_path[160]{};')
                code = code.replace('std::strstr(resource_name,"halflight_guest_longsword")', 'std::strstr(resource_name,bank_meshes[bank_index])')
                code = arrays + code
                code += f'\nvoid prepare_bank(void* self){{\n    if(bank_lock.test_and_set())return;\n    if(bank_index<{count}){{\n        spawn_attempted=false;asset_handle=asset_entity=asset_mesh=asset_xform=0;\n        mesh_loaded=asset_hidden=mesh_load_result=false;\n        prepare_asset(self);\n        if(spawn_attempted.load()){{bank_records[bank_index]={{asset_handle,asset_entity,asset_mesh,asset_xform,mesh_loaded,asset_hidden}};++bank_index;}}\n    }}\n    bank_lock.clear();\n}}\n'
            text = text.replace('#include <cwchar>', '#include <cwchar>\n#include <cstring>')
            text = text.replace('void observe(void* self) {', code + '\nvoid observe(void* self) {')
            prepare_call = 'prepare_bank' if bank else 'prepare_asset'
            text = text.replace('    original(self);', f'    original(self);\n    if(active.load() && GetTickCount64()<deadline){prepare_call}(self);')
            text = text.replace('    fputs("complete,1\\n",log);', '    fprintf(log,"asset_attempted,%d\\nprefab_loaded,%d\\nroot_verified,%d\\nprefab_lookup_matches,%d\\nasset_handle,0x%llx\\nmesh_loaded,%d\\nasset_hidden,%d\\nasset_entity,0x%llx\\nasset_mesh,0x%llx\\nasset_xform,0x%llx\\n",spawn_attempted.load()?1:0,prefab_loaded?1:0,root_verified?1:0,prefab_lookup_matches?1:0,static_cast<unsigned long long>(asset_handle),mesh_loaded?1:0,asset_hidden?1:0,static_cast<unsigned long long>(asset_entity),static_cast<unsigned long long>(asset_mesh),static_cast<unsigned long long>(asset_xform));\n    fputs("complete,1\\n",log);')
            text = text.replace('    fputs("complete,1\\n",log);', '    fprintf(log,"registered_name,%s\\nmesh_load_result,%d\\n",registered_name,mesh_load_result?1:0);\n    fputs("complete,1\\n",log);')
            if bank:
                text = text.replace('    fputs("complete,1\\n",log);', '    for(unsigned i=0;i<bank_index;++i)fprintf(log,"activation,%u,%u,%d\\n",i,unsigned(bank_stages[i]),bank_activated[i]?1:0);\n    fputs("complete,1\\n",log);')
                text = text.replace('    fputs("complete,1\\n",log);', '    for(unsigned i=0;i<bank_index;++i)fprintf(log,"pack,%u,%d,0x%llx\\n",i,pack_results[i],static_cast<unsigned long long>(pack_addresses[i]));\n    fputs("complete,1\\n",log);')
                text = text.replace('    fputs("complete,1\\n",log);', '    for(unsigned i=0;i<bank_index;++i){const auto& b=bank_records[i];fprintf(log,"bank,%u,0x%llx,0x%llx,0x%llx,0x%llx,%d,%d\\n",i,static_cast<unsigned long long>(b.handle),static_cast<unsigned long long>(b.entity),static_cast<unsigned long long>(b.mesh),static_cast<unsigned long long>(b.xform),b.loaded?1:0,b.hidden?1:0);}\n    fputs("complete,1\\n",log);')
        assets=Path(json.loads((ROOT/'.local/install.json').read_text())['asset_root']).resolve()
        owned=json.loads((ROOT/'.local/assets-files.json').read_text())
        assert assets.is_relative_to(Path(owned['roots']['dying_light']).resolve()),'Asset path escapes owned installation'
        text=text.replace('HALFLIGHT_ASSET_ROOT',str(assets).replace(chr(92),'/'))
        text=text.replace('char pack_path[256]{};','char pack_path[1024]{};')
        text=text.replace('auto* runtime=reinterpret_cast<GetRuntime>(engine+0x14d760)();', '''
        // Newly generated packs may arrive after the campaign's initial directory scan.
        static bool filesystem_refreshed=false;
        if(!filesystem_refreshed){
            using Refresh=void(*)();
            const auto filesystem=GetModuleHandleW(L"filesystem_x64_rwdi.dll");
            const auto refresh=filesystem?GetProcAddress(filesystem,"?refresh@fs@@YAXXZ"):nullptr;
            if(!refresh)return;
            reinterpret_cast<Refresh>(refresh)();filesystem_refreshed=true;
        }
        auto* runtime=reinterpret_cast<GetRuntime>(engine+0x14d760)();''')
        source = OUT / 'native_retail_observer.cpp'
        source.write_text(text)
        dll = OUT / ('HalfLightRetailObserver' + str(time.time_ns()) + '.dll')
        env = dict(os.environ, ZIG_GLOBAL_CACHE_DIR=str(ROOT / '.local/zig-cache'))
        subprocess.run([str(ROOT / '.local/tools/zig-windows-x86_64-0.13.0/zig.exe'), 'c++', str(source), '-target', 'x86_64-windows-gnu', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', '-shared', '-static', '-ladvapi32', '-o', str(dll)], env=env, check=True)
        load_native(reader, loaded, dll, slot, original)
        log = OUT / f'native-update-observation-{pid}.csv'
        deadline = time.monotonic() + 12
        content = ''
        while time.monotonic() < deadline and reader.alive():
            if log.exists():
                content = log.read_text()
                if 'complete,1' in content:
                    break
            time.sleep(0.1)
        restored = reader.alive() and reader.number(slot) == original
        result = {'pid': pid, 'player': state, 'dll': str(dll), 'sha256': hashlib.sha256(dll.read_bytes()).hexdigest(), 'slot_restored': restored, 'log': str(log), 'output': content, 'gameplay_input_injected': False}
        (OUT / ('native-bank-verification.json' if bank else 'native-asset-verification.json' if create else 'native-prefab-verification.json' if spawn else 'native-phase-verification.json')).write_text(json.dumps(result, indent=2))
        assert restored and content.startswith('status,observation_finished\nrestored,1\n'), 'Retail observer did not restore cleanly'
        calls = int(next((line.split(',')[1] for line in content.splitlines() if line.startswith('calls,'))))
        assert calls > 0, 'Retail callback did not run during observation'
        if spawn:
            assert 'root_verified,1\n' in content, 'Retail prefab root metadata invalid; no entity creation was attempted'
        if create:
            assert 'mesh_loaded,1\n' in content and 'asset_hidden,1\n' in content, 'Retail weapon resource not verified; inspect native-asset-verification.json'
        if bank:
            rows = [line.split(',') for line in content.splitlines() if line.startswith('bank,')]
            assert len(rows) == count and all((row[-2:] == ['1', '1'] for row in rows)), 'Retail weapon bank incomplete'
            activation = [line.split(',') for line in content.splitlines() if line.startswith('activation,')]
            assert len(activation) == count and all((int(row[2]) >= 5 and row[3] == '1' for row in activation)), 'Retail weapon bank lifecycle did not activate'
            print('PASS', count, 'retail weapon instances loaded and hidden')
        print('PASS retail callback:', calls, 'calls; original slot restored; no gameplay input injected')
    finally:
        reader.close()

if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=('verify-bank',));parser.parse_args()
    observe(spawn=True,create=True,bank=True)
