import unittest

from verify_kmf_asset_keys import (
    revision_class_for_revision,
    validate_units,
    weapon_bundle_paths,
)


class VerifyKmfAssetKeysTests(unittest.TestCase):
    def setUp(self):
        self.mapping = [
            {
                "id": (
                    "{Zero.Config.Environment.URL}/binary_assets_binary/"
                    "images/knightmareframes/kmf_260401_weapon_%d.bundle"
                ) % revision_class
            }
            for revision_class in range(1, 5)
        ]
        self.bundles = weapon_bundle_paths(self.mapping)

    def test_revision_class_boundaries(self):
        self.assertEqual(
            [revision_class_for_revision(value)
             for value in (0, 2, 3, 5, 6, 8, 9, 12)],
            [1, 1, 2, 2, 3, 3, 4, 4],
        )

    def test_valid_rows_pick_existing_bundles(self):
        result = validate_units({
            "userKnightmareFrameList": [
                {
                    "customizationId": 260401,
                    "revision": 0,
                    "revisionClass": 1,
                },
                {
                    "customizationId": 260401,
                    "revision": 3,
                    "revisionClass": 2,
                },
            ],
        }, self.bundles)
        self.assertEqual(result["errorCount"], 0)
        self.assertEqual(
            [item["bundle"] for item in result["checked"]],
            [
                "kmf_260401_weapon_1.bundle",
                "kmf_260401_weapon_2.bundle",
            ],
        )

    def test_rejects_zero_class_and_missing_bundle(self):
        wrong_class = validate_units({
            "userKnightmareFrameList": [{
                "customizationId": 260401,
                "revision": 0,
                "revisionClass": 0,
            }],
        }, self.bundles)
        self.assertEqual(wrong_class["errorCount"], 1)

        missing = validate_units({
            "userKnightmareFrameList": [{
                "customizationId": 999999,
                "revision": 0,
                "revisionClass": 1,
            }],
        }, self.bundles)
        self.assertEqual(missing["errorCount"], 1)


if __name__ == "__main__":
    unittest.main()
