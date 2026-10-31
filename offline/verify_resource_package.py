"""Read-only package resource audit with an ephemeral HTTP server and save."""
import argparse
import hashlib
import http.client
import json
from pathlib import Path
import tempfile
import threading
from urllib.parse import quote, urlsplit

from asset_store import AssetStore
from catalog_audit import bundles
from server import LocalServer
from web_audit import decode_text


def verify(package):
    config = json.loads((package / 'config/private-server.json').read_text('utf8'))
    assets = package / config['assetCache']; mapping = package / config['assetMapping']
    store = AssetStore(mapping, assets)
    assert not store.conflicts
    catalogs = package / config['nativeCatalogs']
    client = next((package / 'Client').glob('*_Data')) / 'StreamingAssets/aa'
    count = 0
    for name in ('catalog.json', 'Binary_catalog.json', 'Json_catalog.json'):
        assert (client / name).read_bytes() == (catalogs / name).read_bytes()
        for row in bundles(catalogs / name):
            prefix = 'http://127.0.0.1:%s/assets/' % config['pagePort']
            assert row['id'].startswith(prefix)
            route = '/assets/' + row['id'][len(prefix):]
            opts = row['options']; filename = opts['m_BundleName'] + '_' + opts['m_Hash']
            assert store.routes[route] == (filename, opts['m_BundleSize'])
            assert (assets / filename).stat().st_size == opts['m_BundleSize']
            count += 1
    native = json.loads((package / 'logs/audit-20261019/resource-native.json').read_text('utf8'))
    web = json.loads((package / 'logs/audit-20261019/resource-web.json').read_text('utf8'))
    checks = []
    with tempfile.TemporaryDirectory(prefix='cgls-resource-check-') as temporary:
        server = LocalServer(0, Path(temporary) / 'temporary.sqlite',
            asset_mapping=mapping, asset_cache=assets, native_catalogs=catalogs,
            native_hashes=package / config['nativeHashes'],
            web_root=package / config['webRoot'], web_entry=config['webEntry'],
            preserved_pages_cache=package / config['preservedPages'],
            raw_media=package / config['rawMedia'])
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        def request(path):
            conn = http.client.HTTPConnection(*server.server_address, timeout=90)
            try:
                conn.request('GET', quote(path, safe='/?=&._-'))
                response = conn.getresponse(); body = response.read()
                assert response.status == 200, (path, response.status)
                checks.append({'path': path, 'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest()})
                return body
            finally:
                conn.close()
        try:
            for row in native['records']:
                if (row['status'] == 'downloaded' or
                    any(s in row['path'] for s in ['gachatopscene.bundle', 'advfontmaterialdata.bundle', 'fourthtitle/定着.bundle'])):
                    body = request('/assets/' + row['path'])
                    assert hashlib.sha256(body).hexdigest() == row['sha256']
            for row in web['added']:
                target = row['path'] + ('?rev=' + row['rev'] if row.get('rev') else '')
                body = request(target)
                raw = (package / config['preservedPages'] / (row['sha256'] + '.body')).read_bytes()
                expected = decode_text(raw)[0].encode('utf8') if row['path'].endswith('.js') else raw
                assert body == expected
            request('/web/js/quest/QuestResult.js')
            records = json.loads(request('/assets/filelist.json'))['Records']
            for category in ('Movie/', 'Sound/'):
                record = min((r for r in records if r['Path'].startswith(category)), key=lambda r: r['Size'])
                body = request('/assets/' + record['Path'] + '?hash=' + record['Hash'])
                assert hashlib.sha1(body).hexdigest().upper() == record['Hash'].upper()
            for record in records:
                if ' ' in record['Path']:
                    body = request('/assets/' + record['Path'] + '?hash=' + record['Hash'])
                    assert hashlib.sha1(body).hexdigest().upper() == record['Hash'].upper()
            for name in ('catalog.json', 'Binary_catalog.json', 'Json_catalog.json'):
                assert request('/assets/' + name) == (catalogs / name).read_bytes()
            targets = set()
            for log in (package / 'logs/interaction-live-20261019').glob('segment-*/events.jsonl'):
                for line in log.read_text('utf8').splitlines():
                    event = json.loads(line)
                    if event.get('kind') != 'request':
                        continue
                    url = urlsplit(event.get('url', ''))
                    if (url.path.startswith('/web/') and not url.path.startswith('/web/image/pilots/')
                            and '/web/json/' not in url.path):
                        targets.add(url.path + ('?' + url.query if url.query else ''))
            replay_failures = []
            for target in sorted(targets):
                status = server.web.resolve(target)[0]
                if status in (404, 409) and server.preserved_web.resolve(target)[0] == 200:
                    status = 200
                if status != 200:
                    replay_failures.append({'path': target, 'status': status})
            assert not replay_failures, replay_failures
        finally:
            server.shutdown(); thread.join(); server.server_close()
    return {'native_routes': count, 'native_conflicts': len(store.conflicts),
            'media_records': len(records), 'http_checks': checks,
            'recorded_static_requests': len(targets), 'recorded_static_failures': replay_failures,
            'client_catalogs_equal_server': True, 'production_saves_used': False,
            'native_game_executed': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); report = verify(args.package)
    args.output.write_text(json.dumps(report, indent=2), 'utf8')
    print(json.dumps({k: len(v) if k == 'http_checks' else v for k, v in report.items()}))
