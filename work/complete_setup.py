"""One-start installation: locally build, capture, extract, cook and calibrate."""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from setup import ROOT
from install_files import save

STATE=ROOT/'.local/install.json'


def phase(name,message):
    state=json.loads(STATE.read_text());state.update(phase=name,note=message,ready=False)
    save(STATE,state);print(message,flush=True)


def run(name,*args,env=None):
    env=dict(env or os.environ,PYTHONPATH=str(ROOT/'.local/tools/capstone'))
    subprocess.run([sys.executable,str(ROOT/'work'/name),*map(str,args)],cwd=ROOT,env=env,check=True)


def prepare():
    phase('preparing','Downloading verified tools and building the local adapters.')
    run('get_tools.py')
    sys.path.insert(0,str(ROOT/'.local/tools/capstone'))
    from prepare_local_profile import prepare as metadata
    config=json.loads(STATE.read_text());metadata(config['half_sword'],config['dying_light'])
    run('build_native.py');run('build_extractor.py');run('install_loader.py')
    phase('waiting-for-games','Open Half Sword into a match and DL2 into a single-player save once. Leave F8 off. Setup will continue automatically.')


def wait_games():
    from retail_bridge import attach_reader
    config=json.loads(STATE.read_text());session=config['capture_session']
    deadline=time.monotonic()+1800
    runtime=ROOT/'outputs/HalfLightNext/runtime'
    while time.monotonic()<deadline:
        result=runtime/'setup-mapping.result'
        if result.exists() and 'RunId='+session in result.read_text():
            if 'State=error' in result.read_text():raise RuntimeError('Half Sword mapping generation failed; see its loader log')
            try:
                reader,_,_=attach_reader();reader.close()
                telemetry=list(runtime.glob('half-sword-state-*.txt'))
                if any(time.time()-p.stat().st_mtime<3 and 'run_id='+session in p.read_text()
                       and 'pawn=Willie_BP_C ' in p.read_text() for p in telemetry):return
            except (OSError,ValueError,AssertionError):pass
        time.sleep(1)
    raise TimeoutError('Waiting for a loaded Half Sword match and DL2 campaign timed out. Resume setup after loading them.')


def definitions():
    config=json.loads(STATE.read_text());binary=Path(config['half_sword'])/'HalfSwordUE5/Binaries/Win64'
    mappings=list(binary.rglob('*.usmap'))
    session_file=ROOT/'outputs/HalfLightNext/runtime/session.ini'
    mappings=[p for p in mappings if p.stat().st_mtime>=session_file.stat().st_mtime]
    if not mappings:raise RuntimeError('Fresh reflection mapping missing; old mappings are not reused')
    mapping=max(mappings,key=lambda p:p.stat().st_mtime)
    private_mapping=ROOT/'.local/owned.usmap';shutil.copyfile(mapping,private_mapping)
    run('local_archive_candidates.py')
    env=dict(os.environ,HALFLIGHT_AES_CANDIDATES=str(ROOT/'work/lab/owned-archive-key-candidates.json'))
    command=[str(ROOT/'.local/tools/dotnet/dotnet.exe'),
             str(ROOT/'.local/extractor-build/bin/WeaponExtractor/release/WeaponExtractor.dll'),
             str(Path(config['half_sword'])/'HalfSwordUE5/Content/Paks'),str(private_mapping)]
    listing=ROOT/'.local/owned-weapon-assets.txt'
    subprocess.run([*command,'--weapon-assets',str(listing)],env=env,check=True)
    definitions=ROOT/'work/owned-assets/catalog/definitions';definitions.mkdir(parents=True,exist_ok=True)
    from prepare_recipes import FORGED
    paths=listing.read_text().splitlines()
    wanted=['ModularWeaponBP',*('BP_GameWeapon_Customizable_'+name for name in FORGED.values())]
    names={}
    for name in wanted:
        matches=[p for p in paths if Path(p).stem==name]
        if len(matches)!=1:raise ValueError('Missing or ambiguous forge definition: '+name)
        names[name]=matches[0]
    batch=ROOT/'.local/definition-requests.json'
    pending=names
    seen=set()
    while pending:
        if len(seen)+len(pending)>128:raise ValueError('Excessive forge inheritance')
        save(batch,[{'source':path,'output':str(definitions/(name+'.json'))} for name,path in pending.items()])
        subprocess.run([*command,'--batch',str(batch)],env=env,check=True)
        seen.update(pending);next_batch={}
        for name in pending:
            rows=json.loads((definitions/(name+'.json')).read_text())
            parent=next(row for row in rows if row['Type']=='BlueprintGeneratedClass').get('SuperStruct',{}).get('ObjectPath','')
            if parent.startswith('Halfsword'):
                path=parent.rsplit('.',1)[0]+'.uasset';parent_name=Path(path).stem
                if parent_name not in seen:next_batch[parent_name]=path
        pending=next_batch
    run('prepare_recipes.py')
    return command,env


