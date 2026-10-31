"""Persistent present-box grants and atomic item receipt."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import UserGameItem, UserPresent, UserWallet


class PresentError(ValueError):
    pass


SUPPORTED_ITEM_IDS = {"PRESENTED_MONEY"}
MAX_PENDING_PRESENTS = 200
MAX_PAGE_SIZE = 200


def _iso(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _client_present(row: UserPresent) -> dict:
    return {
        "id": row.present_id,
        "presentType": row.present_type,
        "itemId": row.item_id,
        "quantity": row.quantity,
        "displayName": row.display_name,
        "presentComment": row.present_comment,
        "createdAt": _iso(row.created_at),
        "expiredAt": _iso(row.expired_at),
        "receivedAt": _iso(row.received_at),
    }


def grant_present(
    session: Session,
    user_id: str,
    item_id: str,
    quantity: int,
    present_comment: str = "",
) -> UserPresent:
    if item_id not in SUPPORTED_ITEM_IDS:
        raise PresentError("Unsupported present item: %s" % item_id)
    quantity = int(quantity)
    if quantity <= 0:
        raise PresentError("Present quantity must be positive")
    pending = session.execute(
        select(func.count()).select_from(UserPresent).where(
            UserPresent.user_id == user_id,
            UserPresent.received_at.is_(None),
        )
    ).scalar_one()
    if pending >= MAX_PENDING_PRESENTS:
        raise PresentError("Present box capacity reached")
    now = datetime.now(timezone.utc)
    row = UserPresent(
        user_id=user_id,
        present_type="ITEM",
        item_id=item_id,
        quantity=quantity,
        display_name="\u30b5\u30af\u30e9\u30c0\u30a4\u30c8",
        present_comment=present_comment,
        created_at=now,
        expired_at=now + timedelta(days=3650),
    )
    session.add(row)
    session.commit()
    return row


def pending_present_count(session: Session, user_id: str) -> int:
    return session.execute(
        select(func.count()).select_from(UserPresent).where(
            UserPresent.user_id == user_id,
            UserPresent.received_at.is_(None),
        )
    ).scalar_one()


def present_page(
    session: Session,
    user_id: str,
    page: int = 1,
    history: bool = False,
    page_size: int = MAX_PAGE_SIZE,
) -> dict:
    page = int(page)
    page_size = int(page_size)
    if page < 1 or not 1 <= page_size <= MAX_PAGE_SIZE:
        raise PresentError("Invalid present page")
    condition = (
        UserPresent.received_at.is_not(None)
        if history else UserPresent.received_at.is_(None)
    )
    time_column = UserPresent.received_at if history else UserPresent.created_at
    total = session.execute(
        select(func.count()).select_from(UserPresent).where(
            UserPresent.user_id == user_id,
            condition,
        )
    ).scalar_one()
    rows = session.execute(
        select(UserPresent)
        .where(UserPresent.user_id == user_id, condition)
        .order_by(time_column.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).scalars().all()
    return {
        "presentCount": total,
        "presentCountPerPage": len(rows),
        "presentList": [_client_present(row) for row in rows],
    }


def receive_presents(
    session: Session,
    user_id: str,
    present_ids: list[str] | None = None,
    receive_all: bool = False,
    total: int | None = None,
) -> dict:
    query = select(UserPresent).where(
        UserPresent.user_id == user_id,
        UserPresent.received_at.is_(None),
    )
    if not receive_all:
        ids = list(dict.fromkeys(present_ids or []))
        if not ids:
            raise PresentError("No present IDs supplied")
        query = query.where(UserPresent.present_id.in_(ids))
    else:
        if total is not None and int(total) < 0:
            raise PresentError("Invalid total")
        query = query.order_by(UserPresent.created_at.asc()).limit(
            MAX_PENDING_PRESENTS)

    rows = session.execute(query).scalars().all()
    if not rows:
        return {
            "resultCode": "success",
            "receivedIds": [],
            "failed": True,
            "presentCount": 0,
        }

    wallet = session.get(UserWallet, user_id)
    if wallet is None:
        raise PresentError("Wallet not found")
    now = datetime.now(timezone.utc)
    for row in rows:
        if row.item_id == "PRESENTED_MONEY":
            wallet.free_sakuradite += row.quantity
        else:
            game_item = session.get(UserGameItem, (user_id, row.item_id))
            if game_item is None:
                game_item = UserGameItem(
                    user_id=user_id,
                    item_id=row.item_id,
                    quantity=row.quantity,
                )
                session.add(game_item)
            else:
                game_item.quantity += row.quantity
        row.received_at = now

    session.flush()
    pending = session.execute(
        select(func.count()).select_from(UserPresent).where(
            UserPresent.user_id == user_id,
            UserPresent.received_at.is_(None),
        )
    ).scalar_one()
    user_items = session.execute(
        select(UserGameItem).where(UserGameItem.user_id == user_id)
    ).scalars().all()
    item_list = {
        row.item_id: row.quantity for row in user_items
    }
    item_list["PRESENTED_MONEY"] = wallet.free_sakuradite
    session.commit()
    return {
        "resultCode": "success",
        "receivedIds": [row.present_id for row in rows],
        "receivedPresents": [_client_present(row) for row in rows],
        "failed": False,
        "presentCount": pending,
        "freeSakuradite": wallet.free_sakuradite,
        "userItemList": [
            {"itemId": item_id, "quantity": quantity}
            for item_id, quantity in sorted(item_list.items())
        ],
    }
