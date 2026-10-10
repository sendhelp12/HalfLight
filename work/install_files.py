"""Journal only new installer-owned files; never overwrite another mod's files."""
import hashlib
import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def destination(root, relative):
    root = Path(root).resolve()
    relative = Path(relative)
    if relative.is_absolute() or '..' in relative.parts or not relative.parts:
        raise ValueError('Invalid installation destination')
    path = root / relative
    for ancestor in (path, *path.parents):
        if ancestor == root:
            break
        if ancestor.is_symlink() or ancestor.is_junction():
            raise ValueError('Installation destination contains a link')
    if not path.resolve().is_relative_to(root):
        raise ValueError('Installation destination escapes selected root')
    return path


def save(path, state):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as stream:
            json.dump(state, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def uninstall(journal):
    journal = Path(journal)
    if not journal.exists():
        return []
    state = json.loads(journal.read_text(encoding='utf-8'))
    preserved = []
    for item in reversed(state['files']):
        if not item['owned']:
            continue
        path = destination(state['roots'][item['root']], item['relative'])
        if not path.exists():
            continue
        if item.get('backup') and path.is_file() and digest(path)==item['replace_sha256']:
            continue
        if not path.is_file() or digest(path) != item['sha256']:
            preserved.append(item['relative'])
            continue
        if item.get('backup'):
            backup=Path(item['backup'])
            if not backup.is_file() or digest(backup)!=item['replace_sha256']:
                preserved.append(item['relative']);continue
            temporary=path.with_name('.halflight-restore-'+uuid.uuid4().hex+'.tmp')
            try:
                shutil.copyfile(backup,temporary)
                if digest(path)!=item['sha256']:preserved.append(item['relative']);continue
                temporary.replace(path)
            finally:temporary.unlink(missing_ok=True)
        else:path.unlink()
    state['phase'] = 'preserved-modified-files' if preserved else 'removed'
    state['preserved'] = preserved
    save(journal, state)
    return preserved


def install(roots, files, journal):
    if os.name != 'nt':
        raise ValueError('The installer supports Windows only')
    journal = Path(journal)
    if journal.exists() and json.loads(journal.read_text())['phase'] != 'removed':
        raise ValueError('Existing installation journal requires uninstall first')
    roots = {key: str(Path(value).resolve()) for key, value in roots.items()}
    prepared = []; seen = set()
    for item in files:
        source = Path(item['source']).resolve()
        path = destination(roots[item['root']], item['relative'])
        if path in seen:
            raise ValueError('Duplicate installation destination')
        seen.add(path)
        checksum = digest(source)
        if checksum != item['sha256']:
            raise ValueError('Installation source changed')
        replacing=path.exists() and path.is_file() and digest(path)!=checksum
        if path.exists() and (not path.is_file() or replacing and digest(path)!=item.get('replace_sha256')):
            raise ValueError('Preserving differing existing file: ' + item['relative'])
        entry=dict(item,source=str(source),owned=not path.exists() or replacing)
        if replacing:
            backup=journal.parent/'backups'/uuid.uuid4().hex;backup.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(path,backup)
            if digest(backup)!=item['replace_sha256']:raise ValueError('Existing file changed during backup')
            entry['backup']=str(backup.resolve())
        prepared.append(entry)
    state = {'phase': 'installing', 'roots': roots, 'files': prepared}
    save(journal, state)
    try:
        for item in prepared:
            if not item['owned']:
                continue
            path = destination(roots[item['root']], item['relative'])
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name('.halflight-' + uuid.uuid4().hex + '.tmp')
            try:
                with Path(item['source']).open('rb') as source, temporary.open('xb') as target:
                    while chunk := source.read(1024 * 1024):
                        target.write(chunk)
                    target.flush()
                    os.fsync(target.fileno())
                if digest(temporary) != item['sha256']:
                    raise ValueError('Installation source changed during copy')
                if item.get('backup'):
                    if digest(path)!=item['replace_sha256']:raise ValueError('Existing file changed before replacement')
                    temporary.replace(path)
                else:os.rename(temporary, path)  # Windows refuses an existing destination.
            finally:
                temporary.unlink(missing_ok=True)
        state['phase'] = 'installed'
        save(journal, state)
    except BaseException:
        uninstall(journal)
        raise


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--uninstall', action='store_true', required=True)
    parser.parse_args()
    private=Path(__file__).resolve().parents[1]/'.local'
    running=subprocess.run(['tasklist','/FI','IMAGENAME eq HalfSwordUE5-Win64-Shipping.exe','/FO','CSV','/NH'],capture_output=True,text=True,check=True)
    if 'HalfSwordUE5-Win64-Shipping.exe' in running.stdout:raise ValueError('Close Half Sword before uninstalling its loader')
    running=subprocess.run(['tasklist','/FI','IMAGENAME eq DyingLightGame_x64_rwdi.exe','/FO','CSV','/NH'],capture_output=True,text=True,check=True)
    if 'DyingLightGame_x64_rwdi.exe' in running.stdout:raise ValueError('Close DL2 before uninstalling its active bridge assets')
    retained=uninstall(private/'assets-files.json')+uninstall(private/'files.json')
    print('Uninstall complete. Modified files preserved: ' + str(len(retained)))
    if retained:
        raise SystemExit(1)
    state_path=private/'install.json'
    if state_path.exists():
        state=json.loads(state_path.read_text())
        state.update(ready=False,phase='uninstalled',note='Uninstalled. Run Setup to install again.')
        for key in ('capture_session','asset_root'):state.pop(key,None)
        save(state_path,state)