def extract():
    command,env=definitions()
    (ROOT/'outputs/HalfLightNext/runtime/actor-capture.ini').write_text(
        'Enabled=1\nEpoch='+str(time.time_ns())+'\n',encoding='ascii')
    run('capture_catalog.py');run('prepare_catalog_captures.py')
    subprocess.run([*command,'--batch',str(ROOT/'work/lab/catalog-mesh-requests.json')],env=env,check=True)


def finish():
    phase('waiting-for-games','Load a Half Sword match and a DL2 single-player save once; keep F8 off. Waiting automatically.')
    wait_games()
    phase('extracting','Capturing weapons and fresh hand references; extracting only from your own installation.')
    extract()
    phase('cooking','Exporting and compiling all weapon meshes with your own Developer Tools.')
    subprocess.run([str(ROOT/'.local/tools/blender-3.6.23-windows-x64/blender.exe'),
                    '--background','--python',str(ROOT/'work/export_catalog.py')],cwd=ROOT,check=True)
    run('cook_assets.py');run('publish_catalog.py');run('install_assets.py')
    verify_bridge()


def components_ready(status):
    rows={row['part']:row['state'] for row in status.get('rows',[])}
    expected={'Source poses':'Fresh','World rendering':'Off','Camera sync':'Fresh','Weapon and hand adapter':'Active',
              'Input / vanilla attack filter':'Active','Weapon equipping':'Ready'}
    return bool(status.get('connected') and not status.get('errors')
                and all(rows.get(key)==value for key,value in expected.items())
                and rows.get('Dropped weapon cleanup','').startswith('Active;'))


def verify_bridge():
    phase('calibrating','Calibrating both hands and verifying all native weapon instances in the loaded campaign.')
    from campaign_control import control, health
    if health().get('controller'):control('stop')
    sys.path.insert(0,str(ROOT/'.local/tools/capstone'))
    run('calibrate_hands.py');run('retail_bridge.py','verify-bank');run('inspect_retail_damage.py')
    try:
        with (ROOT/'work/retail/controller-output.log').open('w') as stdout,\
                (ROOT/'work/retail/controller-error.log').open('w') as stderr:
            subprocess.Popen([sys.executable,str(ROOT/'work/run_retail_bridge.py')],cwd=ROOT,
                             stdout=stdout,stderr=stderr,creationflags=134217728)
        deadline=time.monotonic()+60
        while time.monotonic()<deadline:
            status=health()
            if components_ready(status):
                run('verify_equipping.py')
                status=health()
                assert components_ready(status),'Bridge components changed during equipment verification'
                save(ROOT/'.local/setup-verification.json',{'verified_at':time.time(),'status':status,
                     'local_assets':True,'fresh_calibration':True,'gameplay_input_injected':False})
                state=json.loads(STATE.read_text());state.update(phase='installed',ready=True,
                     note='Local assets, hand calibration and live bridge verified. F8 enables control.')
                save(STATE,state)
                print('Installation and live bridge checks passed. Open F7 for status; F8 enables control.',flush=True)
                return
            time.sleep(.5)
        raise RuntimeError('Live bridge did not report connected; installation remains unready')
    except BaseException:
        control('stop')
        phase('verification-failed','Live bridge verification failed. See the private setup log before retrying.')
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=('prepare','finish','all'))
    args=parser.parse_args()
    try:
        if args.action in ('prepare','all'):prepare()
        if args.action in ('finish','all'):finish()
    except Exception as error:
        phase('setup-error',str(error));raise
