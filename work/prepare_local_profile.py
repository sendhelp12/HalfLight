"""Generate private binary metadata from the owner's hash-verified game files."""
import json
from pathlib import Path
from setup import ROOT, validate
from install_files import save
from pe_tools import PE, inspect


def prepare(half_sword, dying_light):
    paths=validate(half_sword,dying_light)
    expected=json.loads((ROOT/'profiles/retail.json').read_text())
    update=json.loads((ROOT/'profiles/update.json').read_text())
    modules={}
    for name,identity in expected['modules'].items():
        pe=PE(paths[name])
        if pe.size!=identity['image_size'] or pe.timestamp!=identity['timestamp']:
            raise ValueError('Owned module metadata differs: '+name)
        modules[name]={**identity,'path':str(paths[name].resolve()),'bindings':{}}
        if name=='engine_x64_rwdi.dll':
            creator=pe.exports()['?Create@CoMeshRender@@SAPEAV1@UWorldIndex@cbs@@@Z']
            modules[name]['asset_functions']={'CoMeshRender::Create(struct cbs::WorldIndex)':inspect(pe,creator,{})}
        if name=='gamedll_ph_x64_rwdi.dll':
            candidates=pe.vtables('CoDamageReceiver')
            if candidates!=[0x2469170]:
                raise ValueError('Native damage receiver table differs')
            modules[name]['bindings']['0x25695f8']={'retail_rva':candidates[0]}
    save(ROOT/'work/lab/retail-bridge-profile.json',{'modules':modules,'world_geometry_collision':False})
    save(ROOT/'outputs/HalfLightNext/Native-Update-Profiles.json',update)
    print('Private runtime metadata generated from the owned binaries; no process attachment.')


if __name__=='__main__':
    config=json.loads((ROOT/'.local/install.json').read_text())
    prepare(Path(config['half_sword']),Path(config['dying_light']))
