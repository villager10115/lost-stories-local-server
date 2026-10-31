import unittest

from pilot_image_store import PilotImageStore


class PilotImageStoreTests(unittest.TestCase):
    def test_cutin_uses_sprite_bundle(self):
        self.assertEqual(
            PilotImageStore.bundle_route("122001", None, "cutin"),
            "/assets/sprite_assets_sprites/pilot/image/"
            "pilot_122001_cutin.bundle",
        )

    def test_card_art_uses_binary_bundle(self):
        self.assertEqual(
            PilotImageStore.bundle_route("122001", None, "full"),
            "/assets/binary_assets_binary/images/pilots/"
            "pilot_122001_full.bundle",
        )

    def test_unknown_suffix_is_rejected(self):
        store = PilotImageStore(type("Assets", (), {"routes": {}})())
        status, body, _ = store.resolve(
            "/web/image/pilots/pilot_122001_unknown.png"
        )
        self.assertEqual(status, 404)
        self.assertEqual(body, b"Unknown pilot image")


if __name__ == "__main__":
    unittest.main()
