import hashlib
import json
import shutil
import sqlite3
import sys
from pathlib import Path

source = Path(sys.argv[1]).resolve()
destination = Path(sys.argv[2]).resolve()
if destination.exists():
    raise SystemExit('Backup destination already exists.')
destination.mkdir(parents=True)
database_paths = [
    source / 'data/state/state.sqlite',
    source / 'data/page/prototype.sqlite',
    source / 'data/page/decks.sqlite',
]
records = []
for path in database_paths:
    relative = path.relative_to(source)
    target = destination / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as old:
        with sqlite3.connect(target) as new:
            old.backup(new)
            if new.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise RuntimeError('Integrity check failed: ' + str(relative))
            if new.execute('PRAGMA foreign_key_check').fetchone():
                raise RuntimeError('Foreign key check failed: ' + str(relative))
    records.append({
        'path': relative.as_posix(),
        'bytes': target.stat().st_size,
        'sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
    })
claims = source / 'data/page/mission_claims.json'
if claims.is_file():
    target = destination / claims.relative_to(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(claims, target)
    records.append({
        'path': claims.relative_to(source).as_posix(),
        'bytes': target.stat().st_size,
        'sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
    })
(destination / 'backup.json').write_text(
    json.dumps({'source': str(source), 'files': records}, indent=2),
    encoding='utf8')
print(json.dumps({'files': len(records), 'backup': str(destination)}))
