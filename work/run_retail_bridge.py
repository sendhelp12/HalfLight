"""Campaign session using the existing source, pose, menu and combat adapters.

Starts disarmed. No world geometry publisher or campaign spawner is launched.
"""
import argparse, ctypes as C, hashlib, json, math, os, re, secrets, shutil, struct, subprocess, sys, threading, time
from pathlib import Path
from retail_bridge import ROOT, OUT, attach_reader, load_native, K, W
from live_pose_transport import PoseFeed, replace_packet
from native_camera_reader import CameraMapper
from weapon_profile import catalog
from halflight_runtime import processes, atomic_json, read_json
LAB = ROOT / 'work/lab'
STATE = OUT / 'active-session.json'
STOP = OUT / 'stop-session.txt'

def boost_source_priority(pid):
    K.GetPriorityClass.argtypes = [W.HANDLE]
    K.GetPriorityClass.restype = W.DWORD
    K.SetPriorityClass.argtypes = [W.HANDLE, W.DWORD]
    K.SetPriorityClass.restype = W.BOOL
    K.QueryFullProcessImageNameW.argtypes = [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)]
    K.QueryFullProcessImageNameW.restype = W.BOOL
    handle = K.OpenProcess(4608, False, pid)
    if not handle:
        raise C.WinError(C.get_last_error())
    try:
        name = C.create_unicode_buffer(32768)
        length = W.DWORD(len(name))
        assert K.QueryFullProcessImageNameW(handle, 0, name, C.byref(length)) and Path(name.value).name.lower() == 'halfswordue5-win64-shipping.exe', 'Source priority process identity changed'
        original = K.GetPriorityClass(handle)
        assert original, 'Source priority unavailable'
        wanted = 32768 if original in (32, 64, 16384) else original
        assert K.SetPriorityClass(handle, wanted) and K.GetPriorityClass(handle) == wanted, 'Source priority boost did not apply'
        return (handle, original, wanted)
    except BaseException:
        K.CloseHandle(handle)
        raise

def restore_source_priority(saved):
    handle, original, wanted = saved
    try:
        K.GetExitCodeProcess.argtypes = [W.HANDLE, C.POINTER(W.DWORD)]
        K.GetExitCodeProcess.restype = W.BOOL
        code = W.DWORD()
        assert K.GetExitCodeProcess(handle, C.byref(code)), 'Source liveness unavailable during priority restoration'
        if code.value == 259 and K.GetPriorityClass(handle) == wanted:
            assert K.SetPriorityClass(handle, original) and K.GetPriorityClass(handle) == original, 'Source priority restoration did not apply'
    finally:
        K.CloseHandle(handle)

def retained_seed(reader, loaded, previous):
    if previous.get('host') != 'retail' or previous.get('target_pid') != reader.pid:
        return None
    name = previous.get('damage_dll', '')
    if not re.fullmatch('HalfLightNativeAxeDamageRetail[0-9]+\\.dll', name):
        return None
    module = loaded.get(name.lower())
    if not module:
        return None
    path = LAB / name
    assert module['path'] == path.resolve(), 'Retained adapter path changed'
    log = (LAB / f'native-axe-damage-{reader.pid}.log').read_text()
    restored = previous.get('state') == 'stopped' and previous.get('callback_restored') is True and (previous.get('weapons_restored') is True)
    assert restored or all((k in log for k in ('status,stopped', 'hit_callback_restored,1', 'movement_callback_restored,1', 'complete,1')))
    image = path.read_bytes()
    nt = struct.unpack_from('<I', image, 60)[0]
    count = struct.unpack_from('<H', image, nt + 6)[0]
    opt = struct.unpack_from('<H', image, nt + 20)[0]
    hits = []
    for i in range(count):
        section = nt + 24 + opt + i * 40
        if image[section:section + 8].rstrip(b'\x00') not in (b'.data', b'.bss'):
            continue
        size, rva = struct.unpack_from('<II', image, section + 8)
        assert 0 < size < 32 * 2 ** 20
        raw = reader.read(module['base'] + rva, size)
        assert raw
        for offset in range(0, len(raw) - 224 + 1, 16):
            address = module['base'] + rva + offset
            vector = struct.unpack_from('<Q', raw, offset + 128)[0]
            if vector & 281474976710655 != address + 136 or vector >> 56 != 2:
                continue
            effect, value = struct.unpack_from('<If', raw, offset + 136)
            owner, pool = struct.unpack_from('<QQ', raw, offset + 112)
            if effect != 11 or not 0 < value <= 1000000 or (not owner) or (not pool):
                continue
            container = reader.number(owner)
            if reader.number(container) != reader.game + 40931608:
                continue
            hits.append(address)
    if not hits:
        return None
    assert len(hits) == 1, 'Retained owned seed is not unique: ' + str(hits)
    return {'module': module['base'], 'seed': hits[0], 'hash': hashlib.sha256(image).digest()}

