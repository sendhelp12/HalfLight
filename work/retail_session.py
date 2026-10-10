"""Retail bootstrap for the two existing camera/target helper implementations."""
import json
from retail_bridge import ROOT, OUT, Reader, find_game_pid
root = ROOT
active = json.loads((ROOT / 'work/lab/active-axe-session.json').read_text())
pid = find_game_pid()
assert active.get('host') == 'retail' and active['target_pid'] == pid
profile = json.loads((ROOT / 'work/lab/retail-bridge-profile.json').read_text())['modules']['engine_x64_rwdi.dll']
creator = next((row for name, row in profile['asset_functions'].items() if 'CoMeshRender::Create(struct cbs::WorldIndex)' in name))
engine_profile = {'exports': {'CoMeshRender::Create(struct cbs::WorldIndex)': creator}}

def EditorReader(target_pid):
    assert target_pid == pid
    reader = Reader(pid, ROOT / 'outputs/HalfLightNext')
    if not reader.profile_ok:
        reader.close()
        raise ValueError('Retail build changed')
    return reader
