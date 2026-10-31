import json
import sqlite3
from pathlib import Path
import shutil
import sys


source = Path(sys.argv[1]).resolve()
destination = Path(sys.argv[2]).resolve()
config = json.loads(
    (source / 'config/private-server.json').read_text(encoding='utf8'))

for key in ('stateDatabase', 'pageDatabase', 'deckDatabase'):
    relative = config[key]
    source_file = source / relative
    destination_file = destination / relative
    destination_file.parent.mkdir(parents=True, exist_ok=True)
    if not source_file.is_file():
        continue
    with sqlite3.connect(
            source_file.as_uri() + '?mode=ro', uri=True) as old:
        with sqlite3.connect(destination_file) as new:
            old.backup(new)
            if new.execute('pragma integrity_check').fetchone()[0] != 'ok':
                raise SystemExit('Save backup integrity failure: ' + key)

mission_claims = config.get('missionClaims')
if mission_claims:
    source_file = source / mission_claims
    if source_file.is_file():
        destination_file = destination / mission_claims
        destination_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, destination_file)

print(json.dumps({
    'stateDatabase': config['stateDatabase'],
    'pageDatabase': config['pageDatabase'],
    'deckDatabase': config['deckDatabase'],
    'missionClaims': mission_claims,
}, ensure_ascii=False))