def stage_helpers(registration):
    assert registration['receiver_systems'] == [205], 'Unsupported native receiver system'
    for name in ('publish_host_camera_follow.py', 'publish_discovered_target.py'):
        shutil.copy2(ROOT / 'work' / name, OUT / name)

def campaign_binding_valid(reader, state, rig):
    current = reader.snapshot('campaign-lifecycle')
    if any((current.get(key) != state.get(key) for key in ('player', 'level', 'camera', 'gameph'))):
        return False
    return reader.number(rig['player'] + 56) == rig['proxy'] and reader.number(rig['proxy'] + 16) == rig['entity'] and (reader.number(rig['entity'] + 8) == rig['entity_handle']) and (reader.number(rig['entity'] + 88) == rig['handle']) and (reader.number(rig['skeleton'] + 8) == rig['handle']) and (reader.number(rig['skeleton'] + 688) == rig['buffers'][0]['definition'])

def write_grips(pid, nonce, rig):
    definition = rig['buffers'][0]['definition']
    (LAB / f'native-axe-hand-{pid}.config').write_bytes(struct.pack('<II8Q6I', 826820168, pid, nonce, rig['player'], rig['proxy'], rig['entity'], rig['entity_handle'], rig['skeleton'], rig['handle'], definition, 390, 10, 11, 25, 45, 1))
    for bank in range(2 * len(catalog())):
        for prefix, count, first in (('', 68, 10), ('left-', 53, 79)):
            candidates = sorted(LAB.glob(f'native-axe-{prefix}grip-*-{bank}.config'), key=lambda p: p.stat().st_mtime_ns)
            assert candidates, 'Missing calibrated grip ' + str(bank)
            packet = bytearray(candidates[-1].read_bytes())
            assert len(packet) == 144 + count * 56
            old = struct.unpack_from('<II4QII', packet)
            assert old[0] == 844121672 and old[6:] == (count, 1)
            for i in range(count):
                index, parent = struct.unpack_from('<Ii', packet, 144 + i * 56)
                assert index == first + i and parent == rig['bones'][index]['parent']
            struct.pack_into('<II4QII', packet, 0, 844121672, pid, nonce, rig['skeleton'], rig['handle'], definition, count, 1)
            (LAB / f'native-axe-{prefix}grip-{pid}-{bank}.config').write_bytes(packet)
            if bank == 0:
                (LAB / f'native-axe-{prefix}grip-{pid}.config').write_bytes(packet)

