"""Persistent local deck overlays.

The imported account snapshot is treated as read-only. Deck edits live in a
separate SQLite file so a failed save cannot mutate the preserved MyPage data.
Deck payloads keep the client's positional ``userCardIdN`` and
``userKnightmareFrameIdN`` fields.
"""

from __future__ import annotations

from contextlib import closing, nullcontext
from datetime import datetime, timedelta, timezone
import json
import copy
from pathlib import Path
import sqlite3


JST = timezone(timedelta(hours=9))
MAX_DECK_SLOTS = 10

DEFAULT_DECKS = (
    "MULTI_FRONT",
    "MAIN1",
    "MAIN2",
    "MAIN3",
    "MAIN4",
    "MAIN5",
    "MAIN6",
    "MAIN7",
    "MAIN8",
    "MAIN9",
    "MAIN10",
    "MAIN11",
    "MAIN12",
    "MAIN13",
    "MAIN14",
    "MAIN15",
    "ARENA",
)


class DeckStoreError(ValueError):
    pass


def _flatten_deck(deck_type, slots, name=None, created_at=None):
    row = {
        "deckType": deck_type,
        "createdAt": created_at or datetime.now(JST).isoformat(),
    }
    if name:
        row["name"] = name
    for index, slot in enumerate(slots[:MAX_DECK_SLOTS], 1):
        card_id = slot.get("userCardId") if slot else None
        kmf_id = slot.get("userKnightmareFrameId") if slot else None
        if card_id:
            row["userCardId%d" % index] = str(card_id)
        if kmf_id:
            row["userKnightmareFrameId%d" % index] = str(kmf_id)
    return row


def _slots_from_deck(deck):
    slots = []
    for index in range(1, MAX_DECK_SLOTS + 1):
        card_id = deck.get("userCardId%d" % index)
        kmf_id = deck.get("userKnightmareFrameId%d" % index)
        if card_id or kmf_id:
            slots.append({
                "userCardId": str(card_id) if card_id else None,
                "userKnightmareFrameId": str(kmf_id) if kmf_id else None,
            })
        else:
            slots.append(None)
    return slots


