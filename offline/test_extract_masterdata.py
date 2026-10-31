import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from extract_masterdata import extract


class ExtractMasterDataTests(unittest.TestCase):
    def test_exports_only_static_tables_with_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / "cache"
            cache.mkdir()
            body = gzip.compress(json.dumps({
                "resultCode": "success",
                "currentTime": "2026-10-18T18:42:41+09:00",
                "cardList": [{"cardId": 1}],
                "charaList": [{"charaId": 1}],
                "affiliationList": [],
                "backgroundGroupList": [],
                "costumeList": [],
                "eventList": [],
                "itemList": [{"itemId": 1}],
                "knightmareFrameCustomizeList": [],
                "knightmareFrameList": [{"knightmareFrameId": 1}],
                "levelList": [],
                "loginBonusCharaList": [],
                "loginBonusList": [],
                "loginBonusTotalList": [],
                "viewIconList": [],
                "userCardList": [{"private": "must not be exported"}],
                "gameUser": {"userId": "must not be exported"},
            }).encode())
            digest = hashlib.sha256(body).hexdigest()
            (cache / (digest + ".body")).write_bytes(body)
            (cache / "manifest.json").write_text(json.dumps([
                {"path": "/api/page/MyPage", "sha256": digest}
            ]))
            output = root / "output"
            result = extract(
                cache, [("/api/page/MyPage", digest)], output
            )
            self.assertEqual(len(result["tables"]), 1)
            data = json.loads(
                (output / "pages" / "MyPage.static.json").read_text()
            )
            self.assertEqual(data["cardList"], [{"cardId": 1}])
            self.assertNotIn("userCardList", data)
            self.assertNotIn("gameUser", data)
            self.assertEqual(result["tables"][0]["source_sha256"], digest)

    def test_rejects_checksum_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / "cache"
            cache.mkdir()
            digest = "0" * 64
            (cache / (digest + ".body")).write_bytes(b"{}")
            (cache / "manifest.json").write_text(json.dumps([
                {"path": "/api/page/MyPage", "sha256": digest}
            ]))
            with self.assertRaises(ValueError):
                extract(cache, [("/api/page/MyPage", digest)], root / "output")


if __name__ == "__main__":
    unittest.main()
