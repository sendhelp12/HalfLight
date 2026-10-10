"""Install only locally cooked content into an isolated game asset directory."""
import json
import uuid
from pathlib import Path
from setup import ROOT, validate
from install_files import digest, install, save, uninstall


def main():
    state=json.loads((ROOT/'.local/install.json').read_text())
    validate(state['half_sword'],state['dying_light'])
    cooked=json.loads((ROOT/'.local/cooked-assets.json').read_text())
    assert cooked['banks']==2*len(json.loads((ROOT/'.local/catalog.json').read_text())['weapons'])
    journal=ROOT/'.local/assets-files.json'
    if journal.exists() and json.loads(journal.read_text())['phase']!='removed':
        prior=json.loads(journal.read_text())
        if all(digest(ROOT/'.local/assets/meshes'/Path(p['relative']).name)==p['sha256']
               and digest(Path(prior['roots'][p['root']])/p['relative'])==p['sha256'] for p in prior['files']):
            directory=Path(prior['files'][0]['relative']).parts[0]
            assert directory.startswith('halflight-') and all(Path(p['relative']).parts[0]==directory for p in prior['files'])
            state['asset_root']=str((Path(prior['roots']['dying_light'])/directory).resolve())
            save(ROOT/'.local/install.json',state)
            print('Verified existing local asset installation');return
        if uninstall(journal):raise ValueError('Preserving user-modified installed assets; setup stopped')
    root=Path(state['dying_light'])/'ph/work/data_platform/pc/assets'
    relative='halflight-'+uuid.uuid4().hex
    files=[]
    for item in cooked['files']:
        name=item['name']
        assert Path(name).name==name and name.startswith('halflight_') and name.endswith(('.msh_obj','.msh_obj_dep'))
        source=ROOT/'.local/assets/meshes'/name
        assert digest(source)==item['sha256']
        files.append({'source':str(source),'root':'dying_light','relative':relative+'/meshes/'+name,
                      'sha256':item['sha256']})
    install({'dying_light':root},files,journal)
    state['asset_root']=str((root/relative).resolve());save(ROOT/'.local/install.json',state)
    print('Locally cooked assets installed in their own game directory with an uninstall journal.')


if __name__=='__main__':main()
