import http.client
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest

from asset_store import AssetStore
from server import LocalServer


class AssetStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cache = self.root / "cache"
        self.cache.mkdir()
        self.mapping = self.root / "mapping.json"
        self.name = "a" * 32
        self.version = "b" * 32
        self.filename = self.name + "_" + self.version
        self.body = b"synthetic-bundle"
        (self.cache / self.filename).write_bytes(self.body)
        self.row = {
            "id": AssetStore.PREFIX + "data/test.bundle",
            "options": {"m_BundleName": self.name, "m_Hash": self.version,
                        "m_BundleSize": len(self.body)},
            "matching_cache_files": {"literal_bundle_name": self.filename},
        }
        self.mapping.write_text(json.dumps([self.row]), encoding="utf-8")

    def store(self, rows=None):
        if rows is not None:
            self.mapping.write_text(json.dumps(rows), encoding="utf-8")
        return AssetStore(self.mapping, self.cache)

    def test_exact_bytes_and_rejected_targets(self):
        store = self.store()
        self.assertEqual(store.resolve("/assets/data/test.bundle"),
                         (200, self.body, "application/octet-stream"))
        for target in ("https://evil.test/assets/data/test.bundle",
                       "//evil.test/assets/data/test.bundle",
                       "/assets/data/test.bundle?rev=1",
                       "/assets/data/test.bundle#fragment",
                       "/assets/%2e%2e/test.bundle"):
            with self.subTest(target=target):
                self.assertEqual(store.resolve(target)[0], 400)
        self.assertEqual(store.resolve("/assets/../mapping.json")[0], 404)
        self.assertEqual(store.resolve("/assets/missing.bundle")[0], 404)

    def test_native_cache_buster_does_not_select_version(self):
        store = self.store()
        for value in ("0", "-1", "2147483647", "-2147483648"):
            self.assertEqual(store.resolve("/assets/data/test.bundle?hash=" + value),
                             (200, self.body, "application/octet-stream"))
        for query in ("hash=2147483648", "hash=-2147483649", "hash=abc",
                      "hash=1&hash=2", "hash=1&rev=2", "hash=", "hash=01"):
            self.assertEqual(store.resolve("/assets/data/test.bundle?" + query)[0], 400)

    def test_catalog_unicode_path_keeps_exact_identity(self):
        self.row['id'] = AssetStore.PREFIX + 'sprite_assets_ui/sprites/fourthtitle/定着.bundle'
        store = self.store([self.row])
        self.assertEqual(store.resolve('/assets/sprite_assets_ui/sprites/fourthtitle/定着.bundle')[1], self.body)
        self.assertEqual(store.resolve('/assets/sprite_assets_ui/sprites/fourthtitle/%E5%AE%9A%E7%9D%80.bundle')[1], self.body)
        for target in ('/assets/%2e%2e/secret', '/assets/%252e/secret',
                       '/assets/%2fsecret', '/assets/%FF.bundle', '/assets/%QQ.bundle'):
            self.assertEqual(store.resolve(target)[0], 400)

    def test_missing_and_changed_file(self):
        store = self.store()
        path = self.cache / self.filename
        path.write_bytes(b"bad")
        self.assertEqual(store.resolve("/assets/data/test.bundle")[0], 503)
        path.unlink()
        self.assertEqual(store.resolve("/assets/data/test.bundle")[0], 503)

    def test_conflicting_versions(self):
        second = json.loads(json.dumps(self.row))
        second["options"]["m_Hash"] = "c" * 32
        second["matching_cache_files"] = {"literal": self.name + "_" + "c" * 32}
        store = self.store([self.row, second])
        self.assertEqual(store.resolve("/assets/data/test.bundle")[0], 409)
        second["matching_cache_files"] = {}
        store = self.store([self.row, second])
        self.assertEqual(store.resolve("/assets/data/test.bundle")[0], 409)
        store = self.store([self.row, self.row])
        self.assertEqual(store.resolve("/assets/data/test.bundle")[0], 200)

    def test_untrusted_mapping_not_exposed(self):
        for change in (
            {"id": AssetStore.PREFIX + "../private.json"},
            {"matching_cache_files": {"literal": "../private.json"}},
            {"options": {"m_BundleName": self.name, "m_Hash": self.version,
                         "m_BundleSize": True}},
        ):
            with self.subTest(change=change):
                self.assertEqual(self.store([{**self.row, **change}]).routes, {})

    def test_http_resource_and_host_validation(self):
        server = LocalServer(0, self.root / "shop.sqlite",
                             asset_mapping=self.mapping, asset_cache=self.cache)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for headers, expected in (({}, 200), ({"Host": "evil.test"}, 403)):
                conn = http.client.HTTPConnection(*server.server_address, timeout=5)
                try:
                    conn.request("GET", "/assets/data/test.bundle", headers=headers)
                    response = conn.getresponse()
                    body = response.read()
                    self.assertEqual(response.status, expected)
                    if expected == 200:
                        self.assertEqual(body, self.body)
                finally:
                    conn.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_unicode_bundle_and_head_with_catalog_service_enabled(self):
        self.row['id'] = AssetStore.PREFIX + 'fourthtitle/定着.bundle'
        self.mapping.write_text(json.dumps([self.row]), 'utf8')
        catalogs = self.root / 'catalogs'; catalogs.mkdir()
        outputs = {}
        for name in ('catalog.json', 'Binary_catalog.json', 'Json_catalog.json'):
            (catalogs / name).write_bytes(b'{}')
            outputs[name] = hashlib.sha256(b'{}').hexdigest()
        (catalogs / 'manifest.json').write_text(json.dumps({'outputs': outputs}), 'utf8')
        server = LocalServer(0, self.root / 'shop.sqlite', asset_mapping=self.mapping,
                             asset_cache=self.cache, native_catalogs=catalogs)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            for method in ('GET', 'HEAD'):
                conn = http.client.HTTPConnection(*server.server_address, timeout=5)
                conn.request(method, '/assets/fourthtitle/%E5%AE%9A%E7%9D%80.bundle')
                response = conn.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(int(response.getheader('Content-Length')), len(self.body))
                self.assertEqual(response.read(), self.body if method == 'GET' else b'')
                conn.close()
        finally:
            server.shutdown(); server.server_close(); thread.join()

    def test_builtin_shader_name(self):
        self.row["options"]["m_BundleName"] += "_unitybuiltinshaders"
        filename = self.row["options"]["m_BundleName"] + "_" + self.version
        self.row["matching_cache_files"] = {"literal_bundle_name": filename}
        (self.cache / filename).write_bytes(self.body)
        self.assertEqual(self.store([self.row]).resolve("/assets/data/test.bundle")[0], 200)
        for name in ("../escape", self.name + "_unknown", self.name + "_unitybuiltinshaders/evil"):
            self.row["options"]["m_BundleName"] = name
            self.assertEqual(self.store([self.row]).routes, {})

    def test_configuration_pair_required(self):
        with self.assertRaises(ValueError):
            LocalServer(0, self.root / "unused.sqlite", asset_mapping=self.mapping)


if __name__ == "__main__":
    unittest.main()
