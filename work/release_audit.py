"""Fail closed on unlisted files, private paths, secrets and generated content."""
import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWED = {'.py', '.lua', '.h', '.hpp', '.c', '.cpp', '.cs', '.csproj', '.ps1', '.cmd', '.md', '.json', '.yml'}
SPECIAL = {'.gitignore', 'LICENSE'}
PATTERNS = [
    ('personal Windows path', re.compile(r'[A-Za-z]:[/\\]+U' + r'sers[/\\]+[^/\\\s]+', re.I)),
    ('private Unix home', re.compile(r'/h' + r'ome/[^/\s]+/')),
    ('credential', re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|sk-[A-Za-z0-9_-]{30,}|AKIA[A-Z0-9]{16})\b')),
    ('email address', re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b')),
    ('decompiler output', re.compile(r'Decompiled w' + r'ith|\bFUN_[0-9a-f]{8,}\b|\bsub_[0-9a-f]{8,}\b', re.I)),
]


def audit(root, paths=None):
    root = Path(root).resolve()
    failures = []; entries = []
    if paths is None:
        paths = [p for p in root.rglob('*') if p.is_file() and not any(x in ('.git', '.local', '__pycache__') for x in p.relative_to(root).parts)]
    for path in paths:
        path = Path(path).resolve()
        if not path.is_relative_to(root):
            failures.append('Path outside repository'); continue
        relative = path.relative_to(root).as_posix()
        if path.suffix.lower() not in ALLOWED and path.name not in SPECIAL:
            failures.append('Non-source file: ' + relative); continue
        if any(part in ('assets', 'owned-assets', 'lab', 'retail', 'vendor', 'runtime', '.local') for part in path.relative_to(root).parts) and not relative.startswith('native/retail/'):
            failures.append('Private/generated directory: ' + relative); continue
        raw = path.read_bytes()
        if len(raw) > 1024 * 1024 or b'\0' in raw:
            failures.append('Large or binary file: ' + relative); continue
        try: text = raw.decode('utf-8-sig')
        except UnicodeError:
            failures.append('Non-UTF8 file: ' + relative); continue
        for label, pattern in PATTERNS:
            if pattern.search(text): failures.append(label + ': ' + relative)
        entries.append({'path': relative, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
    return failures, entries


def history_audit(root):
    result = subprocess.run(['git', 'rev-list', '--objects', '--all'], cwd=root, check=True, capture_output=True, text=True)
    failures = []; seen = set()
    for line in result.stdout.splitlines():
        fields = line.split(' ', 1); oid = fields[0]
        if oid in seen: continue
        seen.add(oid)
        kind = subprocess.run(['git', 'cat-file', '-t', oid], cwd=root, check=True, capture_output=True, text=True).stdout.strip()
        if kind != 'blob': continue
        name = fields[1] if len(fields) == 2 else '(unnamed blob)'
        size = int(subprocess.run(['git', 'cat-file', '-s', oid], cwd=root, check=True, capture_output=True, text=True).stdout)
        if size > 1024 * 1024:
            failures.append('Large historical blob: ' + name); continue
        raw = subprocess.run(['git', 'cat-file', 'blob', oid], cwd=root, check=True, capture_output=True).stdout
        if Path(name).suffix.lower() not in ALLOWED and Path(name).name not in SPECIAL:
            failures.append('Non-source historical file: ' + name)
        if any(part in ('.local', 'assets', 'owned-assets', 'lab', 'vendor', 'runtime') for part in Path(name).parts):
            failures.append('Private/generated historical file: ' + name)
        try: text = raw.decode('utf-8-sig')
        except UnicodeError:
            failures.append('Binary historical blob: ' + name); continue
        if b'\0' in raw: failures.append('Binary historical blob: ' + name)
        for label, pattern in PATTERNS:
            if pattern.search(text): failures.append(label + ' in history: ' + name)
    return failures


def staged_audit(root):
    records=subprocess.run(['git','ls-files','--stage','-z'],cwd=root,check=True,capture_output=True).stdout
    failures=[]
    for record in records.split(b'\0'):
        if not record:continue
        metadata,name=record.split(b'\t',1);mode,oid,stage=metadata.decode().split()
        name=name.decode('utf-8')
        if mode!='100644' or stage!='0':
            failures.append('Unsupported staged entry: '+name);continue
        size=int(subprocess.run(['git','cat-file','-s',oid],cwd=root,check=True,capture_output=True,text=True).stdout)
        if size>1024*1024:
            failures.append('Large staged blob: '+name);continue
        raw=subprocess.run(['git','cat-file','blob',oid],cwd=root,check=True,capture_output=True).stdout
        if Path(name).suffix.lower() not in ALLOWED and Path(name).name not in SPECIAL:
            failures.append('Non-source staged file: '+name)
        if any(part in ('.local','assets','owned-assets','lab','vendor','runtime') for part in Path(name).parts):
            failures.append('Private/generated staged file: '+name)
        try:text=raw.decode('utf-8-sig')
        except UnicodeError:
            failures.append('Binary staged blob: '+name);continue
        if b'\0' in raw:failures.append('Binary staged blob: '+name)
        for label,pattern in PATTERNS:
            if pattern.search(text):failures.append(label+' in staging: '+name)
    return failures


def metadata_audit(root):
    records=subprocess.run(['git','log','--all','--format=%an%x00%ae%x00%cn%x00%ce%x00%B%x00'],
                           cwd=root,capture_output=True,text=True)
    # An unborn branch has no metadata. Other Git failures must fail the release check.
    if records.returncode:
        head=subprocess.run(['git','rev-parse','--verify','HEAD'],cwd=root,capture_output=True)
        if head.returncode:return []
        records.check_returncode()
    values=records.stdout.split('\0');failures=[]
    for index in range(0,len(values)-1,5):
        author,email,committer,committer_email,message=values[index:index+5]
        if (author.strip(),committer.strip())!=('HalfLight contributors','HalfLight contributors') or \
                email!='release'+chr(64)+'example.invalid' or committer_email!=email:
            failures.append('Personal or unapproved Git author/committer metadata')
        for label,pattern in PATTERNS:
            if pattern.search(message):failures.append(label+' in commit message')
    return sorted(set(failures))


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--tracked', action='store_true'); args = parser.parse_args()
    paths = None
    if args.tracked:
        result = subprocess.run(['git', 'ls-files', '-z'], cwd=ROOT, check=True, capture_output=True)
        paths = [ROOT / p.decode('utf-8') for p in result.stdout.split(b'\0') if p]
    failures, entries = audit(ROOT, paths)
    if args.tracked:
        failures.extend(staged_audit(ROOT));failures.extend(history_audit(ROOT));failures.extend(metadata_audit(ROOT))
    print(json.dumps({'files': len(entries), 'source_bytes': sum(e['bytes'] for e in entries), 'failures': failures}, indent=2))
    if failures: raise SystemExit(1)
    print('PASS source/privacy scan. This is not a legal opinion or a clean-machine gameplay check.')


if __name__ == '__main__':
    main()
