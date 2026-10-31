import json
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from cgls.app import create_app
from cgls.bootstrap import StarterProfile
from cgls.gacha_service import UNLIMITED_TEN_PERK_ITEM_ID, ensure_local_user
from cgls.missions import DAILY_LOGIN_DEFINITIONS
from cgls.models import User, UserGameItem, UserGachaPoint, UserKmf


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "gacha_1005.json"


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.database = Path(self.directory.name) / "api.sqlite"
        self.app = create_app(
            self.database,
            FIXTURE,
            masterdata_dir=Path(__file__).parent / "masterdata",
        )
        self.client = TestClient(self.app)
        self.client.__enter__()

        session = self.app.state.session_factory()
        user = ensure_local_user(session)
        user.wallet.free_sakuradite = 1100
        ticket = session.get(UserGameItem, (user.id, "GACHA_TICKET"))
        if ticket is None:
            ticket = UserGameItem(
                user_id=user.id,
                item_id="GACHA_TICKET",
                quantity=13,
            )
            session.add(ticket)
        else:
            ticket.quantity = 13
        session.commit()
        session.close()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.directory.cleanup()

    def test_health_and_probability(self):
        health = self.client.get("/api/health")
        self.assertEqual(health.status_code, 200)
        self.assertTrue(health.json()["localOnly"])

        probability = self.client.post(
            "/api/gacha/probability",
            json={"gachaScheduleId": 1005},
        )
        self.assertEqual(probability.status_code, 200)
        body = probability.json()
        self.assertEqual(len(body["gachaProbabilityList"]), 2)
        self.assertEqual(len(body["gachaDrawList"]), 227)

    def test_local_save_status_does_not_create_an_account(self):
        empty_path = Path(self.directory.name) / "save-status.sqlite"
        empty_app = create_app(empty_path, FIXTURE)
        with TestClient(empty_app) as client:
            before = client.get("/api/local/save-status")
            self.assertEqual(before.status_code, 200)
            self.assertFalse(before.json()["hasSave"])
            self.assertFalse(before.json()["hadSaveAtStart"])
            with empty_app.state.session_factory() as session:
                self.assertIsNone(session.query(User).first())

            client.get("/api/local/page-state")
            after = client.get("/api/local/save-status")
            self.assertEqual(after.status_code, 200)
            body = after.json()
            self.assertTrue(body["hasSave"])
            self.assertFalse(body["hadSaveAtStart"])
            self.assertEqual(body["displayName"], "Commander")
            self.assertEqual(body["tutorialId"], "TU0401")

        restarted_app = create_app(empty_path, FIXTURE)
        with TestClient(restarted_app) as client:
            restarted = client.get("/api/local/save-status").json()
            self.assertTrue(restarted["hasSave"])
            self.assertTrue(restarted["hadSaveAtStart"])

    def test_four_star_rate_override_is_visible(self):
        response = self.client.post(
            "/api/gacha/probability",
            json={"gachaScheduleId": 1005},
        )
        self.assertEqual(response.status_code, 200)
        probability_set = response.json()["gachaProbabilityList"][0]
        four_star_percent = sum(
            float(item["probability"])
            for item in probability_set["cardProbabilityList"]
            if int(item["gachaResult"]["rarity"]) == 4
        )
        self.assertAlmostEqual(four_star_percent, 6.0, places=3)

    def test_ten_draw_updates_local_state_and_log(self):
        response = self.client.post(
            "/api/gacha/draw",
            json={
                "gachaScheduleId": 1005,
                "gachaBeanKind": "RARE10",
            },
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body["gachaAnimation"]["cardList"]), 10)
        items = {
            item["itemId"]: item["quantity"]
            for item in body["userItemList"]
        }
        self.assertEqual(items["GACHA_TICKET"], 3)

        state = self.client.get("/api/local/state").json()
        self.assertEqual(state["gameItems"]["GACHA_TICKET"], 3)
        self.assertEqual(state["drawLogs"], 1)

    def test_money_schedule_draw_uses_free_sakuradite(self):
        self.client.post(
            "/api/local/dev-state",
            json={"free_sakuradite": 5000},
        )
        response = self.client.post(
            "/api/gacha/draw",
            json={
                "gachaScheduleId": 1001,
                "gachaBeanKind": "RARE10",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            len(response.json()["gachaAnimation"]["cardList"]), 10)
        state = self.client.get("/api/local/state").json()
        self.assertEqual(state["freeSakuradite"], 2000)

    def test_selectable_gacha_pickup_is_persisted(self):
        response = self.client.post(
            "/api/gacha/selectCard",
            json={
                "gachaScheduleId": 1796,
                "cardIds": [101011, 101053],
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["gachaGroupId"], 130)
        state = self.client.get("/api/local/page-state").json()
        self.assertEqual(state["userGachaGroupList"], [{
            "gachaScheduleId": 1796,
            "gachaGroupId": 130,
            "cardIds": [101011, 101053],
        }])

        invalid = self.client.post(
            "/api/gacha/selectCard",
            json={
                "gachaScheduleId": 1796,
                "cardIds": [101011],
            },
        )
        self.assertEqual(invalid.status_code, 400)

        captured_catalog = self.client.post(
            "/api/gacha/selectCard",
            json={"gachaScheduleId": 1795, "cardIds": [101003, 101007]},
        )
        self.assertEqual(captured_catalog.status_code, 200, captured_catalog.text)
        self.assertEqual(captured_catalog.json()["gachaGroupId"], 129)

    def test_selectable_schedules_can_draw_single_and_free_ten(self):
        session = self.app.state.session_factory()
        user = ensure_local_user(session)
        session.add(
            UserGameItem(
                user_id=user.id,
                item_id=UNLIMITED_TEN_PERK_ITEM_ID,
                quantity=1,
            )
        )
        session.commit()
        session.close()

        single = self.client.post(
            "/api/gacha/draw",
            json={"gachaScheduleId": 1795, "gachaBeanKind": "SELECTABLE"},
        )
        self.assertEqual(single.status_code, 200, single.text)
        self.assertEqual(
            len(single.json()["gachaAnimation"]["cardList"]), 1
        )

        ten = self.client.post(
            "/api/gacha/draw",
            json={"gachaScheduleId": 1796, "gachaBeanKind": "SELECTABLE10"},
        )
        self.assertEqual(ten.status_code, 200, ten.text)
        self.assertEqual(
            len(ten.json()["gachaAnimation"]["cardList"]), 10
        )

    def test_gacha_exchange_deducts_points_and_grants_card(self):
        session = self.app.state.session_factory()
        user = ensure_local_user(session)
        point = session.get(UserGachaPoint, (user.id, 1796))
        if point is None:
            point = UserGachaPoint(
                user_id=user.id,
                gacha_schedule_id=1796,
                point=200,
            )
            session.add(point)
        else:
            point.point = 200
        session.commit()
        session.close()

        response = self.client.post(
            "/api/gacha/exchange",
            json={"gachaExchangeId": 1638, "num": 1},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["resultCode"], "success")
        self.assertEqual(body["userGachaPointList"][0]["point"], 0)
        units = self.client.get("/api/local/units").json()
        self.assertIn(101011, [
            row["cardId"] for row in units["userCardList"]
        ])

        replay = self.client.post(
            "/api/gacha/exchange",
            json={"gachaExchangeId": 1638, "num": 1},
        )
        self.assertEqual(replay.status_code, 400)

    def test_page_state_exposes_local_items_and_limits(self):
        response = self.client.get("/api/local/page-state")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["freeSakuradite"], 1100)
        self.assertEqual(body["gameItems"]["GACHA_TICKET"], 13)
        self.assertIn("gachaPoints", body)
        self.assertIn("gachaKinds", body)
        self.assertIn("cardLimitBreaks", body)

    def test_task_catalog_populates_all_mission_lists(self):
        list_keys = (
            "userDailyChallengeList",
            "userWeeklyChallengeList",
            "userTotalChallengeList",
            "userBeginnerChallengeList",
            "userLimitedChallengeList",
            "userSideTotalChallengeList",
            "userEntangleTotalChallengeList",
        )
        tasks = []
        for index, list_key in enumerate(list_keys, start=1):
            challenge_id = (
                1000013
                if list_key == "userWeeklyChallengeList"
                else 9000000 + index
            )
            tasks.append({
                "category": list_key.removeprefix("user").removesuffix(
                    "ChallengeList").lower(),
                "listKey": list_key,
                "challengeId": challenge_id,
                "groupId": index,
                "bean": "LOGIN",
                "parameter": "",
                "count": 1,
                "displayName": "Task %d" % index,
                "rewardComment": "Reward %d" % index,
                "presentType": "ITEM",
                "itemId": "GOLD",
                "itemNum": index,
                "sortKey": index,
                "challengeGroup": {
                    "id": index,
                    "kind": list_key,
                    "sortKey": index,
                },
            })

        with tempfile.TemporaryDirectory() as directory:
            masterdata = Path(directory)
            (masterdata / "task-catalog.json").write_text(
                json.dumps({"tasks": tasks}),
                encoding="utf-8",
            )
            app = create_app(
                Path(directory) / "tasks.sqlite",
                FIXTURE,
                masterdata_dir=masterdata,
            )
            with TestClient(app) as client:
                page = client.get("/api/local/page-state").json()

        self.assertGreaterEqual(
            len(page["userDailyChallengeList"]),
            len(DAILY_LOGIN_DEFINITIONS),
        )
        for list_key in list_keys[1:]:
            self.assertEqual(len(page[list_key]), 1)
            self.assertEqual(
                page[list_key][0]["challenge"]["displayName"],
                "Task %d" % (list_keys.index(list_key) + 1),
            )
            self.assertEqual(
                page[list_key][0]["challenge"]["sortKey"],
                list_keys.index(list_key) + 1,
            )
            self.assertEqual(page[list_key][0]["clearedCount"], 0)

    def test_present_box_grant_and_receive(self):
        grant = self.client.post(
            "/api/local/presents/grant",
            json={
                "itemId": "PRESENTED_MONEY",
                "quantity": 10000,
                "presentComment": "local test",
            },
        )
        self.assertEqual(grant.status_code, 200)
        self.assertEqual(grant.json()["presentCount"], 1)

        listing = self.client.post(
            "/api/page/PresentList", json={"page": 1})
        self.assertEqual(listing.status_code, 200)
        present = listing.json()["presentList"][0]
        self.assertEqual(present["itemId"], "PRESENTED_MONEY")
        self.assertEqual(present["quantity"], 10000)

        receipt = self.client.post(
            "/api/present/receive",
            json={"presentIds": [present["id"]]},
        )
        self.assertEqual(receipt.status_code, 200)
        self.assertEqual(receipt.json()["freeSakuradite"], 11100)

        state = self.client.get("/api/local/state").json()
        self.assertEqual(state["freeSakuradite"], 11100)
        self.assertEqual(state["presentCount"], 0)

        history = self.client.post(
            "/api/page/PresentHistory", json={"page": 1})
        self.assertEqual(history.status_code, 200)
        self.assertEqual(history.json()["presentCount"], 1)

    def test_local_units_exposes_drawn_pilots_and_kmfs(self):
        empty = self.client.get("/api/local/units")
        self.assertEqual(empty.status_code, 200)
        self.assertEqual(len(empty.json()["userCardList"]), 2)
        self.assertEqual(len(empty.json()["userKnightmareFrameList"]), 2)
        self.assertEqual(len(empty.json()["userDeckList"]), 1)

        draw = self.client.post(
            "/api/gacha/draw",
            json={
                "gachaScheduleId": 1005,
                "gachaBeanKind": "RARE10",
            },
        )
        self.assertEqual(draw.status_code, 200)

        response = self.client.get("/api/local/units")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertGreater(len(body["userCardList"]), 2)
        self.assertTrue(all(
            item["userCardId"] and item["cardId"]
            for item in body["userCardList"]
        ))
        self.assertTrue(all(
            item["userKnightmareFrameId"] and item["knightmareFrameId"]
            for item in body["userKnightmareFrameList"]
        ))
        self.assertTrue(all(
            item["revisionClass"] >= 1
            for item in body["userKnightmareFrameList"]
        ))

    def test_kmf_storage_and_local_color_are_persisted(self):
        units = self.client.get("/api/local/units").json()
        kmf = units["userKnightmareFrameList"][0]
        user_kmf_id = kmf["userKnightmareFrameId"]
        with self.app.state.session_factory() as session:
            row = session.query(UserKmf).filter_by(
                user_kmf_id=user_kmf_id).one()
            row.upgrade_ranks = {"first": True, "other": 7}
            session.commit()

        stored = self.client.post("/api/local/kmf/storage", json={
            "userKmfId": user_kmf_id,
            "isInStorage": True,
        })
        self.assertEqual(stored.status_code, 200, stored.text)
        self.assertTrue(
            stored.json()["userKnightmareFrameList"][0]["isInStorage"])

        colored = self.client.post("/api/local/kmf/color", json={
            "userKmfId": user_kmf_id,
            "red": 12,
            "green": 34,
            "blue": 56,
        })
        self.assertEqual(colored.status_code, 200, colored.text)
        row = colored.json()["userKnightmareFrameList"][0]
        self.assertTrue(row["useCustomColor"])
        self.assertEqual(
            (row["customColorR"], row["customColorG"], row["customColorB"]),
            (12, 34, 56),
        )
        with self.app.state.session_factory() as session:
            ranks = session.query(UserKmf).filter_by(
                user_kmf_id=user_kmf_id).one().upgrade_ranks
            self.assertTrue(ranks["first"])
            self.assertEqual(ranks["other"], 7)

        official = self.client.post("/api/knightmareFrame/color", json={
            "userKnightmareFrameId": user_kmf_id,
            "customColorR": 91,
            "customColorG": 92,
            "customColorB": 93,
        })
        self.assertEqual(official.status_code, 200, official.text)
        self.assertEqual(
            official.json()["userKnightmareFrameList"][0]["customColorR"],
            91,
        )

        default_color = self.client.post(
            "/api/knightmareFrame/notUseColor",
            json={"userKnightmareFrameId": user_kmf_id},
        )
        self.assertEqual(
            default_color.status_code, 200, default_color.text)
        default_row = default_color.json()["userKnightmareFrameList"][0]
        self.assertFalse(default_row["useCustomColor"])
        self.assertEqual(default_row["customColorB"], 93)

        use_color = self.client.post(
            "/api/knightmareFrame/useColor",
            json={"userKnightmareFrameId": user_kmf_id},
        )
        self.assertEqual(use_color.status_code, 200, use_color.text)
        self.assertTrue(
            use_color.json()["userKnightmareFrameList"][0][
                "useCustomColor"])

        self.client.__exit__(None, None, None)
        restarted_app = create_app(
            self.database,
            FIXTURE,
            masterdata_dir=Path(__file__).parent / "masterdata",
        )
        self.app = restarted_app
        self.client = TestClient(restarted_app)
        self.client.__enter__()
        persisted = next(
            row for row in self.client.get(
                "/api/local/units").json()["userKnightmareFrameList"]
            if row["userKnightmareFrameId"] == user_kmf_id
        )
        self.assertTrue(persisted["isInStorage"])
        self.assertTrue(persisted["useCustomColor"])
        self.assertEqual(
            (persisted["customColorR"], persisted["customColorG"],
             persisted["customColorB"]),
            (91, 92, 93),
        )

    def test_fresh_database_bootstraps_minimal_starter_account(self):
        fresh_path = Path(self.directory.name) / "fresh.sqlite"
        fresh_app = create_app(fresh_path, FIXTURE)
        with TestClient(fresh_app) as fresh_client:
            state = fresh_client.get("/api/local/state")
            self.assertEqual(state.status_code, 200)
            body = state.json()
            self.assertEqual(body["freeSakuradite"], 300)
            self.assertEqual(body["gameItems"]["GACHA_TICKET"], 1)
            page = fresh_client.get("/api/local/page-state").json()
        self.assertEqual(body["bootstrapProfile"], "local-starter-v1")
        self.assertEqual(body["bootstrapVersion"], 1)
        self.assertEqual(body["pilots"], 2)
        self.assertEqual(body["kmfs"], 2)
        self.assertEqual(body["decks"], 1)

        self.assertEqual(page["freeSakuradite"], 300)
        self.assertEqual(len(page["decks"]), 1)
        self.assertEqual(len(page["decks"][0]["slots"]), 2)

    def test_restart_does_not_duplicate_starter_state(self):
        self.client.__exit__(None, None, None)
        second_app = create_app(self.database, FIXTURE)
        self.client = TestClient(second_app)
        self.client.__enter__()
        body = self.client.get("/api/local/state").json()
        self.assertEqual(body["pilots"], 2)
        self.assertEqual(body["kmfs"], 2)
        self.assertEqual(body["decks"], 1)

    def test_empty_profile_is_a_valid_zero_state(self):
        empty_path = Path(self.directory.name) / "empty.sqlite"
        empty_app = create_app(
            empty_path,
            FIXTURE,
            starter_profile=StarterProfile.empty(),
        )
        with TestClient(empty_app) as empty_client:
            state = empty_client.get("/api/local/state")
            self.assertEqual(state.status_code, 200)
            body = state.json()
            self.assertEqual(body["freeSakuradite"], 0)
            self.assertEqual(body["gameItems"], {})
            self.assertEqual(body["pilots"], 0)
            self.assertEqual(body["kmfs"], 0)
            self.assertEqual(body["decks"], 0)

            units = empty_client.get("/api/local/units")
            self.assertEqual(units.status_code, 200)
            self.assertEqual(units.json()["userCardList"], [])
            self.assertEqual(units.json()["userKnightmareFrameList"], [])
            self.assertEqual(units.json()["userDeckList"], [])

            page = empty_client.get("/api/local/page-state")
            self.assertEqual(page.status_code, 200)
            self.assertEqual(page.json()["freeSakuradite"], 0)

    def test_insufficient_tickets_returns_game_error(self):
        seeded = self.client.post(
            "/api/local/dev-state",
            json={"items": {"GACHA_TICKET": 0}},
        )
        self.assertEqual(seeded.status_code, 200)

        response = self.client.post(
            "/api/gacha/draw",
            json={
                "gachaScheduleId": 1005,
                "gachaBeanKind": "RARE10",
            },
        )
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual(body["resultCode"], "error")
        self.assertIn("errorTxt", body)

    def test_unknown_schedule_is_rejected(self):
        response = self.client.post(
            "/api/gacha/draw",
            json={"gachaScheduleId": 999999, "gachaBeanKind": "RARE"},
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["resultCode"], "error")


if __name__ == "__main__":
    unittest.main()
