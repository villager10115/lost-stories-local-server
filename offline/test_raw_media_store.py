import hashlib
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest

from raw_media_store import RawMediaStore
from server import LocalServer


class RawMediaTests(unittest.TestCase):
    def test_native_filelist_download_and_wrong_version(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / 'Sound').mkdir()
            body = b'preserved-media-example'; path = root / 'Sound/sample.acb'
            path.write_bytes(body)
            record = {'Type': 2, 'Path': 'Sound/sample.acb', 'Hash': hashlib.sha1(body).hexdigest().upper(),
                      'Size': len(body), 'Labels': ['default', 'voice']}
            (root / 'filelist.json').write_text(json.dumps({'Records': [record]}), 'utf8')
            server = LocalServer(0, root / 'temporary.sqlite', raw_media=root)
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            try:
                conn = http.client.HTTPConnection(*server.server_address, timeout=5)
                conn.request('GET', '/assets/filelist.json?time=123'); response = conn.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(json.loads(response.read()), {'Records': [record]})
                conn.request('GET', '/assets/Sound/sample.acb?hash=' + record['Hash'])
                response = conn.getresponse(); self.assertEqual(response.status, 200)
                self.assertEqual(response.read(), body)
                conn.close()
            finally:
                server.shutdown(); thread.join(); server.server_close()
            store = RawMediaStore(root)
            spaced = dict(record, Path='Sound/sample voice.acb')
            (root / 'Sound/sample voice.acb').write_bytes(body)
            (root / 'filelist.json').write_text(json.dumps({'Records': [record, spaced]}), 'utf8')
            store = RawMediaStore(root)
            self.assertEqual(store.resolve('/assets/Sound/sample%20voice.acb')[1], body)
            self.assertEqual(store.resolve('/assets/Sound/%2e%2e/secret')[0], 400)
            self.assertEqual(store.resolve('/assets/Sound/sample.acb?hash=wrong')[0], 409)
            self.assertEqual(store.resolve('/assets/Sound/../secret')[0], 400)
            self.assertEqual(store.resolve('/assets/Sound/unknown.acb')[0], 404)
            path.write_bytes(b'x' * len(body))
            self.assertEqual(store.resolve('/assets/Sound/sample.acb')[0], 503)
            path.unlink()
            self.assertEqual(store.resolve('/assets/Sound/sample.acb')[0], 503)


if __name__ == '__main__':
    unittest.main()
