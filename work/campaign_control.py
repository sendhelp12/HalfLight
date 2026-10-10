"""Persistent F7 panel and bounded commands for the owned campaign controller."""
import argparse, ctypes, json, os, subprocess, sys, threading, time
from pathlib import Path
from halflight_runtime import atomic_json, processes, read_json, read_lease_deadline
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'work/retail'
LAB = ROOT / 'work/lab'
REQUEST = OUT / 'panel-request.json'
STATUS = OUT / 'panel-status.json'

def fields(path, separator='=', age=3):
    try:
        if time.time() - path.stat().st_mtime > age:
            return {}
        raw = path.read_text()
        assert len(raw) <= 32768
        return dict((line.split(separator, 1) for line in raw.splitlines() if separator in line))
    except (OSError, ValueError, AssertionError):
        return {}

def health():
    inventory = processes()
    supervisor = read_json(OUT / 'supervisor.json', {})
    active = read_json(OUT / 'active-session.json', {})
    pid = active.get('target_pid', 0)
    session = active.get('session', '')
    controller = supervisor.get('pid') in inventory and inventory.get(supervisor.get('pid')) in ('python.exe', 'pythonw.exe')
    connected = controller and active.get('state') == 'running' and (active.get('controller_pid') == supervisor.get('pid')) and (inventory.get(pid) == 'dyinglightgame_x64_rwdi.exe')
    kernel = ctypes.WinDLL('kernel32')
    kernel.GetTickCount64.restype = ctypes.c_uint64
    try:
        connected = connected and bool(read_lease_deadline(LAB / f'native-axe-session-{pid}.lease', pid, int(session, 16), kernel.GetTickCount64()))
    except ValueError:
        connected = False
    render = fields(LAB / f'guest-background-rendering-{session}.txt', age=float('inf'))
    performance = fields(LAB / f'guest-performance-{session}.txt')
    damage = fields(LAB / f'native-axe-damage-{pid}.log', ',')
    camera = fields(LAB / f'native-camera-lock-{pid}.log', ',')
    menu = fields(LAB / f'weapon-menu-status-{session}.txt', age=float('inf'))
    alignment = fields(LAB / f'guest-camera-alignment-{session}.txt')
    cleanup = fields(LAB / f'weapon-cleanup-{session}.txt', age=float('inf'))
    source = bool(performance) and performance.get('session') == session
    rows = [('DL2 campaign', 'Open' if 'dyinglightgame_x64_rwdi.exe' in inventory.values() else 'Closed'), ('Half Sword', 'Open' if any(('halfsword' in n and 'shipping' in n for n in inventory.values())) else 'Closed'), ('Controller', supervisor.get('state', 'Stopped') if controller else 'Stopped'), ('Source poses', 'Fresh' if connected and source else 'Waiting'), ('World rendering', 'Off' if connected and source and (render.get('world_rendering') == '0') else 'On / waiting'), ('Camera sync', 'Fresh' if connected and alignment.get('Session') == session else 'Waiting'), ('Weapon and hand adapter', 'Active' if connected and damage.get('hand_enabled') == '1' and (damage.get('left_hand_enabled') == '1') else 'Waiting'), ('Input / vanilla attack filter', 'Active' if connected and camera.get('status') == 'active' else 'Waiting'), ('F8 control', 'On' if connected and damage.get('input_armed') == '1' else 'Off'), ('Weapon equipping', 'Ready' if connected and source and (menu.get('Session') == session) and (menu.get('state') in ('ready', 'applied')) else menu.get('state', 'Waiting') if connected else 'Waiting'), ('Native damage', 'Ready' if connected and int(damage.get('seed_copies', '0')) > 0 else 'Needs one normal melee hit with F8 off' if connected else 'Waiting'), ('Dropped weapon cleanup', 'Active; removed ' + cleanup.get('removed_total', '0') if connected and source and (cleanup.get('Session') == session) and (cleanup.get('error') == 'none') else 'Waiting / error'), ('Source performance', f"{float(performance.get('engine_frame_hz', 0)):.1f} FPS; worst frame {float(performance.get('max_world_delta_ms', 0)):.1f} ms" if source else 'Waiting')]
    errors = [supervisor.get('error'), active.get('error') if active.get('state') == 'needs_attention' else None, render.get('error') if connected and render.get('error') != 'none' else None, menu.get('error') if connected and menu.get('error') != 'none' else None]
    if connected and cleanup.get('error') not in (None, 'none'):
        errors.append(cleanup['error'])
    return {'updated_at': time.time(), 'controller': controller, 'connected': connected, 'target_pid': pid, 'session': session, 'rows': [{'part': k, 'state': v} for k, v in rows], 'errors': [e for e in errors if e], 'features': 'Lab pose smoothing, CUT / BLUNT profiles, dual hands, Alt, X, host-only sticking. Scenery collision excluded.'}

