import json
import tempfile
import unittest
from pathlib import Path

from extract_quest_battle_catalog import extract


class QuestBattleCatalogExtractionTests(unittest.TestCase):
    def test_extracts_every_battle_type_and_rejects_conflicts(self):
        response = {
            "resultCode": "success",
            "currentTime": "2026-10-30T12:00:00+09:00",
            "userQuestList": [
                {"questId": "ignored", "quest": {"questId": "bad"}},
                {"quest": {"questId": 101101, "questType": "MAIN"}},
                {"quest": {"questId": 810101, "questType": "ANOTHER_CHARA"}},
                {"quest": {"questId": 930101, "questType": "SIDE", "onlyStory": True}},
                {"quest": {"questId": 101101, "questType": "MAIN"}},
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "GachaTop.body"
            source.write_text(json.dumps(response), encoding="utf-8")
            payload = extract(source)
        self.assertEqual(payload["counts"]["all"], 3)
        self.assertEqual(payload["counts"]["battles"], 2)
        self.assertEqual(payload["counts"]["storyOnly"], 1)
        self.assertEqual(payload["counts"]["battlesByQuestType"],
                         {"ANOTHER_CHARA": 1, "MAIN": 1})

        response["userQuestList"].append({
            "quest": {"questId": 101101, "questType": "CHALLENGE"}
        })
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "GachaTop.body"
            source.write_text(json.dumps(response), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Conflicting quest"):
                extract(source)


if __name__ == "__main__":
    unittest.main()