def run():
    reader, loaded, state = attach_reader()
    pid = reader.pid
    nonce = secrets.randbits(64) or 1
    session = f'{nonce:016x}'
    children = []
    feed = None
    registration = None
    renew_stop = threading.Event()
    renew_thread = None
    heartbeat_error = []
    slot = reader.game + 37874600 + 944
    original = reader.game + 30180808
    source_stop = LAB / f'guest-stop-{session}.txt'
    lease = LAB / f'native-axe-session-{pid}.lease'
    inventory = processes()
    previous = json.loads((LAB / 'active-axe-session.json').read_text()) if (LAB / 'active-axe-session.json').exists() else {}
    source_pids = [key for key, value in inventory.items() if 'halfsword' in value and 'shipping' in value]
    if len(source_pids) != 1:
        reader.close()
        raise RuntimeError('Exactly one Half Sword shipping process is required')
    source_pid = source_pids[0]
    assert previous.get('controller_pid') not in inventory or (previous.get('controller_pid') == os.getpid() and previous.get('state') == 'stopped'), 'Another bridge controller is still running'
    retained_session = OUT / 'retained-session.json'
    damage_log = LAB / f'native-axe-damage-{pid}.log'
    if previous.get('damage_dll') and damage_log.exists() and ('seed_retained_until_exit,1\n' in damage_log.read_text()):
        atomic_json(retained_session, previous)
    elif retained_session.exists():
        previous = json.loads(retained_session.read_text())
    launcher = json.loads((LAB / 'halflight-launcher.json').read_text()) if (LAB / 'halflight-launcher.json').exists() else {}
    assert launcher.get('pid') not in inventory, 'Stop the lab launcher before attaching the campaign session'
    assert reader.number(slot) == original, 'Campaign callback already has an owner'
    K.GetTickCount64.restype = C.c_uint64
    active = {'host': 'retail', 'controller_pid': os.getpid(), 'target_pid': pid, 'source_pid': source_pid, 'session': session, 'state': 'starting', 'stop_path': str(source_stop), 'lease_path': str(lease), 'source_path': str(LAB / f'guest-live-pose-{session}.csv'), 'source_mailbox': session, 'follow_player': True, 'simulation_only': False, 'world_geometry_collision': False}

    def status(phase, **extra):
        active.update(state=phase, **extra)
        for path in (STATE, LAB / 'active-axe-session.json'):
            deadline = time.monotonic() + 1
            while not atomic_json(path, active):
                if time.monotonic() >= deadline:
                    raise PermissionError('Session state publication blocked: ' + str(path))
                time.sleep(0.005)
        print(phase, extra, flush=True)

    def launch(path, *arguments):
        log = (OUT / (Path(path).stem + '-session.log')).open('a', encoding='utf-8')
        child = subprocess.Popen([sys.executable, str(path), *map(str, arguments)], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, creationflags=134217728)
        log.close()
        children.append(child)
        return child
    source_priority = None
    try:
        STOP.unlink(missing_ok=True)
        bank = json.loads((OUT / 'native-bank-verification.json').read_text())
        rig = json.loads((OUT / 'native-hand-layout-verification.json').read_text())
        registration = json.loads((OUT / 'native-damage-registration-verification.json').read_text())
        retained = retained_seed(reader, loaded, previous)
        assert bank['pid'] == rig['pid'] == registration['pid'] == pid
        assert rig['player'] == int(state['player']), 'Campaign player changed; refresh the hand binding'
        rows = [line.split(',') for line in bank['output'].splitlines() if line.startswith('bank,')]
        assert len(rows) == 2 * len(catalog()) and all((r[-2:] == ['1', '1'] for r in rows))
        assert len(registration['receiver_systems']) == 1
        source_priority = boost_source_priority(source_pid)
        (LAB / 'guest-rendering-required.ini').write_text('BackgroundRendering=0\n')
        preparation = json.loads((OUT / 'preparation.json').read_text())
        damage = json.loads((OUT / 'damage-preparation.json').read_text())
        dlls = []
        for path, digest in ((preparation['dll'], preparation['dll_sha256']), (damage['dll'], damage['sha256']), (preparation['camera_dll'], preparation['camera_sha256'])):
            source = Path(path)
            assert hashlib.sha256(source.read_bytes()).hexdigest() == digest
            name = source.name
            if name.lower() in loaded:
                name = re.sub('[0-9]+\\.dll$', str(time.time_ns()) + '.dll', name)
                assert name != source.name and name.lower() not in loaded
            destination = LAB / name
            shutil.copy2(source, destination)
            assert hashlib.sha256(destination.read_bytes()).hexdigest() == digest
            dlls.append(destination)
        camera = int(state['camera'])
        transform = reader.number(camera + 56)
        camera_profile = {'pid': pid, 'address': hex(camera), 'vtable': hex(reader.number(camera)), 'transform': hex(transform), 'transform_vtable': hex(reader.number(transform))}
        mapper = CameraMapper(reader, camera_profile, camera_relative=True)
        mapper.read()
        settings = json.loads((ROOT / 'outputs/HalfLightNext/Settings.json').read_text())
        projection = struct.pack('<II5QfI', 827344456, pid, nonce, camera, reader.number(camera), transform, reader.number(transform), settings['hand_reference_vertical_fov'], int(settings['hand_projection_compensation']))
        (LAB / f'native-axe-presentation-{pid}.config').write_bytes(projection)
        live = []
        contacts = []
        impact = []
        from combat_profile import combat_profile
        for index, (row, p) in enumerate(zip(rows, catalog() * 2)):
            mesh, xform = (int(row[4], 16), int(row[5], 16))
            handle = reader.number(mesh + 8)
            xh = reader.number(xform + 8)
            assert reader.number(int(row[3], 16) + 74, '<B') >= 5, 'Owned weapon entity did not complete native creation'
            assert reader.number(mesh + 152) == xform and reader.number(xform) == reader.engine + 25278984
            assert reader.number(mesh + 36, '<B') == 0, 'Owned retail bank was not hidden at startup'
            matrix = reader.read(xform + 128, 48)
            assert matrix and all((math.isfinite(v) for v in struct.unpack('<12f', matrix)))
            live.append(struct.pack('<II6Q', 860046920, pid, mesh, xform, handle, xh, int(state['gameph']) + 48, nonce) + matrix)
            contact = struct.pack('<IIQ8f', 827803208, pid, nonce, *(v for point in p['cutting_segment_m'] for v in point), p['blade_radius_m'], p.get('damage_type', 1))
            contacts.append(struct.pack('<QQ', xform, xh) + contact)
            impact.append(combat_profile(p))
        (LAB / f'native-axe-live-{pid}.config').write_bytes(live[0] + struct.pack('<4Q', camera, reader.number(camera), transform, reader.number(transform)))
        (LAB / f'native-weapons-live-{pid}.config').write_bytes(b''.join(live))
        (LAB / f'native-weapon-contact-{pid}.config').write_bytes(contacts[0][16:])
        (LAB / f'native-weapons-damage-{pid}.config').write_bytes(b''.join(contacts))
        (LAB / f'native-combat-profiles-{pid}.config').write_bytes(struct.pack('<IIQ', 826885704, pid, nonce) + b''.join(impact))
        write_grips(pid, nonce, rig)
        atomic_json(LAB / 'host-camera-profile.json', camera_profile)
        atomic_json(LAB / 'native-player-hands.json', {'pid': pid, 'player': hex(rig['player'])})
        atomic_json(LAB / 'host-alignment-graph.json', {'pid': pid, 'game': hex(reader.game), 'graph': {hex(int(state['leveldi'])): {'type': '.?AVLevelDI@@'}}})
        atomic_json(LAB / 'target-damage-graph.json', {'pid': pid, 'spatial': [{'components': [{'type': '.?AVCoDamageReceiver@@', 'handle': hex(registration['receiver_systems'][0] << 34)}]}]})
        stage_helpers(registration)
        for name in (f'native-axe-damage-stop-{pid}.txt', f'native-camera-lock-stop-{pid}.txt', f'native-axe-rebind-{pid}.signal'):
            (LAB / name).unlink(missing_ok=True)
        status('starting', dll=dlls[0].name)

        def renew():
            last_issued = 0
            while not renew_stop.is_set():
                try:
                    issued = K.GetTickCount64() + 8000
                    for path, data in ((lease, struct.pack('<IIQQ', 827541064, pid, nonce, issued)), (LAB / 'guest-live-control.ini', f'Session={session}\nExpiresUnix={int(time.time()) + 10}\nInput=1\nContinuous=1\nFollowPlayer=1\nGuestTargetQueries=0\nSourcePipe=\\\\.\\pipe\\HalfLightGuest-{session}\n'.encode()), (LAB / 'guest-probe-control.ini', f'WorldRendering=0\nExpiresUnix={int(time.time()) + 10}\n'.encode())):
                        temporary = path.with_suffix('.tmp')
                        temporary.write_bytes(data)
                        replace_packet(temporary, path)
                        if path == lease:
                            last_issued = issued
                except PermissionError as exc:
                    if K.GetTickCount64() >= last_issued:
                        heartbeat_error.append(str(exc))
                        return
                except Exception as exc:
                    heartbeat_error.append(str(exc))
                    return
                renew_stop.wait(1)
        renew_thread = threading.Thread(target=renew, daemon=True)
        renew_thread.start()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if lease.exists() and len(lease.read_bytes()) == 24 and (struct.unpack('<IIQQ', lease.read_bytes())[2] == nonce):
                break
            time.sleep(0.02)
        assert not heartbeat_error and struct.unpack('<IIQQ', lease.read_bytes())[2] == nonce
        launch(ROOT / 'work/run_guest_source_pipe.py', session, pid)
        input_log = (OUT / 'input-session.log').open('a')
        input_reader = subprocess.Popen([str(LAB / 'native_input_reader_session.exe'), str(LAB), str(pid), session, 'continuous'], stdout=input_log, stderr=subprocess.STDOUT, creationflags=134217728)
        input_log.close()
        children.append(input_reader)
        subprocess.run([sys.executable, str(ROOT / 'work/reload_guest_probe.py')], cwd=ROOT, check=True, creationflags=134217728)
        feed = PoseFeed(active['source_path'], LAB / f'native-axe-live-{pid}.packet', pid, nonce, (0, 0, 0), continuous=True, pose_mapper=mapper, source_mailbox=session)
        feed.start()
        deadline = time.monotonic() + 60
        while not feed.ready.wait(0.1) and time.monotonic() < deadline and (not STOP.exists()):
            assert reader.alive() and (not heartbeat_error), 'Campaign or source lease ended'
        assert feed.ready.is_set() and feed.error is None, 'No fresh Half Sword weapon pose; native callbacks were not loaded'
        load_native(reader, loaded, dlls[0], slot, original)
        deadline = time.monotonic() + 3
        while reader.number(slot) == original and time.monotonic() < deadline:
            time.sleep(0.02)
        update = reader.number(slot)
        assert update != original, 'Movement startup refused'
        xform, xh = struct.unpack_from('<QQ', contacts[0])
        seed = retained['seed'] if retained else 0
        if retained:
            (LAB / f'native-axe-seed-transfer-{pid}.config').write_bytes(struct.pack('<II6Q', 827606600, pid, nonce, retained['module'], seed, rig['entity'], rig['entity_handle'], K.GetTickCount64() + 30000) + retained['hash'])
        config = struct.pack('<II15Q', 826558024, pid, registration['hit_slot'], registration['hit_original'], 0, 0, 0, nonce, slot, update, int(state['gameph']) + 48, xform, xh, 0, 0, 0, seed) + bytes.fromhex(preparation['dll_sha256'])
        (LAB / f'native-axe-damage-{pid}.config').write_bytes(config)
        load_native(reader, loaded, dlls[1], registration['hit_slot'], registration['hit_original'])
        deadline = time.monotonic() + 3
        damage_log = LAB / f'native-axe-damage-{pid}.log'
        content = ''
        while time.monotonic() < deadline and reader.alive():
            if damage_log.exists():
                content = damage_log.read_text()
                if 'hand_enabled,1\n' in content:
                    break
            time.sleep(0.05)
        assert 'hand_enabled,1\n' in content and 'left_hand_enabled,1\n' in content, 'Retail damage startup refused: ' + content
        prefixes = []
        user = C.WinDLL('user32')
        K.GetModuleHandleW.argtypes = [W.LPCWSTR]
        K.GetModuleHandleW.restype = W.HMODULE
        for name in ('GetRawInputData', 'GetRawInputBuffer'):
            local = C.cast(getattr(user, name), C.c_void_p).value
            local_base = K.GetModuleHandleW('user32.dll')
            remote = loaded['user32.dll']['base'] + local - local_base
            prefix = reader.read(remote, 32)
            assert prefix
            prefixes.append(prefix)
        (LAB / f'native-camera-lock-{pid}.config').write_bytes(struct.pack('<IIQ', 827082312, pid, nonce) + b''.join(prefixes))
        load_native(reader, loaded, dlls[2], registration['hit_slot'], reader.number(registration['hit_slot']))
        deadline = time.monotonic() + 3
        camera_log = LAB / f'native-camera-lock-{pid}.log'
        camera_status = ''
        while reader.alive() and time.monotonic() < deadline:
            if camera_log.exists():
                camera_status = camera_log.read_text()
                if 'status,active\n' in camera_status:
                    break
            time.sleep(0.05)
        assert 'status,active\n' in camera_status, 'Retail input-filter startup refused: ' + camera_status
        status('running', damage_dll=dlls[1].name, camera_dll=dlls[2].name, source_priority=source_priority[2], source_original_priority=source_priority[1])
        launch(OUT / 'publish_discovered_target.py')
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and (not (LAB / f'guest-camera-alignment-{session}.txt').exists()):
            time.sleep(0.1)
        assert (LAB / f'guest-camera-alignment-{session}.txt').exists(), 'Source camera telemetry missing'
        launch(OUT / 'publish_host_camera_follow.py')
        helper_restarts = {}
        panel_check = 0
        while not STOP.exists() and (not source_stop.exists()) and reader.alive():
            if time.monotonic() >= panel_check:
                from campaign_control import ensure_panel
                try:
                    ensure_panel()
                except OSError as exc:
                    print('F7 worker restart failed:', str(exc), flush=True)
                panel_check = time.monotonic() + 5
            if source_pid not in processes():
                break
            assert not heartbeat_error and feed.error is None, 'Live pose or lease failed: ' + json.dumps({'heartbeat': heartbeat_error, 'pose': feed.error})
            assert not (LAB / f'native-axe-rebind-{pid}.signal').exists(), 'Campaign objects changed; callbacks are restoring'
            assert campaign_binding_valid(reader, state, rig), 'Campaign player or hand rig changed; callbacks are restoring'
            for child in list(children):
                if child.poll() is None:
                    continue
                command = child.args
                recoverable = Path(command[1]).name in ('run_weapon_menu.py', 'publish_host_camera_follow.py', 'publish_discovered_target.py') if len(command) > 1 else False
                attempts = helper_restarts.setdefault(tuple(command), [])
                attempts[:] = [stamp for stamp in attempts if time.monotonic() - stamp < 60]
                assert recoverable and len(attempts) < 3, 'Session helper repeatedly exited: ' + json.dumps({'command': command, 'exit_code': child.returncode})
                attempts.append(time.monotonic())
                children.remove(child)
                status('running', restarted_helper=Path(command[1]).name)
                launch(command[1], *command[2:])
            mapper.read()
            time.sleep(0.25)
        reason = 'controller stop' if STOP.exists() else 'source stop' if source_stop.exists() else 'game liveness check failed'
        detail = source_stop.read_text()[:200] if source_stop.exists() else ''
        status('stopping', stop_reason=reason, stop_detail=detail)
    except BaseException as exc:
        status('needs_attention', error=str(exc))
        raise
    finally:
        cleanup_errors = []
        for name in (f'native-axe-damage-stop-{pid}.txt', f'native-camera-lock-stop-{pid}.txt'):
            try:
                (LAB / name).write_text('retail controller stop\n')
            except OSError as exc:
                cleanup_errors.append(str(exc))
        deadline = time.monotonic() + 3
        while reader.alive() and time.monotonic() < deadline:
            if reader.number(slot) in (original, locals().get('update', original)):
                break
            time.sleep(0.05)
        renew_stop.set()
        if renew_thread:
            renew_thread.join(2)
        try:
            control = LAB / 'guest-live-control.ini'
            temporary = control.with_suffix('.tmp')
            temporary.write_text(f'Session={session}\nExpiresUnix=0\nInput=0\nContinuous=1\nFollowPlayer=1\n')
            replace_packet(temporary, control)
        except OSError as exc:
            cleanup_errors.append(str(exc))
        try:
            temporary = lease.with_suffix('.tmp')
            temporary.write_bytes(struct.pack('<IIQQ', 827541064, pid, nonce, 0))
            replace_packet(temporary, lease)
        except OSError as exc:
            cleanup_errors.append(str(exc))
        try:
            source_stop.write_text('retail session ended\n')
        except OSError as exc:
            cleanup_errors.append(str(exc))
        if feed:
            feed.close()
        deadline = time.monotonic() + 10
        while reader.alive() and time.monotonic() < deadline:
            camera_restored = True
            if 'camera_log' in locals():
                try:
                    camera_restored = 'hooks_restored,1\n' in camera_log.read_text()
                except OSError:
                    camera_restored = False
            if camera_restored and reader.number(slot) == original and (registration is None or reader.number(registration['hit_slot']) == registration['hit_original']):
                break
            time.sleep(0.05)
        for child in children:
            try:
                child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                child.terminate()
                child.wait(timeout=2)
        rendering = LAB / f'guest-background-rendering-{session}.txt'
        deadline = time.monotonic() + 12
        while rendering.exists() and reader.alive() and (source_pid in processes()) and (time.monotonic() < deadline):
            try:
                values = dict((line.split('=', 1) for line in rendering.read_text().splitlines() if '=' in line))
                if values.get('world_rendering') == '1' and values.get('mesh_settings_restored') == '1':
                    break
            except OSError:
                pass
            time.sleep(0.1)
        restored = not reader.alive() or (reader.number(slot) == original and (registration is None or reader.number(registration['hit_slot']) == registration['hit_original']))
        weapons_restored = True
        if reader.alive():
            for packet in locals().get('live', []):
                _, _, mesh, xform, handle, xh, _, _ = struct.unpack_from('<II6Q', packet)
                if reader.number(mesh + 8) != handle or reader.number(xform + 8) != xh:
                    continue
                matrix = reader.read(xform + 128, 48)
                if not matrix or reader.number(mesh + 36, '<B') != 0 or any((abs(a - b) > 0.0001 for a, b in zip(struct.unpack('<12f', matrix), struct.unpack('<12f', packet[56:])))):
                    weapons_restored = False
        priority_restored = True
        if source_priority:
            try:
                restore_source_priority(source_priority)
            except Exception as exc:
                priority_restored = False
                cleanup_errors.append(str(exc))
        try:
            status('stopped', callback_restored=restored, weapons_restored=weapons_restored, source_priority_restored=priority_restored, cleanup_errors=cleanup_errors)
        finally:
            reader.close()
    return active

