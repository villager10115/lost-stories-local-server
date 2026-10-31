"""Database-backed gacha transactions.

The pure mechanics live in :mod:`cgls.gacha`. This module loads the user's
persisted state, invokes the engine once, and commits every observable delta
with a draw log in a single transaction.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional
import random
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from .gacha import GachaEngine, GachaPool, GachaState, JST
from .bootstrap import ensure_local_user
from .models import (
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


class GachaServiceError(Exception):
    pass


UNLIMITED_TEN_PERK_ITEM_ID = "LOCAL_UNLIMITED_TEN_PULL"


class UserNotFound(GachaServiceError):
    pass


class GachaService:
    def __init__(self, session: Session, pool: GachaPool, user_id: str):
        self.session = session
        self.pool = pool
        self.user_id = user_id
        self.engine = GachaEngine(pool)

    def load_state(self) -> GachaState:
        user = self.session.get(User, self.user_id)
        if user is None:
            raise UserNotFound("user %r does not exist" % self.user_id)

        # Query the rows directly instead of walking relationship collections.
        # A service instance may run multiple draws in one session, and a
        # previously loaded collection would otherwise stay stale after the
        # first commit.
        wallet = self.session.get(UserWallet, self.user_id)
        if wallet is None:
            wallet = UserWallet(user_id=self.user_id)
            self.session.add(wallet)
            self.session.flush()

        def rows(model):
            return self.session.execute(
                select(model).where(model.user_id == self.user_id)
            ).scalars().all()

        return GachaState(
            free_sakuradite=wallet.free_sakuradite,
            paid_sakuradite=wallet.paid_sakuradite,
            items={row.item_id: row.quantity for row in rows(UserGameItem)},
            owned_cards={row.mst_pilot_id for row in rows(UserPilot)},
            owned_kmfs={row.mst_kmf_id for row in rows(UserKmf)},
            limit_break={
                row.card_id: row.quantity for row in rows(UserCardLimitBreak)
            },
            kmf_keys={
                row.knightmare_frame_id: row.quantity
                for row in rows(UserKmfKey)
            },
            points={
                row.gacha_schedule_id: row.point
                for row in rows(UserGachaPoint)
            },
            daily_used={
                row.gacha_kind_id: row.last_drawn_on
                for row in rows(UserGachaKind)
                if row.last_drawn_on
            },
        )

    def draw(
        self,
        bean_kind: str,
        seed: Optional[int] = None,
        now: Optional[datetime] = None,
    ) -> dict:
        kind = self.pool.kinds.get(bean_kind)
        if kind is None:
            raise GachaServiceError(
                "bean kind %r is not available for schedule %s"
                % (bean_kind, self.pool.schedule_id)
            )

        draw_seed = (
            int(seed)
            if seed is not None
            else random.SystemRandom().randrange(0, 2**31)
        )
        draw_time = (now or datetime.now(JST)).astimezone(JST)

        try:
            state = self.load_state()
            free_ten_draw = (
                kind.draw_count == 10
                and state.items.get(UNLIMITED_TEN_PERK_ITEM_ID, 0) > 0
            )
            response = self.engine.draw(
                state,
                bean_kind,
                rng=random.Random(draw_seed),
                now=draw_time,
                free_draw=free_ten_draw,
            )
            self._persist(
                state, response, kind, draw_seed, draw_time, free_ten_draw)
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        return response

    def _persist(
        self,
        state: GachaState,
        response: dict,
        kind,
        seed: int,
        now: datetime,
        free_draw: bool = False,
    ) -> None:
        user = self.session.get(User, self.user_id)
        if user is None:
            raise UserNotFound("user %r does not exist" % self.user_id)

        wallet = user.wallet
        if wallet is None:
            wallet = UserWallet(user_id=self.user_id)
            self.session.add(wallet)
        wallet.free_sakuradite = state.free_sakuradite
        wallet.paid_sakuradite = state.paid_sakuradite

        for item_id, quantity in state.items.items():
            row = self.session.get(UserGameItem, (self.user_id, item_id))
            if row is None:
                row = UserGameItem(
                    user_id=self.user_id,
                    item_id=item_id,
                    quantity=quantity,
                )
                self.session.add(row)
            else:
                row.quantity = quantity

        for schedule_id, point in state.points.items():
            row = self.session.get(
                UserGachaPoint, (self.user_id, schedule_id)
            )
            if row is None:
                row = UserGachaPoint(
                    user_id=self.user_id,
                    gacha_schedule_id=schedule_id,
                    point=point,
                    created_at=now,
                )
                self.session.add(row)
            else:
                row.point = point

        for card_id, quantity in state.limit_break.items():
            row = self.session.get(UserCardLimitBreak, (self.user_id, card_id))
            if row is None:
                row = UserCardLimitBreak(
                    user_id=self.user_id,
                    card_id=card_id,
                    quantity=quantity,
                    created_at=now,
                )
                self.session.add(row)
            else:
                row.quantity = quantity

        for kmf_id, quantity in state.kmf_keys.items():
            row = self.session.get(UserKmfKey, (self.user_id, kmf_id))
            if row is None:
                row = UserKmfKey(
                    user_id=self.user_id,
                    knightmare_frame_id=kmf_id,
                    quantity=quantity,
                    created_at=now,
                )
                self.session.add(row)
            else:
                row.quantity = quantity

        kind_row = self.session.get(
            UserGachaKind, (self.user_id, kind.gacha_kind_id)
        )
        if kind_row is None:
            kind_row = UserGachaKind(
                user_id=self.user_id,
                gacha_kind_id=kind.gacha_kind_id,
                schedule_id=self.pool.schedule_id,
                total_count=0,
                stock_count=0,
                created_at=now,
            )
            self.session.add(kind_row)
        kind_row.total_count += kind.draw_count
        if kind.type == "DAILY" and not free_draw:
            kind_row.stock_count = 0
            kind_row.last_drawn_on = now.date().isoformat()

        for card in response["gachaAnimation"]["cardList"]:
            card_id = int(card["cardId"])
            if card.get("isNew") and not self._has_pilot(card_id):
                self.session.add(
                    UserPilot(
                        user_id=self.user_id,
                        user_card_id=str(uuid.uuid4()),
                        mst_pilot_id=card_id,
                        mst_chara_id=None,
                        obtained_at=now,
                    )
                )
            kmf_id = card.get("knightmareFrameId")
            if kmf_id and card.get("isNewKnightmareFrame") and not self._has_kmf(int(kmf_id)):
                self.session.add(
                    UserKmf(
                        user_id=self.user_id,
                        user_kmf_id=str(uuid.uuid4()),
                        mst_kmf_id=int(kmf_id),
                        customization_id=card.get(
                            "firstKnightmareFrameCustomizeId"
                        ),
                        revision_class=1,
                        obtained_at=now,
                    )
                )

        self.session.add(
            GachaDrawLog(
                user_id=self.user_id,
                schedule_id=self.pool.schedule_id,
                bean_kind=kind.bean_kind,
                seed=seed,
                request_json={
                    "gachaScheduleId": self.pool.schedule_id,
                    "gachaBeanKind": kind.bean_kind,
                },
                response_json=response,
                created_at=now,
            )
        )
        self.session.flush()

    def _has_pilot(self, card_id: int) -> bool:
        return (
            self.session.execute(
                select(UserPilot.id).where(
                    UserPilot.user_id == self.user_id,
                    UserPilot.mst_pilot_id == card_id,
                )
            ).first()
            is not None
        )

    def _has_kmf(self, kmf_id: int) -> bool:
        return (
            self.session.execute(
                select(UserKmf.id).where(
                    UserKmf.user_id == self.user_id,
                    UserKmf.mst_kmf_id == kmf_id,
                )
            ).first()
            is not None
        )


__all__ = [
    "GachaService",
    "GachaServiceError",
    "UserNotFound",
    "ensure_local_user",
]
