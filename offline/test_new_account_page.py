import json
import unittest
from pathlib import Path

from new_account_page import NewAccountPage


MASTERDATA = Path(
    r"D:\LostStories_Private_Client_20261019\assets\masterdata"
)


class FakeNewAccountPage(NewAccountPage):
    def _state(self):
        return {
            "userId": "00000000-0000-0000-0000-000000000000",
            "displayName": "Commander",
            "stamina": 135,
            "maxStamina": 135,
            "gold": 1000,
            "freeSakuradite": 300,
            "paidSakuradite": 0,
            "gameItems": {"GACHA_TICKET": 1},
            "costumes": [{
                "costumeId": 103047,
                "createdAt": "2026-10-31T10:00:00+09:00",
            }],
            "charaBookmarks": {"103": True},
            "cardCostumes": {"card-a": 103047},
            "decks": [{
                "deckNo": 1,
                "name": "Knights1",
                "slots": [
                    {"pilot": "card-a", "kmf": "kmf-a"},
                    {"pilot": "card-b", "kmf": "kmf-b"},
                ],
            }],
            "cardAttributeRanks": [{
                "attribute": "ROOK",
                "level": 17,
                "nextCardAttributeRank": {"id": 18, "exp": 4},
                "exp": 1,
                "createdAt": "2026-10-31T10:00:00+09:00",
            }],
        }

    def _units(self):
        return {
            "userCardList": [
                {
                    "userCardId": "card-a",
                    "cardId": 103004,
                    "level": 1,
                    "experience": 0,
                    "bondsLevel": 0,
                    "bondsPoint": 0,
                },
                {
                    "userCardId": "card-b",
                    "cardId": 113001,
                    "level": 1,
                    "experience": 0,
                    "bondsLevel": 0,
                    "bondsPoint": 0,
                },
            ],
            "userKnightmareFrameList": [
                {
                    "userKnightmareFrameId": "kmf-a",
                    "knightmareFrameId": 2602,
                    "customizationId": 260201,
                    "skillPoint": 0,
                    "revision": 0,
                    "revisionClass": 1,
                },
                {
                    "userKnightmareFrameId": "kmf-b",
                    "knightmareFrameId": 2604,
                    "customizationId": 260401,
                    "skillPoint": 0,
                    "revision": 0,
                    "revisionClass": 1,
                },
            ],
        }


