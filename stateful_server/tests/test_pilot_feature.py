from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from cgls.app import create_app
from cgls.bootstrap import ensure_local_user
from cgls.models import (
    ProgressionReceipt,
    UserCardLimitBreak,
    UserGameItem,
    UserPilot,
    UserWallet,
)
from cgls.progression import FeatureService, ProgressionError


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/gacha_1005.json"


class PilotFeatureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.database = Path(self.tmp.name) / "state.sqlite"
        self.masterdata = Path(self.tmp.name) / "masterdata"
        (self.masterdata / "pages").mkdir(parents=True)
        self.card_definition = {
            "cardId": 405001,
            "charaId": 405,
            "attribute": "ROOK",
            "growthType": "FAR_DEFENSE",
            "rarity": {"maxRevision": 15},
            "cost": 13,
            "blockNum": 3,
            "hp": 2260,
            "nearAttackAdjust": 1612,
            "nearHitAccuracy": 1000,
            "nearAttackInterval": 1375,
            "farAttackAdjust": 2137,
            "farHitAccuracy": 1000,
            "farAttackInterval": 1200,
            "defenseAdjust": 1827,
            "avoidRate": 1000,
            "relocationTime": 60000,
            "cardLevelBonus": {"boostList": []},
            "revisionGroup": {},
            "cardFeatureList": [
                {
                    "cardFeatureId": 700001,
                    "cardId": 405001,
                    "cardFeatureSkillId": 900001,
                    "cardFeatureItem": {
                        "needGold": 1000,
                        "needItemId1": "FEATURE_MATERIAL_A",
                        "needQuantity1": 2,
                        "needItemId2": "FEATURE_MATERIAL_B",
                        "needQuantity2": 1,
                    },
                },
                {
                    "cardFeatureId": 700002,
                    "cardId": 405001,
                    "cardFeatureSkillId": 900002,
                    "cardFeatureItem": {
                        "needGold": 0,
                        "needLimitBreakQuantity": 5,
                    },
                },
            ],
        }
        (self.masterdata / "pages" / "MyPage.static.json").write_text(
            json.dumps({"cardList": [self.card_definition]}),
            encoding="utf-8",
        )
        self.app = create_app(
            self.database, FIXTURE, masterdata_dir=self.masterdata)
        self.factory = self.app.state.session_factory
        with self.factory() as session:
            self.uid = ensure_local_user(session).id
            self.user_card_id = "TEST-FEATURE-PILOT"
            session.add(UserPilot(
                user_id=self.uid,
                user_card_id=self.user_card_id,
                mst_pilot_id=405001,
                mst_chara_id=405,
                level=25,
                skill_levels=[1, 1],
                unlocked_feature_ids=[],
            ))
            session.add_all([
                UserGameItem(
                    user_id=self.uid,
                    item_id="FEATURE_MATERIAL_A",
                    quantity=5,
                ),
                UserGameItem(
                    user_id=self.uid,
                    item_id="FEATURE_MATERIAL_B",
                    quantity=2,
                ),
                UserCardLimitBreak(
                    user_id=self.uid,
                    card_id=405001,
                    quantity=7,
                ),
            ])
            session.get(UserWallet, self.uid).gold = 3000
            session.commit()
        self.service = FeatureService(
            self.factory, self.uid, {405001: self.card_definition})

    def tearDown(self):
        self.app.state.engine.dispose()
        self.tmp.cleanup()

    def state(self):
        with self.factory() as session:
            pilot = session.scalar(select(UserPilot).where(
                UserPilot.user_card_id == self.user_card_id))
            return {
                "features": list(pilot.unlocked_feature_ids),
                "gold": session.get(UserWallet, self.uid).gold,
                "materialA": session.get(
                    UserGameItem,
                    (self.uid, "FEATURE_MATERIAL_A"),
                ).quantity,
                "materialB": session.get(
                    UserGameItem,
                    (self.uid, "FEATURE_MATERIAL_B"),
                ).quantity,
                "limitBreak": session.get(
                    UserCardLimitBreak,
                    (self.uid, 405001),
                ).quantity,
                "receipts": len(
                    session.scalars(select(ProgressionReceipt)).all()),
            }

    def test_item_feature_unlock_spends_cost_and_returns_delta(self):
        response = self.service.apply(
            self.user_card_id, 700001, "feature-item")

        self.assertEqual(self.state(), {
            "features": [700001],
            "gold": 2000,
            "materialA": 3,
            "materialB": 1,
            "limitBreak": 7,
            "receipts": 1,
        })
        card = response["userCardList"][0]
        self.assertEqual(card["unlockedFeatureIdList"], [700001])
        self.assertEqual(
            {row["itemId"]: row["quantity"]
             for row in response["userItemList"]},
            {
                "GOLD": 2000,
                "FEATURE_MATERIAL_A": 3,
                "FEATURE_MATERIAL_B": 1,
            },
        )
        self.assertEqual(response["userCardLimitBreakList"], [])

    def test_unique_feature_unlock_uses_same_card_duplicate_points(self):
        response = self.service.apply(
            self.user_card_id, 700002, "feature-unique")

        self.assertEqual(self.state(), {
            "features": [700002],
            "gold": 3000,
            "materialA": 5,
            "materialB": 2,
            "limitBreak": 2,
            "receipts": 1,
        })
        self.assertEqual(
            response["userCardList"][0]["unlockedFeatureIdList"],
            [700002],
        )
        self.assertEqual(
            response["userCardLimitBreakList"],
            [{"cardId": 405001, "quantity": 2}],
        )

    def test_missing_cost_owner_and_foreign_feature_do_not_spend(self):
        with self.factory() as session:
            material = session.get(
                UserGameItem,
                (self.uid, "FEATURE_MATERIAL_A"),
            )
            material.quantity = 1
            session.commit()
        with self.assertRaisesRegex(
                ProgressionError, "Not enough pilot feature materials"):
            self.service.apply(
                self.user_card_id, 700001, "feature-short-item")

        with self.factory() as session:
            material = session.get(
                UserGameItem,
                (self.uid, "FEATURE_MATERIAL_A"),
            )
            material.quantity = 5
            unique = session.get(
                UserCardLimitBreak,
                (self.uid, 405001),
            )
            unique.quantity = 4
            session.commit()
        with self.assertRaisesRegex(
                ProgressionError, "Not enough pilot feature limit-break"):
            self.service.apply(
                self.user_card_id, 700002, "feature-short-unique")

        for owner, feature_id, request_id in (
            ("foreign-pilot", 700001, "feature-owner"),
            (self.user_card_id, 999999, "feature-foreign"),
        ):
            with self.assertRaises(ProgressionError):
                self.service.apply(owner, feature_id, request_id)

        self.assertEqual(self.state(), {
            "features": [],
            "gold": 3000,
            "materialA": 5,
            "materialB": 2,
            "limitBreak": 4,
            "receipts": 0,
        })

    def test_already_unlocked_and_invalid_requests_do_not_spend(self):
        self.service.apply(self.user_card_id, 700001, "feature-first")
        before = self.state()

        cases = (
            (self.user_card_id, 700001, "feature-already"),
            (self.user_card_id, 0, "feature-zero"),
            (self.user_card_id, True, "feature-bool"),
            (self.user_card_id, 700001, None),
            (self.user_card_id, 700001, " "),
        )
        for owner, feature_id, request_id in cases:
            with self.assertRaises(ProgressionError):
                self.service.apply(owner, feature_id, request_id)

        self.assertEqual(self.state(), before)

    def test_receipt_replay_conflict_concurrency_and_restart(self):
        first = self.service.apply(
            self.user_card_id, 700001, "feature-retry")
        self.app.state.engine.dispose()
        self.app = create_app(
            self.database, FIXTURE, masterdata_dir=self.masterdata)
        self.factory = self.app.state.session_factory
        service = FeatureService(
            self.factory, self.uid, {405001: self.card_definition})

        self.assertEqual(
            service.apply(self.user_card_id, 700001, "feature-retry"),
            first,
        )
        with self.assertRaisesRegex(ProgressionError, "different action"):
            service.apply(self.user_card_id, 700002, "feature-retry")

        self.assertGreaterEqual(self.state()["receipts"], 1)
        state_after_first = self.state()
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(
                lambda _: service.apply(
                    self.user_card_id, 700002, "feature-parallel"),
                range(8),
            ))
        self.assertTrue(all(result == results[0] for result in results))
        self.assertEqual(
            self.state()["features"],
            state_after_first["features"] + [700002],
        )
        self.assertEqual(self.state()["limitBreak"], 2)

    def test_distinct_requests_cannot_unlock_twice(self):
        def attempt(i):
            try:
                self.service.apply(
                    self.user_card_id, 700001, "feature-distinct-%s" % i)
                return True
            except ProgressionError:
                return False

        with ThreadPoolExecutor(max_workers=4) as pool:
            self.assertEqual(sum(pool.map(attempt, range(4))), 1)
        self.assertEqual(self.state()["features"], [700001])
        self.assertEqual(self.state()["gold"], 2000)
        self.assertEqual(self.state()["materialA"], 3)

    def test_commit_failure_rolls_back_and_retry_succeeds(self):
        with patch.object(
                Session, "commit", side_effect=RuntimeError("disk failure")):
            with self.assertRaises(RuntimeError):
                self.service.apply(
                    self.user_card_id, 700001, "feature-disk")
        self.assertEqual(self.state(), {
            "features": [],
            "gold": 3000,
            "materialA": 5,
            "materialB": 2,
            "limitBreak": 7,
            "receipts": 0,
        })
        self.service.apply(self.user_card_id, 700001, "feature-disk")
        self.assertEqual(self.state()["features"], [700001])

    def test_http_route_is_strict_and_updates_local_units(self):
        payload = {"userCardId": self.user_card_id, "cardFeatureId": 700001}
        with TestClient(self.app) as client:
            url = "/api/card/enforce/feature"
            self.assertEqual(client.post(url, json=payload).status_code, 400)
            self.assertEqual(client.post(
                url,
                json={**payload, "cardFeatureId": "700001"},
                headers={"X-Request-Id": "feature-string-id"},
            ).status_code, 422)
            self.assertEqual(client.post(
                url,
                json={**payload, "gold": 0},
                headers={"X-Request-Id": "feature-extra"},
            ).status_code, 422)

            response = client.post(
                url,
                json=payload,
                headers={"X-Request-Id": "feature-http"},
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                response.json()["userCardList"][0]["unlockedFeatureIdList"],
                [700001],
            )
            units = client.get("/api/local/units").json()
            card = next(
                row for row in units["userCardList"]
                if row["userCardId"] == self.user_card_id
            )
            self.assertEqual(card["unlockedFeatureIdList"], [700001])


if __name__ == "__main__":
    unittest.main()
