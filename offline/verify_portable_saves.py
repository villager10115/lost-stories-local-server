"""Compare logical database content without exposing player values."""
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

package = Path(sys.argv[1]).resolve()
build = json.loads((package / 'reports/build.json').read_text('utf8'))
source = Path(build['source'])
backup = Path(build['backup'])

def digest(path):
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
        integrity = db.execute('pragma integrity_check').fetchone()[0]
        foreign_keys = len(db.execute('pragma foreign_key_check').fetchall())
        text = '\n'.join(db.iterdump()).encode('utf8')
        return {'integrity': integrity, 'foreignKeyErrors': foreign_keys,
                'logicalSha256': hashlib.sha256(text).hexdigest()}

rows = []
for row in build['saveFiles']:
    relative = row['path']
    if not relative.endswith('.sqlite'):
        continue
    values = {label: digest(root / relative) for label, root in
              [('original', source), ('backup', backup), ('portable', package)]}
    assert all(v['integrity'] == 'ok' and v['foreignKeyErrors'] == 0 for v in values.values())
    assert len(set(v['logicalSha256'] for v in values.values())) == 1, relative
    rows.append({'path': relative, 'checks': values})
(package / 'reports/save-preservation.json').write_text(json.dumps(rows, indent=2), encoding='utf8')
print('Original, consistent backup, portable save are logically identical: %s databases' % len(rows))
