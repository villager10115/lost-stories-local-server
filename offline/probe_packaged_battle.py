"""Probe actual packaged handlers using consistent copies of all three saves."""
import hashlib
import http.client
import json
from pathlib import Path
import sqlite3
import sys
import threading


ROOT = Path('D:/LostStories_Offline')
OUT = Path('D:/codegeass/snapshots/battle-system-audit/http-probe')


def main():
    OUT.mkdir(parents=True, exist_ok=False)
    config = json.loads((ROOT / 'config/private-server.json').read_text('utf8'))
    copies, checks = {}, {}
    for key in ('stateDatabase', 'pageDatabase', 'deckDatabase'):
        source = ROOT / config[key]
        target = OUT / (key + '.sqlite')
        with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as src:
            with sqlite3.connect(target) as dest:
                src.backup(dest)
                checks[key] = {'integrity': dest.execute('PRAGMA integrity_check').fetchone()[0],
                    'foreignKeyFailures': dest.execute('PRAGMA foreign_key_check').fetchall(),
                    'logicalCopyMatches': list(src.iterdump()) == list(dest.iterdump())}
        copies[key] = target
    sys.path[:0] = [str(ROOT / 'app/offline'), str(ROOT / 'app/stateful_server')]
    from cgls.app import create_app
    from fastapi.testclient import TestClient
    from server import LocalServer
    app = create_app(copies['stateDatabase'], ROOT / 'app/stateful_server/fixtures/gacha_1005.json',
                     masterdata_dir=ROOT / config['masterdata'])
    state = TestClient(app)
    # Inject reads into this test instance only; every write is confined to copies.
    import new_account_page
    new_account_page.NewAccountPage._state = lambda self: state.get('/api/local/page-state').json()
    new_account_page.NewAccountPage._units = lambda self: state.get('/api/local/units').json()
    server = LocalServer(0, copies['pageDatabase'], deck_database=copies['deckDatabase'],
        masterdata=ROOT / config['masterdata'],
        preserved_pages_cache=ROOT / config['preservedPages'],
        web_root=ROOT / config['webRoot'], web_entry=config['webEntry'],
        native_catalogs=ROOT / config['nativeCatalogs'], native_hashes=ROOT / config['nativeHashes'],
        asset_mapping=ROOT / config['assetMapping'], asset_cache=ROOT / config['assetCache'])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    probes = []
    try:
        for method, path in [
            ('GET', '/api/page/QuestBackground'), ('GET', '/api/page/QuestResult'),
            ('POST', '/api/battle/start'), ('POST', '/api/battle/end'),
            ('POST', '/api/battle/skip'),
            ('GET', '/web/js/quest/QuestBackground.js'),
            ('GET', '/assets/Json_catalog.json.gz'), ('GET', '/assets/Binary_catalog.json.gz'),
            ('HEAD', '/assets/Json_catalog.json'), ('HEAD', '/assets/Binary_catalog.json')]:
            connection = http.client.HTTPConnection(*server.server_address, timeout=20)
            connection.request(method, path, '{}' if method == 'POST' else None,
                {'X-Web-Session-Id': 'isolated-battle-audit', 'Content-Type': 'application/json'})
            response = connection.getresponse()
            body = response.read()
            probes.append({'surface': 'page', 'method': method, 'path': path,
                           'status': response.status, 'bytes': len(body),
                           'body': body.decode('utf8', errors='replace') if response.status >= 400 else None})
            connection.close()
        for path in ('/api/battle/start', '/api/battle/end', '/api/battle/skip'):
            response = state.post(path, json={})
            probes.append({'surface': 'state', 'method': 'POST', 'path': path,
                           'status': response.status_code})
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        state.close()
        app.state.engine.dispose()
    report = {'copies': checks, 'requests': probes,
              'formalStateWritten': False, 'gameLaunched': False}
    (OUT / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
