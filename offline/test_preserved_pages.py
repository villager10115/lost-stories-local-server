import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import brotli

from preserved_pages import PreservedPageStore


class FakeAccountPage:
    def page_payload(self):
        return json.dumps({
            "gameUser": {"name": "local"},
            "user": {"id": "local", "partId": 1, "chapterId": 1},
            "itemList": [{"itemId": "GOLD"}],
            "userItemList": [{"itemId": "GOLD", "quantity": 10}],
        }).encode("utf-8")


class PreservedPageTests(unittest.TestCase):
    def test_compose_pages_use_local_ownership_and_required_collections(self):
        class LocalAccount:
            authoritative_local_state = True

            def page_payload(self):
                return json.dumps({
                    "gameUser": {"name": "local"},
                    "userCardList": [{"userCardId": "owned", "cardId": 1}],
                    "userCardLimitBreakList": [{"cardId": 1, "lbCount": 2}],
                    "userKnightmareFrameList": [{"userKnightmareFrameId": "owned-kmf"}],
                    "userItemList": [{"itemId": "GOLD", "quantity": 10}],
                }).encode()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            body = json.dumps({"resultCode": "success",
                               "userCardList": [{"userCardId": "captured"}]}).encode()
            digest = hashlib.sha256(body).hexdigest()
            (root / (digest + ".body")).write_bytes(body)
            store = PreservedPageStore(root, LocalAccount(),
                selections={"/api/page/ComposeTop": digest})
            for page, collection in (("ComposePilot", "userCardAttributeRankList"),
                                     ("ComposeKmf", "userKnightmareFrameKeyList")):
                with self.subTest(page=page):
                    payload = store.resolve("/api/page/" + page)
                    self.assertEqual(payload["resultCode"], "success")
                    self.assertEqual(payload["userCardList"][0]["userCardId"], "owned")
                    self.assertEqual(payload["userCardLimitBreakList"][0]["lbCount"], 2)
                    self.assertEqual(payload["userItemList"][0]["quantity"], 10)
                    self.assertEqual(payload[collection], [])

    def test_merges_account_and_fills_required_lists(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            captured = {
                "resultCode": "success",
                "currentTime": "2026-10-18T18:43:28+09:00",
                "challengeGroupList": [{"id": 1}],
                "limitedChallengeGroupList": [{"id": 1520}],
                "userDailyChallengeList": [{"challengeId": 2}],
                "userLimitedChallengeList": [
                    {
                        "challengeId": 10,
                        "challenge": {
                            "limitedChallengeGroup": {"id": 1520}
                        },
                    },
                    {
                        "challengeId": 11,
                        "challenge": {
                            "limitedChallengeGroup": {"id": 1521}
                        },
                    },
                ],
            }
            body = brotli.compress(
                json.dumps(captured).encode("utf-8")
            )
            digest = hashlib.sha256(body).hexdigest()
            (root / (digest + ".body")).write_bytes(body)
            store = PreservedPageStore(
                root,
                FakeAccountPage(),
                selections={"/api/page/MissionTop": digest},
            )
            payload = store.resolve("/api/page/MissionTop")
            self.assertEqual(payload["gameUser"]["name"], "local")
            self.assertEqual(payload["challengeGroupList"], [{"id": 1}])
            self.assertEqual(payload["userDailyChallengeList"], [{"challengeId": 2}])
            self.assertEqual(payload["userWeeklyChallengeList"], [])
            self.assertEqual(
                [row["challengeId"] for row in payload["userLimitedChallengeList"]],
                [10],
            )
            self.assertEqual(payload["user"]["partId"], 1)
            self.assertEqual(payload["user"]["chapterId"], 1)
            self.assertEqual(payload["resultCode"], "success")

    def test_rejects_checksum_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            digest = "0" * 64
            (root / (digest + ".body")).write_bytes(b"not-json")
            with self.assertRaises(ValueError):
                PreservedPageStore(
                    root,
                    None,
                    selections={"/api/page/MissionTop": digest},
                )

    def test_activity_pages_merge_local_models_and_required_lists(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cases = {
                "/api/page/RootEntangleTop": {
                    "entangleChallengeQuestList": [{"questId": 961201}],
                    "npcList": [{"npcId": 1}],
                    "gimmickList": [{"gimmickId": 1}],
                },
                "/api/page/EventStoryTop": {
                    "eventList": [{"eventId": 1690, "eventType": "STORY"}],
                    "npcList": [{"npcId": 1}],
                    "gimmickList": [{"gimmickId": 1}],
                },
            }
            selections = {}
            for path, payload in cases.items():
                payload["resultCode"] = "success"
                body = brotli.compress(json.dumps(payload).encode("utf-8"))
                digest = hashlib.sha256(body).hexdigest()
                (root / (digest + ".body")).write_bytes(body)
                selections[path] = digest
            store = PreservedPageStore(root, FakeAccountPage(), selections)
            entangle = store.resolve("/api/page/RootEntangleTop")
            self.assertEqual(entangle["entangleChallengeQuestList"][0]["questId"], 961201)
            self.assertEqual(entangle["userItemList"][0]["quantity"], 10)
            self.assertEqual(entangle["userDailyChallengeList"], [])
            event = store.resolve("/api/page/EventStoryTop")
            self.assertEqual(event["eventList"][0]["eventId"], 1690)
            self.assertEqual(event["userWeeklyChallengeList"], [])

    def test_claims_daily_reward_once_and_persists(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            captured = {
                "resultCode": "success",
                "currentTime": "2026-10-11T12:00:00+09:00",
                "weeklyChallengeCloseAt": "2026-10-18T00:00:00+09:00",
                "userDailyChallengeList": [{
                    "challengeId": 1000009,
                    "challenge": {
                        "count": 1,
                        "presentType": "ITEM",
                        "genericCode": "DAILY_QUEST_DROP_BOOST",
                        "itemNum": 1,
                    },
                    "clearedCount": 1,
                    "receivedAt": "2026-10-10T12:00:00+09:00",
                }],
            }
            body = brotli.compress(json.dumps(captured).encode("utf-8"))
            digest = hashlib.sha256(body).hexdigest()
            (root / (digest + ".body")).write_bytes(body)
            claim_path = root / "claims.json"
            selections = {"/api/page/MissionTop": digest}
            store = PreservedPageStore(
                root,
                None,
                selections=selections,
                claim_state_path=claim_path,
            )
            result = store.claim("daily")
            self.assertEqual(result["results"][0]["itemId"],
                             "DAILY_QUEST_DROP_BOOST")
            self.assertEqual(store.claim("daily")["results"], [])
            reopened = PreservedPageStore(
                root,
                None,
                selections=selections,
                claim_state_path=claim_path,
            )
            payload = reopened.resolve("/api/page/MissionTop")
            self.assertTrue(payload["userDailyChallengeList"][0]["receivedAt"])
            items = {
                item["itemId"]: item["quantity"]
                for item in payload["userItemList"]
            }
            self.assertEqual(items["DAILY_QUEST_DROP_BOOST"], 1)

            # The response must update Backbone's existing models immediately.
            self.assertIn("currentTime", result)
            self.assertIn("userDailyChallengeList", result)
            self.assertIn("userItemList", result)
            from datetime import datetime, timedelta
            next_day = datetime.fromisoformat(payload["currentTime"]) + timedelta(days=1)
            reopened._now = lambda: next_day.isoformat()
            second = reopened.claim("daily")
            self.assertEqual(len(second["results"]), 1)
            self.assertEqual(second["userItemList"][0]["quantity"], 2)
            self.assertEqual(reopened.claim("daily")["results"], [])

    def test_authoritative_account_does_not_inherit_captured_identity(self):
        class LocalAccount(FakeAccountPage):
            authoritative_local_state = True
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            captured = {"resultCode": "success", "gameUser": {"name": "old"},
                        "userShopItemList": [{"id": 99}], "guild": {"id": 11},
                        "guildMemberList": [{"userId": "old"}],
                        "userDailyChallengeList": [{"challengeId": 2}]}
            body = brotli.compress(json.dumps(captured).encode())
            digest = hashlib.sha256(body).hexdigest()
            (root / (digest + ".body")).write_bytes(body)
            store = PreservedPageStore(root, LocalAccount(),
                selections={"/api/page/ShopTop": digest})
            payload = store.resolve("/api/page/ShopTop")
            self.assertEqual(payload["gameUser"]["name"], "local")
            self.assertEqual(payload["userShopItemList"], [])
            self.assertEqual(payload["userDailyChallengeList"], [])
            self.assertNotIn("guild", payload)
            self.assertNotIn("guildMemberList", payload)


if __name__ == "__main__":
    unittest.main()