def control(action):
    assert action in ('start', 'stop', 'restart')
    if action in ('stop', 'restart'):
        active = read_json(OUT / 'active-session.json', {})
        supervisor = read_json(OUT / 'supervisor.json', {})
        pid = supervisor.get('pid')
        (OUT / 'stop-session.txt').write_text('F7 panel stop\n')
        deadline = time.monotonic() + 35
        while pid in processes() and time.monotonic() < deadline:
            time.sleep(0.2)
        if pid in processes():
            raise RuntimeError('Controller is still restoring; restart refused')
        stopped = read_json(OUT / 'active-session.json', {})
        if active.get('target_pid') in processes() and active.get('state') in ('starting', 'running', 'stopping'):
            assert stopped.get('state') == 'stopped' and stopped.get('callback_restored') and stopped.get('weapons_restored'), 'Native restoration unverified; restart refused'
    if action in ('start', 'restart'):
        assert read_json(ROOT/'.local/install.json',{}).get('ready') is True, 'Finish HalfLight Setup before starting the release bridge'
        supervisor = read_json(OUT / 'supervisor.json', {})
        if supervisor.get('pid') in processes():
            return 'Controller already running'
        with (OUT / 'controller-output.log').open('w') as stdout, (OUT / 'controller-error.log').open('w') as stderr:
            subprocess.Popen([sys.executable, str(ROOT / 'work/run_retail_bridge.py')], cwd=ROOT, stdout=stdout, stderr=stderr, creationflags=134217728)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            time.sleep(0.1)
            if health()['controller']:
                return 'Started; waiting for loaded games / match'
        raise RuntimeError('Controller did not start; see status error')
    return 'Stopped; native input and weapon poses restored'

def panel():
    with (OUT / 'panel-output.log').open('a') as stdout:
        child = subprocess.Popen(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(ROOT / 'outputs/HalfLightNext/Show-Weapon-Menu.ps1'), '-Retail'], cwd=ROOT, stdout=stdout, stderr=subprocess.STDOUT, creationflags=134217728)
        last = time.time_ns()
        worker = None
        command = {'sequence': 0, 'state': 'idle', 'message': ''}

        def execute(action, sequence):
            command.update(sequence=sequence, state='working', message=action.title() + ' in progress...')
            try:
                command.update(state='done', message=control(action))
            except Exception as exc:
                command.update(state='error', message=str(exc))
        while child.poll() is None:
            request = read_json(REQUEST, {})
            seq = request.get('sequence', 0)
            expiry = request.get('expires_at', 0)
            action = request.get('action')
            if isinstance(seq, int) and seq > last and isinstance(expiry, (int, float)) and (time.time() < expiry <= time.time() + 40) and (action in ('start', 'stop', 'restart')) and (worker is None or not worker.is_alive()):
                last = seq
                worker = threading.Thread(target=execute, args=(action, seq))
                worker.start()
            try:
                value = health()
            except Exception as exc:
                value = {'updated_at': time.time(), 'connected': False, 'rows': [], 'errors': [str(exc)]}
            value['command'] = dict(command)
            value['panel_pid'] = os.getpid()
            value['panel_ui_pid'] = child.pid
            atomic_json(STATUS, value)
            time.sleep(0.5)
        if worker:
            worker.join(40)

def ensure_panel():
    status = read_json(STATUS, {})
    inventory = processes()
    if 0 <= time.time() - status.get('updated_at', 0) < 3 and status.get('panel_pid') in inventory and (inventory.get(status.get('panel_ui_pid')) == 'powershell.exe'):
        return
    with (OUT/'panel-worker.log').open('a',encoding='utf-8') as log:
        subprocess.Popen([sys.executable, str(Path(__file__).resolve()), 'panel'], cwd=ROOT,
                         stdout=log,stderr=subprocess.STDOUT,creationflags=134217728)
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('start', 'stop', 'restart', 'status', 'panel'))
    action = parser.parse_args().action
    if action == 'panel':
        panel()
    elif action == 'status':
        print(json.dumps(health(), indent=2))
    else:
        if action != 'stop':
            ensure_panel()
        print(control(action))
