import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from snapshot_store import import_snapshot, SnapshotStore


class SnapshotTests(unittest.TestCase):
    def test_import_replay_and_integrity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = json.dumps({'gameUser': {'id': 'local-test'}, 'userItemList': []}).encode()
            digest = hashlib.sha256(payload).hexdigest()
            (root / (digest + '.body')).write_bytes(payload)
            (root / 'manifest.json').write_text(json.dumps([
                {'path': '/api/page/MyPage', 'sha256': digest}]))
            target = root / 'save'
            import_snapshot(root, digest, target)
            store = SnapshotStore(target)
            self.assertEqual(store.resolve('/api/page/MyPage')[0], 200)
            self.assertEqual(store.resolve('/api/money/payment')[0], 501)
            for query in ('timeStamp=1234567890',
                          'value=gameUser%2CuserItemList&timeStamp=1234567890'):
                response = store.resolve('/api/page/MyPage?' + query)
                self.assertEqual(response[0], 200)
                self.assertEqual(response[1], store.payload)
            for request_target in (
                'https://example.invalid/api/page/MyPage',
                '//example.invalid/api/page/MyPage',
                '/api/page/MyPage#fragment',
                '/api/page/MyPage?value=gameUser&value=userItemList',
                '/api/page/MyPage?timeStamp=1&timeStamp=2',
                '/api/page/MyPage?timeStamp=abc',
                '/api/page/MyPage?value=',
                '/api/page/MyPage?value=../secret',
                '/api/page/MyPage?unknown=1',
                '/api/page/MyPage?timeStamp',
                '/api/page/MyPage?value=' + 'a' * 8192,
            ):
                with self.subTest(target=request_target[:80]):
                    self.assertEqual(store.resolve(request_target)[0], 400)
            with self.assertRaises(FileExistsError):
                import_snapshot(root, digest, target)
            (target / 'mypage.json').write_text('{}')
            with self.assertRaises(ValueError):
                SnapshotStore(target)


if __name__ == '__main__':
    unittest.main()