class NewAccountPageTests(unittest.TestCase):
    def setUp(self):
        self.page = FakeNewAccountPage(
            MASTERDATA,
            "http://127.0.0.1:18766/api/local/page-state",
        )

    def test_builds_client_models_from_starter_state(self):
        payload = json.loads(self.page.page_payload().decode("utf-8"))
        self.assertEqual(payload["resultCode"], "success")
        self.assertEqual(payload["gameUser"]["name"], "Commander")
        self.assertEqual(payload["gameUser"]["myPageCardId"], 103004)
        self.assertEqual(payload["user"]["partId"], 6)
        self.assertEqual(payload["user"]["chapterId"], 50)
        self.assertEqual(len(payload["userChapterList"]), 1)
        self.assertEqual(
            payload["userChapterList"][0]["chapter"]["title"],
            "あなたのいない日々",
        )
        self.assertEqual(len(payload["userCardList"]), 2)
        self.assertEqual(len(payload["userKnightmareFrameList"]), 2)
        self.assertEqual(len(payload["userKnightmareFrameCustomizeList"]), 2)
        self.assertEqual(
            {
                row["revisionClass"]
                for row in payload["userKnightmareFrameCustomizeList"]
            },
            {1},
        )
        self.assertEqual(len(payload["userDeckList"]), 1)
        self.assertEqual(payload["userDeckList"][0]["userCardId1"], "card-a")
        self.assertEqual(payload["userDeckList"][0]["userCardId2"], "card-b")
        self.assertEqual(
            payload["userCardAttributeRankList"][0]["nextCardAttributeRank"],
            {"id": 18, "exp": 4},
        )
        self.assertEqual(len(payload["userDailyQuestList"]), 6)
        self.assertEqual(len(payload["userEventExpeditionAreaList"]), 1)
        self.assertEqual(
            payload["userEventExpeditionAreaList"][0]["eventId"],
            1711,
        )
        self.assertEqual(
            {
                row["dailyTypeName"]
                for row in payload["userDailyQuestList"]
            },
            {
                "KMF_FAR",
                "CARD_REVISION_BISHOP_STAR",
                "CARD_REVISION_ROOK_KING",
                "GOLD_CARD_EXP",
                "KMF_NEAR",
                "CARD_REVISION_KNIGHT_QUEEN",
            },
        )
        self.assertEqual(len(payload["userQuestList"]), 30)
        quest_types = {}
        for row in payload["userQuestList"]:
            name = row["quest"]["dailyType"]["name"]
            quest_types[name] = quest_types.get(name, 0) + 1
            self.assertEqual(row["quest"]["dailyType"]["maxClearCount"], 10)
            self.assertEqual(row["quest"]["dailyType"]["maxAdditionalCount"], 10)
            self.assertEqual(row["questStatus"], "OPENED")
            self.assertEqual(row["bestQuestRank"], "NONE")
        self.assertEqual(quest_types, {
            "CARD_REVISION_BISHOP_STAR": 6,
            "CARD_REVISION_KNIGHT_QUEEN": 6,
            "CARD_REVISION_ROOK_KING": 6,
            "GOLD_CARD_EXP": 6,
            "KMF_FAR": 3,
            "KMF_NEAR": 3,
        })
        daily_master = json.loads(
            (MASTERDATA / 'pages' / 'DailyQuestTop.static.json')
            .read_text(encoding='utf-8'))
        enemies = {row['npcId'] for row in daily_master['npcList']}
        item_ids = {row['itemId'] for row in payload['itemList']}
        for row in payload['userQuestList']:
            quest = row['quest']
            self.assertGreater(quest['enemyNum'], 0)
            self.assertTrue(quest['waveIds'])
            self.assertTrue(quest['uniqueEnemyNpcIdList'])
            self.assertTrue(set(quest['uniqueEnemyNpcIdList']) <= enemies)
            self.assertTrue({reward['genericCode'] for reward in
                             quest['questDropLotteryInfoList']} <= item_ids)

        statuses = {
            row["statusId"]: row["point"]
            for row in payload["userStatusList"]
        }
        self.assertEqual(statuses["ACP"], 135)
        self.assertEqual(statuses["MAX_ACP"], 135)
        self.assertGreater(len(payload["cardList"]), 600)
        self.assertGreater(len(payload["knightmareFrameList"]), 200)
        items = {row["itemId"]: row["quantity"] for row in payload["userItemList"]}
        self.assertEqual(items["GOLD"], 1000)
        self.assertEqual(items["PRESENTED_MONEY"], 300)
        self.assertEqual(items["MONEY"], 0)

    def test_shop_exposes_only_working_free_paid_stone_product(self):
        payload = json.loads(self.page.page_payload().decode("utf-8"))
        self.assertEqual(len(payload["localShopList"]), 1)
        shop = payload["localShopList"][0]
        self.assertEqual(shop["shopId"], 99001)
        self.assertEqual(len(shop["shopItemList"]), 3)
        item = shop["shopItemList"][0]
        self.assertEqual(item["genericId"], "MONEY")
        self.assertEqual(item["needNumber"], 0)
        self.assertEqual(item["needItemId"], "PRESENTED_MONEY")
        self.assertEqual(item["consumeType"], "ITEM")
        self.assertEqual(
            payload["localUserShopItemList"][0]["shopItemId"], 990001)

    def test_customization_ids_are_stable(self):
        first = json.loads(self.page.page_payload().decode("utf-8"))
        second = json.loads(self.page.page_payload().decode("utf-8"))
        first_ids = [
            row["userKnightmareFrameCustomizeId"]
            for row in first["userKnightmareFrameCustomizeList"]
        ]
        second_ids = [
            row["userKnightmareFrameCustomizeId"]
            for row in second["userKnightmareFrameCustomizeList"]
        ]
        self.assertEqual(first_ids, second_ids)

    def test_main_story_top_includes_all_preserved_chapters_and_nodes(self):
        payload = json.loads(
            self.page.resolve(
                "/api/page/MainStoryTop"
                "?value=locationList&timeStamp=1792511724163"
            )[1].decode("utf-8")
        )
        self.assertEqual(payload["resultCode"], "success")
        self.assertEqual(len(payload["partList"]), 6)
        self.assertEqual(len(payload["userChapterList"]), 50)
        self.assertEqual(
            payload["userChapterList"][0]["chapter"]["chapterId"],
            50,
        )
        self.assertEqual(len(payload["userQuestList"]), 1640)
        self.assertEqual(len({row["questId"] for row in payload["userQuestList"]}), 1640)
        self.assertEqual({row["questStatus"] for row in payload["userQuestList"]},
                         {"OPENED", "CANDIDATE"})
        self.assertEqual(sum(row["quest"]["onlyStory"] for row in payload["userQuestList"]), 782)
        self.assertEqual({row["chapter"]["partId"] for row in payload["userChapterList"]},
                         {1, 2, 3, 4, 5, 6})
        self.assertEqual(
            payload["userQuestList"][0]["questStatus"],
            "OPENED",
        )
        self.assertTrue(
            all(
                row["clearedAt"] is None
                for row in payload["userQuestList"]
            )
        )
        self.assertEqual(len(payload["locationList"]), 498)
        enemies = {row["npcId"]: row for row in payload["npcList"]}
        weapons = {row["knightmareFrameCustomizeId"] for row in
                   payload["knightmareFrameCustomizeList"]}
        for row in payload["userQuestList"]:
            for npc_id in row["quest"].get("uniqueEnemyNpcIdList", []):
                self.assertIn(npc_id, enemies)
                self.assertIn(enemies[npc_id]["knightmareFrameCustomizeId"], weapons)
        battle_rows = [row for row in payload["userQuestList"]
                       if not row["quest"]["onlyStory"]]
        self.assertTrue(battle_rows)
        self.assertTrue(all(any(drop["genericCode"] == "SKIP_QUEST"
                            for drop in row["quest"].get(
                                "uniqueQuestDropRewardList", []))
                        for row in battle_rows))
        self.assertTrue({row["quest"]["locationId"] for row in payload["userQuestList"]}
                        <= {row["locationId"] for row in payload["locationList"]})
        for location in payload["locationList"]:
            self.assertTrue({"mapDataNo", "x", "y", "imageNo"} <= location.keys())

    def test_main_story_unlock_marks_required_successors_as_new(self):
        state = {"userQuestList": [{
            "questId": 101103, "questStatus": "CLEARED",
            "bestQuestRank": "S"}]}
        rows = self.page._main_story_quests(
            "2026-10-30T12:00:00+09:00", state)
        by_id = {row["questId"]: row for row in rows}
        for quest_id in (101003, 101004, 101104):
            with self.subTest(questId=quest_id):
                self.assertEqual(by_id[quest_id]["questStatus"], "OPENED")
                self.assertTrue(by_id[quest_id]["isNew"])
        self.assertEqual(by_id[101105]["questStatus"], "CANDIDATE")
        self.assertFalse(by_id[101105]["isNew"])
        self.assertEqual(by_id[101106]["questStatus"], "CANDIDATE")
        self.assertFalse(by_id[101106]["isNew"])

    def test_later_clear_closes_missing_main_story_prerequisite_chain(self):
        state = {"userQuestList": [{
            "questId": 101105, "questStatus": "CLEARED",
            "bestQuestRank": "S",
        }]}
        rows = self.page._main_story_quests(
            "2026-10-30T12:00:00+09:00", state)
        by_id = {row["questId"]: row for row in rows}
        # A later clear is evidence that missing historical prerequisites were
        # satisfied, but it must not fabricate a CLEARED row for them.
        self.assertEqual(by_id[101103]["questStatus"], "OPENED")
        for quest_id in (101003, 101004):
            with self.subTest(questId=quest_id):
                self.assertEqual(by_id[quest_id]["questStatus"], "OPENED")
                self.assertTrue(by_id[quest_id]["isNew"])
        self.assertEqual(by_id[101104]["questStatus"], "OPENED")
        self.assertFalse(by_id[101104]["isNew"])
        self.assertEqual(by_id[101105]["questStatus"], "CLEARED")
        self.assertFalse(by_id[101105]["isNew"])
        self.assertEqual(by_id[101106]["questStatus"], "OPENED")
        self.assertTrue(by_id[101106]["isNew"])
        self.assertEqual(by_id[101107]["questStatus"], "CANDIDATE")
        self.assertFalse(by_id[101107]["isNew"])

    def test_cleared_story_behind_save_advances_frontier_to_101121(self):
        state = {
            "userQuestList": [{
                "questId": 101105, "questStatus": "CLEARED",
                "bestQuestRank": "S",
            }],
            "userStoryList": [{
                "questId": 101018, "questStatus": "CLEARED",
            }],
        }
        rows = self.page._main_story_quests(
            "2026-10-31T00:00:00+09:00", state)
        by_id = {row["questId"]: row for row in rows}
        self.assertEqual(by_id[101120]["questStatus"], "OPENED")
        self.assertFalse(by_id[101120]["isNew"])
        self.assertEqual(by_id[101121]["questStatus"], "OPENED")
        self.assertTrue(by_id[101121]["isNew"])
        self.assertEqual(by_id[101122]["questStatus"], "CANDIDATE")
        self.assertFalse(by_id[101122]["isNew"])

    def test_main_story_sibling_remains_new_after_one_story_is_watched(self):
        state = {"userStoryList": [
            {"questId": 101103, "questStatus": "CLEARED"},
            {"questId": 101003, "questStatus": "CLEARED", "isNew": False},
        ]}
        rows = self.page._main_story_quests(
            "2026-10-30T12:00:00+09:00", state)
        by_id = {row["questId"]: row for row in rows}
        self.assertEqual(by_id[101003]["questStatus"], "CLEARED")
        self.assertFalse(by_id[101003]["isNew"])
        self.assertTrue(by_id[101004]["isNew"])
        self.assertTrue(by_id[101104]["isNew"])

    def test_main_story_extra_condition_does_not_hide_downloaded_stage(self):
        rows = self.page._main_story_quests(
            "2026-10-30T12:00:00+09:00", {})
        by_id = {row["questId"]: row for row in rows}
        self.assertEqual(by_id[417201]["questStatus"], "CANDIDATE")
        self.assertIn(417201, by_id)

    def test_main_story_catalog_does_not_replace_saved_progress(self):
        state = {"userQuestList": [{"questId": 418101, "questStatus": "CLEARED",
                 "bestQuestRank": "S", "clearedAt": "2026-10-21T15:00:00+09:00",
                 "clearedMission1": True, "quest": {"name": "not a static definition"}}]}
        before = json.dumps(self.page.main_story_catalog, sort_keys=True)
        rows = self.page._main_story_quests("2026-10-21T16:00:00+09:00", state)
        saved = next(row for row in rows if row["questId"] == 418101)
        self.assertEqual(saved["questStatus"], "CLEARED")
        self.assertEqual(saved["bestQuestRank"], "S")
        self.assertTrue(saved["clearedMission1"])
        self.assertEqual(saved["quest"]["name"], "7 - 1")
        self.assertEqual(json.dumps(self.page.main_story_catalog, sort_keys=True), before)

    def test_tutorial_quest_is_visible_only_during_tu0401(self):
        now = "2026-10-30T12:00:00+09:00"
        active = self.page._main_story_quests(now, {"tutorialId": "TU0401"})
        self.assertEqual(len(active), 1641)
        tutorial = next(row for row in active if row["questId"] == 1000)
        self.assertEqual(tutorial["quest"]["mapDataNo"], 1010005)
        self.assertEqual(tutorial["quest"]["activeTutorialId"], "TU0401")
        finished = self.page._main_story_quests(now, {"tutorialId": "TU0500"})
        self.assertEqual(len(finished), 1640)
        self.assertNotIn(1000, {row["questId"] for row in finished})

    def test_activity_page_payloads_use_the_unified_battle_catalog(self):
        root = json.loads(self.page.resolve(
            "/api/page/RootEntangleTop")[1].decode("utf-8"))
        root_types = {row["quest"]["questType"]
                      for row in root["userQuestList"]}
        self.assertEqual(root_types, {"ENTANGLE", "ENTANGLE_CHALLENGE"})
        self.assertEqual(len(root["userQuestList"]), 134)
        event = json.loads(self.page.resolve(
            "/api/page/EventStoryTop")[1].decode("utf-8"))
        self.assertEqual({row["quest"]["questType"]
                          for row in event["userQuestList"]}, {"EVENT"})
        self.assertEqual(len(event["userQuestList"]), 2)
        cases = {
            "/api/page/ChallengeQuestTop": ("CHALLENGE", 546),
            "/api/page/ExpeditionTop": ("EXPEDITION", 2241),
            "/api/page/SideQuestTop": ({"SIDE", "SIDE_CHALLENGE"}, 181),
            "/api/page/EventMultiFrontTop": ("EVENT", 2),
            "/api/page/EventHighStrategicCommandTop": (
                "STRATEGIC_COMMAND", 30),
        }
        for path, (quest_type, count) in cases.items():
            with self.subTest(path=path):
                body = json.loads(self.page.resolve(path)[1].decode("utf-8"))
                self.assertEqual(len(body["userQuestList"]), count)
                self.assertTrue(body["npcList"])
                self.assertTrue(body["gimmickList"])
                expected_types = ({quest_type}
                                  if isinstance(quest_type, str)
                                  else quest_type)
                self.assertEqual(
                    {row["quest"]["questType"]
                     for row in body["userQuestList"]}, expected_types)


    def test_costume_state_reaches_client_models(self):
        payload = json.loads(self.page.page_payload().decode("utf-8"))
        self.assertEqual(payload["userCostumeList"], [{
            "costumeId": 103047,
            "createdAt": "2026-10-31T10:00:00+09:00",
        }])
        chara = next(
            row for row in payload["userCharaList"]
            if row["charaId"] == 103
        )
        self.assertTrue(chara["bookmarkCostume"])
        card = next(
            row for row in payload["userCardList"]
            if row["userCardId"] == "card-a"
        )
        self.assertEqual(card["costumeId"], 103047)

if __name__ == "__main__":
    unittest.main()
