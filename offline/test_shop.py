from datetime import datetime
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from shop import LOCAL_FREE_MONEY_SHOP_ID, LOCAL_FREE_MONEY_PRODUCTS
from shop import Shop, local_shop_models


class ShopTests(unittest.TestCase):
    def test_persistence_and_retry(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'save.sqlite'
            shop = Shop(path)
            first = shop.claim('demo_ticket', 'order-1')
            self.assertEqual(first, shop.claim('demo_ticket', 'order-1'))
            self.assertEqual(Shop(path).inventory(), {'demo_ticket': 1})
            shop.claim('demo_ticket', 'order-2')
            self.assertEqual(shop.inventory(), {'demo_ticket': 2})

    def test_concurrent_retry(self):
        with tempfile.TemporaryDirectory() as root:
            shop = Shop(Path(root) / 'save.sqlite')
            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(lambda _: shop.claim('demo_ticket', 'same'), range(20)))
            self.assertEqual(shop.inventory(), {'demo_ticket': 1})

    def test_invalid_product(self):
        with tempfile.TemporaryDirectory() as root:
            shop = Shop(Path(root) / 'save.sqlite')
            with self.assertRaises(ValueError):
                shop.claim('unknown', 'order')
            self.assertEqual(shop.inventory(), {})

    def test_local_paid_stone_shop_has_visible_tab_and_no_purchase_limit(self):
        models = local_shop_models({}, datetime.now())
        shop = models["localShopList"][0]
        self.assertEqual(shop["shopId"], LOCAL_FREE_MONEY_SHOP_ID)
        self.assertEqual(shop["shopType"], "ITEM")
        self.assertEqual(
            len(shop["shopItemList"]), len(LOCAL_FREE_MONEY_PRODUCTS))
        self.assertTrue(all(
            item["limitedNumber"] is None
            for item in shop["shopItemList"]
        ))
        self.assertEqual(shop["shopItemList"][0]["needNumber"], 0)


if __name__ == '__main__':
    unittest.main()
