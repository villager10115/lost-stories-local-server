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
    UserCardAttributeRank,
    UserGameItem,
    UserPilot,
    UserWallet,
)
from cgls.progression import (
    CARD_PROGRESSION,
    BondsService,
    ExperienceService,
    ProgressionError,
    RevisionService,
    card_attribute_rank_state,
    _add_bonds,
    _add_experience,
    _add_attribute_rank_experience,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/gacha_1005.json"


class CardProgressionTests(unittest.TestCase):
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
            "revisionGroup": {
                "revision1": {
                    "boostCode1": "DEFENSE_ADJUST",
                    "boostValue1": "175",
                    "boostCode2": "HP",
                    "boostValue2": "175",
                    "boostCode3": "MASTER_LEVEL_EXP",
                    "boostValue3": "1",
                    "needGold": 3750,
                    "needItemId1": "CARD_CRYSTAL_ROOK_BRONZE",
                    "needQuantity1": 20,
                }
            },
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
            self.card_id = "TEST-RARE4"
            session.add(UserPilot(
                user_id=self.uid,
                user_card_id=self.card_id,
                mst_pilot_id=405001,
                mst_chara_id=405,
                level=25,
                experience=771,
                bonds_level=3,
                bonds_point=131,
            ))
            session.add_all([
                UserGameItem(user_id=self.uid, item_id="EXP", quantity=10),
                UserGameItem(user_id=self.uid, item_id="EXP_P", quantity=5),
                UserGameItem(user_id=self.uid, item_id="EXP_PP", quantity=2),
                UserGameItem(user_id=self.uid, item_id="TRUST_EXP", quantity=10),
                UserGameItem(
                    user_id=self.uid,
                    item_id="CARD_CRYSTAL_ROOK_BRONZE",
                    quantity=1000,
                ),
            ])
            session.get(UserWallet, self.uid).gold = 10000
            session.add(UserCardAttributeRank(
                user_id=self.uid,
                attribute="ROOK",
                level=17,
                experience=0,
            ))
            session.commit()
        self.experience = ExperienceService(self.factory, self.uid)
        self.bonds = BondsService(self.factory, self.uid)
        self.revision = RevisionService(
            self.factory, self.uid, {405001: self.card_definition})

    def tearDown(self):
        self.app.state.engine.dispose()
        self.tmp.cleanup()

    def state(self):
        with self.factory() as session:
            pilot = session.scalar(
                select(UserPilot).where(UserPilot.user_card_id == self.card_id)
            )
            items = {
                item_id: session.get(UserGameItem, (self.uid, item_id)).quantity
                for item_id in ("EXP", "EXP_P", "EXP_PP", "TRUST_EXP")
            }
            return (
                pilot.level,
                pilot.experience,
                pilot.bonds_level,
                pilot.bonds_point,
                items,
                len(session.scalars(select(ProgressionReceipt)).all()),
            )

    def revision_state(self):
        with self.factory() as session:
            pilot = session.scalar(
                select(UserPilot).where(UserPilot.user_card_id == self.card_id)
            )
            rank = session.get(UserCardAttributeRank, (self.uid, "ROOK"))
            wallet = session.get(UserWallet, self.uid)
            material = session.get(
                UserGameItem,
                (self.uid, "CARD_CRYSTAL_ROOK_BRONZE"),
            )
            return (
                pilot.awakening_level,
                wallet.gold,
                material.quantity,
                rank.level,
                rank.experience,
                len(session.scalars(select(ProgressionReceipt)).all()),
            )

    def test_captured_experience_delta_and_response(self):
        response = self.experience.apply(
            self.card_id, {"EXP": 1, "EXP_P": 0, "EXP_PP": 0}, "exp-captured"
        )
        self.assertEqual(self.state()[0:2], (25, 871))
        self.assertEqual(self.state()[4]["EXP"], 9)
        self.assertEqual(response["enforceResult"], "GOOD")
        self.assertEqual(response["userCardList"][0]["level"], 25)
        self.assertEqual(response["userCardList"][0]["experience"], 871)
        self.assertEqual(response["userItemList"][0]["itemId"], "EXP")

    def test_experience_level_up_uses_client_curve(self):
        with self.factory() as session:
            pilot = session.scalar(
                select(UserPilot).where(UserPilot.user_card_id == self.card_id)
            )
            pilot.experience = 970
            session.commit()
        response = self.experience.apply(
            self.card_id, {"EXP": 1, "EXP_P": 0, "EXP_PP": 0}, "exp-level"
        )
        self.assertEqual(self.state()[0:2], (26, 50))
        self.assertEqual(response["userCardList"][0]["level"], 26)
        self.assertEqual(response["userCardList"][0]["experience"], 50)

    def test_experience_mixed_items_and_partial_quantities(self):
        response = self.experience.apply(
            self.card_id, {"EXP": 2, "EXP_P": 1, "EXP_PP": 0}, "exp-mixed"
        )
        self.assertEqual(self.state()[0:2], (26, 201))
        items = {item["itemId"]: item["quantity"]
                 for item in response["userItemList"]}
        self.assertEqual(items, {"EXP": 8, "EXP_P": 4})

    def test_experience_cap_and_missing_items_do_not_spend(self):
        with self.factory() as session:
            pilot = session.scalar(
                select(UserPilot).where(UserPilot.user_card_id == self.card_id)
            )
            pilot.level = 60
            session.commit()
        with self.assertRaisesRegex(ProgressionError, "level cap"):
            self.experience.apply(
                self.card_id, {"EXP": 1, "EXP_P": 0, "EXP_PP": 0}, "exp-cap"
            )
        self.assertEqual(self.state()[0:2], (60, 771))
        self.assertEqual(self.state()[4]["EXP"], 10)

        with self.factory() as session:
            pilot = session.scalar(
                select(UserPilot).where(UserPilot.user_card_id == self.card_id)
            )
            pilot.level = 25
            session.commit()
        with self.assertRaisesRegex(ProgressionError, "Not enough"):
            self.experience.apply(
                self.card_id, {"EXP": 11, "EXP_P": 0, "EXP_PP": 0}, "exp-short"
            )
        self.assertEqual(self.state()[0:2], (25, 771))
        self.assertEqual(self.state()[4]["EXP"], 10)

    def test_experience_invalid_requests_have_no_effect(self):
        cases = [
            ("foreign", {"EXP": 1}, "foreign"),
            (self.card_id, {"EXP": 0}, "zero"),
            (self.card_id, {"EXP": -1}, "negative"),
            (self.card_id, {"EXP": True}, "bool"),
            (self.card_id, {"EXP": 1, "GOLD": 1}, "unknown"),
            (self.card_id, {"EXP": 1}, None),
            (self.card_id, {"EXP": 1}, " "),
        ]
        for card_id, items, request_id in cases:
            with self.assertRaises(ProgressionError):
                self.experience.apply(card_id, items, request_id)
        self.assertEqual(self.state(), (25, 771, 3, 131, {
            "EXP": 10, "EXP_P": 5, "EXP_PP": 2, "TRUST_EXP": 10
        }, 0))

    def test_experience_receipt_replay_conflict_and_restart(self):
        first = self.experience.apply(
            self.card_id, {"EXP": 1}, "exp-retry"
        )
        self.app.state.engine.dispose()
        self.app = create_app(self.database, FIXTURE)
        self.factory = self.app.state.session_factory
        service = ExperienceService(self.factory, self.uid)
        self.assertEqual(
            service.apply(self.card_id, {"EXP": 1}, "exp-retry"), first
        )
        with self.assertRaisesRegex(ProgressionError, "different action"):
            service.apply(self.card_id, {"EXP": 2}, "exp-retry")
        self.assertEqual(self.state()[0:2], (25, 871))
        self.assertEqual(self.state()[4]["EXP"], 9)

    def test_experience_concurrent_replay_charges_once(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(
                lambda _: self.experience.apply(
                    self.card_id, {"EXP": 1}, "exp-parallel"), range(8)
            ))
        self.assertTrue(all(result == results[0] for result in results))
        self.assertEqual(self.state()[0:2], (25, 871))
        self.assertEqual(self.state()[4]["EXP"], 9)

    def test_experience_commit_failure_rolls_back(self):
        with patch.object(Session, "commit", side_effect=RuntimeError("disk failure")):
            with self.assertRaises(RuntimeError):
                self.experience.apply(self.card_id, {"EXP": 1}, "exp-disk")
        self.assertEqual(self.state(), (25, 771, 3, 131, {
            "EXP": 10, "EXP_P": 5, "EXP_PP": 2, "TRUST_EXP": 10
        }, 0))
        self.experience.apply(self.card_id, {"EXP": 1}, "exp-disk")
        self.assertEqual(self.state()[0:2], (25, 871))

    def test_captured_bonds_delta_and_level_up(self):
        response = self.bonds.apply(
            self.card_id, {"TRUST_EXP": 1}, "bonds-captured"
        )
        self.assertEqual(self.state()[2:4], (3, 181))
        self.assertEqual(response["userCardList"][0]["bondsPoint"], 181)
        self.assertEqual(response["userItemList"][0]["quantity"], 9)
        self.bonds.apply(self.card_id, {"TRUST_EXP": 1}, "bonds-level")
        self.assertEqual(self.state()[2:4], (4, 31))

    def test_bonds_cap_and_insufficient_item(self):
        with self.factory() as session:
            pilot = session.scalar(
                select(UserPilot).where(UserPilot.user_card_id == self.card_id)
            )
            pilot.bonds_level = 5
            session.commit()
        with self.assertRaisesRegex(ProgressionError, "bonds cap"):
            self.bonds.apply(self.card_id, {"TRUST_EXP": 1}, "bonds-cap")
        self.assertEqual(self.state()[2:4], (5, 131))
        self.assertEqual(self.state()[4]["TRUST_EXP"], 10)

        with self.factory() as session:
            pilot = session.scalar(
                select(UserPilot).where(UserPilot.user_card_id == self.card_id)
            )
            pilot.bonds_level = 3
            session.commit()
        with self.assertRaisesRegex(ProgressionError, "Not enough"):
            self.bonds.apply(self.card_id, {"TRUST_EXP": 11}, "bonds-short")
        self.assertEqual(self.state()[2:4], (3, 131))

    def test_bonds_invalid_payload_and_foreign_owner(self):
        for card_id, items in [
            ("foreign", {"TRUST_EXP": 1}),
            (self.card_id, {"EXP": 1}),
            (self.card_id, {"TRUST_EXP": 0}),
            (self.card_id, {"TRUST_EXP": -1}),
            (self.card_id, {"TRUST_EXP": True}),
        ]:
            with self.assertRaises(ProgressionError):
                self.bonds.apply(card_id, items, "bonds-invalid")
        self.assertEqual(self.state()[2:4], (3, 131))
        self.assertEqual(self.state()[4]["TRUST_EXP"], 10)

    def test_http_experience_and_bonds_persist(self):
        with TestClient(self.app) as client:
            exp_url = "/api/card/enforce/experience"
            bonds_url = "/api/card/enforce/bonds"
            payload = {"userCardId": self.card_id,
                       "useItem": {"EXP": 1, "EXP_P": 0, "EXP_PP": 0}}
            self.assertEqual(client.post(exp_url, json=payload).status_code, 400)
            self.assertEqual(client.post(exp_url, json={
                **payload, "useItem": {"EXP": "1"}},
                headers={"X-Request-Id": "strict"}).status_code, 422)
            response = client.post(
                exp_url, json=payload, headers={"X-Request-Id": "http-exp"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["userCardList"][0]["experience"], 871)

            bonds_payload = {"userCardId": self.card_id,
                             "useItem": {"TRUST_EXP": 1}}
            response = client.post(
                bonds_url, json=bonds_payload,
                headers={"X-Request-Id": "http-bonds"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["userCardList"][0]["bondsPoint"], 181)
            units = client.get("/api/local/units").json()
            card = next(row for row in units["userCardList"]
                        if row["userCardId"] == self.card_id)
            self.assertEqual(card["level"], 25)
            self.assertEqual(card["experience"], 871)
            self.assertEqual(card["bondsPoint"], 181)

    def test_captured_revision_delta_and_response(self):
        response = self.revision.apply(self.card_id, "revision-captured")
        self.assertEqual(self.revision_state(), (1, 6250, 980, 17, 1, 1))
        card = response["userCardList"][0]
        self.assertEqual(card["revision"], 1)
        self.assertEqual(card["revisionClass"], 1)
        self.assertEqual(card["hp"], 3835)
        self.assertEqual(card["defenseAdjust"], 3545)
        self.assertEqual(card["strength"], 1089)
        rank = response["userCardAttributeRankList"][0]
        self.assertEqual(
            (rank["attribute"], rank["level"], rank["exp"]),
            ("ROOK", 17, 1),
        )
        self.assertEqual(rank["nextCardAttributeRank"], {"id": 18, "exp": 4})
        self.assertEqual(
            {row["itemId"]: row["quantity"] for row in response["userItemList"]},
            {"GOLD": 6250, "CARD_CRYSTAL_ROOK_BRONZE": 980},
        )

    def test_revision_rejects_missing_materials_and_cap_without_spending(self):
        with self.factory() as session:
            material = session.get(
                UserGameItem,
                (self.uid, "CARD_CRYSTAL_ROOK_BRONZE"),
            )
            material.quantity = 19
            session.commit()
        with self.assertRaisesRegex(ProgressionError, "Not enough revision materials"):
            self.revision.apply(self.card_id, "revision-short")
        self.assertEqual(self.revision_state(), (0, 10000, 19, 17, 0, 0))

        with self.factory() as session:
            material = session.get(
                UserGameItem,
                (self.uid, "CARD_CRYSTAL_ROOK_BRONZE"),
            )
            material.quantity = 1000
            pilot = session.scalar(
                select(UserPilot).where(UserPilot.user_card_id == self.card_id))
            pilot.awakening_level = 15
            session.commit()
        with self.assertRaisesRegex(ProgressionError, "revision cap"):
            self.revision.apply(self.card_id, "revision-cap")
        self.assertEqual(self.revision_state(), (15, 10000, 1000, 17, 0, 0))

    def test_revision_receipt_replay_conflict_and_restart(self):
        first = self.revision.apply(self.card_id, "revision-retry")
        self.app.state.engine.dispose()
        self.app = create_app(
            self.database, FIXTURE, masterdata_dir=self.masterdata)
        self.factory = self.app.state.session_factory
        service = RevisionService(
            self.factory, self.uid, {405001: self.card_definition})
        self.assertEqual(
            service.apply(self.card_id, "revision-retry"), first)
        with self.assertRaisesRegex(ProgressionError, "different action"):
            service.apply("another-pilot", "revision-retry")
        self.assertEqual(self.revision_state(), (1, 6250, 980, 17, 1, 1))

    def test_revision_concurrent_replay_and_rank_boundaries(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(
                lambda _: self.revision.apply(
                    self.card_id, "revision-parallel"),
                range(8),
            ))
        self.assertTrue(all(result == results[0] for result in results))
        self.assertEqual(self.revision_state(), (1, 6250, 980, 17, 1, 1))
        self.assertEqual(_add_attribute_rank_experience(17, 3, 1), (18, 0))
        self.assertEqual(_add_attribute_rank_experience(27, 5, 1), (28, 0))

    def test_http_revision_persists_stats_and_page_rank(self):
        with TestClient(self.app) as client:
            url = "/api/card/enforce/revision"
            self.assertEqual(
                client.post(url, json={"userCardId": self.card_id}).status_code,
                400,
            )
            response = client.post(
                url,
                json={"userCardId": self.card_id},
                headers={"X-Request-Id": "http-revision"},
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["userCardList"][0]["revision"], 1)
            units = client.get("/api/local/units").json()
            card = next(
                row for row in units["userCardList"]
                if row["userCardId"] == self.card_id
            )
            self.assertEqual((card["revision"], card["revisionClass"]), (1, 1))
            self.assertEqual(card["hp"], 3835)
        with self.factory() as session:
            ranks = card_attribute_rank_state(session, self.uid)
        rook = next(row for row in ranks if row["attribute"] == "ROOK")
        self.assertEqual((rook["level"], rook["exp"]), (17, 1))

    def test_progression_fixture_matches_captured_values(self):
        self.assertEqual(CARD_PROGRESSION["itemExpArr"],
                         {"EXP": 100, "EXP_P": 250, "EXP_PP": 600})
        self.assertEqual(CARD_PROGRESSION["bondsThresholds"],
                         [0, 100, 150, 200, 250])
        self.assertEqual(len(CARD_PROGRESSION["expArr"]["RARE_4"]), 99)
        self.assertEqual(_add_experience(25, 771, 100, 60,
                                         CARD_PROGRESSION["expArr"]["RARE_4"]),
                         (25, 871))
        self.assertEqual(_add_experience(25, 970, 100, 60,
                                         CARD_PROGRESSION["expArr"]["RARE_4"]),
                         (26, 50))
        self.assertEqual(_add_bonds(3, 181, 50), (4, 31))


if __name__ == "__main__":
    unittest.main()
