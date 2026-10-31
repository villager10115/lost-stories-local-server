import copy
import unittest

from stage_native_catalogs import local_settings, rewrite_catalog


class NativeCatalogTests(unittest.TestCase):
    def test_rewrite_preserves_encoded_tables_and_source(self):
        source = {"m_InternalIds": ["0#test.bundle"],
                  "m_InternalIdPrefixes": ["{Zero.Config.Environment.URL}/data/"],
                  "m_EntryDataString": "unchanged", "m_ExtraDataString": "unchanged"}
        before = copy.deepcopy(source)
        result, count = rewrite_catalog(source, 18765)
        self.assertEqual(source, before)
        self.assertEqual(count, 1)
        self.assertEqual(result["m_InternalIdPrefixes"], ["http://127.0.0.1:18765/assets/data/"])
        self.assertEqual(result["m_ExtraDataString"], "unchanged")

    def test_unknown_network_and_invalid_port_rejected(self):
        for value in ("https://example.invalid/a", "prefix{Zero.Config.Environment.URL}/a"):
            with self.assertRaises(ValueError):
                rewrite_catalog({"m_InternalIds": [value]}, 18765)
        with self.assertRaises(ValueError):
            rewrite_catalog({}, 0)

    def test_local_settings_removes_remote_and_cache_dependencies(self):
        source = {"m_CatalogLocations": [
            {"m_Keys": ["remote"], "m_InternalId": "https://example.invalid/catalog.hash"},
            {"m_Keys": ["AddressablesMainContentCatalog"],
             "m_InternalId": "{UnityEngine.AddressableAssets.Addressables.RuntimePath}/catalog.json",
             "m_Dependencies": ["remote", "cache"]}]}
        result = local_settings(source)
        self.assertEqual(len(result["m_CatalogLocations"]), 1)
        self.assertEqual(result["m_CatalogLocations"][0]["m_Dependencies"], [])
        self.assertTrue(result["m_DisableCatalogUpdateOnStart"])
        self.assertEqual(len(source["m_CatalogLocations"]), 2)


if __name__ == "__main__":
    unittest.main()
