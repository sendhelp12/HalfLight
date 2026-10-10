"""Build authored campaign adapters locally; never attach to or launch a game."""
import argparse
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def build(zig,minhook):
    zig=Path(zig).resolve();minhook=Path(minhook).resolve()
    if not zig.is_file() or not (minhook/'include/MinHook.h').is_file():
        raise ValueError('The verified Zig compiler and MinHook source are required')
    source=ROOT/'native/retail';shared=ROOT/'outputs/HalfLightNext/src'
    output=ROOT/'work/retail';output.mkdir(parents=True,exist_ok=True)
    env=dict(os.environ,ZIG_GLOBAL_CACHE_DIR=str(ROOT/'.local/zig-cache'))
    lab=ROOT/'work/lab';lab.mkdir(parents=True,exist_ok=True)
    for filename,target,options in (
            ('native_input_reader.c','native_input_reader_session.exe',['-luser32']),
            ('native_pose_publish.c','native_pose_publish.dll',['-shared'])):
        subprocess.run([str(zig),'cc',str(shared/filename),'-target','x86_64-windows-gnu',
                        '-O2','-Wall','-Wextra','-Werror','-o',str(lab/target),*options],env=env,check=True)
    for filename in ('arm_ik_fixture.cpp','native_live_fixture.cpp'):
        fixture=output/(Path(filename).stem+'.exe')
        subprocess.run([str(zig),'c++',str(shared/filename),'-target','x86_64-windows-gnu',
                        '-std=c++17','-O2','-Wall','-Wextra','-Werror','-o',str(fixture)],env=env,check=True)
        subprocess.run([str(fixture)],check=True)
    versions=time.time_ns();results=[]
    for cpp,prefix in (('native_retail_live.cpp','HalfLightNativeAxeSessionRetail'),
                       ('native_axe_damage.cpp','HalfLightNativeAxeDamageRetail'),
                       ('native_retail_camera.cpp','HalfLightRetailCamera')):
        dll=output/f'{prefix}{versions}.dll'
        command=[str(zig),'c++',str(source/cpp),'-I'+str(shared),'-target','x86_64-windows-gnu','-std=c++17','-O2','-Wall','-Wextra','-Werror','-shared','-static','-ladvapi32','-o',str(dll)]
        if 'camera' in cpp:
            command.extend(['-I'+str(minhook/'include')])
            for name in ('hook.c','buffer.c','trampoline.c','hde/hde64.c'):
                obj=output/(name.replace('/','_')+'.o')
                subprocess.run([str(zig),'cc',str(minhook/'src'/name),'-I'+str(minhook/'include'),
                                '-target','x86_64-windows-gnu','-O2','-c','-o',str(obj)],env=env,check=True)
                command.append(str(obj))
        subprocess.run(command,env=env,check=True)
        with dll.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
        results.append({'source':cpp,'dll':str(dll),'sha256':digest,'bytes':dll.stat().st_size})
    from install_files import save
    movement,damage,camera=results
    save(output/'build.json',{'adapters':results,'attached':False})
    save(output/'preparation.json',{'status':'compiled; local assets and calibration still required',
         'dll':movement['dll'],'dll_sha256':movement['sha256'],
         'camera_dll':camera['dll'],'camera_sha256':camera['sha256'],
         'source_sha256':hashlib.sha256((source/'native_retail_live.cpp').read_bytes()).hexdigest(),
         'world_geometry_collision':False,'runtime_load_verified':False})
    save(output/'damage-preparation.json',{'dll':damage['dll'],'sha256':damage['sha256'],
         'world_geometry_collision':False,'native_damage_calls_verified':False})
    print('PASS all three campaign adapters built from the clean source workspace. No game attachment.')

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--zig',type=Path,default=ROOT/'.local/tools/zig-windows-x86_64-0.13.0/zig.exe')
    parser.add_argument('--minhook',type=Path,default=ROOT/'.local/tools/minhook-1.3.4')
    args=parser.parse_args();build(args.zig,args.minhook)
