"""Persistent gacha exchange-point redemption."""

from __future__ import annotations

import json
from pathlib import Path
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from .kmf_rules import revision_class_for_revision
from .models import (
    UserCardLimitBreak,
    UserGameItem,
    UserGachaExchange,
    UserGachaPoint,
    UserKmf,
    UserPilot,
    UserWallet,
)


class GachaExchangeError(ValueError):
    pass


def _read_page(masterdata_dir, name):
    path = Path(masterdata_dir) / "pages" / name
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_reward(code):
    parts = str(code).split("_")
    if len(parts) < 3:
        raise GachaExchangeError("Invalid reward code")
    quantity = int(parts[-1])
    reward_type = parts[0]
    generic_id = "_".join(parts[1:-1])
    return reward_type, generic_id, quantity


def _add_pilot(session, user_id, card_id, quantity):
    created = []
    for _ in range(quantity):
        pilot = session.execute(
            select(UserPilot).where(
                UserPilot.user_id == user_id,
                UserPilot.mst_pilot_id == card_id,
            )
        ).scalars().first()
        if pilot is None:
            pilot = UserPilot(
                user_id=user_id,
                user_card_id=str(uuid.uuid4()),
                mst_pilot_id=card_id,
                mst_chara_id=card_id // 1000,
                level=1,
                skill_levels=[],
                unlocked_feature_ids=[],
            )
            session.add(pilot)
        else:
            material = session.get(
                UserCardLimitBreak, (user_id, card_id))
            if material is None:
                material = UserCardLimitBreak(
                    user_id=user_id,
                    card_id=card_id,
                    quantity=15,
                )
                session.add(material)
            else:
                material.quantity += 15
        created.append(card_id)
    return created


def _add_kmf(session, user_id, masterdata_dir, kmf_id):
    customize = _read_page(
        masterdata_dir, "MyPage.static.json"
    ).get("knightmareFrameCustomizeList", [])
    options = sorted(
        (
            row for row in customize
            if int(row.get("knightmareFrameId", 0)) == int(kmf_id)
        ),
        key=lambda row: int(row.get("sortKey", 0)),
    )
    if not options:
        raise GachaExchangeError("KMF master definition not found")
    definition = options[0]
    existing = session.execute(
        select(UserKmf).where(
            UserKmf.user_id == user_id,
            UserKmf.mst_kmf_id == int(kmf_id),
        )
    ).scalars().first()
    if existing is not None:
        raise GachaExchangeError("KMF already owned")
    session.add(UserKmf(
        user_id=user_id,
        user_kmf_id=str(uuid.uuid4()),
        mst_kmf_id=int(kmf_id),
        customization_id=int(definition["knightmareFrameCustomizeId"]),
        revision=0,
        revision_class=revision_class_for_revision(0),
    ))


def _add_item(session, user_id, item_id, quantity):
    row = session.get(UserGameItem, (user_id, item_id))
    if row is None:
        row = UserGameItem(
            user_id=user_id,
            item_id=item_id,
            quantity=quantity,
        )
        session.add(row)
    else:
        row.quantity += quantity


def _result_state(session, user_id):
    points = session.execute(
        select(UserGachaPoint).where(UserGachaPoint.user_id == user_id)
    ).scalars().all()
    return {
        "userGachaPointList": [
            {
                "gachaScheduleId": row.gacha_schedule_id,
                "point": row.point,
                "createdAt": row.created_at.isoformat(),
            }
            for row in points
        ],
    }


def exchange(
    session: Session,
    user_id: str,
    masterdata_dir,
    exchange_id: int,
    num: int,
) -> dict:
    if masterdata_dir is None:
        raise GachaExchangeError("Gacha masterdata is not configured")
    if int(num) != 1:
        raise GachaExchangeError("Only one exchange at a time is supported")
    definitions = _read_page(
        masterdata_dir, "GachaTop.static.json"
    ).get("gachaExchangeList", [])
    definition = next(
        (row for row in definitions
         if int(row.get("gachaExchangeId", 0)) == int(exchange_id)),
        None,
    )
    if definition is None:
        raise GachaExchangeError("Gacha exchange not found")

    schedule_ids = [
        int(value)
        for value in str(definition.get("gachaScheduleIds", "")).split(",")
        if value
    ]
    need = int(definition.get("needGachaPoint", 0))
    point_row = session.execute(
        select(UserGachaPoint).where(
            UserGachaPoint.user_id == user_id,
            UserGachaPoint.gacha_schedule_id.in_(schedule_ids),
        )
    ).scalars().first()
    if point_row is None or point_row.point < need:
        raise GachaExchangeError("Not enough gacha points")

    usage = session.get(UserGachaExchange, (user_id, int(exchange_id)))
    if usage is None:
        usage = UserGachaExchange(
            user_id=user_id,
            exchange_id=int(exchange_id),
            used_count=0,
        )
        session.add(usage)
    usage.used_count += 1
    point_row.point -= need

    reward_type, generic_id, quantity = _parse_reward(
        definition["rewardCodes"])
    if reward_type == "CARD":
        _add_pilot(session, user_id, int(generic_id), quantity)
    elif reward_type == "KMF":
        _add_kmf(session, user_id, masterdata_dir, int(generic_id))
    elif reward_type == "ITEM":
        _add_item(session, user_id, generic_id, quantity)
    else:
        raise GachaExchangeError("Unsupported reward type")

    session.flush()
    result = _result_state(session, user_id)
    session.commit()
    return {
        "resultCode": "success",
        "gachaExchangeId": int(exchange_id),
        **result,
    }
