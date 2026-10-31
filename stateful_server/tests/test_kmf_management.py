from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import select

from cgls.app import create_app
from cgls.bootstrap import ensure_local_user
from cgls.kmf_management_models import UserKmfDevelopment
from cgls.models import UserDeck, UserKmf, UserKmfKey


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "gacha_1005.json"
MASTERDATA_CANDIDATES = (
    Path(r"D:\LostStories_Japanese\assets\masterdata"),
    Path(r"D:\LostStories_Offline\assets\masterdata"),
)
MASTERDATA = next(
    (path for path in MASTERDATA_CANDIDATES
     if (path / "pages" / "MyPage.static.json").is_file()),
    None,
)
FRAME_ID = 2602
CUSTOMIZATION_ID = 260201


@unittest.skipUnless(MASTERDATA is not None, "Preserved masterdata is unavailable")
class KmfManagementTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.database = Path(self.tmp.name) / "kmf.sqlite"
        self.app = create_app(
            self.database,
            FIXTURE,
            masterdata_dir=MASTERDATA,
        )
        self.client = TestClient(self.app)
        self.client.__enter__()
        with self.app.state.session_factory() as session:
            user = ensure_local_user(session)
            self.user_id = user.id
            wallet = user.wallet
            wallet.gold = 100000
            wallet.free_sakuradite = 300
            wallet.paid_sakuradite = 0
            key = session.get(UserKmfKey, (user.id, FRAME_ID))
            if key is None:
                key = UserKmfKey(
                    user_id=user.id,
                    knightmare_frame_id=FRAME_ID,
                    quantity=2,
                )
                session.add(key)
            else:
                key.quantity = 2
            session.commit()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.app.state.engine.dispose()
        self.tmp.cleanup()

    def test_development_start_receive_and_page_state(self):
        started = self.client.post(
            "/api/knightmareFrame/development/start",
            json={"frameNo": 1, "knightmareFrameId": FRAME_ID},
        )
        self.assertEqual(started.status_code, 200, started.text)
        body = started.json()
        self.assertEqual(
            body["userKnightmareFrameKeyList"][0]["quantity"], 1)
        development = body["userKnightmareFrameDevelopmentList"][0]
        self.assertEqual(development["frameNo"], 1)
        self.assertIsNone(development["receivedAt"])

        too_early = self.client.post(
            "/api/knightmareFrame/development/receive",
            json={"frameNo": 1},
        )
        self.assertEqual(too_early.status_code, 400, too_early.text)

        with self.app.state.session_factory() as session:
            row = session.get(UserKmfDevelopment, (self.user_id, 1))
            row.end_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            session.commit()

        received = self.client.post(
            "/api/knightmareFrame/development/receive",
            json={"frameNo": 1},
        )
        self.assertEqual(received.status_code, 200, received.text)
        body = received.json()
        created = body["userKnightmareFrameList"][0]
        self.assertEqual(created["knightmareFrameId"], FRAME_ID)
        self.assertTrue(created["isNew"])
        self.assertRegex(
            body["userKnightmareFrameCustomizeList"][0]
            ["userKnightmareFrameCustomizeId"],
            r"^[0-9a-f-]{36}$",
        )
        self.assertIsNotNone(
            body["userKnightmareFrameDevelopmentList"][0]["receivedAt"])

        state = self.client.get("/api/local/page-state").json()
        self.assertEqual(
            state["userKnightmareFrameKeyList"][0]["quantity"], 1)
        self.assertIsNotNone(
            state["userKnightmareFrameDevelopmentList"][0]["receivedAt"])

        with self.app.state.session_factory() as session:
            count = len(session.execute(
                select(UserKmf).where(
                    UserKmf.user_id == self.user_id,
                    UserKmf.mst_kmf_id == FRAME_ID,
                )
            ).scalars().all())
        self.assertEqual(count, 2)

    def test_development_skip_spends_sakuradite(self):
        started = self.client.post(
            "/api/knightmareFrame/development/start",
            json={"frameNo": 2, "knightmareFrameId": FRAME_ID},
        )
        self.assertEqual(started.status_code, 200, started.text)

        skipped = self.client.post(
            "/api/knightmareFrame/development/skip",
            json={"frameNo": 2},
        )
        self.assertEqual(skipped.status_code, 200, skipped.text)
        items = {
            row["itemId"]: row["quantity"]
            for row in skipped.json()["userItemList"]
        }
        self.assertLess(items["PRESENTED_MONEY"], 300)
        self.assertEqual(items["MONEY"], 0)
        self.assertIsNone(
            skipped.json()["userKnightmareFrameDevelopmentList"][0]
            ["receivedAt"])

    def test_dismantle_adds_same_frame_core_and_clears_deck(self):
        with self.app.state.session_factory() as session:
            unit = session.execute(
                select(UserKmf).where(
                    UserKmf.user_id == self.user_id,
                    UserKmf.mst_kmf_id == FRAME_ID,
                )
            ).scalars().first()
            user_kmf_id = unit.user_kmf_id
            session.commit()

        response = self.client.post(
            "/api/knightmareFrame/dismantle",
            json={"userKnightmareFrameIdList": [user_kmf_id]},
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(
            body["userKnightmareFrameKeyList"][0]["quantity"], 3)
        self.assertEqual(
            body["deleted"]["userKnightmareFrameList"][0]
            ["userKnightmareFrameId"],
            user_kmf_id,
        )

        with self.app.state.session_factory() as session:
            self.assertIsNone(session.execute(
                select(UserKmf).where(
                    UserKmf.user_kmf_id == user_kmf_id)
            ).scalars().first())
            decks = session.execute(
                select(UserDeck).where(UserDeck.user_id == self.user_id)
            ).scalars().all()
            self.assertTrue(all(
                slot.get("kmf") != user_kmf_id
                for deck in decks for slot in (deck.slots or [])
            ))

    def test_dismantle_locked_unit_is_transactional(self):
        with self.app.state.session_factory() as session:
            unit = session.execute(
                select(UserKmf).where(
                    UserKmf.user_id == self.user_id,
                    UserKmf.mst_kmf_id == FRAME_ID,
                )
            ).scalars().first()
            unit.is_locked = True
            session.commit()
            user_kmf_id = unit.user_kmf_id

        response = self.client.post(
            "/api/knightmareFrame/dismantle",
            json={"userKnightmareFrameIdList": [user_kmf_id]},
        )
        self.assertEqual(response.status_code, 400, response.text)
        with self.app.state.session_factory() as session:
            self.assertIsNotNone(session.execute(
                select(UserKmf).where(
                    UserKmf.user_kmf_id == user_kmf_id)
            ).scalars().first())
            key = session.get(UserKmfKey, (self.user_id, FRAME_ID))
            self.assertEqual(key.quantity, 2)

    def test_storage_batch_round_trip_and_duplicate_rejection(self):
        with self.app.state.session_factory() as session:
            unit = session.execute(
                select(UserKmf).where(
                    UserKmf.user_id == self.user_id,
                    UserKmf.mst_kmf_id == FRAME_ID,
                )
            ).scalars().first()
            user_kmf_id = unit.user_kmf_id

        carried_in = self.client.post(
            "/api/knightmareFrame/carryIn",
            json={"userKnightmareFrameIdList": [user_kmf_id]},
        )
        self.assertEqual(carried_in.status_code, 200, carried_in.text)
        self.assertTrue(
            carried_in.json()["userKnightmareFrameList"][0]["isInStorage"])

        duplicate = self.client.post(
            "/api/knightmareFrame/carryOut",
            json={"userKnightmareFrameIdList": [user_kmf_id, user_kmf_id]},
        )
        self.assertEqual(duplicate.status_code, 400, duplicate.text)

        carried_out = self.client.post(
            "/api/knightmareFrame/carryOut",
            json={"userKnightmareFrameIdList": [user_kmf_id]},
        )
        self.assertEqual(carried_out.status_code, 200, carried_out.text)
        self.assertFalse(
            carried_out.json()["userKnightmareFrameList"][0]["isInStorage"])


if __name__ == "__main__":
    unittest.main()
