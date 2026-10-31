import importlib.metadata as metadata
import json
from pathlib import Path
import shutil
import sys
from packaging.requirements import Requirement

root = Path(sys.argv[1]).resolve()
runtime = root / 'runtime/python/Lib/site-packages'
pending = ['UnityPy', 'Brotli', 'Pillow']
done = set()
versions = {}
while pending:
    name = pending.pop().lower().replace('_', '-')
    if name in done:
        continue
    done.add(name)
    dist = metadata.distribution(name)
    versions[dist.metadata['Name']] = dist.version
    for requirement in dist.requires or []:
        req = Requirement(requirement)
        if req.marker is None or req.marker.evaluate({'extra': ''}):
            pending.append(req.name)
    for entry in dist.files or []:
        if '..' in entry.parts or '__pycache__' in entry.parts:
            continue
        source = Path(dist.locate_file(entry))
        if source.is_file():
            dest = runtime / entry
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)
report = root / 'reports/build.json'
data = json.loads(report.read_text('utf8'))
data['dependencies'].update(versions)
report.write_text(json.dumps(data, indent=2), encoding='utf8')
print(json.dumps(versions, indent=2))
