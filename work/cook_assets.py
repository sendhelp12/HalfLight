"""Cook locally exported meshes with the owned editor, then retain private outputs."""
import json
import re
import shutil
import subprocess
import uuid
from pathlib import Path
from setup import ROOT
from install_files import digest, save


def prepare(profiles,root=ROOT):
    root=Path(root);config=json.loads((root/'.local/install.json').read_text())
    devtools=Path(config['dying_light'])/'DevTools';state_path=root/'.local/cook-project.json'
    if state_path.exists():state=json.loads(state_path.read_text())
    else:
        suffix=uuid.uuid4().hex[:12]
        state={'directory':'HalfLightSetup'+suffix,'name':'HalfLight Setup '+suffix}
        if (devtools/'projects/local'/state['directory']).exists():raise ValueError('Preserving existing project')
        save(state_path,state)
    assert re.fullmatch('HalfLightSetup(?:[a-f0-9]{12})?',state['directory'])
    files=[]
    for profile in profiles:
        stem=Path(profile['native_mesh']).stem
        assert re.fullmatch('halflight_[a-z0-9_]+',stem)
        geometry=(root/profile['geometry_path']).resolve()
        assert geometry.is_relative_to((root/'work/owned-assets').resolve())
        for suffix in ('','_offhand'):
            for extension in ('.msh','.skn'):
                source=geometry.parent/'native'/(stem+extension)
                files.append({'source':str(source),'name':stem+suffix+extension,'sha256':digest(source)})
    if not files or len({item['name'] for item in files})!=len(files):raise ValueError('Invalid cooking batch')
    manifest={'devtools':str(devtools.resolve()),**state,'files':files}
    save(root/'.local/cooking-manifest.json',manifest)
    return manifest


def verify(manifest,root=ROOT):
    root=Path(root);project=Path(manifest['devtools'])/'projects/local'/manifest['directory']
    source=project/'source/data/Meshes';compiled=project/'work/data_platform/pc/assets/meshes'
    output=root/'.local/assets/meshes';output.mkdir(parents=True,exist_ok=True);records=[]
    for item in manifest['files']:
        if not item['name'].endswith('.msh'):continue
        name=item['name'];mesh=compiled/(name+'_obj');dependency=compiled/(name+'_obj_dep')
        assert digest(source/name)==item['sha256'],'Cooked source no longer matches export'
        assert mesh.is_file() and mesh.stat().st_size>0 and dependency.is_file(),'Missing cooked output'
        assert mesh.stat().st_mtime_ns>=max((source/name).stat().st_mtime_ns,
                                           (source/(Path(name).stem+'.skn')).stat().st_mtime_ns),'Stale cooked output'
        text=dependency.read_text(encoding='utf-8-sig')
        assert 'Source("meshes/'+name+'",' in text,'Cooked mesh has wrong source identity'
        skin=(source/(Path(name).stem+'.skn')).read_text()
        for material in re.findall(r'Replace\("([^"/]+)\.mat"',skin):
            assert material+'&0004.mat' in text,'Missing material dependency: '+material
        for file in (mesh,dependency):
            destination=output/file.name
            temporary=destination.with_suffix('.'+uuid.uuid4().hex+'.tmp')
            try:
                shutil.copyfile(file,temporary)
                assert digest(temporary)==digest(file)
                temporary.replace(destination)
            finally:temporary.unlink(missing_ok=True)
            records.append({'name':file.name,'sha256':digest(destination),'bytes':destination.stat().st_size})
    save(root/'.local/cooked-assets.json',{'banks':len(records)//2,'files':records,'scope':'local official compilation'})
    return records


def cook(profiles):
    manifest=prepare(profiles)
    subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',
                    str(ROOT/'work/Cook-Assets.ps1'),'-Manifest',str(ROOT/'.local/cooking-manifest.json')],check=True)
    records=verify(manifest)
    print('Verified',len(records)//2,'fresh cooked banks and material dependencies; outputs remain private.')
    return records


if __name__=='__main__':
    cook(json.loads((ROOT/'work/owned-assets/catalog/profiles.json').read_text()))
