"""Build the authored extractor against privately downloaded upstream sources."""
import argparse
import os
import subprocess
from pathlib import Path
from setup import ROOT


def build(dotnet):
    private=ROOT/'.local';home=private/'dotnet-home';home.mkdir(parents=True,exist_ok=True)
    env=dict(os.environ,DOTNET_CLI_HOME=str(home),DOTNET_CLI_TELEMETRY_OPTOUT='1',
             DOTNET_NOLOGO='1',NUGET_PACKAGES=str(private/'nuget-packages'))
    subprocess.run([str(Path(dotnet).resolve()),'build',str(ROOT/'extractor/WeaponExtractor.csproj'),
                    '-c','Release','--artifacts-path',str(private/'extractor-build')],env=env,check=True)
    binary=private/'extractor-build/bin/WeaponExtractor/release/WeaponExtractor.dll'
    if not binary.is_file():raise RuntimeError('Extractor output missing')
    print('Extractor built privately; no game assets bundled.')
    return binary


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--dotnet',type=Path,default=ROOT/'.local/tools/dotnet/dotnet.exe')
    build(parser.parse_args().dotnet)
