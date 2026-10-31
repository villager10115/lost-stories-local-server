from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
import uuid

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utc_now():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    display_name: Mapped[Optional[str]] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )

    wallet: Mapped["UserWallet"] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False
    )
    pilots: Mapped[list["UserPilot"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    kmfs: Mapped[list["UserKmf"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    items: Mapped[list["UserItem"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    decks: Mapped[list["UserDeck"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    quest_progress: Mapped[list["UserQuestProgress"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    game_items: Mapped[list["UserGameItem"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    gacha_points: Mapped[list["UserGachaPoint"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    gacha_kinds: Mapped[list["UserGachaKind"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    card_limit_breaks: Mapped[list["UserCardLimitBreak"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    kmf_keys: Mapped[list["UserKmfKey"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    costumes: Mapped[list["UserCostume"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    chara_bookmarks: Mapped[list["UserCharaBookmark"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    card_costumes: Mapped[list["UserCardCostume"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    gacha_logs: Mapped[list["GachaDrawLog"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    presents: Mapped[list["UserPresent"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    gacha_selections: Mapped[list["UserGachaSelection"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    gacha_exchanges: Mapped[list["UserGachaExchange"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    bootstrap_state: Mapped[Optional["UserBootstrapState"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False
    )


class UserBootstrapState(Base):
    __tablename__ = "user_bootstrap_states"

    user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    profile_id: Mapped[str] = mapped_column(String(64))
    profile_version: Mapped[int] = mapped_column(Integer, default=1)
    seeded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )

    user: Mapped[User] = relationship(back_populates="bootstrap_state")


class MissionReceipt(Base):
    __tablename__ = "mission_receipts"

    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    challenge_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    period: Mapped[str] = mapped_column(String(16), primary_key=True)
    result: Mapped[dict] = mapped_column(JSON)


class ProgressionReceipt(Base):
    __tablename__ = "progression_receipts"

    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    request_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict] = mapped_column(JSON)


class LocalBattle(Base):
    __tablename__ = "local_battles"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), index=True)
    request_id: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    quest_id: Mapped[int] = mapped_column(Integer)
    period: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    start_response: Mapped[dict] = mapped_column(JSON)
    drop_rewards: Mapped[dict] = mapped_column(JSON)
    finish_response: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    __table_args__ = (UniqueConstraint("user_id", "request_id"),)


class LocalBattleProgress(Base):
    __tablename__ = "local_battle_progress"
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), primary_key=True)
    quest_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    state: Mapped[dict] = mapped_column(JSON)


class UserWallet(Base):
    __tablename__ = "user_wallets"
    __table_args__ = (
        CheckConstraint("free_sakuradite >= 0", name="ck_wallet_free_nonnegative"),
        CheckConstraint("paid_sakuradite >= 0", name="ck_wallet_paid_nonnegative"),
        CheckConstraint("gold >= 0", name="ck_wallet_gold_nonnegative"),
        CheckConstraint("skip_tickets >= 0", name="ck_wallet_skip_nonnegative"),
        CheckConstraint("stamina >= 0", name="ck_wallet_stamina_nonnegative"),
        CheckConstraint("max_stamina >= 0", name="ck_wallet_max_stamina_nonnegative"),
    )

    user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    free_sakuradite: Mapped[int] = mapped_column(Integer, default=0)
    paid_sakuradite: Mapped[int] = mapped_column(Integer, default=0)
    gold: Mapped[int] = mapped_column(BigInteger, default=0)
    skip_tickets: Mapped[int] = mapped_column(Integer, default=0)
    stamina: Mapped[int] = mapped_column(Integer, default=0)
    max_stamina: Mapped[int] = mapped_column(Integer, default=0)
    stamina_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )

    user: Mapped[User] = relationship(back_populates="wallet")


class UserPilot(Base):
    __tablename__ = "user_pilots"
    __table_args__ = (
        UniqueConstraint("user_id", "mst_pilot_id", name="uq_user_pilot"),
        CheckConstraint("level >= 1", name="ck_pilot_level"),
        CheckConstraint("experience >= 0", name="ck_pilot_experience"),
        CheckConstraint("limit_break BETWEEN 0 AND 4", name="ck_pilot_limit_break"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    user_card_id: Mapped[Optional[str]] = mapped_column(String(64), unique=True)
    mst_pilot_id: Mapped[int] = mapped_column(Integer, index=True)
    mst_chara_id: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    level: Mapped[int] = mapped_column(Integer, default=1)
    experience: Mapped[int] = mapped_column(Integer, default=0)
    awakening_level: Mapped[int] = mapped_column(Integer, default=0)
    limit_break: Mapped[int] = mapped_column(Integer, default=0)
    bonds_level: Mapped[int] = mapped_column(Integer, default=0)
    bonds_point: Mapped[int] = mapped_column(Integer, default=0)
    skill_levels: Mapped[list[int]] = mapped_column(JSON, default=list)
    unlocked_feature_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    obtained_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )

    user: Mapped[User] = relationship(back_populates="pilots")

class UserCardAttributeRank(Base):
    __tablename__ = "user_card_attribute_ranks"
    __table_args__ = (
        CheckConstraint("level >= 1", name="ck_card_attribute_rank_level"),
        CheckConstraint("experience >= 0", name="ck_card_attribute_rank_exp"),
    )

    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    attribute: Mapped[str] = mapped_column(String(16), primary_key=True)
    level: Mapped[int] = mapped_column(Integer, default=1)
    experience: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class UserKmf(Base):
    __tablename__ = "user_kmfs"
    __table_args__ = (
        UniqueConstraint("user_id", "user_kmf_id", name="uq_user_kmf"),
        CheckConstraint(
            "revision_class BETWEEN 1 AND 4",
            name="ck_user_kmf_revision_class",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    user_kmf_id: Mapped[str] = mapped_column(String(64), index=True)
    mst_kmf_id: Mapped[int] = mapped_column(Integer, index=True)
    customization_id: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    upgrade_ranks: Mapped[dict] = mapped_column(JSON, default=dict)
    skill_point: Mapped[int] = mapped_column(Integer, default=0)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    revision_class: Mapped[int] = mapped_column(Integer, default=1)
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    is_in_storage: Mapped[bool] = mapped_column(Boolean, default=False)
    obtained_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )

    user: Mapped[User] = relationship(back_populates="kmfs")


class UserItem(Base):
    __tablename__ = "user_items"
    __table_args__ = (
        UniqueConstraint("user_id", "mst_item_id", name="uq_user_item"),
        CheckConstraint("count >= 0", name="ck_user_item_count"),
    )

    user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    mst_item_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    count: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    user: Mapped[User] = relationship(back_populates="items")


class UserDeck(Base):
    __tablename__ = "user_decks"
    __table_args__ = (
        CheckConstraint("deck_no BETWEEN 1 AND 10", name="ck_deck_number"),
    )

    user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    deck_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    deck_name: Mapped[str] = mapped_column(String(64), default="")
    slots: Mapped[list[dict]] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    user: Mapped[User] = relationship(back_populates="decks")


class UserQuestProgress(Base):
    __tablename__ = "user_quest_progress"
    __table_args__ = (
        CheckConstraint("best_stars BETWEEN 0 AND 3", name="ck_quest_stars"),
    )

    user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    quest_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    best_stars: Mapped[int] = mapped_column(Integer, default=0)
    clear_flags: Mapped[list[bool]] = mapped_column(JSON, default=list)
    cleared_count: Mapped[int] = mapped_column(Integer, default=0)
    first_cleared_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    user: Mapped[User] = relationship(back_populates="quest_progress")


class UserGameItem(Base):
    """String-keyed game items such as GACHA_TICKET.

    UserItem stays int-keyed for master item rows. Gacha costs use string
    item IDs, so they need a separate table rather than a lossy mapping.
    """

    __tablename__ = "user_game_items"
    __table_args__ = (
        UniqueConstraint("user_id", "item_id", name="uq_user_game_item"),
        CheckConstraint("quantity >= 0", name="ck_user_game_item_quantity"),
    )

    user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    item_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    quantity: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    user: Mapped[User] = relationship(back_populates="game_items")


class UserPresent(Base):
    __tablename__ = "user_presents"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_present_quantity"),
    )

    present_id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    present_type: Mapped[str] = mapped_column(String(16), default="ITEM")
    item_id: Mapped[str] = mapped_column(String(64), index=True)
    quantity: Mapped[int] = mapped_column(Integer)
    display_name: Mapped[str] = mapped_column(String(128))
    present_comment: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    expired_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    received_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )

    user: Mapped[User] = relationship(back_populates="presents")


class UserGachaSelection(Base):
    __tablename__ = "user_gacha_selections"

    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    schedule_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(Integer)
    card_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    user: Mapped[User] = relationship(back_populates="gacha_selections")


class UserGachaExchange(Base):
    __tablename__ = "user_gacha_exchanges"

    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    exchange_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    user: Mapped[User] = relationship(back_populates="gacha_exchanges")


class UserGachaPoint(Base):
    __tablename__ = "user_gacha_points"
    __table_args__ = (
        CheckConstraint("point >= 0", name="ck_gacha_point_nonnegative"),
    )

    user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    gacha_schedule_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    point: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    user: Mapped[User] = relationship(back_populates="gacha_points")


class UserGachaKind(Base):
    __tablename__ = "user_gacha_kinds"
    __table_args__ = (
        CheckConstraint("total_count >= 0", name="ck_gacha_kind_total"),
        CheckConstraint("stock_count >= 0", name="ck_gacha_kind_stock"),
    )

    user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    gacha_kind_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    schedule_id: Mapped[int] = mapped_column(Integer, index=True)
    total_count: Mapped[int] = mapped_column(Integer, default=0)
    stock_count: Mapped[int] = mapped_column(Integer, default=0)
    last_drawn_on: Mapped[Optional[str]] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    user: Mapped[User] = relationship(back_populates="gacha_kinds")


class UserCardLimitBreak(Base):
    __tablename__ = "user_card_limit_breaks"
    __table_args__ = (
        CheckConstraint("quantity >= 0", name="ck_card_limit_break"),
    )

    user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    card_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    user: Mapped[User] = relationship(back_populates="card_limit_breaks")


class UserKmfKey(Base):
    __tablename__ = "user_kmf_keys"
    __table_args__ = (
        CheckConstraint("quantity >= 0", name="ck_kmf_key_nonnegative"),
    )

    user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    knightmare_frame_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    user: Mapped[User] = relationship(back_populates="kmf_keys")


class GachaDrawLog(Base):
    __tablename__ = "gacha_draw_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    schedule_id: Mapped[int] = mapped_column(Integer, index=True)
    bean_kind: Mapped[str] = mapped_column(String(32))
    seed: Mapped[int] = mapped_column(BigInteger)
    request_json: Mapped[dict] = mapped_column(JSON, default=dict)
    response_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )

    user: Mapped[User] = relationship(back_populates="gacha_logs")
