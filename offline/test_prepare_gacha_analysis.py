import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from prepare_gacha_analysis import build


class GachaAnalysisTests(unittest.TestCase):
    def test_builds_current_modes_and_historical_variants(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / "cache"
            cache.mkdir()
            bodies = []

            def add(path, value):
                raw = gzip.compress(json.dumps(value).encode())
                digest = hashlib.sha256(raw).hexdigest()
                (cache / (digest + ".body")).write_bytes(raw)
                bodies.append({"path": path, "sha256": digest})

            add("/api/page/GachaTop", {
                "currentTime": "2026-10-18T19:41:50+09:00",
                "gachaScheduleList": [{
                    "id": 1,
                    "scheduleId": 2,
                    "gachaType": "RARE",
                    "enable": True,
                    "gachaKindList": [
                        {"gachaKindId": 1, "beanKind": "RARE", "needPointKind": "MONEY", "needQuantity": 300},
                        {"gachaKindId": 2, "beanKind": "RARE10", "needPointKind": "MONEY", "needQuantity": 3000},
                    ],
                }],
                "userGachaPointList": [],
                "userGachaGroupList": [],
                "userGachaGroupPointList": [],
                "userCardLimitBreakList": [],
            })
            add("/api/page/GachaTop", {
                "currentTime": "2026-10-17T19:41:50+09:00",
                "gachaScheduleList": [{
                    "id": 9,
                    "gachaType": "SELECTABLE_STEPUP",
                    "gachaKindList": [{
                        "gachaKindId": 9,
                        "beanKind": "STEPSELECT10",
                        "needPointKind": "ITEM",
                        "needQuantity": 10,
                    }],
                }],
            })
            add("/api/page/MyPage", {
                "currentTime": "2026-10-18T19:40:16+09:00",
                "userItemList": [],
                "userGachaKindList": [],
            })
            for path in (
                "/web/js/gacha/GachaAnimation.js",
                "/web/js/gacha/GachaTop.js",
                "/web/js/gacha/GachaResult.js",
                "/web/js/view/gacha/GachaBtnView.js",
                "/web/js/view/gacha/GachaSelectablePilotListView.js",
                "/web/js/view/gacha/GachaSelectPilotView.js",
                "/web/template/gacha/GachaProbability.html",
                "/web/template/gacha/GachaSelectPopup.html",
                "/web/template/gacha/GachaAnimation.html",
                "/web/template/gacha/GachaResult.html",
                "/web/css/gacha/GachaTop.css",
                "/web/css/gacha/GachaResult.css",
            ):
                raw = gzip.compress(b"test")
                digest = hashlib.sha256(raw).hexdigest()
                (cache / (digest + ".body")).write_bytes(raw)
                bodies.append({"path": path, "sha256": digest})
            (cache / "manifest.json").write_text(json.dumps(bodies))

            result = build(cache, root / "output")
            self.assertEqual(len(result["gacha_top"]["schedules"]), 1)
            self.assertEqual(
                [mode["draw_count"] for mode in result["draw_modes"]], [1, 10]
            )
            self.assertIn(
                "STEPSELECT10",
                result["observed_historical_values"]["beanKind"],
            )


if __name__ == "__main__":
    unittest.main()
