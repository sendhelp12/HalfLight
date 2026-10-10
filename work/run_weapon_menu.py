"""Session-owned native Windows weapon popup; physical F7 opens it over DL2."""
import json, subprocess
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
active = json.loads((ROOT / 'work/lab/active-axe-session.json').read_text())
assert active['state'] in ('starting', 'running')
result = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(ROOT / 'outputs/HalfLightNext/Show-Weapon-Menu.ps1'), '-TargetPid', str(active['target_pid']), '-Session', active['session']], capture_output=True, text=True, creationflags=134217728)
print(result.stdout, flush=True)
print(result.stderr, flush=True)
result.check_returncode()
