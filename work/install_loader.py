"""Install the pinned loader once, before starting Half Sword for local capture."""
import json
import re
import shutil
import subprocess
import uuid
import time
from pathlib import Path
from get_tools import fetch
from install_files import digest, install, save
from setup import ROOT, validate


def prepare(game, package, root=ROOT):
    game=Path(game);package=Path(package);root=Path(root)
    staging=root/'.local/loader';staging.mkdir(parents=True,exist_ok=True)
    files=[]
    def add(source, relative):
        files.append({'source':str(source),'root':'half_sword','relative':relative,'sha256':digest(source)})
    for relative in ('dwmapi.dll','ue4ss/UE4SS.dll','ue4ss/LICENSE'):
        add(package/relative,relative)
    # Existing settings and other mods belong to the user, including their load order.
    if not (game/'ue4ss/UE4SS-settings.ini').exists():
        settings=(package/'ue4ss/UE4SS-settings.ini').read_text(encoding='utf-8-sig')
        settings=re.sub(r'(?m)^(ConsoleEnabled|GuiConsoleEnabled)\s*=\s*\d+',r'\1 = 0',settings)
        (staging/'UE4SS-settings.ini').write_text(settings,encoding='utf-8')
        add(staging/'UE4SS-settings.ini','ue4ss/UE4SS-settings.ini')
    for name in ('main.lua','halflight-root.txt','enabled.txt'):
        output=staging/name
        if name=='main.lua':shutil.copyfile(root/'loader/main.lua',output)
        else:output.write_text(str(root.resolve()) if name=='halflight-root.txt' else '',encoding='utf-8')
        relative='ue4ss/Mods/HalfLightBridge/'+('Scripts/' if name!='enabled.txt' else '')+name
        add(output,relative)
        if name=='main.lua' and (game/relative).is_file():
            checksum=digest(game/relative)
            # Only this exact authored predecessor is eligible for migration; other mods are refused.
            if checksum=='35eefbd56affc7daba7127ac60a233aec51872e01a7d638bb1c9f9da20bb6590':
                files[-1]['replace_sha256']=checksum
    return files


def initialize_capture(root=ROOT):
    (Path(root)/'work/lab').mkdir(parents=True,exist_ok=True)
    runtime=Path(root)/'outputs/HalfLightNext/runtime';runtime.mkdir(parents=True,exist_ok=True)
    session=uuid.uuid4().hex
    (runtime/'session.ini').write_text('RunId='+session+'\n',encoding='ascii')
    (runtime/'actor-capture.ini').write_text('Enabled=1\nEpoch='+str(time.time_ns())+'\n',encoding='ascii')
    shutil.copyfile(Path(root)/'loader/actor_capture.lua',runtime/'actor_capture.lua')
    (runtime/'guest-input.ini').write_text('Enabled=0\n',encoding='ascii')
    (runtime/'setup-mapping.request').write_text(session,encoding='ascii')
    return session


def main():
    state=json.loads((ROOT/'.local/install.json').read_text())
    validate(state['half_sword'],state['dying_light'])
    running=subprocess.run(['tasklist','/FI','IMAGENAME eq HalfSwordUE5-Win64-Shipping.exe','/FO','CSV','/NH'],
                           capture_output=True,text=True,check=True)
    if 'HalfSwordUE5-Win64-Shipping.exe' in running.stdout:
        raise ValueError('Close Half Sword before installing its loader. Setup only needs this once.')
    package=fetch('ue4ss',json.loads((ROOT/'profiles/loader.json').read_text()))
    binary=Path(state['half_sword'])/'HalfSwordUE5/Binaries/Win64'
    files=prepare(binary,package)
    install({'half_sword':binary},files,ROOT/'.local/files.json')
    state.update(phase='loader-installed',ready=False,capture_session=initialize_capture())
    save(ROOT/'.local/install.json',state)
    print('Loader installed. Open Half Sword once and load a match for local weapon capture.')


if __name__=='__main__':main()
