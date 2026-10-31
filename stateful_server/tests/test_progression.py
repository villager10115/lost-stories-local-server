from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import hashlib
import json
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from cgls.app import create_app
from cgls.bootstrap import ensure_local_user
from cgls.models import ProgressionReceipt, UserCardLimitBreak, UserGameItem, UserPilot, UserWallet
from cgls.progression import LimitBreakService, ProgressionError, RULES

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/gacha_1005.json"


class LimitBreakTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.database = Path(self.tmp.name) / "state.sqlite"
        self.app = create_app(self.database, FIXTURE)
        self.factory = self.app.state.session_factory
        with self.factory() as session:
            self.uid = ensure_local_user(session).id
            pilot = session.scalar(select(UserPilot).where(UserPilot.mst_pilot_id == 103004))
            self.card_id = pilot.user_card_id
            session.get(UserWallet, self.uid).gold = 10000
            session.add(UserCardLimitBreak(user_id=self.uid, card_id=103004, quantity=70))
            session.add(UserGameItem(user_id=self.uid, item_id="LIMIT_BREAK_RANK_3", quantity=110))
            session.commit()
        self.service = LimitBreakService(self.factory, self.uid)

    def tearDown(self):
        self.app.state.engine.dispose()
        self.tmp.cleanup()

    def state(self):
        with self.factory() as session:
            pilot = session.scalar(select(UserPilot).where(UserPilot.user_card_id == self.card_id))
            return (pilot.limit_break, session.get(UserWallet, self.uid).gold,
                    session.get(UserCardLimitBreak, (self.uid, 103004)).quantity,
                    session.get(UserGameItem, (self.uid, "LIMIT_BREAK_RANK_3")).quantity,
                    len(session.scalars(select(ProgressionReceipt)).all()))

    def test_unique_cost_and_delta_match_captured_first_break(self):
        response = self.service.apply(self.card_id, "UNIQUE", "first")
        self.assertEqual(self.state(), (1, 9000, 60, 110, 1))
        card = response["userCardList"][0]
        self.assertEqual(
            (card["userCardId"], card["cardId"], card["lbCount"]),
            (self.card_id, 103004, 1),
        )
        self.assertEqual(card["revisionClass"], 1)
        self.assertEqual(response["userCardLimitBreakList"][0]["quantity"], 60)
        self.assertEqual(response["userItemList"][0]["quantity"], 9000)
        self.assertEqual(response["resultCode"], "success")

    def test_all_unique_stages_and_cap(self):
        for level, expected in enumerate([(1, 9000, 60), (2, 7000, 45),
                                         (3, 4000, 25), (4, 0, 0)]):
            self.service.apply(self.card_id, "UNIQUE", str(level))
            self.assertEqual(self.state()[:3], expected)
        with self.assertRaisesRegex(ProgressionError, "cap"):
            self.service.apply(self.card_id, "UNIQUE", "over-cap")
        self.assertEqual(self.state(), (4, 0, 0, 110, 4))

    def test_common_materials_use_rarity_specific_inventory(self):
        for level, expected in enumerate([90, 65, 35, 0]):
            response = self.service.apply(self.card_id, "COMMON", str(level))
            items = {r["itemId"]: r["quantity"] for r in response["userItemList"]}
            self.assertEqual(items["LIMIT_BREAK_RANK_3"], expected)
            self.assertEqual(response["userCardLimitBreakList"], [])
        self.assertEqual(self.state(), (4, 0, 70, 0, 4))

    def test_retry_survives_engine_restart_and_conflict_is_rejected(self):
        first = self.service.apply(self.card_id, "UNIQUE", "retry")
        self.app.state.engine.dispose()
        self.app = create_app(self.database, FIXTURE)
        self.factory = self.app.state.session_factory
        service = LimitBreakService(self.factory, self.uid)
        self.assertEqual(service.apply(self.card_id, "UNIQUE", "retry"), first)
        with self.assertRaisesRegex(ProgressionError, "different action"):
            service.apply(self.card_id, "COMMON", "retry")
        self.assertEqual(self.state(), (1, 9000, 60, 110, 1))

    def test_concurrent_same_request_charges_once(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.service.apply(
                self.card_id, "UNIQUE", "parallel"), range(8)))
        self.assertTrue(all(r == results[0] for r in results))
        self.assertEqual(self.state(), (1, 9000, 60, 110, 1))

    def test_distinct_concurrent_requests_cannot_overspend(self):
        with self.factory() as session:
            session.get(UserWallet, self.uid).gold = 1000
            session.commit()
        def attempt(i):
            try:
                self.service.apply(self.card_id, "UNIQUE", str(i))
                return True
            except ProgressionError:
                return False
        with ThreadPoolExecutor(max_workers=4) as pool:
            self.assertEqual(sum(pool.map(attempt, range(4))), 1)
        self.assertEqual(self.state(), (1, 0, 60, 110, 1))

    def test_commit_failure_rolls_back_every_change_and_allows_retry(self):
        with patch.object(Session, "commit", side_effect=RuntimeError("disk failure")):
            with self.assertRaises(RuntimeError):
                self.service.apply(self.card_id, "UNIQUE", "disk")
        self.assertEqual(self.state(), (0, 10000, 70, 110, 0))
        self.service.apply(self.card_id, "UNIQUE", "disk")
        self.assertEqual(self.state(), (1, 9000, 60, 110, 1))

    def test_missing_materials_reject_without_spending(self):
        with self.factory() as session:
            session.get(UserCardLimitBreak, (self.uid, 103004)).quantity = 9
            session.delete(session.get(UserGameItem, (self.uid, "LIMIT_BREAK_RANK_3")))
            session.commit()
        for kind in ["UNIQUE", "COMMON"]:
            with self.assertRaisesRegex(ProgressionError, "materials"):
                self.service.apply(self.card_id, kind, kind)
        with self.factory() as session:
            self.assertEqual(session.get(UserWallet, self.uid).gold, 10000)
            self.assertEqual(session.get(UserCardLimitBreak, (self.uid, 103004)).quantity, 9)
            self.assertEqual(session.scalars(select(ProgressionReceipt)).all(), [])

    def test_invalid_owner_kind_and_request_id_have_no_effect(self):
        for card, kind, key in [("foreign-card", "UNIQUE", "foreign"),
                                (self.card_id, "CHEAT", "kind"),
                                (self.card_id, "UNIQUE", None),
                                (self.card_id, "UNIQUE", " "),
                                (self.card_id, "UNIQUE", "x" * 129)]:
            with self.assertRaises(ProgressionError):
                self.service.apply(card, kind, key)
        self.assertEqual(self.state(), (0, 10000, 70, 110, 0))

    def test_http_rejects_overrides_and_reads_persisted_progress(self):
        payload = {"userCardId": self.card_id, "limitBreakType": "UNIQUE"}
        with TestClient(self.app) as client:
            url = "/api/card/enforce/limitBreak"
            self.assertEqual(client.post(url, json=payload).status_code, 400)
            self.assertEqual(client.post(url, json={**payload, "gold": 0},
                headers={"X-Request-Id": "bad"}).status_code, 422)
            self.assertEqual(client.post(url, json=payload,
                headers={"X-Request-Id": "good"}).status_code, 200)
            units = client.get("/api/local/units").json()
            card = next(r for r in units["userCardList"] if r["userCardId"] == self.card_id)
            self.assertEqual(card["lbCount"], 1)
            self.assertEqual(client.get("/api/local/page-state").json()["gold"], 9000)

    def test_rules_match_preserved_masterdata(self):
        master = Path(r"D:\LostStories_Private_Client_20261019/assets/masterdata/pages/MyPage.static.json")
        if not master.is_file():
            self.skipTest("Preserved masterdata is not installed")
        raw = master.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), RULES["sourceSha256"])
        cards = [c for c in json.loads(raw)["cardList"] if c.get("rarity")]
        self.assertEqual(len(cards), len(RULES["cards"]))
        for card in cards:
            rarity = card["rarity"]
            self.assertEqual(RULES["cards"][str(card["cardId"])], rarity["rarityNum"])
            for key, value in RULES["rarities"][str(rarity["rarityNum"])].items():
                self.assertEqual(value, rarity[key])


if __name__ == "__main__":
    unittest.main()
