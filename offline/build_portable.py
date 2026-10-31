"""Build a private, relocatable copy; never modify the source package/save."""
import argparse
from datetime import datetime
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path
import shutil
import sqlite3
import sys


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(4 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def copy_tree(source, target):
    if source.is_symlink():
        raise RuntimeError('Unexpected directory link: ' + str(source))
    shutil.copytree(source, target, ignore=shutil.ignore_patterns(
        '__pycache__', '*.pyc', '.git', '*Rollback*', '*.log'))


def main():
    p = argparse.ArgumentParser()
    p.add_argument('source', type=Path)
    p.add_argument('destination', type=Path)
    args = p.parse_args()
    src, dst = args.source.resolve(), args.destination.resolve()
    if dst.exists():
        raise RuntimeError('Destination must be new')
    dst.mkdir()
    snapshot = src / 'snapshots' / ('portable-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
    snapshot.mkdir()
    records = []
    for f in (src / 'data').rglob('*'):
        if not f.is_file() or f.name.endswith(('-wal', '-shm')):
            continue
        relative = f.relative_to(src)
        b = snapshot / relative
        b.parent.mkdir(parents=True, exist_ok=True)
        if f.suffix in ('.sqlite', '.db'):
            with sqlite3.connect(f.as_uri() + '?mode=ro', uri=True) as source:
                with sqlite3.connect(b) as target:
                    source.backup(target)
                    assert target.execute('pragma integrity_check').fetchone()[0] == 'ok'
        else:
            shutil.copy2(f, b)
        target = dst / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(b, target)
        records.append({'path': relative.as_posix(), 'sha256': sha(b)})
    print('Consistent save backup: ' + str(snapshot), flush=True)
    # Source client is retained intact as rollback; new copy receives all changes.
    for directory in ('Client', 'app', 'assets', 'config'):
        print('Copying ' + directory, flush=True)
        copy_tree(src / directory, dst / directory)
    for name in ('logs', 'run', 'launcher', 'reports', 'data/native'):
        (dst / name).mkdir(parents=True, exist_ok=True)
    # Preserve native user data privately without putting official browser cookies in the new package.
    native = Path.home() / 'AppData/LocalLow/dmm/ロススト'
    if native.exists():
        print('Backing up native client data', flush=True)
        copy_tree(native, snapshot / 'native-user-data')
    runtime = dst / 'runtime/python'
    runtime.mkdir(parents=True)
    base = Path(sys.base_prefix)
    for f in base.iterdir():
        if f.suffix.lower() in ('.exe', '.dll') or f.name == 'LICENSE.txt':
            shutil.copy2(f, runtime / f.name)
    shutil.copytree(base / 'Lib', runtime / 'Lib', ignore=shutil.ignore_patterns(
        'site-packages', '__pycache__', 'test', 'tests', 'idlelib', 'tkinter', 'ensurepip'))
    copy_tree(base / 'DLLs', runtime / 'DLLs')
    # Copy installed dependency files from their distribution manifests, not the entire user environment.
    from packaging.requirements import Requirement
    pending = ['fastapi', 'uvicorn', 'sqlalchemy', 'httpx', 'UnityPy', 'Brotli', 'Pillow']
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
            r = Requirement(requirement)
            if r.marker is None or r.marker.evaluate({'extra': ''}):
                pending.append(r.name)
        for entry in dist.files or []:
            if '..' in entry.parts or '__pycache__' in entry.parts:
                continue
            f = Path(dist.locate_file(entry))
            if f.is_file():
                out = runtime / 'Lib/site-packages' / entry
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, out)
    # Explicit path list prevents registry / user-site / PYTHONPATH dependencies.
    (runtime / 'python39._pth').write_text(
        '.\nLib\nDLLs\nLib/site-packages\n../../app\n../../app/offline\n../../app/stateful_server\n../../launcher\n', encoding='ascii')
    config = json.loads((dst / 'config/private-server.json').read_text('utf8'))
    config['name'] = 'Lost Stories Offline Portable'
    config['pythonExecutable'] = 'runtime/python/python.exe'
    (dst / 'config/private-server.json').write_text(json.dumps(config, indent=2), encoding='utf8')
    report = {'source': str(src), 'backup': str(snapshot), 'saveFiles': records,
              'runtime': sys.version, 'dependencies': versions,
              'nativeDataPolicy': 'Fresh package-local cache; official cookies not imported',
              'fullOfficialGameplayReproduced': False}
    (dst / 'reports/build.json').write_text(json.dumps(report, indent=2), encoding='utf8')
    (snapshot / 'backup.json').write_text(json.dumps(report, indent=2), encoding='utf8')
    # Populate the native .info index before first launch; copying server assets alone is insufficient.
    from prepare_native_media import prepare
    unity_data = list((dst / 'Client').glob('*_Data'))
    if len(unity_data) != 1:
        raise RuntimeError('Expected one Unity data directory')
    media = prepare(dst / 'assets/raw-media', dst / 'data/native/raw_data',
                    dst / 'snapshots/media-build', unity_data[0] / 'StreamingAssets/LocalMovie/Opening.usm')
    (dst / 'reports/native-media-preparation.json').write_text(json.dumps(media, indent=2), encoding='utf8')
    print('Portable staging complete: ' + str(dst), flush=True)


if __name__ == '__main__':
    main()
