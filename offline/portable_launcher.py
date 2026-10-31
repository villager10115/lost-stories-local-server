"""Portable service supervisor. All persistent paths stay beneath the package."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
CRITICAL_MANIFEST_FILES = (
    'Client/ロストストーリーズ.exe',
    'Client/ロストストーリーズ_Data/Managed/Assembly-CSharp.dll',
    'Client/ロストストーリーズ_Data/Managed/LocalDirectBootstrap.dll',
    'runtime/python/python.exe',
    'runtime/python/pythonw.exe',
    'runtime/python/python3.dll',
    'runtime/python/python39.dll',
    'app/offline/server.py',
    'app/stateful_server/cgls/app.py',
    'app/stateful_server/cgls/battle_data.py',
    'app/stateful_server/cgls/battles.py',
)


def path(value):
    target = (ROOT / value).resolve()
    target.relative_to(ROOT)
    return target


def load_config():
    return json.loads((ROOT / 'config/private-server.json').read_text('utf8'))


def backup(config):
    destination = ROOT / 'snapshots' / datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    destination.mkdir(parents=True)
    for key in ('stateDatabase', 'pageDatabase', 'deckDatabase'):
        source = path(config[key])
        if source.exists():
            target = destination / source.name
            with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as old:
                with sqlite3.connect(target) as new:
                    old.backup(new)
                    if new.execute('pragma integrity_check').fetchone()[0] != 'ok':
                        raise RuntimeError('Save backup integrity failure: ' + key)
    print('Save backup: ' + str(destination), flush=True)


def verify(config, full=False):
    for key in ('clientExecutable', 'pythonExecutable', 'masterdata', 'gachaStatic',
                'preservedPages', 'webRoot', 'assetMapping', 'assetCache',
                'nativeCatalogs', 'nativeHashes', 'starterProfile', 'rawMedia'):
        if not path(config[key]).exists():
            raise RuntimeError('Required package path missing: ' + key)
    import fastapi, uvicorn, sqlalchemy, sqlite3, ssl, UnityPy, brotli, PIL
    configured = path(config['pythonExecutable'])
    actual = Path(sys.executable).resolve()
    packaged = {
        os.path.normcase(str(configured.resolve())),
        os.path.normcase(str(configured.with_name('pythonw.exe').resolve())),
    }
    if os.path.normcase(str(actual)) not in packaged:
        raise RuntimeError('Use the packaged Python runtime')
    for entry in sys.path:
        if entry:
            Path(entry).resolve().relative_to(ROOT)
    for key in ('stateDatabase', 'pageDatabase', 'deckDatabase'):
        f = path(config[key])
        if f.exists():
            with sqlite3.connect(f.as_uri() + '?mode=ro', uri=True) as conn:
                assert conn.execute('pragma integrity_check').fetchone()[0] == 'ok', key
    manifest = json.loads((ROOT / 'reports/files.json').read_text('utf8'))
    total = len(manifest['files'])
    selected = [
        row for row in manifest['files']
        if full or row['path'].startswith(('launcher/', 'config/', 'runtime/'))
        or row['path'] in CRITICAL_MANIFEST_FILES
    ]
    for index, row in enumerate(selected):
        f = path(row['path'])
        if not f.is_file() or f.stat().st_size != row['bytes']:
            raise RuntimeError('Missing or changed package file: ' + row['path'])
        must_hash = (full or row['path'].startswith(('launcher/', 'config/'))
                     or row['path'] in CRITICAL_MANIFEST_FILES)
        if must_hash:
            h = hashlib.sha256()
            with f.open('rb') as stream:
                for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b''):
                    h.update(chunk)
            if h.hexdigest() != row['sha256']:
                raise RuntimeError('Package checksum mismatch: ' + row['path'])
        if index and index % 1000 == 0:
            print('Checking critical files: %s/%s' % (index, len(selected)),
                  flush=True)
    scope = 'all' if full else 'critical'
    print('Package verification passed: %s/%s %s files; external Python disabled.'
          % (len(selected), total, scope), flush=True)


def wait_http(url, process, timeout=60):
    deadline = time.monotonic() + timeout
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError('Local service exited; inspect logs')
        try:
            with opener.open(url, timeout=2) as response:
                if response.status == 200:
                    return
        except OSError:
            pass
        time.sleep(.25)
    raise RuntimeError('Local service startup timed out: ' + url)


def write_ready_file(filename, status, **extra):
    if not filename:
        return
    target = path(filename)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {"status": status, "launcherPid": os.getpid()}
    payload.update(extra)
    temporary = target.with_suffix(target.suffix + '.tmp')
    temporary.write_text(json.dumps(payload), encoding='utf8')
    os.replace(temporary, target)


def process_is_running(pid):
    if os.name != 'nt':
        try:
            os.kill(int(pid), 0)
            return True
        except OSError:
            return False
    import ctypes
    synchronize = 0x00100000
    handle = ctypes.windll.kernel32.OpenProcess(synchronize, False, int(pid))
    if not handle:
        return False
    try:
        return ctypes.windll.kernel32.WaitForSingleObject(handle, 0) == 0x102
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def native_media_is_prepared(source, destination, opening):
    """Fast launch check: verify all records by size and metadata."""
    try:
        records = json.loads((source / 'filelist.json').read_text('utf8'))['Records']
        report = json.loads((ROOT / 'reports/native-media-preparation.json').read_text('utf8'))
        if (report.get('records') != len(records) or
                report.get('mediaDownloadRequired') != 0 or
                not report.get('openingPrepared')):
            return 0
        for record in records:
            rel = Path(record['Path'])
            target = (destination / rel).resolve()
            target.relative_to(destination)
            if not target.is_file() or target.stat().st_size != record['Size']:
                return 0
            info = Path(str(target) + '.info')
            expected = '%s;%s;%s;%s' % (
                record['Type'], record['Hash'], record['Size'],
                ','.join(record['Labels']))
            if (not info.is_file() or
                    info.stat().st_size != len(expected.encode('utf8'))):
                return 0
        if opening is not None:
            opening_record = next(
                row for row in records if row['Path'] == 'Movie/Opening.usm')
            if (not opening.is_file() or
                    opening.stat().st_size != opening_record['Size']):
                return 0
        return len(records)
    except Exception:
        return 0


def start(config, smoke=False, parent_pid=None, ready_file=None):
    ports = (config['pagePort'], config['statePort'], config['debugPort'])
    for port in ports:
        with socket.socket() as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            sock.bind(('127.0.0.1', port))
    if smoke:
        config = dict(config)
        scratch = path('run/smoke/' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        scratch.mkdir(parents=True)
        for key in ('stateDatabase', 'pageDatabase', 'deckDatabase'):
            original = path(config[key])
            destination = scratch / original.name
            if original.exists():
                with sqlite3.connect(original.as_uri() + '?mode=ro', uri=True) as source:
                    with sqlite3.connect(destination) as target:
                        source.backup(target)
            config[key] = str(destination.relative_to(ROOT))
        config['missionClaims'] = str((scratch / 'mission_claims.json').relative_to(ROOT))
    else:
        backup(config)
        from prepare_native_media import prepare
        unity_data = list(path('Client').glob('*_Data'))
        if len(unity_data) != 1:
            raise RuntimeError('Expected one Unity data directory')
        media_source = path(config['rawMedia'])
        media_destination = path('data/native/raw_data')
        opening = unity_data[0] / 'StreamingAssets/LocalMovie/Opening.usm'
        prepared_records = native_media_is_prepared(
            media_source, media_destination, opening)
        if prepared_records:
            print('Packaged media fast check passed: %s records; no full hash.'
                  % prepared_records, flush=True)
        else:
            media_result = prepare(
                media_source, media_destination,
                path('snapshots/media-start-' +
                     datetime.now().strftime('%Y%m%d-%H%M%S-%f')), opening)
            path('reports/native-media-preparation.json').write_text(
                json.dumps(media_result, indent=2), encoding='utf8')
            print('Packaged media repaired; native media download requirement: 0.',
                  flush=True)
    env = os.environ.copy()
    for key in ('PYTHONHOME', 'PYTHONPATH', 'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY'):
        env.pop(key, None)
    env['NO_PROXY'] = '127.0.0.1,localhost'
    env['PYTHONIOENCODING'] = 'utf-8'
    env['CGLS_NATIVE_DATA'] = str(path('data/native'))
    path('data/native').mkdir(parents=True, exist_ok=True)
    state_url = 'http://127.0.0.1:%s' % config['statePort']
    page_url = 'http://127.0.0.1:%s' % config['pagePort']
    children, streams, stop_files = [], [], []
    def spawn(name, args, cwd):
        output = (ROOT / 'logs' / (name + '.log')).open('ab')
        streams.append(output)
        stop_file = path('run/' + name + '-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.stop')
        stop_files.append(stop_file)
        prefix_length = 3 if name == 'state' else 2
        command = [str(path(config['pythonExecutable'])), '-u', str(path('launcher/portable_service.py')),
                   str(stop_file), name] + args[prefix_length:]
        process = subprocess.Popen(command,
                                   cwd=str(cwd), env=env, stdout=output, stderr=output,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        children.append(process)
        return process
    try:
        state = spawn('state', ['-u', '-m', 'cgls.app', '--database', str(path(config['stateDatabase'])),
                      '--port', str(config['statePort']), '--starter-profile', str(path(config['starterProfile'])),
                      '--masterdata', str(path(config['masterdata']))], path('app/stateful_server'))
        wait_http(state_url + '/api/health', state)
        args = ['-u', str(path('app/offline/server.py')), '--port', str(config['pagePort']),
                '--gacha-upstream', state_url, '--gacha-state-url', state_url + '/api/local/page-state',
                '--web-entry', config['webEntry']]
        for flag, key in [('database', 'pageDatabase'), ('deck-database', 'deckDatabase'),
                          ('masterdata', 'masterdata'), ('gacha-static', 'gachaStatic'),
                          ('preserved-pages', 'preservedPages'), ('web-root', 'webRoot'),
                          ('asset-mapping', 'assetMapping'), ('asset-cache', 'assetCache'),
                          ('raw-media', 'rawMedia'), ('native-catalogs', 'nativeCatalogs'),
                          ('native-hashes', 'nativeHashes'), ('mission-claims', 'missionClaims')]:
            args.extend(['--' + flag, str(path(config[key]))])
        page = spawn('page', args, ROOT)
        wait_http(page_url + '/api/state', page)
        print('Local services ready; writing ready marker.', flush=True)
        if os.environ.get('CGLS_EXTENDED_PREFLIGHT') == '1':
            print('Running extended resource preflight.', flush=True)
            for check in [
                ['app/offline/verify_kmf_asset_keys.py', '--state-url', state_url,
                 '--bundle-mapping', str(path(config['assetMapping'])), '--base-url', page_url],
                ['app/offline/verify_network_structure.py',
                 str(path('assets/network-structure/network-structure.json')),
                 '--base-url', page_url],
            ]:
                check[0] = str(path(check[0]))
                completed = subprocess.run(
                    [sys.executable] + check, cwd=str(ROOT), env=env,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    encoding='utf8', errors='replace',
                    creationflags=subprocess.CREATE_NO_WINDOW)
                report = path('logs/' + Path(check[0]).stem + '.json')
                report.write_text(completed.stdout, encoding='utf8')
                completed.check_returncode()
                print('Preflight passed: ' + report.name, flush=True)
        write_ready_file(
            ready_file, 'ready', parentPid=parent_pid,
            statePort=config['statePort'], pagePort=config['pagePort'])
        if smoke:
            print('Service/resource smoke test passed; game was not launched.', flush=True)
            return
        if parent_pid:
            print('Direct client services ready; waiting for parent process.', flush=True)
            while process_is_running(parent_pid):
                if state.poll() is not None or page.poll() is not None:
                    raise RuntimeError('Local service failure')
                time.sleep(1)
            print('Direct client closed.', flush=True)
            return
        game = subprocess.Popen([str(path(config['clientExecutable'])), '-logFile',
                                 str(path('logs/Player.log'))], cwd=str(path('Client')), env=env)
        print('Game started. Close the game normally to stop local services.', flush=True)
        while game.poll() is None:
            if state.poll() is not None or page.poll() is not None:
                print('A service stopped unexpectedly. Close the game and inspect logs.', flush=True)
                game.wait()
                raise RuntimeError('Local service failure')
            time.sleep(1)
        print('Game closed.', flush=True)
    finally:
        # Request orderly shutdown only from services owned by this supervisor.
        for child, stop_file in reversed(list(zip(children, stop_files))):
            if child.poll() is None:
                stop_file.touch()
                try:
                    child.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    print('Service did not stop within 20 seconds; terminating owned process.', flush=True)
                    child.terminate()
                    child.wait(timeout=10)
        for stream in streams:
            stream.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--verify', action='store_true')
    parser.add_argument('--smoke', action='store_true')
    parser.add_argument('--services-only', action='store_true')
    parser.add_argument('--parent-pid', type=int)
    parser.add_argument('--ready-file')
    args = parser.parse_args()
    # OS-held byte lock survives stale lock files but releases on process exit.
    import msvcrt
    lock = (ROOT / 'run/launcher.lock').open('a+b')
    lock.seek(0)
    if lock.read(1) == b'':
        lock.write(b'0'); lock.flush()
    lock.seek(0)
    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    try:
        config = load_config()
        verify(config, full=args.verify)
        if not args.verify:
            if args.services_only and not args.parent_pid:
                raise ValueError('--services-only requires --parent-pid')
            start(config, args.smoke, args.parent_pid, args.ready_file)
    finally:
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        lock.close()


if __name__ == '__main__':
    ready_file_for_error = None
    for _index, _value in enumerate(sys.argv[:-1]):
        if _value == '--ready-file':
            ready_file_for_error = sys.argv[_index + 1]
            break
    try:
        main()
    except Exception as error:
        try:
            write_ready_file(
                ready_file_for_error, 'error', error=str(error))
        except Exception:
            pass
        print('ERROR: ' + str(error), flush=True)
        raise SystemExit(1)
