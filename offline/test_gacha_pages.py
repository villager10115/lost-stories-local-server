import json
import tempfile
import unittest
from pathlib import Path

from gacha_pages import GachaPageStore


class FakeAccountPage:
    def page_payload(self):
        return json.dumps({
            "resultCode": "success",
            "gameUser": {"name": "local"},
            "userItemList": [
                {
                    "itemId": "GACHA_TICKET",
                    "environmentId": "COMMON",
                    "quantity": 15,
                    "total": 0,
                    "createdAt": "2026-10-18T19:00:00+08:00",
                },
                {
                    "itemId": "GOLD",
                    "environmentId": "COMMON",
                    "quantity": 100,
                    "total": 0,
                    "createdAt": "2026-10-18T19:00:00+08:00",
                },
            ],
            "userStatusList": [{"id": 1}],
            "userGachaKindList": [{
                "gachaKindId": 1007,
                "gachaKind": {"gachaKindId": 1007},
                "totalCount": 0,
                "stockCount": 0,
            }],
            "userCardList": [{"userCardId": "u1"}],
            "userCharaList": [],
            "userKnightmareFrameList": [],
            "userKnightmareFrameCustomizeList": [],
            "itemList": [{"itemId": "GACHA_TICKET"}],
            "cardList": [{"cardId": 1}],
            "charaList": [],
            "affiliationList": [],
            "knightmareFrameList": [],
            "knightmareFrameCustomizeList": [],
            "charaBirthdayLoginBonusList": [{"charaId": 1}],
            "loginBonusList": [{"id": 1}],
        }).encode("utf-8")


class GachaPageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        (root / "_api_page_GachaTop-test.body").write_text(json.dumps({
            "gachaScheduleList": [{
                "id": 1005,
                "gachaKindList": [
                    {"gachaKindId": 1007},
                    {"gachaKindId": 1008, "beanKind": "RARE10",
                     "needPointKind": "MONEY", "needQuantity": 3000},
                ],
            }],
            "gachaExchangeList": [],
            "userQuestList": [{"questId": 1}],
            "userGachaGroupList": [],
            "userGachaGroupPointList": [],
            "eventList": [],
            "campaignList": [],
            "viewIconList": [],
        }), encoding="utf-8")
        (root / "_api_page_GachaAnimation-test.body").write_text(
            json.dumps({
                "eventList": [],
                "campaignList": [],
                "userDeckList": [{"deckNo": 1}],
                "viewIconList": [],
            }),
            encoding="utf-8",
        )
        (root / "_api_page_GachaResult-test.body").write_text(
            json.dumps({
                "eventList": [],
                "campaignList": [],
                "gachaScheduleList": [],
                "viewIconList": [],
            }),
            encoding="utf-8",
        )
        self.store = GachaPageStore(
            FakeAccountPage(), root, "http://127.0.0.1:1", timeout=0.1
        )
        self.store._local = lambda: {
            "freeSakuradite": 1100,
            "paidSakuradite": 0,
            "gameItems": {"GACHA_TICKET": 13},
            "gachaPoints": [{"gachaScheduleId": 1005, "point": 1}],
            "gachaKinds": [{
                "gachaKindId": 1007,
                "scheduleId": 1005,
                "totalCount": 10,
                "stockCount": 0,
                "lastDrawnOn": "2026-10-18",
            }],
            "cardLimitBreaks": [{"cardId": 303001, "quantity": 15}],
        }

    def tearDown(self):
        self.directory.cleanup()

    def test_top_page_uses_local_ticket_and_currency(self):
        payload = self.store.top_page()
        items = {item["itemId"]: item["quantity"] for item in payload["userItemList"]}
        self.assertEqual(payload["user"]["partId"], 0)
        self.assertEqual(payload["gameUser"]["name"], "local")
        self.assertEqual(items["GACHA_TICKET"], 13)
        self.assertEqual(items["PRESENTED_MONEY"], 1100)
        self.assertEqual(items["MONEY"], 0)
        self.assertEqual(items["GOLD"], 100)

    def test_gacha_top_merges_local_state(self):
        payload = self.store.gacha_top_page()
        self.assertEqual(payload["userQuestList"], [])
        self.assertEqual(payload["userGachaPointList"], [
            {"gachaScheduleId": 1005, "point": 1}
        ])
        self.assertEqual(payload["userCardLimitBreakList"], [
            {"cardId": 303001, "quantity": 15}
        ])
        self.assertEqual(payload["userGachaKindList"][0]["totalCount"], 10)
        self.assertEqual(
            payload["gachaScheduleList"][0]["id"], 1005
        )

    def test_ten_draw_is_zero_cost_only_for_perked_account(self):
        ordinary = self.store.gacha_top_page()
        ordinary_kind = next(
            kind for kind in ordinary["gachaScheduleList"][0]["gachaKindList"]
            if kind["gachaKindId"] == 1008)
        self.assertEqual(ordinary_kind["needQuantity"], 3000)
        self.assertNotIn("localUnlimitedTenPull", ordinary_kind)

        self.store._local = lambda: {
            "freeSakuradite": 0,
            "paidSakuradite": 0,
            "gameItems": {
                "GACHA_TICKET": 0,
                "LOCAL_UNLIMITED_TEN_PULL": 1,
            },
            "gachaPoints": [],
            "gachaKinds": [],
            "cardLimitBreaks": [],
        }
        perked = self.store.gacha_top_page()
        perked_kind = next(
            kind for kind in perked["gachaScheduleList"][0]["gachaKindList"]
            if kind["gachaKindId"] == 1008)
        self.assertEqual(perked_kind["needQuantity"], 0)
        self.assertEqual(perked_kind["needPointKind"], "FREE")
        self.assertIs(perked_kind["localUnlimitedTenPull"], True)

    def test_my_page_skips_native_login_cutscenes(self):
        payload = self.store.my_page()
        self.assertNotIn("charaBirthdayLoginBonusList", payload)
        self.assertNotIn("loginBonusList", payload)
        self.assertIn("gameUser", payload)
        self.assertEqual(payload["user"]["partId"], 0)
        self.assertEqual(payload["roomId"], "")

    def test_page_routes_resolve(self):
        self.assertIn("userDeckList", self.store.resolve("/api/page/GachaAnimation"))
        self.assertIn(
            "gachaScheduleList", self.store.resolve("/api/page/GachaResult")
        )
        self.assertEqual(
            self.store.resolve("/api/page/TopPage")["resultCode"], "success"
        )


if __name__ == "__main__":
    unittest.main()
