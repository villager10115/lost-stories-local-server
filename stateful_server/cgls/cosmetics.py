"""Persistent local costume ownership, bookmarks, and per-card dress-up."""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
import json
import threading
from pathlib import Path
from typing import Optional

from sqlalchemy import select, text

from .cosmetic_models import UserCardCostume, UserCharaBookmark, UserCostume
from .gacha import JST
from .models import UserPilot


class CostumeError(ValueError):
    pass


_OWNERSHIP_LOCK = threading.Lock()


@lru_cache(maxsize=8)
def _catalog(static_path: str):
    path = Path(static_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    costumes = {
        int(row["costumeId"]): row
        for row in data.get("costumeList", [])
        if isinstance(row, dict) and row.get("costumeId") is not None
    }
    cards = {
        int(row["cardId"]): row
        for row in data.get("cardList", [])
        if isinstance(row, dict) and row.get("cardId") is not None
    }
    return costumes, cards


def _catalog_for(masterdata_dir) -> Optional[tuple[dict, dict]]:
    if masterdata_dir is None:
        return None
    path = Path(masterdata_dir) / "pages" / "MyPage.static.json"
    if not path.is_file():
        return None
    return _catalog(str(path.resolve()))


def _pilot_character_id(cards, pilot):
    """Resolve a pilot's character even when its stored back-reference is stale."""
    card = cards.get(int(pilot.mst_pilot_id))
    if card is not None and card.get("charaId") is not None:
        return int(card["charaId"])
    return int(pilot.mst_chara_id or 0)


def ensure_costume_ownership(session, user_id, masterdata_dir):
    with _OWNERSHIP_LOCK:
        return _ensure_costume_ownership(session, user_id, masterdata_dir)


def _ensure_costume_ownership(session, user_id, masterdata_dir):
    """Grant character costumes compatible with characters already owned.

    Card artwork costumes remain tied to ownership of the corresponding card,
    matching the original client's ``defaultCostumeId`` lookup.
    """
    catalog = _catalog_for(masterdata_dir)
    if catalog is None:
        return 0
    costumes, _ = catalog
    _, cards = catalog
    owned_chara_ids = {
        chara_id
        for pilot in session.execute(
            select(UserPilot).where(UserPilot.user_id == user_id)
        ).scalars()
        if (chara_id := _pilot_character_id(cards, pilot))
    }
    existing = set(session.scalars(
        select(UserCostume.costume_id).where(UserCostume.user_id == user_id)
    ))
    wanted = sorted(
        costume_id
        for costume_id, row in costumes.items()
        if row.get("type") == "CHARA"
        and int(row.get("charaId", 0)) in owned_chara_ids
    )
    additions = [
        UserCostume(user_id=user_id, costume_id=costume_id)
        for costume_id in wanted
        if costume_id not in existing
    ]
    if additions:
        session.add_all(additions)
        session.commit()
    return len(additions)


def costume_state(session, user_id, masterdata_dir=None):
    granted = ensure_costume_ownership(session, user_id, masterdata_dir)
    costumes = session.execute(
        select(UserCostume)
        .where(UserCostume.user_id == user_id)
        .order_by(UserCostume.costume_id)
    ).scalars().all()
    bookmarks = session.scalars(
        select(UserCharaBookmark.chara_id).where(
            UserCharaBookmark.user_id == user_id
        )
    )
    selections = session.execute(
        select(UserCardCostume).where(UserCardCostume.user_id == user_id)
    ).scalars().all()
    return {
        "costumesGranted": granted,
        "costumes": [
            {
                "costumeId": row.costume_id,
                "createdAt": row.created_at.isoformat(),
            }
            for row in costumes
        ],
        "charaBookmarks": {
            str(chara_id): True for chara_id in bookmarks
        },
        "cardCostumes": {
            row.user_card_id: row.costume_id for row in selections
        },
    }


def set_bookmark(session, user_id, chara_id, bookmarked, masterdata_dir=None):
    if isinstance(chara_id, bool) or not isinstance(chara_id, int) or chara_id <= 0:
        raise CostumeError("Invalid character identifier")
    catalog = _catalog_for(masterdata_dir)
    cards = catalog[1] if catalog is not None else {}
    owned_chara_ids = {
        character_id
        for pilot in session.execute(
            select(UserPilot).where(UserPilot.user_id == user_id)
        ).scalars()
        if (character_id := _pilot_character_id(cards, pilot))
    }
    if chara_id not in owned_chara_ids:
        raise CostumeError("Character is not owned by this account")
    session.rollback()
    session.execute(text("BEGIN IMMEDIATE"))
    try:
        row = session.get(UserCharaBookmark, (user_id, chara_id))
        if bookmarked and row is None:
            session.add(UserCharaBookmark(user_id=user_id, chara_id=chara_id))
        elif not bookmarked and row is not None:
            session.delete(row)
        now = datetime.now(JST).isoformat()
        session.commit()
        return {
            "resultCode": "success",
            "currentTime": now,
            "userCharaList": [{
                "charaId": chara_id,
                "bookmarkCostume": bool(bookmarked),
            }],
        }
    except Exception:
        session.rollback()
        raise


def dress_up(session, user_id, user_card_id, costume_id, masterdata_dir):
    if (not isinstance(user_card_id, str)
            or not 1 <= len(user_card_id) <= 64):
        raise CostumeError("Invalid owned pilot identifier")
    ensure_costume_ownership(session, user_id, masterdata_dir)
    if costume_id is not None and (
        isinstance(costume_id, bool)
        or not isinstance(costume_id, int)
        or costume_id < 0
    ):
        raise CostumeError("Invalid costume identifier")
    catalog = _catalog_for(masterdata_dir)
    if catalog is None:
        raise CostumeError("Costume definitions are unavailable")
    costumes, cards = catalog
    pilot = session.scalar(select(UserPilot).where(
        UserPilot.user_id == user_id,
        UserPilot.user_card_id == user_card_id,
    ))
    if pilot is None:
        raise CostumeError("Pilot is not owned by this account")
    pilot_chara_id = _pilot_character_id(cards, pilot)
    selected = int(costume_id or 0)
    if selected:
        definition = costumes.get(selected)
        if definition is None:
            raise CostumeError("Unknown costume")
        if int(definition.get("charaId", 0)) != pilot_chara_id:
            raise CostumeError("Costume belongs to a different character")
        owned_costume = session.get(UserCostume, (user_id, selected))
        owned_card_ids = set(session.scalars(
            select(UserPilot.mst_pilot_id).where(UserPilot.user_id == user_id)
        ))
        owned_card_cosmetics = {
            int(card.get("defaultCostumeId", 0))
            for card_id, card in cards.items()
            if card_id in owned_card_ids
        }
        if (definition.get("type") == "CHARA" and owned_costume is None
                and selected not in owned_card_cosmetics):
            raise CostumeError("Costume is not owned by this account")
        if (definition.get("type") == "CARD"
                and selected not in owned_card_cosmetics):
            raise CostumeError("Costume card is not owned by this account")
    session.rollback()
    session.execute(text("BEGIN IMMEDIATE"))
    try:
        row = session.get(UserCardCostume, (user_id, user_card_id))
        if selected:
            if row is None:
                session.add(UserCardCostume(
                    user_id=user_id,
                    user_card_id=user_card_id,
                    costume_id=selected,
                ))
            else:
                row.costume_id = selected
        elif row is not None:
            session.delete(row)
        now = datetime.now(JST).isoformat()
        session.commit()
        return {
            "resultCode": "success",
            "currentTime": now,
            "userCardList": [{
                "userCardId": user_card_id,
                "cardId": pilot.mst_pilot_id,
                "costumeId": selected,
            }],
        }
    except Exception:
        session.rollback()
        raise
