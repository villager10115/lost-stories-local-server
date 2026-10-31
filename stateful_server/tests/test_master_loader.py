import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from cgls.master_loader import MasterDataRepository


def write_page(root, name, rows):
    body = json.dumps(rows).encode()
    path = root / "pages" / (name + ".static.json")
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(body)
    return {
        "path": "/api/page/" + name,
        "source_sha256": "a" * 64,
        "source_time": "2026-10-18T18:42:41+09:00",
        "file": "pages/" + path.name,
        "counts": {},
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
    }


class MasterLoaderTests(unittest.TestCase):
    def test_loads_and_indexes_core_tables(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pages = {
                "MyPage": {
                    "cardList": [{"cardId": 101}],
                    "charaList": [{"charaId": 101}],
                    "knightmareFrameList": [{"knightmareFrameId": 1001}],
                    "knightmareFrameCustomizeList": [
                        {"knightmareFrameCustomizeId": 100101}
                    ],
                    "itemList": [{"itemId": 1}],
                    "affiliationList": [{"affiliationId": 1}],
                    "backgroundGroupList": [{"backgroundGroupId": 1}],
                    "costumeList": [{"costumeId": 101001}],
                    "levelList": [{"id": 1}],
                },
                "GachaTop": {
                    "gachaScheduleList": [{"id": "g1", "scheduleId": "s1"}],
                    "gachaExchangeList": [{"gachaExchangeId": 1}],
                },
                "ShopTop": {"shopList": [{"shopId": 1}]},
                "QuestTop": {
                    "partList": [{"partId": 1}],
                    "anotherQuestDetailList": [{"anotherQuestDetailId": 1}],
                },
                "MissionTop": {
                    "challengeGroupList": [{"id": 1}],
                    "limitedChallengeGroupList": [{"id": 2}],
                },
            }
            manifest = {"tables": []}
            for name, rows in pages.items():
                manifest["tables"].append(write_page(root, name, rows))
            (root / "manifest.json").write_text(json.dumps(manifest))
            repository = MasterDataRepository(root)
            self.assertEqual(repository.get("cards", 101)["cardId"], 101)
            self.assertEqual(repository.get("gacha_schedules", "g1")["scheduleId"], "s1")
            self.assertEqual(repository.source("MyPage")["source_sha256"], "a" * 64)

    def test_duplicate_id_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            page = {
                "cardList": [{"cardId": 1}, {"cardId": 1}],
                "charaList": [],
                "knightmareFrameList": [],
                "knightmareFrameCustomizeList": [],
                "itemList": [],
                "affiliationList": [],
                "backgroundGroupList": [],
                "costumeList": [],
                "levelList": [],
            }
            manifest = {"tables": [
                write_page(root, "MyPage", page),
                write_page(root, "GachaTop", {
                    "gachaScheduleList": [], "gachaExchangeList": []
                }),
                write_page(root, "ShopTop", {"shopList": []}),
                write_page(root, "QuestTop", {
                    "partList": [], "anotherQuestDetailList": []
                }),
                write_page(root, "MissionTop", {
                    "challengeGroupList": [], "limitedChallengeGroupList": []
                }),
            ]}
            (root / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaises(ValueError):
                MasterDataRepository(root)


if __name__ == "__main__":
    unittest.main()
