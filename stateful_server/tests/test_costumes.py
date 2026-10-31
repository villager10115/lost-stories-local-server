import json
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from cgls.app import create_app
from cgls.cosmetics import CostumeError, costume_state, set_bookmark
from cgls.gacha_service import ensure_local_user


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "gacha_1005.json"
MASTERDATA = Path(r"D:\LostStories_Offline\assets\masterdata")


@unittest.skipUnless(
    (MASTERDATA / "pages" / "MyPage.static.json").is_file(),
    "Preserved masterdata is not installed",
)
class CostumeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.database = Path(self.tmp.name) / "state.sqlite"
        self.app = create_app(
            self.database,
            FIXTURE,
            masterdata_dir=MASTERDATA,
        )
        self.client = TestClient(self.app)
        self.client.__enter__()
        with self.app.state.session_factory() as session:
            user = ensure_local_user(session)
            pilot = next(
                row for row in user.pilots
                if row.mst_pilot_id == 103004
            )
            self.user_card_id = pilot.user_card_id
            owned_card_ids = {row.mst_pilot_id for row in user.pilots}
        static = json.loads(
            (MASTERDATA / "pages" / "MyPage.static.json")
            .read_text(encoding="utf-8")
        )
        self.character_costume_id = next(
            row["costumeId"]
            for row in static["costumeList"]
            if row.get("type") == "CHARA" and row.get("charaId") == 103
        )
        self.other_character_costume_id = next(
            row["costumeId"]
            for row in static["costumeList"]
            if row.get("type") == "CHARA" and row.get("charaId") != 103
        )
        self.owned_card_costume_ids = {
            row["defaultCostumeId"]
            for row in static["cardList"]
            if row.get("cardId") in owned_card_ids
            and row.get("defaultCostumeId")
        }
        self.owned_card_costume_id = next(
            row["costumeId"]
            for row in static["costumeList"]
            if row.get("type") == "CARD"
            and row.get("costumeId") in self.owned_card_costume_ids
        )
        self.unowned_card_costume_id = next(
            row["costumeId"]
            for row in static["costumeList"]
            if row.get("type") == "CARD"
            and row.get("charaId") == 103
            and row.get("costumeId") not in self.owned_card_costume_ids
        )

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.app.state.engine.dispose()
        self.tmp.cleanup()

    def test_character_costumes_are_granted_once_for_owned_characters(self):
        first = self.client.get("/api/local/page-state")
        second = self.client.get("/api/local/page-state")
        self.assertEqual(first.status_code, 200)
        self.assertGreater(first.json()["costumesGranted"], 0)
        self.assertEqual(second.json()["costumesGranted"], 0)
        self.assertIn(
            self.character_costume_id,
            {row["costumeId"] for row in first.json()["costumes"]},
        )

    def test_stale_character_id_uses_catalog_mapping(self):
        with self.app.state.session_factory() as session:
            user = ensure_local_user(session)
            pilot = next(
                row for row in user.pilots if row.mst_pilot_id == 103004)
            pilot.mst_chara_id = None
            user_card_id = pilot.user_card_id
            session.commit()

        static = json.loads(
            (MASTERDATA / "pages" / "MyPage.static.json")
            .read_text(encoding="utf-8")
        )
        chara_id = 103
        costume_id = next(
            row["costumeId"]
            for row in static["costumeList"]
            if row.get("type") == "CHARA" and row.get("charaId") == chara_id
        )

        state = self.client.get("/api/local/page-state").json()
        self.assertIn(
            costume_id, {row["costumeId"] for row in state["costumes"]})
        bookmarked = self.client.post(
            "/api/chara/addBookmarkCostume", json={"charaId": chara_id})
        self.assertEqual(bookmarked.status_code, 200, bookmarked.text)
        removed = self.client.post(
            "/api/chara/removeBookmarkCostume", json={"charaId": chara_id})
        self.assertEqual(removed.status_code, 200, removed.text)
        self.assertFalse(
            removed.json()["userCharaList"][0]["bookmarkCostume"])
        selected = self.client.post("/api/card/costume/dressUp", json={
            "userCardId": user_card_id,
            "costumeId": costume_id,
        })
        self.assertEqual(selected.status_code, 200, selected.text)
        self.assertEqual(
            selected.json()["userCardList"][0]["costumeId"], costume_id)

    def test_dress_up_and_bookmark_survive_restart(self):
        selected = self.client.post("/api/card/costume/dressUp", json={
            "userCardId": self.user_card_id,
            "costumeId": self.character_costume_id,
        })
        self.assertEqual(selected.status_code, 200, selected.text)
        self.assertEqual(
            selected.json()["userCardList"][0]["costumeId"],
            self.character_costume_id,
        )
        bookmarked = self.client.post(
            "/api/chara/addBookmarkCostume", json={"charaId": 103})
        self.assertEqual(bookmarked.status_code, 200, bookmarked.text)
        self.assertTrue(
            bookmarked.json()["userCharaList"][0]["bookmarkCostume"])

        self.app.state.engine.dispose()
        self.app = create_app(
            self.database,
            FIXTURE,
            masterdata_dir=MASTERDATA,
        )
        with TestClient(self.app) as client:
            state = client.get("/api/local/page-state").json()
            self.assertEqual(
                state["cardCostumes"][self.user_card_id],
                self.character_costume_id,
            )
            self.assertTrue(state["charaBookmarks"]["103"])
            removed = client.post(
                "/api/chara/removeBookmarkCostume", json={"charaId": 103})
            self.assertEqual(removed.status_code, 200)
            self.assertFalse(
                removed.json()["userCharaList"][0]["bookmarkCostume"])

    def test_card_cosmetic_unlocks_from_owned_card(self):
        response = self.client.post("/api/card/costume/dressUp", json={
            "userCardId": self.user_card_id,
            "costumeId": self.owned_card_costume_id,
        })
        self.assertEqual(response.status_code, 200, response.text)
        state = self.client.get("/api/local/page-state").json()
        self.assertEqual(
            state["cardCostumes"][self.user_card_id],
            self.owned_card_costume_id,
        )

    def test_clear_and_invalid_cosmetics_are_transactional(self):
        self.client.get("/api/local/page-state")
        self.client.post("/api/card/costume/dressUp", json={
            "userCardId": self.user_card_id,
            "costumeId": self.character_costume_id,
        })
        cleared = self.client.post("/api/card/costume/dressUp", json={
            "userCardId": self.user_card_id,
        })
        self.assertEqual(cleared.status_code, 200, cleared.text)
        self.assertEqual(cleared.json()["userCardList"][0]["costumeId"], 0)
        self.assertNotIn(
            self.user_card_id,
            self.client.get("/api/local/page-state").json()["cardCostumes"],
        )

        for body in (
            {"userCardId": self.user_card_id, "costumeId": 999999},
            {
                "userCardId": self.user_card_id,
                "costumeId": self.other_character_costume_id,
            },
            {
                "userCardId": self.user_card_id,
                "costumeId": self.unowned_card_costume_id,
            },
            {
                "userCardId": "foreign-card",
                "costumeId": self.character_costume_id,
            },
        ):
            with self.subTest(body=body):
                response = self.client.post(
                    "/api/card/costume/dressUp", json=body)
                self.assertEqual(response.status_code, 400, response.text)
        self.assertFalse(
            self.client.get("/api/local/page-state").json()["cardCostumes"])

    def test_service_rejects_non_owned_character_bookmarks(self):
        with self.app.state.session_factory() as session:
            user = ensure_local_user(session)
            with self.assertRaisesRegex(CostumeError, "not owned"):
                set_bookmark(session, user.id, 999, True)
            first = costume_state(session, user.id, MASTERDATA)
            second = costume_state(session, user.id, MASTERDATA)
        self.assertGreater(first["costumesGranted"], 0)
        self.assertEqual(second["costumesGranted"], 0)


if __name__ == "__main__":
    unittest.main()
