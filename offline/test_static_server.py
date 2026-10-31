import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from static_server import StaticStore


class StaticTests(unittest.TestCase):
    def test_exact_routes_and_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "bodies").mkdir()
            body = b"<html>offline</html>"
            digest = hashlib.sha256(body).hexdigest()
            (root / "bodies" / digest).write_bytes(body)
            manifest = {
                "entries": [{"source": "chosen", "body": digest,
                             "direct_dependencies_complete": True}],
                "routes": [{"path": "/web/a.js", "rev": "v1", "body": digest}],
                "conflicts": [{"path": "/web/data.json", "rev": None}]
            }
            (root / "routes.json").write_text(json.dumps(manifest))
            store = StaticStore(root, "chosen")
            self.assertEqual(store.resolve("/web/index.html")[1], body)
            self.assertEqual(store.resolve("/web/a.js?rev=v1")[0], 200)
            self.assertEqual(store.resolve("/web/a.js?rev=v2")[0], 404)
            self.assertEqual(store.resolve("/web/data.json")[0], 409)
            self.assertEqual(store.resolve("/api/page/MyPage")[0], 501)
            self.assertEqual(store.resolve("https://example.com/")[0], 400)
            self.assertEqual(store.resolve("/../../secret")[0], 404)
            (root / "bodies" / digest).write_bytes(b"changed")
            with self.assertRaises(ValueError):
                store.resolve("/web/index.html")


if __name__ == "__main__":
    unittest.main()
