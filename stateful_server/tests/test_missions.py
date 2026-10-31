from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from cgls.app import create_app
from cgls.bootstrap import ensure_local_user
from cgls.missions import MissionService
from cgls.models import MissionReceipt, UserGameItem
from cgls.models import LocalBattleProgress

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/gacha_1005.json"
MASTER = Path("D:/LostStories_Offline/assets/masterdata")


class MissionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app(Path(self.tmp.name) / "state.sqlite", FIXTURE)
        self.factory = self.app.state.session_factory
        with self.factory() as session:
            self.uid = ensure_local_user(session).id
        self.time = datetime.fromisoformat("2026-10-19T23:59:59+09:00")
        self.service = MissionService(
            self.factory, self.uid, None, lambda: self.time
        )

    def tearDown(self):
        self.app.state.engine.dispose()
        self.tmp.cleanup()

    def test_captured_reward_quantities_and_response_contract(self):
        response = self.service.claim("normal")
        self.assertEqual({r["itemId"]: r["quantity"] for r in response["results"]},
                         {"GACHA_MEDAL": 50, "DAILY_QUEST_DROP_BOOST": 1})
        self.assertTrue(all(r["receivedAt"] for r in response["userDailyChallengeList"]))
        self.assertEqual(len({r["instanceId"] for r in response["results"]}), 2)
        self.assertTrue(all(r["originType"] == "CHALLENGE" for r in response["results"]))
        self.assertIn("currentTime", response)
        self.assertEqual(len(response["userItemList"]), 2)

    def test_midnight_accumulates_and_reopen_preserves_receipts(self):
        self.service.claim("daily")
        self.time = datetime.fromisoformat("2026-10-19T15:00:00+00:00")
        response = self.service.claim("daily")
        quantities = {r["itemId"]: r["quantity"] for r in response["userItemList"]}
        self.assertEqual(quantities, {"GACHA_MEDAL": 100, "DAILY_QUEST_DROP_BOOST": 2})
        reopened = MissionService(
            self.factory, self.uid, None, lambda: self.time
        )
        retry = reopened.claim("daily")
        self.assertEqual(retry["results"], [])
        self.assertEqual(retry["userItemList"], [])
        with self.factory() as session:
            self.assertEqual(len(session.scalars(select(MissionReceipt)).all()), 4)

    def test_concurrent_claims_grant_once(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            responses = list(pool.map(lambda _: self.service.claim("normal"), range(8)))
        self.assertEqual(sum(len(r["results"]) for r in responses), 2)
        with self.factory() as session:
            self.assertEqual(session.get(UserGameItem, (self.uid, "GACHA_MEDAL")).quantity, 50)

    def test_failed_commit_does_not_mark_or_award(self):
        with patch.object(Session, "commit", side_effect=RuntimeError("disk failure")):
            with self.assertRaises(RuntimeError):
                self.service.claim("daily")
        with self.factory() as session:
            self.assertEqual(session.scalars(select(MissionReceipt)).all(), [])
            self.assertIsNone(session.get(UserGameItem, (self.uid, "GACHA_MEDAL")))
        self.assertEqual(len(self.service.claim("daily")["results"]), 2)

    def test_unknown_conditions_fail_without_grant(self):
        for scope, cid in [("unknown", None), ("daily", 999)]:
            with self.assertRaises(ValueError):
                self.service.claim(scope, cid)
        self.assertEqual(len(self.service.claim("daily", 1000009)["results"]), 1)

    def test_api_uses_shared_inventory_and_rejects_reward_override(self):
        with TestClient(self.app) as client:
            self.assertEqual(client.post("/api/local/missions/claim", json={
                "scope": "daily", "quantity": 9000}).status_code, 422)
            self.assertEqual(client.post("/api/local/missions/claim",
                json={"scope": "normal"}).status_code, 200)
            state = client.get("/api/local/page-state").json()
            self.assertEqual(state["gameItems"]["GACHA_MEDAL"], 50)
            self.assertTrue(all(r["receivedAt"] for r in state["userDailyChallengeList"]))

    def test_retained_task_progress_is_visible_after_existing_gameplay(self):
        with self.factory() as session:
            session.add(LocalBattleProgress(
                user_id=self.uid, quest_id=101105,
                state={"questStatus": "CLEARED"}))
            session.commit()
        service = MissionService(
            self.factory, self.uid, MASTER, lambda: self.time)
        total = {row["challengeId"]: row
                 for row in service.state()["userTotalChallengeList"]}
        self.assertEqual(total[1100058]["clearedCount"], 490)
        self.assertTrue(total[1100058]["receivedAt"])
        self.assertEqual(service.claim("total", 1100058)["results"], [])


if __name__ == "__main__":
    unittest.main()
