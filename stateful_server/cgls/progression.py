"""Limit-break costs verified against preserved rarity tables and official trace.

The web client already sends X-Request-Id. Reusing that identifier replays a
committed response; a new identifier is a new intentional operation.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

from sqlalchemy import select, text

from .battle_data import pilot_skills, pilot_stats
from .models import (
    ProgressionReceipt,
    UserCardAttributeRank,
    UserCardLimitBreak,
    UserGameItem,
    UserPilot,
    User,
    UserWallet,
)

RULES = json.loads((Path(__file__).resolve().parents[1] / "fixtures" /
                   "limit_break_rules.json").read_text(encoding="utf-8"))
CARD_PROGRESSION = json.loads((Path(__file__).resolve().parents[1] / "fixtures" /
                              "card_progression.json").read_text(encoding="utf-8"))
ITEM_EXP = CARD_PROGRESSION["itemExpArr"]
EXP_TABLE = CARD_PROGRESSION["expArr"]
BONDS_THRESHOLDS = CARD_PROGRESSION["bondsThresholds"]
JST = timezone(timedelta(hours=9))
CARD_ATTRIBUTES = ("KING", "BISHOP", "ROOK", "KNIGHT", "STAR", "QUEEN")


class ProgressionError(ValueError):
    pass


def _validate_request_id(request_id):
    if (not isinstance(request_id, str) or not 1 <= len(request_id) <= 128
            or not request_id.isascii() or not request_id.isprintable()
            or not request_id.strip()):
        raise ProgressionError("X-Request-Id is required")


def _fingerprint(action, user_card_id, payload):
    return hashlib.sha256(json.dumps(
        [action, user_card_id, payload],
        sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()


def _pilot_response(pilot, card=None):
    result = {
        "userCardId": pilot.user_card_id,
        "cardId": pilot.mst_pilot_id,
        "lbCount": pilot.limit_break,
        "revision": pilot.awakening_level,
        "revisionClass": min(6, max(0, pilot.awakening_level) // 3 + 1),
        "level": pilot.level,
        "experience": pilot.experience,
        "bondsLevel": pilot.bonds_level,
        "bondsPoint": pilot.bonds_point,
        "unlockedFeatureIdList": list(pilot.unlocked_feature_ids or []),
    }
    if card is not None:
        result.update(pilot_stats(card, pilot.level, pilot.awakening_level))
        result.update(pilot_skills(card, pilot))
        result.update({
            "charaId": card.get("charaId", pilot.mst_chara_id),
            "relocationTime": int(card.get("relocationTime", 60000)),
            "expeditionDeadFlg": False,
            "isNew": False,
            "isArchiveNew": False,
            "favorite": False,
            "createdAt": pilot.obtained_at.isoformat() if pilot.obtained_at else None,
            "bonusList": [],
        })
    else:
        skills = pilot.skill_levels or []
        result.update({
            "cardSkillLevel1": skills[0] if len(skills) > 0 else 1,
            "cardSkillLocked1": False,
            "cardSkillLevel2": skills[1] if len(skills) > 1 else 1,
            "cardSkillLocked2": False,
        })
    return result


def _item_response(row, now):
    return {
        "itemId": row.item_id,
        "environmentId": "COMMON",
        "quantity": row.quantity,
        "total": 0,
        "createdAt": now,
    }


def _add_experience(level, experience, amount, max_level, table):
    if level >= max_level:
        return level, 0
    experience += amount
    while level < max_level:
        required = table[level] - table[level - 1]
        if experience < required:
            break
        experience -= required
        level += 1
    if level >= max_level:
        experience = 0
    return level, experience


def _add_bonds(level, points, amount):
    points += amount
    while level < 5:
        threshold = 100 if level == 0 else BONDS_THRESHOLDS[level]
        if points < threshold:
            break
        points -= threshold
        level += 1
    if level >= 5:
        points = 0
    return level, points


def _attribute_rank_threshold(level):
    return int(level) // 5 + 1


def _add_attribute_rank_experience(level, experience, amount):
    level = max(1, int(level))
    experience = max(0, int(experience)) + max(0, int(amount))
    while experience >= _attribute_rank_threshold(level):
        experience -= _attribute_rank_threshold(level)
        level += 1
    return level, experience


def _attribute_rank_response(row):
    return {
        "attribute": row.attribute,
        "level": row.level,
        "nextCardAttributeRank": {
            "id": row.level + 1,
            "exp": _attribute_rank_threshold(row.level),
        },
        "exp": row.experience,
        "createdAt": row.created_at.isoformat() if row.created_at else None,
    }


def card_attribute_rank_state(session, user_id):
    rows = session.execute(
        select(UserCardAttributeRank).where(
            UserCardAttributeRank.user_id == user_id)
    ).scalars().all()
    by_attribute = {row.attribute: row for row in rows}
    user = session.get(User, user_id)
    created_at = (
        user.created_at.isoformat() if user and user.created_at
        else datetime.now(JST).isoformat()
    )
    result = []
    for attribute in CARD_ATTRIBUTES:
        row = by_attribute.get(attribute)
        if row is None:
            result.append({
                "attribute": attribute,
                "level": 1,
                "nextCardAttributeRank": {"id": 2, "exp": 1},
                "exp": 0,
                "createdAt": created_at,
            })
        else:
            result.append(_attribute_rank_response(row))
    return result


def _feature_cost(feature):
    item = feature.get("cardFeatureItem")
    if not isinstance(item, dict):
        raise ProgressionError("Missing pilot feature cost definition")
    gold = item.get("needGold", 0)
    if not isinstance(gold, int) or isinstance(gold, bool) or gold < 0:
        raise ProgressionError("Invalid pilot feature GOLD cost")

    unique_quantity = item.get("needLimitBreakQuantity")
    if unique_quantity is not None:
        if (not isinstance(unique_quantity, int)
                or isinstance(unique_quantity, bool)
                or unique_quantity <= 0):
            raise ProgressionError("Invalid pilot feature limit-break cost")
        if any(item.get("needItemId%s" % index) is not None
               or item.get("needQuantity%s" % index) is not None
               for index in range(1, 4)):
            raise ProgressionError("Ambiguous pilot feature cost definition")
        return gold, unique_quantity, {}

    material_costs = {}
    for index in range(1, 4):
        item_id = item.get("needItemId%s" % index)
        quantity = item.get("needQuantity%s" % index)
        if item_id is None and quantity is None:
            continue
        if (not isinstance(item_id, str) or not item_id
                or not isinstance(quantity, int)
                or isinstance(quantity, bool) or quantity <= 0):
            raise ProgressionError("Invalid pilot feature material definition")
        material_costs[item_id] = material_costs.get(item_id, 0) + quantity
    return gold, None, material_costs


class FeatureService:
    def __init__(self, sessions, user_id, cards):
        self.sessions = sessions
        self.user_id = user_id
        self.cards = cards or {}

    def apply(self, user_card_id, card_feature_id, request_id):
        _validate_request_id(request_id)
        if not isinstance(user_card_id, str) or not 1 <= len(user_card_id) <= 64:
            raise ProgressionError("Invalid owned pilot identifier")
        if (not isinstance(card_feature_id, int)
                or isinstance(card_feature_id, bool)
                or card_feature_id <= 0):
            raise ProgressionError("Invalid pilot feature identifier")
        fingerprint = _fingerprint(
            "feature", user_card_id, {"cardFeatureId": card_feature_id})
        with self.sessions() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            try:
                receipt = session.get(
                    ProgressionReceipt, (self.user_id, request_id))
                if receipt:
                    if receipt.request_hash != fingerprint:
                        raise ProgressionError(
                            "Request ID was already used for a different action")
                    return receipt.response
                pilot = session.scalar(select(UserPilot).where(
                    UserPilot.user_id == self.user_id,
                    UserPilot.user_card_id == user_card_id))
                if pilot is None:
                    raise ProgressionError("Pilot is not owned by this account")
                card = self.cards.get(pilot.mst_pilot_id)
                if not isinstance(card, dict):
                    raise ProgressionError("Pilot masterdata is unavailable")
                feature_rows = card.get("cardFeatureList")
                if not isinstance(feature_rows, list):
                    raise ProgressionError("Pilot feature masterdata is unavailable")
                feature = next((
                    row for row in feature_rows
                    if isinstance(row, dict)
                    and row.get("cardFeatureId") == card_feature_id), None)
                if feature is None:
                    raise ProgressionError(
                        "Pilot feature does not belong to this pilot")

                unlocked = pilot.unlocked_feature_ids
                if not isinstance(unlocked, list):
                    raise ProgressionError("Pilot feature state is invalid")
                if card_feature_id in unlocked:
                    raise ProgressionError("Pilot feature is already unlocked")

                gold_cost, unique_quantity, material_costs = _feature_cost(feature)
                wallet = session.get(UserWallet, self.user_id)
                if wallet is None or wallet.gold < gold_cost:
                    raise ProgressionError("Not enough GOLD")

                materials = {}
                for item_id, quantity in material_costs.items():
                    material = session.get(
                        UserGameItem, (self.user_id, item_id))
                    if material is None or material.quantity < quantity:
                        raise ProgressionError(
                            "Not enough pilot feature materials")
                    materials[item_id] = material
                unique_material = None
                if unique_quantity is not None:
                    unique_material = session.get(
                        UserCardLimitBreak,
                        (self.user_id, pilot.mst_pilot_id))
                    if (unique_material is None
                            or unique_material.quantity < unique_quantity):
                        raise ProgressionError(
                            "Not enough pilot feature limit-break materials")

                wallet.gold -= gold_cost
                for item_id, quantity in material_costs.items():
                    materials[item_id].quantity -= quantity
                if unique_material is not None:
                    unique_material.quantity -= unique_quantity
                pilot.unlocked_feature_ids = unlocked + [card_feature_id]

                now = datetime.now(JST).isoformat()
                items = [{
                    "itemId": "GOLD", "environmentId": "COMMON",
                    "quantity": wallet.gold, "total": 0, "createdAt": now,
                }]
                items.extend(_item_response(materials[item_id], now)
                             for item_id in material_costs)
                response = {
                    "resultCode": "success",
                    "currentTime": now,
                    "userCardList": [_pilot_response(pilot, card)],
                    "userItemList": items,
                    "userCardLimitBreakList": ([
                        {"cardId": pilot.mst_pilot_id,
                         "quantity": unique_material.quantity}
                    ] if unique_material is not None else []),
                }
                session.add(ProgressionReceipt(
                    user_id=self.user_id, request_id=request_id,
                    request_hash=fingerprint, response=response))
                session.commit()
                return response
            except Exception:
                session.rollback()
                raise


class RevisionService:
    def __init__(self, sessions, user_id, cards):
        self.sessions = sessions
        self.user_id = user_id
        self.cards = cards or {}

    def apply(self, user_card_id, request_id):
        _validate_request_id(request_id)
        if not isinstance(user_card_id, str) or not 1 <= len(user_card_id) <= 64:
            raise ProgressionError("Invalid owned pilot identifier")
        fingerprint = _fingerprint("revision", user_card_id, {})
        with self.sessions() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            try:
                receipt = session.get(ProgressionReceipt, (self.user_id, request_id))
                if receipt:
                    if receipt.request_hash != fingerprint:
                        raise ProgressionError(
                            "Request ID was already used for a different action")
                    return receipt.response
                pilot = session.scalar(select(UserPilot).where(
                    UserPilot.user_id == self.user_id,
                    UserPilot.user_card_id == user_card_id))
                if pilot is None:
                    raise ProgressionError("Pilot is not owned by this account")
                card = self.cards.get(pilot.mst_pilot_id)
                if not isinstance(card, dict):
                    raise ProgressionError("Pilot masterdata is unavailable")
                max_revision = int(card.get("rarity", {}).get("maxRevision", 0))
                next_revision = pilot.awakening_level + 1
                if pilot.awakening_level >= max_revision:
                    raise ProgressionError("Pilot is already at the revision cap")
                revision = card.get("revisionGroup", {}).get(
                    "revision%s" % next_revision)
                if not isinstance(revision, dict):
                    raise ProgressionError("Missing revision definition")

                gold_cost = int(revision.get("needGold", 0))
                material_costs = {}
                for index in range(1, 4):
                    item_id = revision.get("needItemId%s" % index)
                    quantity = revision.get("needQuantity%s" % index)
                    if item_id is None and quantity is None:
                        continue
                    if (not isinstance(item_id, str) or not item_id
                            or not isinstance(quantity, int) or quantity <= 0):
                        raise ProgressionError("Invalid revision material definition")
                    material_costs[item_id] = material_costs.get(item_id, 0) + quantity

                wallet = session.get(UserWallet, self.user_id)
                if wallet is None or wallet.gold < gold_cost:
                    raise ProgressionError("Not enough GOLD")
                materials = {}
                for item_id, quantity in material_costs.items():
                    material = session.get(UserGameItem, (self.user_id, item_id))
                    if material is None or material.quantity < quantity:
                        raise ProgressionError("Not enough revision materials")
                    materials[item_id] = material

                wallet.gold -= gold_cost
                for item_id, quantity in material_costs.items():
                    materials[item_id].quantity -= quantity
                pilot.awakening_level = next_revision

                rank_amount = 0
                for index in range(1, 5):
                    if revision.get("boostCode%s" % index) == "MASTER_LEVEL_EXP":
                        rank_amount += int(revision.get("boostValue%s" % index, 0))
                rank_rows = []
                attribute = card.get("attribute")
                if rank_amount and attribute in CARD_ATTRIBUTES:
                    rank = session.get(
                        UserCardAttributeRank, (self.user_id, attribute))
                    if rank is None:
                        rank = UserCardAttributeRank(
                            user_id=self.user_id,
                            attribute=attribute,
                            level=1,
                            experience=0,
                            created_at=datetime.now(JST),
                        )
                        session.add(rank)
                    rank.level, rank.experience = _add_attribute_rank_experience(
                        rank.level, rank.experience, rank_amount)
                    rank_rows.append(_attribute_rank_response(rank))

                now = datetime.now(JST).isoformat()
                items = [{
                    "itemId": "GOLD", "environmentId": "COMMON",
                    "quantity": wallet.gold, "total": 0, "createdAt": now,
                }]
                items.extend(_item_response(materials[item_id], now)
                             for item_id in material_costs)
                response = {
                    "resultCode": "success",
                    "currentTime": now,
                    "userCardList": [_pilot_response(pilot, card)],
                    "userCardAttributeRankList": rank_rows,
                    "userItemList": items,
                }
                session.add(ProgressionReceipt(
                    user_id=self.user_id, request_id=request_id,
                    request_hash=fingerprint, response=response))
                session.commit()
                return response
            except Exception:
                session.rollback()
                raise


class LimitBreakService:
    def __init__(self, sessions, user_id):
        self.sessions = sessions
        self.user_id = user_id
        self.cards = {}

    def with_cards(self, cards):
        self.cards = cards or {}
        return self

    def apply(self, user_card_id, kind, request_id):
        _validate_request_id(request_id)
        if not isinstance(user_card_id, str) or not 1 <= len(user_card_id) <= 64:
            raise ProgressionError("Invalid owned pilot identifier")
        if kind not in ("UNIQUE", "COMMON"):
            raise ProgressionError("Unsupported limit-break type")
        fingerprint = hashlib.sha256(json.dumps(["limitBreak", user_card_id, kind],
                                                separators=(",", ":")).encode()).hexdigest()
        with self.sessions() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            try:
                receipt = session.get(ProgressionReceipt, (self.user_id, request_id))
                if receipt:
                    if receipt.request_hash != fingerprint:
                        raise ProgressionError("Request ID was already used for a different action")
                    return receipt.response
                pilot = session.scalar(select(UserPilot).where(
                    UserPilot.user_id == self.user_id, UserPilot.user_card_id == user_card_id))
                if pilot is None:
                    raise ProgressionError("Pilot is not owned by this account")
                rarity = RULES["cards"].get(str(pilot.mst_pilot_id))
                if rarity is None:
                    raise ProgressionError("No verified limit-break definition for this pilot")
                rule = RULES["rarities"][str(rarity)]
                level = pilot.limit_break
                if not 0 <= level < rule["maxLbCount"]:
                    raise ProgressionError("Pilot is already at the limit-break cap")
                wallet = session.get(UserWallet, self.user_id)
                gold = rule["neededGoldLimitBreakList"][level]
                if wallet is None or wallet.gold < gold:
                    raise ProgressionError("Not enough GOLD")
                if kind == "UNIQUE":
                    material = session.get(UserCardLimitBreak, (self.user_id, pilot.mst_pilot_id))
                    needed = rule["useUniqueLimitBreakNumList"][level]
                    item_id = None
                else:
                    materials = rule["useCommonLimitBreakItemMap"]
                    if len(materials) != 1:
                        raise ProgressionError("Ambiguous common-material definition")
                    item_id, amounts = next(iter(materials.items()))
                    needed = amounts[level]
                    material = session.get(UserGameItem, (self.user_id, item_id))
                if material is None or material.quantity < needed:
                    raise ProgressionError("Not enough limit-break materials")
                wallet.gold -= gold
                material.quantity -= needed
                pilot.limit_break += 1
                now = datetime.now(JST).isoformat()
                items = [{"itemId": "GOLD", "environmentId": "COMMON",
                          "quantity": wallet.gold, "total": 0, "createdAt": now}]
                limits = []
                if item_id is None:
                    limits.append({"cardId": pilot.mst_pilot_id, "quantity": material.quantity})
                else:
                    items.append({"itemId": item_id, "environmentId": "COMMON",
                                  "quantity": material.quantity, "total": 0, "createdAt": now})
                response = {"resultCode": "success", "currentTime": now,
                    "userCardList": [_pilot_response(
                        pilot, self.cards.get(pilot.mst_pilot_id))],
                    "userItemList": items, "userCardLimitBreakList": limits}
                session.add(ProgressionReceipt(user_id=self.user_id, request_id=request_id,
                                                request_hash=fingerprint, response=response))
                session.commit()
                return response
            except Exception:
                session.rollback()
                raise


class ExperienceService:
    def __init__(self, sessions, user_id):
        self.sessions = sessions
        self.user_id = user_id
        self.cards = {}

    def with_cards(self, cards):
        self.cards = cards or {}
        return self

    def apply(self, user_card_id, use_item, request_id):
        _validate_request_id(request_id)
        if not isinstance(user_card_id, str) or not 1 <= len(user_card_id) <= 64:
            raise ProgressionError("Invalid owned pilot identifier")
        if not isinstance(use_item, dict) or not use_item:
            raise ProgressionError("Experience items are required")
        normalized = {}
        for item_id, quantity in use_item.items():
            if item_id not in ITEM_EXP:
                raise ProgressionError("Unsupported experience item")
            if (not isinstance(quantity, int) or isinstance(quantity, bool)
                    or quantity < 0):
                raise ProgressionError("Experience item quantities must be non-negative integers")
            if quantity:
                normalized[item_id] = quantity
        if not normalized:
            raise ProgressionError("At least one experience item is required")
        total_exp = sum(ITEM_EXP[item_id] * quantity
                        for item_id, quantity in normalized.items())
        fingerprint = _fingerprint("experience", user_card_id, normalized)
        with self.sessions() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            try:
                receipt = session.get(ProgressionReceipt, (self.user_id, request_id))
                if receipt:
                    if receipt.request_hash != fingerprint:
                        raise ProgressionError("Request ID was already used for a different action")
                    return receipt.response
                pilot = session.scalar(select(UserPilot).where(
                    UserPilot.user_id == self.user_id,
                    UserPilot.user_card_id == user_card_id))
                if pilot is None:
                    raise ProgressionError("Pilot is not owned by this account")
                rarity_num = RULES["cards"].get(str(pilot.mst_pilot_id))
                if rarity_num is None:
                    raise ProgressionError("No verified progression definition for this pilot")
                rarity = RULES["rarities"][str(rarity_num)]
                max_level = rarity["maxCardLevelList"][pilot.limit_break]
                if pilot.level >= max_level:
                    raise ProgressionError("Pilot is already at the level cap")
                table = EXP_TABLE["RARE_" + str(rarity_num)]
                rows = {}
                for item_id, quantity in normalized.items():
                    row = session.get(UserGameItem, (self.user_id, item_id))
                    if row is None or row.quantity < quantity:
                        raise ProgressionError("Not enough experience items")
                    rows[item_id] = row
                for item_id, quantity in normalized.items():
                    rows[item_id].quantity -= quantity
                pilot.level, pilot.experience = _add_experience(
                    pilot.level, pilot.experience, total_exp, max_level, table)
                now = datetime.now(JST).isoformat()
                response = {
                    "resultCode": "success",
                    "currentTime": now,
                    "userCardList": [_pilot_response(
                        pilot, self.cards.get(pilot.mst_pilot_id))],
                    "userItemList": [
                        _item_response(rows[item_id], now)
                        for item_id in normalized
                    ],
                    "enforceResult": "GOOD",
                }
                session.add(ProgressionReceipt(
                    user_id=self.user_id, request_id=request_id,
                    request_hash=fingerprint, response=response))
                session.commit()
                return response
            except Exception:
                session.rollback()
                raise


class BondsService:
    def __init__(self, sessions, user_id):
        self.sessions = sessions
        self.user_id = user_id
        self.cards = {}

    def with_cards(self, cards):
        self.cards = cards or {}
        return self

    def apply(self, user_card_id, use_item, request_id):
        _validate_request_id(request_id)
        if not isinstance(user_card_id, str) or not 1 <= len(user_card_id) <= 64:
            raise ProgressionError("Invalid owned pilot identifier")
        if not isinstance(use_item, dict) or list(use_item) != ["TRUST_EXP"]:
            raise ProgressionError("Only TRUST_EXP is supported")
        quantity = use_item["TRUST_EXP"]
        if (not isinstance(quantity, int) or isinstance(quantity, bool)
                or quantity <= 0):
            raise ProgressionError("TRUST_EXP quantity must be a positive integer")
        total_points = 50 * quantity
        fingerprint = _fingerprint("bonds", user_card_id, {"TRUST_EXP": quantity})
        with self.sessions() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            try:
                receipt = session.get(ProgressionReceipt, (self.user_id, request_id))
                if receipt:
                    if receipt.request_hash != fingerprint:
                        raise ProgressionError("Request ID was already used for a different action")
                    return receipt.response
                pilot = session.scalar(select(UserPilot).where(
                    UserPilot.user_id == self.user_id,
                    UserPilot.user_card_id == user_card_id))
                if pilot is None:
                    raise ProgressionError("Pilot is not owned by this account")
                if pilot.bonds_level >= 5:
                    raise ProgressionError("Pilot is already at the bonds cap")
                material = session.get(UserGameItem, (self.user_id, "TRUST_EXP"))
                if material is None or material.quantity < quantity:
                    raise ProgressionError("Not enough TRUST_EXP")
                material.quantity -= quantity
                pilot.bonds_level, pilot.bonds_point = _add_bonds(
                    pilot.bonds_level, pilot.bonds_point, total_points)
                now = datetime.now(JST).isoformat()
                response = {
                    "resultCode": "success",
                    "currentTime": now,
                    "userCardList": [_pilot_response(
                        pilot, self.cards.get(pilot.mst_pilot_id))],
                    "userItemList": [_item_response(material, now)],
                    "enforceResult": "GOOD",
                }
                session.add(ProgressionReceipt(
                    user_id=self.user_id, request_id=request_id,
                    request_hash=fingerprint, response=response))
                session.commit()
                return response
            except Exception:
                session.rollback()
                raise