def recovery_allowed(active, inventory):
    if active.get('stop_reason') == 'controller stop' or 'deliberate Ctrl+Shift+F8' in active.get('stop_detail', ''):
        return False
    if active.get('target_pid') not in inventory:
        return True
    if not active.get('callback_restored'):
        raise RuntimeError('Native callback restoration is unverified; automatic attachment refused')
    if active.get('weapons_restored') is False:
        raise RuntimeError('Surviving campaign weapon restoration is unverified')
    for name, keys in (('native-axe-damage', ('hit_callback_restored', 'movement_callback_restored')), ('native-camera-lock', ('hooks_restored',))):
        path = LAB / f"{name}-{active['target_pid']}.log"
        if path.exists():
            values = dict((line.split(',', 1) for line in path.read_text().splitlines() if ',' in line))
            if name == 'native-axe-damage' and values == {'status': 'retained_seed_refused'}:
                continue
            if name == 'native-axe-damage' and values == {'status': 'offhand_mapping_refused'} and not active.get('damage_dll'):
                # Mapping refusal precedes hook installation; both live slots were checked above.
                continue
            if any((values.get(key) != '1' for key in keys)):
                raise RuntimeError('Native ' + name + ' restoration is unverified')
    path = LAB / f"guest-background-rendering-{active['session']}.txt"
    if path.exists() and (not active.get('source_pid') or active['source_pid'] in inventory):
        values = dict((line.split('=', 1) for line in path.read_text().splitlines() if '=' in line))
        if values.get('world_rendering') != '1' or values.get('mesh_settings_restored') != '1':
            raise RuntimeError('Half Sword rendering restoration is pending')
    return True

