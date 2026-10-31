"""Persist selectable-pool pickup choices."""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import UserGachaSelection


class GachaSelectionError(ValueError):
    pass


def _schedule(path, schedule_id):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    schedule = data.get("schedules", {}).get(str(int(schedule_id)))
    if schedule is not None:
        return schedule
    catalog = Path(path).parent / "gacha_selectable_catalog.json"
    if catalog.is_file():
        captured = json.loads(catalog.read_text(encoding="utf-8"))
        for row in captured.get("schedules", []):
            if int(row.get("id", 0)) == int(schedule_id):
                return row
    raise KeyError(schedule_id)


def save_selection(
    session: Session,
    fixture_path,
    user_id: str,
    schedule_id: int,
    card_ids: list[int],
) -> dict:
    try:
        schedule = _schedule(fixture_path, schedule_id)
    except KeyError as error:
        raise GachaSelectionError("Unknown gacha schedule") from error
    if schedule.get("gachaType") != "SELECTABLE":
        raise GachaSelectionError("Gacha schedule is not selectable")
    group = schedule.get("gachaGroup") or {}
    group_id = int(group.get("gachaGroupId") or group.get("id") or 0)
    required = int(group.get("value") or 0)
    if group_id <= 0 or required <= 0:
        raise GachaSelectionError("Selectable gacha group is invalid")

    normalized = list(dict.fromkeys(int(card_id) for card_id in card_ids))
    if len(normalized) != len(card_ids) or len(normalized) != required:
        raise GachaSelectionError("Unexpected pickup card count")
    allowed = {
        int(row["id"])
        for row in schedule.get("selectableCardList") or []
    }
    if not set(normalized).issubset(allowed):
        raise GachaSelectionError("Pickup card is not selectable")

    row = session.get(UserGachaSelection, (user_id, int(schedule_id)))
    if row is None:
        row = UserGachaSelection(
            user_id=user_id,
            schedule_id=int(schedule_id),
            group_id=group_id,
            card_ids=normalized,
        )
        session.add(row)
    else:
        row.group_id = group_id
        row.card_ids = normalized
    session.commit()
    return {
        "resultCode": "success",
        "gachaScheduleId": int(schedule_id),
        "gachaGroupId": group_id,
        "cardIds": normalized,
    }


def user_gacha_groups(session: Session, user_id: str) -> list[dict]:
    rows = session.execute(
        select(UserGachaSelection).where(
            UserGachaSelection.user_id == user_id
        ).order_by(UserGachaSelection.schedule_id)
    ).scalars().all()
    return [
        {
            "gachaScheduleId": row.schedule_id,
            "gachaGroupId": row.group_id,
            "cardIds": list(row.card_ids or []),
        }
        for row in rows
    ]
