from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import select

from cgls.app import create_app
from cgls.bootstrap import ensure_local_user
from cgls.kmf_rules import customization_instance_id
from cgls.models import ProgressionReceipt, UserGameItem, UserKmf


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
FRAME_ID = 7301
CUSTOMIZATION_ID = 730101


@unittest.skipUnless(MASTERDATA is not None, "Preserved masterdata is unavailable")
class KmfEnforceRevisionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.database = Path(self.tmp.name) / "kmf-enforce.sqlite"
        self._start_app()

    def _start_app(self):
        seed = not self.database.exists()
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
            if not seed:
                session.commit()
                self.customize_id = customization_instance_id(
                    "official-enforce-kmf", CUSTOMIZATION_ID)
                return
            user.wallet.gold = 100000
            session.add(UserKmf(
                user_id=user.id,
                user_kmf_id="official-enforce-kmf",
                mst_kmf_id=FRAME_ID,
                customization_id=CUSTOMIZATION_ID,
                revision=0,
                revision_class=1,
            ))
            session.add(UserGameItem(
                user_id=user.id,
                item_id="KMF_CHIP_730101",
                quantity=30,
            ))
            session.commit()
            self.user_id = user.id
        self.customize_id = customization_instance_id(
            "official-enforce-kmf", CUSTOMIZATION_ID)
        self.assertEqual(
            self.customize_id, "295d4d13-09e9-56da-ad25-ad2f6d730523")

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.app.state.engine.dispose()
        self.tmp.cleanup()

    def _row(self):
        with self.app.state.session_factory() as session:
            return session.scalar(select(UserKmf).where(
                UserKmf.user_id == self.user_id,
                UserKmf.user_kmf_id == "official-enforce-kmf",
            ))

    def test_official_revision_costs_stats_and_request_replay(self):
        response = self.client.post(
            "/api/knightmareFrameCustomize/enforce/revision",
            headers={"X-Request-Id": "official-kmf-revision-1"},
            json={"userKnightmareFrameCustomizeId": self.customize_id},
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        items = {
            row["itemId"]: row["quantity"]
            for row in body["userItemList"]
        }
        self.assertEqual(items["GOLD"], 95500)
        self.assertEqual(items["KMF_CHIP_730101"], 20)
        customization = body["userKnightmareFrameCustomizeList"][0]
        self.assertEqual(
            customization["userKnightmareFrameCustomizeId"],
            self.customize_id,
        )
        self.assertEqual(customization["revision"], 1)
        self.assertEqual(customization["revisionClass"], 1)
        self.assertEqual(customization["attack"], 210)
        self.assertEqual(customization["defense"], 210)
        self.assertEqual(customization["knightmareFrameSkillLevel"], 1)

        replay = self.client.post(
            "/api/knightmareFrameCustomize/enforce/revision",
            headers={"X-Request-Id": "official-kmf-revision-1"},
            json={"userKnightmareFrameCustomizeId": self.customize_id},
        )
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(replay.json(), body)
        row = self._row()
        self.assertEqual(row.revision, 1)
        self.assertEqual(row.revision_class, 1)

        self.client.__exit__(None, None, None)
        self.app.state.engine.dispose()
        self._start_app()
        persisted = self.client.post(
            "/api/knightmareFrameCustomize/enforce/revision",
            headers={"X-Request-Id": "official-kmf-revision-1"},
            json={"userKnightmareFrameCustomizeId": self.customize_id},
        )
        self.assertEqual(persisted.status_code, 200, persisted.text)
        self.assertEqual(persisted.json(), body)
        with self.app.state.session_factory() as session:
            receipt = session.get(
                ProgressionReceipt,
                (self.user_id, "official-kmf-revision-1"),
            )
            self.assertIsNotNone(receipt)

    def test_missing_material_and_cap_are_transactional(self):
        with self.app.state.session_factory() as session:
            material = session.get(
                UserGameItem, (self.user_id, "KMF_CHIP_730101"))
            material.quantity = 9
            session.commit()
        before = self._row()
        response = self.client.post(
            "/api/knightmareFrameCustomize/enforce/revision",
            headers={"X-Request-Id": "official-kmf-no-material"},
            json={"userKnightmareFrameCustomizeId": self.customize_id},
        )
        self.assertEqual(response.status_code, 400, response.text)
        after = self._row()
        self.assertEqual(after.revision, before.revision)
        with self.app.state.session_factory() as session:
            self.assertEqual(
                session.get(UserKmf, after.id).revision,
                0,
            )
            self.assertEqual(
                session.get(UserGameItem, (
                    self.user_id, "KMF_CHIP_730101")).quantity,
                9,
            )

        with self.app.state.session_factory() as session:
            row = session.get(UserKmf, after.id)
            row.revision = 9
            row.revision_class = 4
            session.commit()
        capped = self.client.post(
            "/api/knightmareFrameCustomize/enforce/revision",
            headers={"X-Request-Id": "official-kmf-cap"},
            json={"userKnightmareFrameCustomizeId": self.customize_id},
        )
        self.assertEqual(capped.status_code, 400, capped.text)
        self.assertEqual(self._row().revision, 9)


if __name__ == "__main__":
    unittest.main()