def maintain():
    K.CreateMutexW.argtypes = [C.c_void_p, W.BOOL, W.LPCWSTR]
    K.CreateMutexW.restype = W.HANDLE
    mutex = K.CreateMutexW(None, False, 'Local\\HalfLightRetailBridge-20261010')
    assert mutex and C.get_last_error() != 183, 'Campaign bridge supervisor is already running'
    STOP.unlink(missing_ok=True)
    failures = []
    generation = 0
    supervisor_error = None
    atomic_json(OUT / 'supervisor.json', {'pid': os.getpid(), 'state': 'starting', 'generation': generation})
    try:
        while not STOP.exists():
            inventory = processes()
            if 'dyinglightgame_x64_rwdi.exe' not in inventory.values() or not any(('halfsword' in name and 'shipping' in name for name in inventory.values())):
                atomic_json(OUT / 'supervisor.json', {'pid': os.getpid(), 'state': 'waiting_for_games', 'generation': generation})
                time.sleep(1)
                continue
            from retail_bridge import Reader, find_game_pid
            try:
                probe = Reader(find_game_pid(), ROOT / 'outputs/HalfLightNext')
                try:
                    snapshot = probe.snapshot('campaign-recovery')
                    ready = probe.profile_ok and snapshot.get('camera_valid') == '1' and int(snapshot.get('player', '0')) and int(snapshot.get('level', '0'))
                finally:
                    probe.close()
            except (OSError, ValueError):
                ready = False
            if not ready:
                atomic_json(OUT / 'supervisor.json', {'pid': os.getpid(), 'state': 'waiting_for_campaign', 'generation': generation})
                time.sleep(1)
                continue
            started = time.monotonic()
            atomic_json(OUT / 'supervisor.json', {'pid': os.getpid(), 'state': 'preparing_campaign', 'generation': generation})
            try:
                previous = read_json(STATE, {})
                if previous and previous.get('state') == 'stopped':
                    if not recovery_allowed(previous, inventory) and generation:
                        break
                reader, loaded, snapshot = attach_reader()
                try:
                    bank = read_json(OUT / 'native-bank-verification.json', {})
                    records = [line.split(',') for line in bank.get('output', '').splitlines() if line.startswith('bank,')]
                    bank_valid = bank.get('pid') == reader.pid and len(records) == 2 * len(catalog()) and all((reader.number(int(row[3], 16) + 8) == int(row[2], 16) for row in records))
                    registration = read_json(OUT / 'native-damage-registration-verification.json', {})
                    changed_process = registration.get('pid') != reader.pid
                finally:
                    reader.close()
                if not bank_valid:
                    subprocess.run([sys.executable, str(ROOT / 'work/retail_bridge.py'), 'verify-bank'], cwd=ROOT, check=True, timeout=60, creationflags=134217728)
                import inspect_retail_hands
                inspect_retail_hands.run()
                if changed_process:
                    import inspect_retail_damage
                    inspect_retail_damage.run()
                generation += 1
                atomic_json(OUT / 'supervisor.json', {'pid': os.getpid(), 'state': 'playing', 'generation': generation})
                active = run()
                if not recovery_allowed(active, processes()):
                    break
            except Exception as exc:
                active = read_json(STATE, {})
                if active.get('controller_pid') == os.getpid() and active.get('state') == 'stopped':
                    recovery_allowed(active, processes())
                failures = [stamp for stamp in failures if time.monotonic() - stamp < 600]
                if time.monotonic() - started >= 60:
                    failures = []
                failures.append(time.monotonic())
                atomic_json(OUT / 'supervisor.json', {'pid': os.getpid(), 'state': 'recovering', 'generation': generation, 'error': str(exc), 'recent_failures': len(failures)})
                if len(failures) >= 3:
                    raise RuntimeError('Repeated recovery failure; native attachments stopped: ' + str(exc)) from exc
                print('recovering', str(exc), flush=True)
            time.sleep(2)
    except Exception as exc:
        supervisor_error = str(exc)
        raise
    finally:
        atomic_json(OUT / 'supervisor.json', {'pid': os.getpid(), 'state': 'needs_attention' if supervisor_error else 'stopped', 'generation': generation, 'error': supervisor_error})
        K.CloseHandle(mutex)
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--stop', action='store_true')
    args = parser.parse_args()
    if args.stop:
        STOP.write_text('human stop\n')
    else:
        from campaign_control import ensure_panel
        ensure_panel()
        maintain()
