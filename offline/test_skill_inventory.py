import json
from pathlib import Path
import tempfile
import unittest

from skill_inventory import build, expand_description


class SkillInventoryTests(unittest.TestCase):
    def test_inventory_and_parameter_expansion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "MyPage.static.json"
            source.write_text(json.dumps({
                "cardList": [
                    {
                        "cardId": 1,
                        "cardSkill1": {
                            "cardSkillId": 10,
                            "cardSkillClass": "ATTACK_BUFF",
                            "activateType": "ALL_DAMAGE",
                            "description": "attack %s11",
                            "affector1": {
                                "affectorDetail": {
                                    "affectorCode": "DAMAGE_MULTIPLY_ATTACK"
                                }
                            },
                            "affector1Parameters1": "100",
                        },
                        "cardFeatureList": [{"cardFeatureId": 5}],
                    }
                ],
                "knightmareFrameCustomizeList": [{
                    "knightmareFrameId": 2,
                    "knightmareFrameCustomizeId": 3,
                    "knightmareFrameSkill": {
                        "knightmareFrameSkillId": 20,
                        "knightmareFrameSkillClass": "NONE",
                        "activateType": "KMF_SKILL",
                        "description": "damage %s11",
                        "affector1": {
                            "affectorDetail": {
                                "affectorCode": "DAMAGE_CONSTANT_ATTACK"
                            }
                        },
                        "affector1Parameters1": "5000",
                    },
                }],
            }), encoding="utf-8")
            result = build(source, root / "out")
            self.assertEqual(result["unique_card_skills"], 1)
            self.assertEqual(result["unique_kmf_skills"], 1)
            self.assertEqual(result["unique_feature_ids"], 1)
            self.assertEqual(expand_description(
                {"description": "%s11 damage", "affector1Parameters1": "42"}
            ), "42 damage")

    def test_conflicting_duplicate_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "MyPage.static.json"
            base = {
                "cardSkillId": 10,
                "description": "a",
                "affector1Parameters1": "1",
            }
            changed = dict(base, description="b")
            source.write_text(json.dumps({
                "cardList": [
                    {"cardId": 1, "cardSkill1": base},
                    {"cardId": 2, "cardSkill1": changed},
                ],
                "knightmareFrameCustomizeList": [],
            }), encoding="utf-8")
            with self.assertRaises(ValueError):
                build(source, root / "out")


if __name__ == "__main__":
    unittest.main()
