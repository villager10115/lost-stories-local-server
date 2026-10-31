import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from native_catalog_store import NativeCatalogStore


class NativeCatalogStoreTests(unittest.TestCase):
    def test_serves_staged_catalogs_and_local_hashes(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            stage = root / "stage"
            stage.mkdir()
            outputs = {}
            for name in ("catalog.json", "Binary_catalog.json", "Json_catalog.json"):
                body = (name + "-body").encode("utf-8")
                (stage / name).write_bytes(body)
                outputs[name] = hashlib.sha256(body).hexdigest()
            (stage / "manifest.json").write_text(
                json.dumps({"outputs": outputs}), encoding="utf-8"
            )

            hash_dir = root / "hashes"
            hash_dir.mkdir()
            for name in (
                "catalog.hash",
                "Binary_catalog.hash",
                "Json_catalog.hash",
            ):
                (hash_dir / name).write_bytes(b"abc123")

            store = NativeCatalogStore(stage, hash_dir)
            status, body, content_type = store.resolve("/assets/catalog.hash")
            self.assertEqual((status, body), (200, b"abc123"))
            self.assertEqual(content_type, "text/plain")

            status, body, _ = store.resolve("/assets/catalog.json")
            self.assertEqual(status, 200)
            self.assertEqual(body, b"catalog.json-body")

            status, _, _ = store.resolve("/assets/missing.json")
            self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
