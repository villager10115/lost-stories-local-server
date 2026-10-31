"""Initialize the native media cache from verified package files, without HTTP.

The .info layout follows FileDataRecord.SaveAsync in the shipped client.
Payloads are committed before metadata so interrupted copies are never indexed.
"""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil


def sha1(path):
    digest = hashlib.sha1()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest().upper()


def valid(path, record):
    return path.is_file() and path.stat().st_size == record['Size'] and sha1(path) == record['Hash'].upper()


def prepare(source, destination, backup, opening=None):
    source, destination, backup = map(lambda p: Path(p).resolve(), (source, destination, backup))
    records = json.loads((source / 'filelist.json').read_text('utf8'))['Records']
    # Validate the entire path/metadata set before writing anything.
    seen = set()
    for record in records:
        rel = Path(record['Path'])
        if rel.is_absolute() or '..' in rel.parts or rel.parts[0] not in ('Movie', 'Sound'):
            raise ValueError('Unsafe media path')
        if record['Path'] in seen or record['Type'] != 2:
            raise ValueError('Duplicate or unsupported media record')
        if len(record['Hash']) != 40 or any(c not in '0123456789abcdefABCDEF' for c in record['Hash']):
            raise ValueError('Invalid media digest')
        if type(record['Size']) is not int or record['Size'] <= 0:
            raise ValueError('Invalid media size')
        if any(not isinstance(label, str) or any(c in label for c in ',;\r\n') for label in record['Labels']):
            raise ValueError('Invalid media labels')
        (source / rel).resolve().relative_to(source)
        (destination / rel).resolve().relative_to(destination)
        seen.add(record['Path'])
    copied = reused = metadata_repaired = 0
    def preserve(path):
        if path.exists():
            relative = path.relative_to(destination) if destination in path.parents else Path('LocalMovie') / path.name
            out = backup / relative
            out.parent.mkdir(parents=True, exist_ok=True)
            if out.exists():
                raise RuntimeError('Backup collision: ' + str(out))
            shutil.copy2(path, out)
    def install(src, dst, record):
        dst.parent.mkdir(parents=True, exist_ok=True)
        temporary = dst.with_name(dst.name + '.preparing')
        digest = hashlib.sha1()
        with src.open('rb') as reader, temporary.open('wb') as writer:
            for chunk in iter(lambda: reader.read(4 * 1024 * 1024), b''):
                digest.update(chunk)
                writer.write(chunk)
        if temporary.stat().st_size != record['Size'] or digest.hexdigest().upper() != record['Hash'].upper():
            temporary.unlink()
            raise ValueError('Package media checksum mismatch: ' + record['Path'])
        preserve(dst)
        os.replace(temporary, dst)
    for i, record in enumerate(records):
        src, dst = source / record['Path'], destination / record['Path']
        if valid(dst, record):
            reused += 1
        else:
            install(src, dst, record)
            copied += 1
        info = Path(str(dst) + '.info')
        expected = '%s;%s;%s;%s' % (record['Type'], record['Hash'], record['Size'], ','.join(record['Labels']))
        if not info.exists() or info.read_text('utf-8-sig') != expected:
            preserve(info)
            temporary = Path(str(info) + '.preparing')
            temporary.write_text(expected, encoding='utf8')
            os.replace(temporary, info)
            metadata_repaired += 1
        if i % 500 == 0:
            print('Preparing packaged media: %s/%s' % (i, len(records)), flush=True)
    if opening is not None:
        record = next(r for r in records if r['Path'] == 'Movie/Opening.usm')
        if not valid(Path(opening), record):
            install(source / record['Path'], Path(opening), record)
    return {'records': len(records), 'copied': copied, 'reused': reused,
            'metadataRepaired': metadata_repaired, 'mediaDownloadRequired': 0,
            'openingPrepared': opening is not None}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('package', type=Path)
    args = parser.parse_args()
    root = args.package.resolve()
    data = list((root / 'Client').glob('*_Data'))
    if len(data) != 1:
        raise ValueError('Expected one Unity data directory')
    result = prepare(root / 'assets/raw-media', root / 'data/native/raw_data',
                     root / 'snapshots' / ('media-repair-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f')),
                     data[0] / 'StreamingAssets/LocalMovie/Opening.usm')
    (root / 'reports/native-media-preparation.json').write_text(json.dumps(result, indent=2), encoding='utf8')
    print(json.dumps(result, indent=2), flush=True)


if __name__ == '__main__':
    main()
