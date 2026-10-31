from datetime import datetime
from pathlib import Path
import tempfile
import unittest

from sqlalchemy import select

from cgls.db import create_database_engine, create_session_factory, initialize_database
from cgls.gacha import (
    GachaKind,
    GachaKindUnavailable,
    GachaPool,
    InsufficientFunds,
    JST,
    ProbabilityEntry,
    ProbabilitySet,
    load_fixture,
)
from cgls.gacha_service import (
    GachaService,
    UNLIMITED_TEN_PERK_ITEM_ID,
    ensure_local_user,
)
from cgls.models import (
    GachaDrawLog,
    User,
    UserCardLimitBreak,
    UserGameItem,
    UserGachaKind,
    UserGachaPoint,
    UserKmf,
    UserKmfKey,
    UserPilot,
    UserWallet,
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
    "firstKnightmareFrameCustomizeId": 400601,
}


def stub_pool(kind, cards):
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


class GachaServiceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.engine = create_database_engine(
            Path(self.directory.name) / "gacha.sqlite"
        )
        initialize_database(self.engine)
        self.session = create_session_factory(self.engine)()

        user = User(display_name="tester")
        user.wallet = UserWallet(
            free_sakuradite=1100,
            paid_sakuradite=0,
            gold=0,
            skip_tickets=0,
            stamina=0,
            max_stamina=0,
        )
        user.game_items.append(
            UserGameItem(item_id="GACHA_TICKET", quantity=13)
        )
        self.session.add(user)
        self.session.commit()
        self.user_id = user.id

    def tearDown(self):
        self.session.close()
        self.engine.dispose()
        self.directory.cleanup()

    def test_ticket_ten_draw_is_persisted_with_log(self):
        pool = load_fixture(FIXTURE, 1005)
        service = GachaService(self.session, pool, self.user_id)
        now = datetime(2026, 10, 18, 20, 30, tzinfo=JST)
        response = service.draw("RARE10", seed=20261018, now=now)

        self.assertEqual(len(response["gachaAnimation"]["cardList"]), 10)
        ticket = self.session.get(
            UserGameItem, (self.user_id, "GACHA_TICKET")
        )
        self.assertEqual(ticket.quantity, 3)
        kind = self.session.get(UserGachaKind, (self.user_id, 1008))
        self.assertIsNotNone(kind)
        self.assertEqual(kind.total_count, 10)

        logs = self.session.execute(select(GachaDrawLog)).scalars().all()
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].seed, 20261018)
        self.assertEqual(logs[0].bean_kind, "RARE10")
        self.assertEqual(
            len(logs[0].response_json["gachaAnimation"]["cardList"]), 10
        )

    def test_account_perk_allows_unlimited_free_ten_draws_only(self):
        self.session.add(UserGameItem(
            user_id=self.user_id,
            item_id=UNLIMITED_TEN_PERK_ITEM_ID,
            quantity=1,
        ))
        self.session.commit()
        service = GachaService(
            self.session, load_fixture(FIXTURE, 1005), self.user_id)
        now = datetime(2026, 10, 31, 0, 5, tzinfo=JST)

        for seed in (1, 2):
            response = service.draw("RARE10", seed=seed, now=now)
            self.assertEqual(
                len(response["gachaAnimation"]["cardList"]), 10)

        ticket = self.session.get(
            UserGameItem, (self.user_id, "GACHA_TICKET"))
        perk = self.session.get(
            UserGameItem, (self.user_id, UNLIMITED_TEN_PERK_ITEM_ID))
        self.assertEqual(ticket.quantity, 13)
        self.assertEqual(perk.quantity, 1)
        self.assertEqual(
            len(self.session.execute(select(GachaDrawLog)).scalars().all()), 2)

        # The account perk is intentionally limited to ten-draw kinds.
        service.draw("RARE", seed=3, now=now)
        self.session.refresh(ticket)
        self.assertEqual(ticket.quantity, 12)

    def test_insufficient_tickets_rolls_back(self):
        pool = load_fixture(FIXTURE, 1005)
        self.session.get(
            UserGameItem, (self.user_id, "GACHA_TICKET")
        ).quantity = 0
        self.session.commit()

        service = GachaService(self.session, pool, self.user_id)
        with self.assertRaises(InsufficientFunds):
            service.draw("RARE10", seed=1)
        self.assertEqual(
            self.session.execute(select(GachaDrawLog)).scalars().all(), []
        )
        self.assertEqual(
            self.session.get(
                UserGameItem, (self.user_id, "GACHA_TICKET")
            ).quantity,
            0,
        )

    def test_paid_draw_persists_wallet_and_point(self):
        kind = GachaKind(3348, 1796, "SELECTABLE", "1回スカウト", "MONEY", 300)
        pool = stub_pool(kind, [DUMMY_CARD])
        service = GachaService(self.session, pool, self.user_id)
        service.draw("SELECTABLE", seed=1)

        wallet = self.session.get(User, self.user_id).wallet
        self.assertEqual(wallet.free_sakuradite, 800)
        point = self.session.get(UserGachaPoint, (self.user_id, 1796))
        self.assertEqual(point.point, 1)
        self.assertEqual(
            len(self.session.execute(select(GachaDrawLog)).scalars().all()), 1
        )

    def test_duplicate_material_and_kmf_key_are_persisted(self):
        self.session.add(
            UserPilot(
                user_id=self.user_id,
                user_card_id="owned-303001",
                mst_pilot_id=303001,
                mst_chara_id=None,
            )
        )
        self.session.add(
            UserKmf(
                user_id=self.user_id,
                user_kmf_id="owned-4006",
                mst_kmf_id=4006,
            )
        )
        self.session.commit()

        kind = GachaKind(
            1007, 1005, "RARE", "1回スカウト", "ITEM", 1, "GACHA_TICKET"
        )
        service = GachaService(self.session, stub_pool(kind, [KMF_CARD]), self.user_id)
        response = service.draw("RARE", seed=1)
        card = response["gachaAnimation"]["cardList"][0]

        self.assertEqual(card["limitBreakNum"], 15)
        self.assertEqual(card["keyNum"], 1)
        limit_break = self.session.get(
            UserCardLimitBreak, (self.user_id, 303001)
        )
        key = self.session.get(UserKmfKey, (self.user_id, 4006))
        self.assertEqual(limit_break.quantity, 15)
        self.assertEqual(key.quantity, 1)

    def test_daily_kind_is_consumed_once(self):
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
        service = GachaService(self.session, stub_pool(kind, [DUMMY_CARD]), self.user_id)
        now = datetime(2026, 10, 18, 21, 0, tzinfo=JST)
        service.draw("DAILY", seed=1, now=now)

        row = self.session.get(UserGachaKind, (self.user_id, 1003))
        self.assertEqual(row.last_drawn_on, "2026-10-18")
        self.assertEqual(row.total_count, 1)
        with self.assertRaises(GachaKindUnavailable):
            service.draw("DAILY", seed=2, now=now)
        self.assertEqual(
            len(self.session.execute(select(GachaDrawLog)).scalars().all()), 1
        )

    def test_missing_user_fails(self):
        pool = load_fixture(FIXTURE, 1005)
        service = GachaService(self.session, pool, "missing-user")
        with self.assertRaises(Exception):
            service.draw("RARE10", seed=1)


if __name__ == "__main__":
    unittest.main()
