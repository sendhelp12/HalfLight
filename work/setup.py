"""Validate owned installs and record private paths before any installation."""
import argparse
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def inside(root, relative):
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError('Required file missing inside selected installation: ' + relative)
    return path


def validate(half_sword, dying_light, profiles=None):
    profile = profiles or json.loads((ROOT / 'profiles/retail.json').read_text())
    paths = {
        'HalfSwordUE5-Win64-Shipping.exe': inside(half_sword, 'HalfSwordUE5/Binaries/Win64/HalfSwordUE5-Win64-Shipping.exe'),
        'DyingLightGame_x64_rwdi.exe': inside(dying_light, 'ph/work/bin/x64/DyingLightGame_x64_rwdi.exe'),
    }
    for name in profile['modules']:
        paths[name] = inside(dying_light, 'ph/work/bin/x64/' + name)
    for name, path in paths.items():
        expected = (profile['modules'] if name in profile['modules'] else profile['games'])[name]['sha256']
        if digest(path) != expected:
            raise ValueError('Unsupported game build: ' + name + '. No files have been installed.')
    inside(half_sword, 'HalfSwordUE5/Content/Paks/pakchunk0-Windows.pak')
    exporter = Path(dying_light) / 'DevTools/dcc/blender/techland_msh_exporter'
    if not exporter.is_dir():
        raise ValueError('Install the free Dying Light 2 Developer Tools from Steam first.')
    version = inside(dying_light, 'DevTools/version.txt').read_text().strip()
    if version != profile['devtools_version']:
        raise ValueError('Unsupported Developer Tools build: ' + version)
    return paths


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--half-sword', required=True, type=Path)
    parser.add_argument('--dying-light', required=True, type=Path)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    paths = validate(args.half_sword, args.dying_light)
    print('Both owned game builds and the local exporter are compatible.')
    if args.check:
        return
    private = ROOT / '.local'
    private.mkdir(exist_ok=True)
    existing=private/'install.json'
    if existing.exists():
        prior=json.loads(existing.read_text())
        if Path(prior['half_sword']).resolve()==args.half_sword.resolve() and Path(prior['dying_light']).resolve()==args.dying_light.resolve():
            print('Existing local setup retained. Use Install / Resume to continue.')
            return
        journal=private/'files.json'
        if journal.exists() and json.loads(journal.read_text())['phase']!='removed':
            raise ValueError('Uninstall the previous owned setup before selecting different game folders.')
    state = {'half_sword': str(args.half_sword.resolve()), 'dying_light': str(args.dying_light.resolve()),
             'phase': 'validated', 'ready': False,
             'note': 'Asset cooking and first-run hand calibration are not yet complete.'}
    temporary = private / ('install.' + str(os.getpid()) + '.tmp')
    temporary.write_text(json.dumps(state, indent=2), encoding='utf-8')
    temporary.replace(private / 'install.json')
    print('Local configuration saved. No game files changed.')


if __name__ == '__main__':
    main()
