from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base
from .models import User, utc_now


class UserCostume(Base):
    __tablename__ = "user_costumes"

    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    costume_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )

    user: Mapped[User] = relationship(back_populates="costumes")


class UserCharaBookmark(Base):
    __tablename__ = "user_chara_bookmarks"

    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    chara_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )

    user: Mapped[User] = relationship(back_populates="chara_bookmarks")


class UserCardCostume(Base):
    __tablename__ = "user_card_costumes"
    __table_args__ = (
        UniqueConstraint("user_id", "user_card_id", name="uq_user_card_costume"),
    )

    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    user_card_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    costume_id: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )

    user: Mapped[User] = relationship(back_populates="card_costumes")
