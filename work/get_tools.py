"""Download checksum-pinned third-party tools into the private source workspace."""
import hashlib
import json
import shutil
import stat
import ssl
import subprocess
import urllib.error
import urllib.request
import uuid
import zipfile
from pathlib import Path
from setup import ROOT


def verified_archive(archive, destination, expected, algorithm='sha256'):
    archive=Path(archive);destination=Path(destination)
    with archive.open('rb') as stream:
        if hashlib.file_digest(stream,algorithm).hexdigest()!=expected:
            raise ValueError('Tool archive checksum mismatch; nothing extracted')
    if destination.exists():raise ValueError('Preserving existing tool directory')
    with zipfile.ZipFile(archive) as package:
        entries=package.infolist();seen={}
        if len(entries)>100000 or sum(entry.file_size for entry in entries)>3*1024**3:
            raise ValueError('Tool archive exceeds extraction limits')
        for entry in entries:
            name=entry.filename.replace('\\','/');relative=Path(name)
            if relative.is_absolute() or '..' in relative.parts or ':' in name or \
                    any(part.endswith(('.', ' ')) for part in relative.parts) or \
                    stat.S_ISLNK(entry.external_attr>>16):
                raise ValueError('Invalid tool archive path')
            key=name.rstrip('/').casefold()
            if key in seen and not (entry.is_dir() and seen[key]):raise ValueError('Duplicate tool archive path')
            seen[key]=entry.is_dir()
        destination.mkdir(parents=True)
        try:
            for entry in entries:
                path=destination/entry.filename.replace('\\','/')
                if entry.is_dir():path.mkdir(parents=True,exist_ok=True);continue
                path.parent.mkdir(parents=True,exist_ok=True)
                with package.open(entry) as source,path.open('xb') as target:
                    shutil.copyfileobj(source,target,1024*1024)
        except BaseException:
            # This directory was created by this call after every archive path passed validation.
            shutil.rmtree(destination)
            raise


def fetch(name, spec, cache=None):
    private=ROOT/'.local';tools=private/'tools';tools.mkdir(parents=True,exist_ok=True)
    archive=private/'downloads'/(name+'.zip');archive.parent.mkdir(parents=True,exist_ok=True)
    checksum=spec.get('sha256') or spec['sha512'];algorithm='sha256' if 'sha256' in spec else 'sha512'
    destination=tools/spec.get('directory',name)
    marker=tools/(name+'.verified.json')
    if marker.exists() and destination.is_dir():
        prior=json.loads(marker.read_text())
        if prior.get('checksum')==checksum:return destination
        raise ValueError('Preserving a different existing tool installation')
    if not archive.exists():
        temporary=archive.with_suffix('.'+uuid.uuid4().hex+'.tmp')
        try:
            if cache:
                shutil.copyfile(Path(cache)/Path(spec['url']).name,temporary)
            else:
                request=urllib.request.Request(spec['url'],headers={'User-Agent':'HalfLight-Setup'})
                try:
                    with urllib.request.urlopen(request,timeout=60) as response,temporary.open('xb') as target:
                        shutil.copyfileobj(response,target,1024*1024)
                except urllib.error.URLError as error:
                    if not isinstance(error.reason,ssl.SSLCertVerificationError):raise
                    # Windows curl validates with the OS certificate store; archive pins still apply.
                    subprocess.run(['curl.exe','--fail','--location','--proto','=https',
                                    '--proto-redir','=https','--output',str(temporary),spec['url']],check=True)
            temporary.replace(archive)
        finally:temporary.unlink(missing_ok=True)
    staging=tools/('.extract-'+uuid.uuid4().hex)
    verified_archive(archive,staging,checksum,algorithm)
    try:
        # Some upstream archives contain one enclosing directory; .NET's SDK does not.
        children=list(staging.iterdir())
        source=children[0] if len(children)==1 and children[0].is_dir() else staging
        if destination.exists():
            current={str(p.relative_to(destination)).casefold():p for p in destination.rglob('*') if p.is_file()}
            expected={str(p.relative_to(source)).casefold():p for p in source.rglob('*') if p.is_file()}
            if current.keys()!=expected.keys() or any(
                hashlib.sha256(current[name].read_bytes()).digest()!=hashlib.sha256(path.read_bytes()).digest()
                for name,path in expected.items()):
                raise ValueError('Preserving an existing tool directory that differs from the verified archive')
        else:source.rename(destination)
        marker.write_text(json.dumps({'checksum':checksum,'url':spec['url']}),encoding='utf-8')
    finally:
        if staging.exists():shutil.rmtree(staging)
    return destination


def tools():
    specs=json.loads((ROOT/'profiles/compiler-tools.json').read_text())
    extractor=json.loads((ROOT/'profiles/extractor-tools.json').read_text())
    specs['dotnet']={'url':extractor['sdk_url'],'sha512':extractor['sdk_sha512']}
    specs['cue4parse']={'url':extractor['cue4parse_source_url'],'sha256':extractor['source_sha256'],
                       'directory':'CUE4Parse-'+extractor['cue4parse_commit']}
    specs['blender']={**json.loads((ROOT/'profiles/blender.json').read_text()),'directory':'blender-3.6.23-windows-x64'}
    specs['capstone']=json.loads((ROOT/'profiles/capstone.json').read_text())
    return specs


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--cache',type=Path)
    args=parser.parse_args()
    for name,spec in tools().items():
        print('Preparing '+name,flush=True)
        fetch(name,spec,args.cache)
    print('Verified tools ready privately. No game files changed.')
