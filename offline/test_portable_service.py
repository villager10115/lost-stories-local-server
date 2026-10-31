"""Exercise the actual portable entry point, including lazy body validation."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request


class PortableServiceTests(unittest.TestCase):
    def test_claim_retry_validation_and_restart(self):
        root = Path(__file__).resolve().parents[1]
        environment = os.environ.copy()
        environment['PYTHONPATH'] = os.pathsep.join((
            str(root / 'stateful_server'),
            str(root / 'offline'),
        ))
        service = Path(os.environ.get('PORTABLE_SERVICE_UNDER_TEST',
                                     str(root / 'offline/portable_service.py')))
        fixture = root / 'stateful_server/fixtures/gacha_1005.json'
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            for attempt in range(2):
                with socket.socket() as sock:
                    sock.bind(('127.0.0.1', 0))
                    port = sock.getsockname()[1]
                stop = folder / ('stop%s' % attempt)
                with (folder / 'server.log').open('ab') as log:
                    process = subprocess.Popen([
                        sys.executable, str(service), str(stop), 'state',
                        '--database', str(folder / 'state.sqlite'),
                        '--fixture', str(fixture), '--port', str(port)],
                        stdout=log, stderr=log,
                        env=environment,
                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                    def request(path, body=None):
                        data = None if body is None else json.dumps(body).encode()
                        req = urllib.request.Request(
                            'http://127.0.0.1:%s%s' % (port, path), data=data,
                            headers={'Content-Type': 'application/json'})
                        try:
                            with urllib.request.urlopen(req, timeout=2) as response:
                                return response.status, json.load(response)
                        except urllib.error.HTTPError as error:
                            return error.code, error.read().decode()
                    try:
                        for _ in range(100):
                            if process.poll() is not None:
                                self.fail('Service exited before becoming ready')
                            try:
                                if request('/api/health')[0] == 200:
                                    break
                            except OSError:
                                time.sleep(.1)
                        else:
                            self.fail('Service did not become ready')
                        status, body = request('/api/local/missions/claim', {'scope': 'daily'})
                        self.assertEqual(status, 200, str(body))
                        self.assertEqual(len(body['results']), 2 if attempt == 0 else 0)
                        if attempt == 0:
                            self.assertEqual({r['itemId']: r['quantity'] for r in body['results']},
                                             {'GACHA_MEDAL': 50, 'DAILY_QUEST_DROP_BOOST': 1})
                        self.assertEqual(request('/api/local/missions/claim',
                                                 {'scope': 'daily'})[1]['results'], [])
                        self.assertEqual(request('/api/local/missions/claim',
                                                 {'scope': 'daily', 'quantity': 999})[0], 422)
                        state = request('/api/local/page-state')[1]
                        self.assertEqual(state['gameItems']['GACHA_MEDAL'], 50)
                    finally:
                        stop.touch()
                        process.wait(timeout=15)
                    self.assertEqual(process.returncode, 0)


if __name__ == '__main__':
    unittest.main()
