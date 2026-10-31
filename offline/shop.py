"""Standalone local-shop prototype. No network client or real payment integration."""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

PRODUCTS = {
    "demo_ticket": {"title": "演示招募券（非官方商品）", "items": {"demo_ticket": 1}},
}

LOCAL_FREE_MONEY_SHOP_ID = 99001
LOCAL_FREE_MONEY_PRODUCTS = {
    990001: {"paid": 3000, "free_cost": 0, "name": "氪金石补给 x3000"},
    990002: {"paid": 33000, "free_cost": 10, "name": "氪金石补给 x33000"},
    990003: {"paid": 360000, "free_cost": 100, "name": "氪金石补给 x360000"},
}


LOCAL_FREE_MONEY_TARGET_USER_ID = (
    "00000000-0000-0000-0000-000000000000"
)


def purchase_counter_id(shop_item_id):
    if int(shop_item_id) not in LOCAL_FREE_MONEY_PRODUCTS:
        raise ValueError("Unknown local money product")
    return "LOCAL_FREE_PAID_STONE_COUNT_%s" % int(shop_item_id)


def local_shop_models(purchase_counts, now):
    items = []
    user_rows = []
    for sort_key, (shop_item_id, definition) in enumerate(
            LOCAL_FREE_MONEY_PRODUCTS.items(), start=1):
        count = max(0, int(purchase_counts.get(shop_item_id, 0) or 0))
        items.append({
            "id": shop_item_id,
            "shopId": LOCAL_FREE_MONEY_SHOP_ID,
            "shopItemType": "ITEM",
            "genericId": "MONEY",
            "num": definition["paid"],
            "consumeType": "ITEM",
            "needItemId": "PRESENTED_MONEY",
            "needNumber": definition["free_cost"],
            "limitedNumber": None,
            "name": definition["name"],
            "description": "本地专用0真钱商品：使用免费石头兑换付费石头，不入DMM付费流程。",
            "recommend": True,
            "sortKey": sort_key,
            "noResetFlag": True,
            "openConditionGroupList": [],
        })
        user_rows.append({
            "shopItemId": shop_item_id,
            "num": count,
            "opened": True,
            "recentExchangedAt": now if count else None,
            "createdAt": now,
        })
    shop = {
        "shopId": LOCAL_FREE_MONEY_SHOP_ID,
        "name": "本地0真钱氪金石头",
        "shopType": "ITEM",
        "resetType": "NONE",
        "sortKey": 0,
        "schedule": {"displayStartDate": "常時", "displayCloseDate": ""},
        "shopItemList": items,
    }
    return {
        "localShopList": [shop],
        "localUserShopItemList": user_rows,
    }


class Shop:
    def __init__(self, database):
        self.database = str(database)
        Path(self.database).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS orders(
                    id TEXT PRIMARY KEY, product TEXT NOT NULL, result TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS inventory(
                    item TEXT PRIMARY KEY, quantity INTEGER NOT NULL CHECK(quantity >= 0));
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.database, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def inventory(self):
        with self.connect() as db:
            return dict(db.execute("SELECT item, quantity FROM inventory"))

    def claim(self, product, order_id):
        if product not in PRODUCTS:
            raise ValueError("Unknown product")
        if not isinstance(order_id, str) or not 1 <= len(order_id) <= 128:
            raise ValueError("Invalid order ID")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute(
                "SELECT product, result FROM orders WHERE id=?", (order_id,)
            ).fetchone()
            if previous:
                if previous[0] != product:
                    raise ValueError("Order ID belongs to another product")
                return json.loads(previous[1])
            result = {"offline": True, "order_id": order_id,
                      "product": product, "items": PRODUCTS[product]["items"]}
            for item, amount in result["items"].items():
                db.execute(
                    "INSERT INTO inventory VALUES (?, ?) ON CONFLICT(item) "
                    "DO UPDATE SET quantity=quantity+excluded.quantity", (item, amount)
                )
            db.execute("INSERT INTO orders VALUES (?, ?, ?)",
                       (order_id, product, json.dumps(result)))
            return result
