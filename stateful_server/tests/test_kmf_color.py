import unittest

from cgls.kmf_color import (
    DEFAULT_CUSTOM_COLOR,
    custom_color_fields,
    custom_color_state,
    with_custom_color,
    with_custom_color_enabled,
)


class KmfColorTests(unittest.TestCase):
    def test_legacy_color_is_active_and_unknown_data_is_preserved(self):
        ranks = {
            "first": True,
            "localColor": {"r": 12, "g": 34, "b": 56, "future": "kept"},
        }
        self.assertEqual(custom_color_state(ranks), {
            "enabled": True,
            "r": 12,
            "g": 34,
            "b": 56,
        })

        disabled = with_custom_color_enabled(ranks, False)
        self.assertTrue(disabled["first"])
        self.assertEqual(disabled["localColor"]["future"], "kept")
        self.assertFalse(disabled["localColor"]["enabled"])
        self.assertEqual(custom_color_state(disabled)["r"], 12)

    def test_invalid_persisted_channels_fall_back_without_crashing(self):
        fields = custom_color_fields({"localColor": {
            "r": -1, "g": "invalid", "b": 999, "enabled": False,
        }})
        self.assertFalse(fields["useCustomColor"])
        self.assertEqual(fields["customColorR"], DEFAULT_CUSTOM_COLOR)
        self.assertEqual(fields["customColorG"], DEFAULT_CUSTOM_COLOR)
        self.assertEqual(fields["customColorB"], DEFAULT_CUSTOM_COLOR)
        self.assertTrue(
            with_custom_color([], 1, 2, 3)["localColor"]["enabled"])

    def test_setting_color_reactivates_and_preserves_existing_metadata(self):
        ranks = with_custom_color(
            {"favorite": True, "localColor": {"enabled": False}},
            1, 2, 3, enabled=True,
        )
        self.assertTrue(ranks["favorite"])
        self.assertEqual(ranks["localColor"], {
            "enabled": True, "r": 1, "g": 2, "b": 3,
        })


if __name__ == "__main__":
    unittest.main()
