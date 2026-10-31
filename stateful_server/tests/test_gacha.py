from datetime import datetime
from pathlib import Path
import random
import unittest

from cgls.gacha import (
    GachaEngine,
    GachaKind,
    GachaKindUnavailable,
    GachaPool,
    GachaState,
    InsufficientFunds,
    JST,
    ProbabilityEntry,
    ProbabilitySet,
    load_fixture,
    restrict_pool,
)


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "gacha_1005.json"

DUMMY_CARD = {
    "cardId": 114001,
    "heroFlag": False,
    "rarity": 2,
    "jpName": "千葉凪沙",
    "enName": "Nagisa Chiba",
    "title": "日本解放戦線",
    "attribute": "KNIGHT",
}

KMF_CARD = {
    "cardId": 303001,
    "heroFlag": False,
    "rarity": 4,
    "jpName": "佐山リョウ",
    "enName": "Ryo Sayama",
    "title": "新しい仲間のために",
    "attribute": "ROOK",
    "knightmareFrameId": 4006,
    "knightmareFrameJpName": "アレクサンダ・ヴァリアント（リョウ機）",
    "firstKnightmareFrameCustomizeId": 400601,
}


def make_pool(kind, cards):
    entries = tuple(
        ProbabilityEntry(card=dict(card), weight=1000) for card in cards
    )
    normal = ProbabilitySet(
        display_name="通常",
        lottery_map={},
        entries=entries,
        total_weight=1000 * len(entries),
    )
    return GachaPool(
        schedule_id=kind.schedule_id,
        gacha_type="TEST",
        description="",
        kinds={kind.bean_kind: kind},
        probability_sets={"通常": normal},
        cards={int(card["cardId"]): dict(card) for card in cards},
    )


class FixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pool = load_fixture(FIXTURE, 1005)

    def test_probability_sets_match_capture(self):
        normal = self.pool.probability_sets["通常"]
        guaranteed = self.pool.probability_sets["★3以上確定時"]
        self.assertEqual(
            normal.lottery_map,
            {"CARD_4": 30, "CARD_3": 150, "CARD_2": 400, "CARD_1": 420},
        )
        self.assertEqual(guaranteed.lottery_map, {"CARD_4": 30, "CARD_3": 970})
        self.assertEqual(len(normal.entries), 227)
        # Zero-weight rows are filtered, so the guaranteed set keeps only
        # the 199 cards that can appear at rarity 3 or 4.
        self.assertEqual(len(guaranteed.entries), 199)
        self.assertTrue(
            all(entry.card["rarity"] >= 3 for entry in guaranteed.entries)
        )
        self.assertGreater(normal.total_weight, 0)

    def test_ticket_ten_draw_consumes_ten_and_marks_guaranteed_slot(self):
        state = GachaState(items={"GACHA_TICKET": 13})
        response = GachaEngine(self.pool).draw(
            state, "RARE10", rng=random.Random(1234)
        )
        cards = response["gachaAnimation"]["cardList"]
        self.assertEqual(len(cards), 10)
        self.assertEqual(state.items["GACHA_TICKET"], 3)
        self.assertNotIn("userGachaPointList", response)
        effects = response["gachaAnimation"]["effects"]
        self.assertEqual(effects["direction1"], 2)
        self.assertEqual(len(effects["direction2"]), 10)
        self.assertEqual(effects["direction2"][9][0], 1)
        self.assertGreaterEqual(effects["direction2"][9][1], 3)
        self.assertEqual(
            response["userItemList"][0]["itemId"], "GACHA_TICKET"
        )
        self.assertEqual(response["userItemList"][0]["quantity"], 3)

    def test_ticket_single_consumes_one(self):
        state = GachaState(items={"GACHA_TICKET": 15})
        response = GachaEngine(self.pool).draw(
            state, "RARE", rng=random.Random(7)
        )
        self.assertEqual(len(response["gachaAnimation"]["cardList"]), 1)
        self.assertEqual(state.items["GACHA_TICKET"], 14)
        self.assertNotIn("userGachaPointList", response)

    def test_restricted_four_star_pool_is_hundred_percent(self):
        four_star_pool = restrict_pool(self.pool, {4})
        state = GachaState(items={"GACHA_TICKET": 10})
        response = GachaEngine(four_star_pool).draw(
            state, "RARE10", rng=random.Random(9)
        )
        cards = response["gachaAnimation"]["cardList"]
        self.assertEqual(len(cards), 10)
        self.assertTrue(all(card["rarity"] == 4 for card in cards))

    def test_seed_reproduces_cards(self):
        engine = GachaEngine(self.pool)
        results = []
        for _ in range(2):
            state = GachaState(items={"GACHA_TICKET": 20})
            response = engine.draw(
                state, "RARE10", rng=random.Random(20261018)
            )
            results.append(
                [card["cardId"] for card in response["gachaAnimation"]["cardList"]]
            )
        self.assertEqual(results[0], results[1])

    def test_insufficient_tickets(self):
        state = GachaState(items={"GACHA_TICKET": 9})
        with self.assertRaises(InsufficientFunds):
            GachaEngine(self.pool).draw(
                state, "RARE10", rng=random.Random(1)
            )
        self.assertEqual(state.items["GACHA_TICKET"], 9)


