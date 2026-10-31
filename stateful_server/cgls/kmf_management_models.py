from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class UserKmfDevelopment(Base):
    __tablename__ = "user_kmf_developments"
    __table_args__ = (
        CheckConstraint(
            "frame_no BETWEEN 1 AND 3",
            name="ck_user_kmf_development_frame",
        ),
    )

    user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    frame_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    knightmare_frame_id: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