class DeckStore:
    VERSION = 1

    def __init__(self, database, seed_decks=None):
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.seed_decks = list(seed_decks or ())
        self.seed_order = [
            deck.get("deckType") for deck in self.seed_decks
            if isinstance(deck, dict) and isinstance(deck.get("deckType"), str)
        ]
        if not self.seed_order:
            self.seed_order = list(DEFAULT_DECKS)
        self.seed_order = list(dict.fromkeys(self.seed_order))
        with self._transaction() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, self.VERSION):
                raise ValueError("Unsupported deck database version")
            db.execute("""
                CREATE TABLE IF NOT EXISTS local_decks(
                    account TEXT NOT NULL,
                    deck_type TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    name TEXT,
                    slots_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(account, deck_type)
                )
            """)
            db.execute("PRAGMA user_version=1")

    def _connect(self):
        connection = sqlite3.connect(self.database, timeout=10)
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def _transaction(self):
        from contextlib import contextmanager

        @contextmanager
        def transaction():
            with closing(self._connect()) as db:
                with db:
                    db.execute("BEGIN IMMEDIATE")
                    yield db

        return transaction()

    def _ensure_seeded(self, db, account):
        existing = db.execute(
            "SELECT COUNT(*) FROM local_decks WHERE account=?", (account,)
        ).fetchone()[0]
        if existing:
            return
        now = datetime.now(JST).isoformat()
        for position, deck_type in enumerate(self.seed_order):
            source = next(
                (
                    deck for deck in self.seed_decks
                    if isinstance(deck, dict) and deck.get("deckType") == deck_type
                ),
                {},
            )
            slots = _slots_from_deck(source)
            db.execute(
                """
                INSERT INTO local_decks(
                    account, deck_type, position, name, slots_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    account,
                    deck_type,
                    position,
                    source.get("name"),
                    json.dumps(slots, ensure_ascii=False, allow_nan=False),
                    source.get("createdAt") or now,
                    now,
                ),
            )

    def list(self, account):
        with self._transaction() as db:
            self._ensure_seeded(db, account)
            rows = db.execute(
                """
                SELECT deck_type, name, slots_json, created_at
                FROM local_decks WHERE account=? ORDER BY position
                """,
                (account,),
            ).fetchall()
        return [
            {
                "deckType": deck_type,
                "name": name,
                "slots": json.loads(slots_json),
                "createdAt": created_at,
            }
            for deck_type, name, slots_json, created_at in rows
        ]

    def reconcile_ownership(self, account, models):
        """Remove captured foreign slots, preserving every locally owned pair.

        Older packages seeded their new account from GameConfig's captured
        decks. Restore the starter MAIN1 only if no owned pair remains there.
        This migration is idempotent and runs inside one SQLite transaction.
        """
        cards = {row["userCardId"] for row in models.get("userCardList", [])}
        kmfs = {row["userKnightmareFrameId"] for row in models.get("userKnightmareFrameList", [])}
        starters = {row["deckType"]: row for row in models.get("userDeckList", [])}
        def valid(slot):
            return (isinstance(slot, dict) and slot.get("userCardId") in cards
                    and slot.get("userKnightmareFrameId") in kmfs)
        with self._transaction() as db:
            self._ensure_seeded(db, account)
            for kind, raw in db.execute(
                    "SELECT deck_type, slots_json FROM local_decks WHERE account=?",
                    (account,)).fetchall():
                old = json.loads(raw)
                slots = [s if valid(s) else None for s in old]
                if not any(slots) and kind in starters:
                    slots = [s if valid(s) else None for s in _slots_from_deck(starters[kind])]
                if slots != old:
                    db.execute("UPDATE local_decks SET slots_json=? WHERE account=? AND deck_type=?",
                               (json.dumps(slots), account, kind))

    def save(self, account, deck_type, slots, name=None,
             owned_cards=None, owned_kmfs=None, *, _db=None, allow_empty=False):
        if not isinstance(deck_type, str) or deck_type not in self.seed_order:
            raise DeckStoreError("Unknown deck type")
        if not isinstance(slots, list) or not (0 if allow_empty else 1) <= len(slots) <= MAX_DECK_SLOTS:
            raise DeckStoreError("Deck must contain between 1 and 10 slots")
        if name is not None:
            if not isinstance(name, str) or len(name) > 32:
                raise DeckStoreError("Deck name is too long")
            name = name.strip() or None

        normalized = []
        seen_cards = set()
        seen_kmfs = set()
        for slot in slots:
            if slot is None:
                normalized.append(None)
                continue
            if not isinstance(slot, dict):
                raise DeckStoreError("Invalid deck slot")
            card_id = slot.get("userCardId")
            kmf_id = slot.get("userKnightmareFrameId")
            if not isinstance(card_id, str) or not isinstance(kmf_id, str):
                raise DeckStoreError("Each filled slot needs a pilot and KMF")
            card_id = card_id.strip()
            kmf_id = kmf_id.strip()
            if not card_id or not kmf_id or len(card_id) > 64 or len(kmf_id) > 64:
                raise DeckStoreError("Invalid deck member")
            if card_id in seen_cards:
                raise DeckStoreError("A pilot cannot occupy two slots")
            if kmf_id in seen_kmfs:
                raise DeckStoreError("A KMF cannot occupy two slots")
            if owned_cards is not None and card_id not in owned_cards:
                raise DeckStoreError("Pilot is not owned by this account")
            if owned_kmfs is not None and kmf_id not in owned_kmfs:
                raise DeckStoreError("KMF is not owned by this account")
            seen_cards.add(card_id)
            seen_kmfs.add(kmf_id)
            normalized.append({
                "userCardId": card_id,
                "userKnightmareFrameId": kmf_id,
            })

        filled = [slot for slot in normalized if slot]
        if not filled and not allow_empty:
            raise DeckStoreError("Deck cannot be empty")
        while normalized and normalized[-1] is None:
            normalized.pop()

        now = datetime.now(JST).isoformat()
        with (self._transaction() if _db is None else nullcontext(_db)) as db:
            self._ensure_seeded(db, account)
            current = db.execute(
                "SELECT created_at, name FROM local_decks WHERE account=? AND deck_type=?",
                (account, deck_type),
            ).fetchone()
            if current is None:
                raise DeckStoreError("Deck does not exist")
            if name is None:
                name = current[1]
            db.execute(
                """
                UPDATE local_decks
                SET name=?, slots_json=?, updated_at=?
                WHERE account=? AND deck_type=?
                """,
                (
                    name,
                    json.dumps(normalized, ensure_ascii=False, allow_nan=False),
                    now,
                    account,
                    deck_type,
                ),
            )
            created_at = current[0]
        return {
            "deckType": deck_type,
            "name": name,
            "slots": normalized,
            "createdAt": created_at,
        }

    def save_many(self, account, requests, owned_cards=None, owned_kmfs=None):
        if not isinstance(requests, list) or not 1 <= len(requests) <= len(self.seed_order):
            raise DeckStoreError("Expected a bounded deck list")
        result, seen = [], set()
        with self._transaction() as db:
            for request in requests:
                if not isinstance(request, dict):
                    raise DeckStoreError("Expected deck object")
                kind = request.get("deckType")
                if not isinstance(kind, str) or kind in seen:
                    raise DeckStoreError("Invalid or duplicate deck type")
                seen.add(kind)
                slots = request.get("slots")
                official = "userCardIdList" in request or "userKnightmareFrameIdList" in request
                if official:
                    cards, kmfs = request.get("userCardIdList"), request.get("userKnightmareFrameIdList")
                    if ("slots" in request or not isinstance(cards, list) or not isinstance(kmfs, list)
                            or len(cards) != len(kmfs) or len(cards) > MAX_DECK_SLOTS):
                        raise DeckStoreError("Expected paired pilot/KMF arrays")
                    slots = [None if c in (None, "") and k in (None, "") else
                             {"userCardId": c, "userKnightmareFrameId": k} for c, k in zip(cards, kmfs)]
                result.append(self.save(account, kind, slots, request.get("name"),
                                        owned_cards, owned_kmfs, _db=db, allow_empty=official))
        return result

    def rename(self, account, deck_type, name):
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 10:
            raise DeckStoreError("Deck name must contain 1-10 characters")
        if not isinstance(deck_type, str) or deck_type not in self.seed_order:
            raise DeckStoreError("Unknown deck type")
        with self._transaction() as db:
            self._ensure_seeded(db, account)
            row = db.execute("SELECT slots_json, created_at FROM local_decks WHERE account=? AND deck_type=?",
                             (account, deck_type)).fetchone()
            if row is None:
                raise DeckStoreError("Deck does not exist")
            db.execute("UPDATE local_decks SET name=?, updated_at=? WHERE account=? AND deck_type=?",
                       (name.strip(), datetime.now(JST).isoformat(), account, deck_type))
        return {"deckType": deck_type, "name": name.strip(), "slots": json.loads(row[0]), "createdAt": row[1]}

    def page_payload(self, account, account_models, extra_user_cards=(),
                     extra_user_kmfs=()):
        decks = self.list(account)
        user_cards = list(account_models.get("userCardList") or ())
        user_kmfs = list(account_models.get("userKnightmareFrameList") or ())
        known_cards = {
            item.get("userCardId") for item in user_cards
            if isinstance(item, dict)
        }
        known_kmfs = {
            item.get("userKnightmareFrameId") for item in user_kmfs
            if isinstance(item, dict)
        }
        for item in extra_user_cards:
            if (
                isinstance(item, dict)
                and item.get("userCardId")
                and item["userCardId"] not in known_cards
            ):
                user_cards.append(item)
                known_cards.add(item["userCardId"])
        for item in extra_user_kmfs:
            if (
                isinstance(item, dict)
                and item.get("userKnightmareFrameId")
                and item["userKnightmareFrameId"] not in known_kmfs
            ):
                user_kmfs.append(item)
                known_kmfs.add(item["userKnightmareFrameId"])

        owned_card_ids = {
            item.get("cardId") for item in user_cards
            if isinstance(item, dict)
        }
        owned_kmf_ids = {
            item.get("knightmareFrameId") for item in user_kmfs
            if isinstance(item, dict)
        }
        card_definitions = []
        for item in account_models.get("cardList") or ():
            if not isinstance(item, dict) or item.get("cardId") not in owned_card_ids:
                continue
            rarity = item.get("rarity")
            rarity_num = (
                rarity.get("rarityNum")
                if isinstance(rarity, dict)
                else rarity
            )
            card_definitions.append({
                "cardId": item.get("cardId"),
                "name": item.get("name") or item.get("jpName") or "",
                "rarity": {"rarityNum": int(rarity_num or 0)},
            })
        kmf_definitions = [
            {
                "knightmareFrameId": item.get("knightmareFrameId"),
                "name": item.get("name") or item.get("jpName") or "",
            }
            for item in account_models.get("knightmareFrameList") or ()
            if isinstance(item, dict)
            and item.get("knightmareFrameId") in owned_kmf_ids
        ]
        payload = {
            "resultCode": "success",
            "currentTime": datetime.now(JST).isoformat(),
            "user": {
                "id": "local-user",
                "snsUserId": "local-sns-user",
                "tutorialId": "",
                "partId": 0,
                "chapterId": 0,
                "relink": False,
            },
            "gameUser": account_models.get("gameUser") or {},
            "userDeckList": [
                _flatten_deck(
                    deck["deckType"],
                    deck["slots"],
                    deck.get("name"),
                    deck.get("createdAt"),
                )
                for deck in decks
            ],
            "userCardList": [
                {
                    "userCardId": item.get("userCardId"),
                    "cardId": item.get("cardId"),
                    "level": item.get("level", 1),
                    "cost": item.get("cost", 0),
                }
                for item in user_cards
                if isinstance(item, dict) and item.get("userCardId")
            ],
            "userKnightmareFrameList": [
                {
                    "userKnightmareFrameId": item.get("userKnightmareFrameId"),
                    "knightmareFrameId": item.get("knightmareFrameId"),
                }
                for item in user_kmfs
                if isinstance(item, dict) and item.get("userKnightmareFrameId")
            ],
            "userCardLimitBreakList": [],
            "userKnightmareFrameCustomizeList": [],
            "userCharaList": [],
            "userItemList": [],
            "userStatusList": [],
            "itemList": [],
            "charaList": [],
            "knightmareFrameCustomizeList": [],
            "eventList": [],
            "campaignList": [],
            "viewIconList": [],
            "backgroundGroupList": [],
            "userBackgroundGroupList": [],
            "cardList": card_definitions,
            "knightmareFrameList": kmf_definitions,
        }
        # These collections are merged into the Unity WebView's shared store.
        # Do not replace fully populated models with shortened editor DTOs.
        payload["userCardList"] = copy.deepcopy(user_cards)
        payload["userKnightmareFrameList"] = copy.deepcopy(user_kmfs)
        for key in ("userCardLimitBreakList", "userKnightmareFrameCustomizeList",
                    "userCharaList", "userItemList", "userStatusList", "itemList",
                    "charaList", "knightmareFrameCustomizeList", "eventList",
                    "campaignList", "viewIconList", "backgroundGroupList",
                    "userBackgroundGroupList"):
            payload[key] = copy.deepcopy(account_models.get(key, []))
        payload["cardList"] = [copy.deepcopy(row) for row in
            account_models.get("cardList", []) if row.get("cardId") in owned_card_ids]
        payload["knightmareFrameList"] = [copy.deepcopy(row) for row in
            account_models.get("knightmareFrameList", [])
            if row.get("knightmareFrameId") in owned_kmf_ids]
        # Preserve the full shared model required by the original card/KMF UI.
        full = copy.deepcopy(account_models)
        full.update(payload)
        for key in ("user", "affiliationList", "costumeList", "userCostumeList",
                    "userQuestList", "userCardAttributeRankList", "naviDeckList",
                    "naviDeckCardList", "naviDeckKnightmareFrameCustomizeList"):
            full[key] = copy.deepcopy(account_models.get(key, {} if key == "user" else []))
        return full


__all__ = [
    "DEFAULT_DECKS",
    "DeckStore",
    "DeckStoreError",
    "MAX_DECK_SLOTS",
]
