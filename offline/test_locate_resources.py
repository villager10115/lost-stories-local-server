import hashlib
import unittest
from locate_resources import catalog_keys


class ResourceLocatorTests(unittest.TestCase):
    def test_all_known_cache_key_forms(self):
        row = {"id": "/assets/font.bundle", "options": {"m_BundleName": "bundle"}}
        keys = catalog_keys(row)
        self.assertIn("bundle", keys)
        for value in ("bundle", "/assets/font.bundle", "font.bundle"):
            self.assertIn(hashlib.md5(value.encode()).hexdigest(), keys)

    def test_missing_options(self):
        self.assertEqual(len(catalog_keys({"id": "asset", "options": None})), 1)


if __name__ == "__main__":
    unittest.main()