class CostTests(unittest.TestCase):
    def test_paid_single_uses_free_sakuradite_first(self):
        kind = GachaKind(3348, 1796, "SELECTABLE", "1回スカウト", "MONEY", 300)
        engine = GachaEngine(make_pool(kind, [DUMMY_CARD]))
        state = GachaState(free_sakuradite=1100, paid_sakuradite=50)
        response = engine.draw(
            state, "SELECTABLE", rng=random.Random(1)
        )
        self.assertEqual(state.free_sakuradite, 800)
        self.assertEqual(state.paid_sakuradite, 50)
        self.assertEqual(state.points[1796], 1)
        items = {
            item["itemId"]: item["quantity"]
            for item in response["userItemList"]
        }
        self.assertEqual(items, {"PRESENTED_MONEY": 800})

    def test_daily_free_draw_only_once_per_day(self):
        kind = GachaKind(
            1003,
            1001,
            "DAILY",
            "1回スカウト",
            "FREE",
            0,
            type="DAILY",
            times=1,
        )
        engine = GachaEngine(make_pool(kind, [DUMMY_CARD]))
        state = GachaState()
        now = datetime(2026, 10, 18, 20, 0, tzinfo=JST)
        engine.draw(state, "DAILY", rng=random.Random(1), now=now)
        self.assertEqual(state.points[1001], 1)
        with self.assertRaises(GachaKindUnavailable):
            engine.draw(state, "DAILY", rng=random.Random(2), now=now)
        tomorrow = datetime(2026, 10, 19, 0, 1, tzinfo=JST)
        engine.draw(state, "DAILY", rng=random.Random(3), now=tomorrow)


class DuplicateTests(unittest.TestCase):
    def test_duplicate_card_and_kmf_key(self):
        kind = GachaKind(1007, 1005, "RARE", "1回スカウト", "ITEM", 1, "GACHA_TICKET")
        engine = GachaEngine(make_pool(kind, [KMF_CARD]))
        state = GachaState(
            items={"GACHA_TICKET": 1},
            owned_cards={303001},
            owned_kmfs={4006},
        )
        response = engine.draw(state, "RARE", rng=random.Random(1))
        card = response["gachaAnimation"]["cardList"][0]
        self.assertEqual(card["limitBreakNum"], 15)
        self.assertEqual(card["keyNum"], 1)
        self.assertEqual(state.limit_break[303001], 15)
        self.assertEqual(state.kmf_keys[4006], 1)
        self.assertEqual(
            response["userKnightmareFrameKeyList"][0]["knightmareFrameId"],
            4006,
        )

    def test_new_card_does_not_convert_to_material(self):
        kind = GachaKind(1007, 1005, "RARE", "1回スカウト", "ITEM", 1, "GACHA_TICKET")
        engine = GachaEngine(make_pool(kind, [KMF_CARD]))
        state = GachaState(items={"GACHA_TICKET": 1})
        response = engine.draw(state, "RARE", rng=random.Random(1))
        card = response["gachaAnimation"]["cardList"][0]
        self.assertTrue(card["isNew"])
        self.assertTrue(card["isNewKnightmareFrame"])
        self.assertNotIn("limitBreakNum", card)
        self.assertNotIn("keyNum", card)
        self.assertEqual(state.limit_break, {})
        self.assertEqual(state.kmf_keys, {})


if __name__ == "__main__":
    unittest.main()
