import hashlib
import json
from pathlib import Path
import sys

root = Path(sys.argv[1]).resolve()
client_executable = root / 'Client' / 'ロストストーリーズ.exe'
if not client_executable.is_file():
    raise SystemExit('Missing renamed direct client executable.')

files = []
for directory in ('Client', 'app', 'assets', 'config', 'runtime', 'launcher'):
    base = root / directory
    if not base.is_dir():
        raise SystemExit('Missing package directory: ' + directory)
    for filename in sorted(base.rglob('*')):
        if (not filename.is_file() or '__pycache__' in filename.parts
                or filename.suffix in ('.log', '.pyc', '.portable')):
            continue
        digest = hashlib.sha256()
        with filename.open('rb') as stream:
            for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
                digest.update(block)
        files.append({
            'path': filename.relative_to(root).as_posix(),
            'bytes': filename.stat().st_size,
            'sha256': digest.hexdigest(),
        })
        if len(files) % 10000 == 0:
            print('Manifest hashed: %s' % len(files), flush=True)

for name in ('ロストストーリーズ.lnk', 'README_日本語.md'):
    filename = root / name
    if not filename.is_file():
        raise SystemExit('Missing direct-client package file: ' + name)
    files.append({
        'path': name,
        'bytes': filename.stat().st_size,
        'sha256': hashlib.sha256(filename.read_bytes()).hexdigest(),
    })

files.sort(key=lambda row: row['path'])
report = {
    'name': 'ロストストーリーズ',
    'clientExecutable': client_executable.relative_to(root).as_posix(),
    'launcherExecutableIncluded': False,
    'directClientBootstrap': True,
    'files': len(files),
    'bytes': sum(row['bytes'] for row in files),
}
(root / 'reports').mkdir(exist_ok=True)
(root / 'reports/files.json').write_text(
    json.dumps({'files': files}, indent=2), encoding='utf8')
(root / 'reports/direct-client-package.json').write_text(
    json.dumps(report, indent=2), encoding='utf8')
print(json.dumps(report, ensure_ascii=False))
