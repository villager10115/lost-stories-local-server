from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from cgls.app import (
    LOCAL_FREE_MONEY_SHOP_ID,
    LOCAL_FREE_MONEY_SHOP_ITEM_ID,
    LOCAL_FREE_MONEY_TARGET_USER,
    create_app,
)
from cgls.models import User, UserWallet
from cgls.models import UserBootstrapState


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/gacha_1005.json"


class LocalShopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app(
            Path(self.tmp.name) / "state.sqlite", FIXTURE)
        with self.app.state.session_factory() as session:
            user = User(
                id=LOCAL_FREE_MONEY_TARGET_USER,
                display_name="local-shop-target",
            )
            user.wallet = UserWallet(
                free_sakuradite=300,
                paid_sakuradite=0,
                gold=0,
                skip_tickets=0,
                stamina=0,
                max_stamina=0,
            )
            user.bootstrap_state = UserBootstrapState(
                profile_id="shop-test",
                profile_version=1,
            )
            session.add(user)
            session.commit()
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.app.state.engine.dispose()
        self.tmp.cleanup()

    def test_free_paid_stone_purchase_preserves_free_stones(self):
        first = self.client.post("/api/shop/buy", json={
            "shopId": LOCAL_FREE_MONEY_SHOP_ID,
            "shopItemId": LOCAL_FREE_MONEY_SHOP_ITEM_ID,
            "num": 1,
        })
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["resultCode"], "success")
        state = self.client.get("/api/local/state").json()
        self.assertEqual(state["freeSakuradite"], 300)
        self.assertEqual(state["paidSakuradite"], 3000)

        second = self.client.post("/api/shop/buy", json={
            "shopId": LOCAL_FREE_MONEY_SHOP_ID,
            "shopItemId": LOCAL_FREE_MONEY_SHOP_ITEM_ID,
            "num": 2,
        })
        self.assertEqual(second.status_code, 200, second.text)
        state = self.client.get("/api/local/state").json()
        self.assertEqual(state["freeSakuradite"], 300)
        self.assertEqual(state["paidSakuradite"], 9000)
        self.assertEqual(
            second.json()["userShopItemList"][0]["num"], 3)

    def test_shop_rejects_unknown_product_and_invalid_quantity(self):
        unknown = self.client.post("/api/shop/buy", json={
            "shopId": 1, "shopItemId": 2, "num": 1})
        self.assertEqual(unknown.status_code, 400)
        invalid = self.client.post("/api/shop/buy", json={
            "shopId": LOCAL_FREE_MONEY_SHOP_ID,
            "shopItemId": LOCAL_FREE_MONEY_SHOP_ITEM_ID,
            "num": 0,
        })
        self.assertEqual(invalid.status_code, 422)


if __name__ == "__main__":
    unittest.main()
