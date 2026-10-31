from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from cgls.app import create_app
from cgls.models import User, UserBootstrapState, UserGameItem, UserWallet

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "gacha_1005.json"
TARGET = "00000000-0000-0000-0000-000000000000"


class ShopAccountTests(unittest.TestCase):
    def test_free_paid_stone_products_are_account_scoped_and_transactional(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(
                Path(directory) / "shop.sqlite", FIXTURE,
                masterdata_dir=Path("D:/LostStories_Offline/assets/masterdata"))
            with app.state.session_factory() as session:
                session.add(User(
                    id=TARGET,
                    display_name="shop-target",
                    wallet=UserWallet(
                        free_sakuradite=300,
                        paid_sakuradite=0,
                        gold=0,
                        skip_tickets=0,
                        stamina=0,
                        max_stamina=0,
                    ),
                    bootstrap_state=UserBootstrapState(
                        profile_id="shop-test", profile_version=1),
                ))
                session.add(UserGameItem(
                    user_id=TARGET, item_id="EVENT_1690_01", quantity=20))
                session.commit()
            with TestClient(app) as client:
                response = client.post("/api/shop/buy", json={
                    "shopId": 99001, "shopItemId": 990001, "num": 2})
                self.assertEqual(response.status_code, 200, response.text)
                body = response.json()
                quantities = {row["itemId"]: row["quantity"]
                              for row in body["userItemList"]}
                self.assertEqual(quantities["MONEY"], 6000)
                self.assertEqual(quantities["PRESENTED_MONEY"], 300)
                self.assertEqual(
                    body["userShopItemList"][0]["num"], 2)
                with app.state.session_factory() as session:
                    wallet = session.get(UserWallet, TARGET)
                    self.assertEqual(wallet.paid_sakuradite, 6000)
                    self.assertEqual(wallet.free_sakuradite, 300)
                    counter = session.get(
                        UserGameItem,
                        (TARGET, "LOCAL_SHOP_COUNT_990001"))
                    self.assertEqual(counter.quantity, 2)
                kmf = client.post("/api/shop/buy", json={
                    "shopId": 7, "shopItemId": 700001, "num": 1})
                self.assertEqual(kmf.status_code, 200, kmf.text)
                self.assertEqual(
                    kmf.json()["userKnightmareFrameList"][0]["knightmareFrameId"],
                    1001)
                bgm = client.post("/api/shop/buy", json={
                    "shopId": 5, "shopItemId": 500101, "num": 1})
                self.assertEqual(bgm.status_code, 200, bgm.text)
                self.assertIn("BGM_1001", {row["itemId"]
                    for row in bgm.json()["userItemList"]})
                token_item = client.post("/api/shop/buy", json={
                    "shopId": 1114, "shopItemId": 8119001, "num": 1})
                self.assertEqual(token_item.status_code, 200, token_item.text)
                token_quantities = {row["itemId"]: row["quantity"]
                    for row in token_item.json()["userItemList"]}
                self.assertEqual(token_quantities["EVENT_1690_01"], 0)
                self.assertEqual(
                    token_quantities["GACHA_RANK_4_TICKET_1690"], 1)
                with app.state.session_factory() as session:
                    wallet = session.get(UserWallet, TARGET)
                    self.assertEqual(wallet.paid_sakuradite, 2880)
                invalid = client.post("/api/shop/buy", json={
                    "shopId": 99001, "shopItemId": 1, "num": 1})
                self.assertEqual(invalid.status_code, 400)
            app.state.engine.dispose()

    def test_non_target_account_cannot_use_local_money_products(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(Path(directory) / "shop.sqlite", FIXTURE)
            with TestClient(app) as client:
                response = client.post("/api/shop/buy", json={
                    "shopId": 99001, "shopItemId": 990001, "num": 1})
                self.assertEqual(response.status_code, 400)
                self.assertIn("専用", response.json()["errorTxt"])
            app.state.engine.dispose()


if __name__ == "__main__":
    unittest.main()
