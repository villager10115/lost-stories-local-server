"""Stage exact resources for an existing package without changing its live files.

Catalog options are never rewritten. Network retrieval, when explicitly enabled,
uses the observed official origin and catalog/static paths, without credentials.
The output report distinguishes byte-copy verification from Unity validation.
"""
import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import shutil
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.parse import quote

from asset_store import AssetStore, valid_bundle_identity
from catalog_audit import bundles

# Observed in downloads/download-validation.json and Environment.URL's getter.
NATIVE_PREFIX = '/ab/release/latest/StandaloneWindows64/'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def digest_file(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def fetch(path, maximum):
    if not re.fullmatch(r'/[\w./-]+', path) or '..' in path:
        raise ValueError('Invalid source path')
    request = Request('https://app.lost-stories.net' + quote(path, safe='/._-'),
                      headers={'User-Agent': 'ResourcePreservationCheck/1.0'})
    with build_opener(NoRedirect()).open(request, timeout=25) as response:
        body = response.read(maximum + 1)
        if response.status != 200 or len(body) > maximum:
            raise ValueError('Invalid resource response')
        return body


def stage_native(package, caches, output, fetch_missing=False):
    for cache in caches:
        if not cache.is_dir():
            raise ValueError('Resource source directory does not exist: ' + str(cache))
    config = json.loads((package / 'config/private-server.json').read_text('utf8'))
    root = package / config['nativeCatalogs']
    rows = []
    catalog_hashes = {}
    for name in ('catalog.json', 'Binary_catalog.json', 'Json_catalog.json'):
        catalog_hashes[name] = digest_file(root / name)
        rows.extend(bundles(root / name))
    expected_hashes = json.loads((root / 'manifest.json').read_text('utf8'))['outputs']
    if any(expected_hashes[n] != h for n, h in catalog_hashes.items()):
        raise ValueError('Deployed catalog checksum mismatch')
    prefix = 'http://127.0.0.1:%s/assets/' % config['pagePort']
    declarations = defaultdict(set)
    for row in rows:
        if not row['id'].startswith(prefix):
            raise ValueError('Unexpected catalog origin')
        relative = row['id'][len(prefix):]
        if not re.fullmatch(r'[\w./-]+', relative) or '..' in relative:
            raise ValueError('Invalid catalog path')
        row['id'] = AssetStore.PREFIX + relative
        opts = row['options']
        if (not valid_bundle_identity(opts['m_BundleName'], opts['m_Hash'])
                or type(opts['m_BundleSize']) is not int or opts['m_BundleSize'] <= 0):
            raise ValueError('Invalid catalog identity')
        declarations[relative].add((opts['m_BundleName'], opts['m_Hash'], opts['m_BundleSize']))
    if any(len(v) != 1 for v in declarations.values()):
        raise ValueError('Conflicting catalog versions')
    destination = output / 'ResourceCache'
    destination.mkdir(parents=True, exist_ok=False)

    def copy_one(row):
        opts = row['options']; size = opts['m_BundleSize']
        filename = opts['m_BundleName'] + '_' + opts['m_Hash']
        relative = row['id'][len(AssetStore.PREFIX):]
        result = {'path': relative, 'filename': filename, 'bytes': size}
        source = None
        for cache in caches:
            candidate = cache / filename
            if candidate.is_file() and candidate.stat().st_size == size:
                source = candidate
                break
        target = destination / filename
        if source:
            checksum = digest_file(source)
            shutil.copy2(source, target)
            if digest_file(target) != checksum:
                raise ValueError('Resource copy checksum mismatch: ' + relative)
            result.update(source=str(source), sha256=checksum, status='copied')
        elif fetch_missing:
            try:
                body = fetch(NATIVE_PREFIX + relative, size)
                if len(body) != size or not body.startswith(b'UnityFS\0'):
                    raise ValueError('Bundle size or signature mismatch')
                target.write_bytes(body)
                result.update(source='official-exact-path', sha256=digest_file(target),
                              status='downloaded')
            except Exception as error:
                result.update(status='unresolved', error=type(error).__name__)
        else:
            result['status'] = 'unresolved'
        return result

    unique = {r['options']['m_BundleName'] + '_' + r['options']['m_Hash']: r for r in rows}
    with ThreadPoolExecutor(max_workers=4) as pool:
        records = list(pool.map(copy_one, unique.values()))
    by_name = {r['filename']: r for r in records}
    for row in rows:
        opts = row['options']; filename = opts['m_BundleName'] + '_' + opts['m_Hash']
        record = by_name[filename]
        row['matching_cache_files'] = ({'literal_bundle_name': filename}
                                       if record['status'] != 'unresolved' else {})
    (output / 'bundle-mapping.json').write_text(json.dumps(rows, indent=2), 'utf8')
    report = {'catalogs': catalog_hashes, 'entries': len(rows), 'records': records,
              'limitations': 'SHA-256 verifies copying; Unity Hash128 and runtime loading are not independently verified.'}
    (output / 'native-report.json').write_text(json.dumps(report, indent=2), 'utf8')
    print('Native:', len(rows), 'entries;', sum(r['status'] == 'unresolved' for r in records),
          'unresolved', flush=True)
    return report


def stage_web(package, sources, output, fetch_missing=False):
    current_root = package / 'assets/preserved-pages'
    manifest = json.loads((current_root / 'manifest.json').read_text('utf8'))
    known = {(r['path'], r.get('rev'), r['sha256']) for r in manifest}
    destination = output / 'web-additions'; destination.mkdir(exist_ok=False)
    additions = []; skipped = []; variants = defaultdict(dict)
    for source in sources:
        for row in json.loads((source / 'manifest.json').read_text('utf8')):
            if (row.get('host') != 'app.lost-stories.net'
                    or not row.get('path', '').startswith('/web/')
                    or row['path'].endswith('/index.html')
                    or row['path'].startswith('/web/json/')):
                continue
            variants[(row['path'], row.get('rev'))][row['sha256']] = (source, row)
    existing_keys = {(r['path'], r.get('rev')) for r in manifest}
    for key, bodies in variants.items():
        if key in existing_keys:
            continue  # Keep already deployed selections and local overrides.
        if len(bodies) != 1:
            skipped.append({'path': key[0], 'rev': key[1], 'reason': 'same-revision conflict'})
            continue
        source, row = next(iter(bodies.values()))
        checksum = row['sha256']; candidate = source / (checksum + '.body')
        if not re.fullmatch(r'[0-9a-f]{64}', checksum) or digest_file(candidate) != checksum:
            raise ValueError('Static checksum mismatch')
        shutil.copy2(candidate, destination / candidate.name)
        manifest.append(row); additions.append(row)
        known.add((row['path'], row.get('rev'), checksum))
    missing = json.loads((package / 'logs/audit-20261019/click-repair-assets.json').read_text('utf8'))['unlocated']
    failed = []
    if fetch_missing:
        for path in missing:
            if any(r['path'] == path for r in manifest):
                continue
            try:
                body = fetch(path, 8 * 1024 * 1024)
                if not (body.startswith(b'RIFF') and body[8:12] == b'WEBP'):
                    raise ValueError('Not a WebP image')
                checksum = hashlib.sha256(body).hexdigest()
                (destination / (checksum + '.body')).write_bytes(body)
                row = {'host': 'app.lost-stories.net', 'path': path, 'rev': None,
                       'bytes': len(body), 'sha256': checksum,
                       'source_block': 'official-exact-path',
                       'historical_version_verified': False}
                manifest.append(row); additions.append(row)
            except Exception as error:
                failed.append({'path': path, 'error': type(error).__name__})
    (output / 'preserved-manifest.json').write_text(json.dumps(manifest, indent=2), 'utf8')
    report = {'added': additions, 'skipped': skipped, 'download_failures': failed,
              'unlocated': [path for path in missing if not any(r['path'] == path for r in manifest)]}
    (output / 'web-report.json').write_text(json.dumps(report, indent=2), 'utf8')
    print('Web:', len(additions), 'added;', len(report['unlocated']), 'unlocated', flush=True)
    return report


def stage_media(source, output):
    destination = output / 'raw-media'
    destination.mkdir(parents=True, exist_ok=False)
    records = []; evidence = []
    for info in sorted(source.rglob('*.info')):
        original = Path(str(info)[:-5])
        relative = original.relative_to(source).as_posix()
        kind, checksum, size, labels = info.read_text('utf8').split(';')
        if kind != '2' or not re.fullmatch(r'[A-Fa-f0-9]{40}', checksum):
            raise ValueError('Unsupported media metadata: ' + relative)
        body = original.read_bytes()
        if len(body) != int(size) or hashlib.sha1(body).hexdigest().upper() != checksum.upper():
            raise ValueError('Media metadata mismatch: ' + relative)
        target = destination / relative; target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
        sha256 = hashlib.sha256(body).hexdigest()
        if digest_file(target) != sha256:
            raise ValueError('Media copy mismatch')
        shutil.copy2(info, Path(str(target) + '.info'))
        records.append({'Type': int(kind), 'Path': relative, 'Hash': checksum,
                        'Size': int(size), 'Labels': labels.split(',') if labels else []})
        evidence.append({'path': relative, 'sha256': sha256, 'bytes': len(body)})
    (destination / 'filelist.json').write_text(json.dumps({'Records': records}, indent=2), 'utf8')
    (output / 'media-report.json').write_text(json.dumps({'source': str(source),
        'records': evidence, 'total_bytes': sum(r['bytes'] for r in evidence)}, indent=2), 'utf8')
    print('Media:', len(records), 'verified records', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--cache', type=Path, action='append', required=True)
    parser.add_argument('--web-cache', type=Path, action='append', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--fetch-missing', action='store_true')
    parser.add_argument('--raw-media', type=Path)
    args = parser.parse_args(); args.output.mkdir(parents=True, exist_ok=False)
    stage_native(args.package, args.cache, args.output, args.fetch_missing)
    stage_web(args.package, args.web_cache, args.output, args.fetch_missing)
    if args.raw_media:
        stage_media(args.raw_media, args.output)


if __name__ == '__main__':
    main()
