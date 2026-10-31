"""Local gacha mechanics reconstructed from official protocol captures.

The engine reproduces the parts that are observable from the client:
cost checks, item deduction, probability sampling, duplicate conversion,
ten-draw guarantee selection, and the draw response shape.

It cannot reproduce the official server's random sequence. Callers that need
a repeatable local result must pass a seeded ``random.Random`` instance.

Known limits:

- Every duplicate in the captured samples converted to 15 limit-break
  materials. The master data contains per-card and per-level tables, so this
  default must not be treated as universal.
- The ten-draw guarantee uses the ``★3以上確定時`` probability set for one slot.
  The captured ten-draw showed a rarity-up row at index 8, but a single sample
  cannot prove that index 8 is always the guaranteed slot.
- ``direction2``'s third value varies for the same rarity and is treated as a
  presentation variant.
- New-card first-time rewards are not modelled because no new-card capture
  exists.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple
import json
import random


JST = timezone(timedelta(hours=9))
DEFAULT_DUPLICATE_MATERIAL = 15
NORMAL_PROBABILITY_NAME = "通常"
GUARANTEED_PROBABILITY_NAME = "★3以上確定時"


class GachaError(Exception):
    pass


class InsufficientFunds(GachaError):
    pass


class GachaKindUnavailable(GachaError):
    pass


@dataclass(frozen=True)
class GachaKind:
    gacha_kind_id: int
    schedule_id: int
    bean_kind: str
    name: str
    need_point_kind: str
    need_quantity: int
    item_id: Optional[str] = None
    type: Optional[str] = None
    times: Optional[int] = None

    @property
    def draw_count(self) -> int:
        return 10 if "10" in self.bean_kind else 1


@dataclass(frozen=True)
class ProbabilityEntry:
    card: dict
    weight: int


@dataclass(frozen=True)
class ProbabilitySet:
    display_name: str
    lottery_map: Dict[str, int]
    entries: Tuple[ProbabilityEntry, ...]
    total_weight: int


@dataclass(frozen=True)
class GachaPool:
    schedule_id: int
    gacha_type: str
    description: str
    kinds: Dict[str, GachaKind]
    probability_sets: Dict[str, ProbabilitySet]
    cards: Dict[int, dict]
    duplicate_material: int = DEFAULT_DUPLICATE_MATERIAL


@dataclass
class GachaState:
    """Minimal local state needed to evaluate a draw transaction."""

    free_sakuradite: int = 0
    paid_sakuradite: int = 0
    items: Dict[str, int] = field(default_factory=dict)
    owned_cards: Set[int] = field(default_factory=set)
    owned_kmfs: Set[int] = field(default_factory=set)
    limit_break: Dict[int, int] = field(default_factory=dict)
    kmf_keys: Dict[int, int] = field(default_factory=dict)
    points: Dict[int, int] = field(default_factory=dict)
    daily_used: Dict[int, str] = field(default_factory=dict)


def _weight_from_percent(value) -> int:
    """Convert a percent string such as ``"4.66666"`` to an integer weight."""

    return int(
        (Decimal(str(value)) * Decimal(100000)).to_integral_value(
            rounding=ROUND_HALF_UP
        )
    )


def load_fixture(
    path,
    schedule_id: int,
    probability_schedule_id: int | None = None,
    rate_override_path=None,
) -> GachaPool:
    """Load a sanitized pool fixture produced from the live captures."""

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    schedule = data.get("schedules", {}).get(str(schedule_id))
    if schedule is None:
        catalog = Path(path).parent / "gacha_selectable_catalog.json"
        if catalog.is_file():
            captured = json.loads(catalog.read_text(encoding="utf-8"))
            schedule = next(
                (
                    row
                    for row in captured.get("schedules", [])
                    if int(row.get("id", 0)) == int(schedule_id)
                ),
                None,
            )
    if schedule is None:
        raise KeyError(schedule_id)

    kinds = {}
    for raw in schedule.get("gachaKindList", []):
        kind = GachaKind(
            gacha_kind_id=int(raw["gachaKindId"]),
            schedule_id=int(raw["gachaScheduleId"]),
            bean_kind=str(raw["beanKind"]),
            name=str(raw["name"]),
            need_point_kind=str(raw["needPointKind"]),
            need_quantity=int(raw["needQuantity"]),
            item_id=raw.get("itemId"),
            type=raw.get("type"),
            times=raw.get("times"),
        )
        kinds[kind.bean_kind] = kind

    probability = data["probability"][
        str(probability_schedule_id or schedule_id)
    ]
    probability_sets = {}
    for raw_set in probability.get("gachaProbabilityList", []):
        entries = []
        for item in raw_set.get("cardProbabilityList", []):
            weight = _weight_from_percent(item["probability"])
            if weight > 0:
                entries.append(
                    ProbabilityEntry(card=dict(item["gachaResult"]), weight=weight)
                )
        if not entries:
            raise GachaError("probability set has no positive-weight cards")
        probability_sets[raw_set["displayName"]] = ProbabilitySet(
            display_name=raw_set["displayName"],
            lottery_map=dict(raw_set.get("lotteryMap") or {}),
            entries=tuple(entries),
            total_weight=sum(entry.weight for entry in entries),
        )

    cards = {
        int(card["cardId"]): dict(card)
        for card in probability.get("gachaDrawList", [])
    }
    if rate_override_path is not None:
        probability_sets = _boost_probability_sets(
            probability_sets, _load_rate_multipliers(rate_override_path))
    return GachaPool(
        schedule_id=schedule_id,
        gacha_type=str(schedule.get("gachaType") or ""),
        description=str(schedule.get("gachaDescription") or ""),
        kinds=kinds,
        probability_sets=probability_sets,
        cards=cards,
    )


def restrict_pool(pool: GachaPool, rarities: Set[int]) -> GachaPool:
    """Return a pool restricted to the requested card rarities.

    Per-card weights are preserved and renormalised by the drawing engine, so
    restricting schedule 1005 to ``{4}`` yields a 100% four-star pool over the
    167 captured four-star cards.
    """

    probability_sets = {}
    for name, probability in pool.probability_sets.items():
        entries = tuple(
            entry
            for entry in probability.entries
            if int(entry.card.get("rarity", 0)) in rarities
        )
        if entries:
            probability_sets[name] = ProbabilitySet(
                display_name=name,
                lottery_map=dict(probability.lottery_map),
                entries=entries,
                total_weight=sum(entry.weight for entry in entries),
            )
    if not probability_sets:
        raise GachaError("no cards remain after rarity restriction")
    return GachaPool(
        schedule_id=pool.schedule_id,
        gacha_type=pool.gacha_type,
        description=pool.description,
        kinds=dict(pool.kinds),
        probability_sets=probability_sets,
        cards=dict(pool.cards),
        duplicate_material=pool.duplicate_material,
    )


def load_probability_payload(
    path,
    schedule_id: int,
    probability_schedule_id: int | None = None,
    rate_override_path=None,
) -> dict:
    """Return the captured probability response without user state."""

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    probability = data["probability"][
        str(probability_schedule_id or schedule_id)
    ]
    if rate_override_path is not None:
        probability = _boost_probability_payload(
            probability, _load_rate_multipliers(rate_override_path))
    return {
        "resultCode": "success",
        "currentTime": datetime.now(JST).isoformat(),
        "gachaDrawList": probability["gachaDrawList"],
        "gachaProbabilityList": probability["gachaProbabilityList"],
    }


def _load_rate_multipliers(path) -> Dict[int, float]:
    if path is None or not Path(path).is_file():
        return {}
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    raw = data.get("rarityMultipliers") or {}
    if not isinstance(raw, dict):
        raise GachaError("rarityMultipliers must be an object")
    result = {}
    for rarity, multiplier in raw.items():
        rarity = int(rarity)
        multiplier = float(multiplier)
        if rarity < 1 or multiplier <= 0 or multiplier > 100:
            raise GachaError("invalid gacha rarity multiplier")
        result[rarity] = multiplier
    return result


def _boost_probability_sets(
    probability_sets: Dict[str, ProbabilitySet],
    multipliers: Dict[int, float],
) -> Dict[str, ProbabilitySet]:
    if not multipliers:
        return probability_sets
    result = {}
    for name, probability_set in probability_sets.items():
        entries = tuple(
            ProbabilityEntry(
                card=dict(entry.card),
                weight=max(
                    1,
                    int(round(
                        entry.weight
                        * multipliers.get(
                            int(entry.card.get("rarity", 0)), 1.0
                        )
                    )),
                ),
            )
            for entry in probability_set.entries
        )
        result[name] = ProbabilitySet(
            display_name=probability_set.display_name,
            lottery_map=dict(probability_set.lottery_map),
            entries=entries,
            total_weight=sum(entry.weight for entry in entries),
        )
    return result


def _boost_probability_payload(
    probability: dict,
    multipliers: Dict[int, float],
) -> dict:
    if not multipliers:
        return probability
    result = json.loads(json.dumps(probability))
    for probability_set in result.get("gachaProbabilityList", []):
        entries = probability_set.get("cardProbabilityList", [])
        adjusted = []
        for entry in entries:
            rarity = int(
                (entry.get("gachaResult") or {}).get("rarity", 0))
            value = float(entry.get("probability", 0))
            adjusted.append(value * multipliers.get(rarity, 1.0))
        total = sum(adjusted)
        if total <= 0:
            continue
        for entry, value in zip(entries, adjusted):
            entry["probability"] = (
                "%.5f" % (value / total * 100.0)
            ).rstrip("0").rstrip(".")
    return result


class GachaEngine:
    def __init__(
        self,
        pool: GachaPool,
        duplicate_material: Optional[int] = None,
        awards_points: Optional[bool] = None,
    ):
        self.pool = pool
        self.duplicate_material = (
            pool.duplicate_material
            if duplicate_material is None
            else duplicate_material
        )
        self.awards_points = awards_points

    def draw(
        self,
        state: GachaState,
        bean_kind: str,
        rng: Optional[random.Random] = None,
        now: Optional[datetime] = None,
        guaranteed_slot: Optional[int] = None,
        free_draw: bool = False,
    ) -> dict:
        """Evaluate one draw and return a client-shaped response.

        ``guaranteed_slot`` is the zero-based slot that uses the guaranteed
        probability set in a ten-draw. The default is the last slot.
        """

        kind = self.pool.kinds.get(bean_kind)
        if kind is None:
            raise GachaKindUnavailable(
                "bean kind %r is not available for schedule %s"
                % (bean_kind, self.pool.schedule_id)
            )

        rng = rng or random.Random()
        now = (now or datetime.now(JST)).astimezone(JST)
        changed_items = [] if free_draw else self._charge(state, kind, now)
        cards, selected_slot = self._sample_cards(
            kind, rng, guaranteed_slot=guaranteed_slot
        )
        response_cards, changed_lb, changed_kmf = self._apply_cards(state, cards)

        response = {
            "resultCode": "success",
            "currentTime": now.isoformat(),
        }
        if changed_lb:
            response["userCardLimitBreakList"] = [
                {
                    "cardId": card_id,
                    "quantity": quantity,
                    "createdAt": now.isoformat(),
                }
                for card_id, quantity in changed_lb.items()
            ]
        if self._does_award_points(kind):
            point = state.points.get(self.pool.schedule_id, 0) + kind.draw_count
            state.points[self.pool.schedule_id] = point
            response["userGachaPointList"] = [
                {
                    "gachaScheduleId": self.pool.schedule_id,
                    "point": point,
                    "createdAt": now.isoformat(),
                }
            ]
        if changed_items:
            response["userItemList"] = [
                self._item_entry(state, item_id, now) for item_id in changed_items
            ]
        response["gachaAnimation"] = {
            "effects": self._effects(
                response_cards, kind.draw_count, selected_slot, rng
            ),
            "cardList": response_cards,
        }
        if changed_kmf:
            response["userKnightmareFrameKeyList"] = [
                {
                    "knightmareFrameId": kmf_id,
                    "quantity": quantity,
                    "createdAt": now.isoformat(),
                }
                for kmf_id, quantity in changed_kmf.items()
            ]
        return response

    def _does_award_points(self, kind: GachaKind) -> bool:
        if self.awards_points is not None:
            return self.awards_points
        # Observed: MONEY/FREE draws add one point each; ticket draws add none.
        return "ITEM" not in kind.need_point_kind

    def _charge(
        self, state: GachaState, kind: GachaKind, now: datetime
    ) -> List[str]:
        if "ITEM" in kind.need_point_kind:
            if not kind.item_id:
                raise GachaError("item gacha has no itemId")
            have = state.items.get(kind.item_id, 0)
            if have < kind.need_quantity:
                raise InsufficientFunds(
                    "need %s %s, have %s"
                    % (kind.need_quantity, kind.item_id, have)
                )
            state.items[kind.item_id] = have - kind.need_quantity
            return [kind.item_id]

        if "MONEY" in kind.need_point_kind:
            cost = kind.need_quantity
            total = state.free_sakuradite + state.paid_sakuradite
            if total < cost:
                raise InsufficientFunds(
                    "need %s sakuradite, have %s" % (cost, total)
                )
            free_take = min(state.free_sakuradite, cost)
            state.free_sakuradite -= free_take
            paid_take = cost - free_take
            state.paid_sakuradite -= paid_take
            changed = []
            if free_take:
                changed.append("PRESENTED_MONEY")
            if paid_take:
                changed.append("MONEY")
            return changed

        if "FREE" in kind.need_point_kind:
            if kind.type == "DAILY":
                day = now.date().isoformat()
                if state.daily_used.get(kind.gacha_kind_id) == day:
                    raise GachaKindUnavailable("daily draw already used today")
                state.daily_used[kind.gacha_kind_id] = day
            return []

        raise GachaError(
            "unsupported needPointKind %r" % kind.need_point_kind
        )

    def _sample_cards(
        self,
        kind: GachaKind,
        rng: random.Random,
        guaranteed_slot: Optional[int],
    ) -> Tuple[List[dict], Optional[int]]:
        normal = self.pool.probability_sets.get(NORMAL_PROBABILITY_NAME)
        if normal is None:
            raise GachaError("normal probability set is missing")
        guaranteed = self.pool.probability_sets.get(GUARANTEED_PROBABILITY_NAME)

        selected_slot = None
        if kind.draw_count == 10 and guaranteed is not None:
            selected_slot = 9 if guaranteed_slot is None else guaranteed_slot
            if not 0 <= selected_slot < kind.draw_count:
                raise GachaError("guaranteed_slot is outside the draw count")

        cards = []
        for index in range(kind.draw_count):
            probability = (
                guaranteed
                if selected_slot is not None and index == selected_slot
                else normal
            )
            cards.append(self._sample_one(probability, rng))
        return cards, selected_slot

    @staticmethod
    def _sample_one(
        probability: ProbabilitySet, rng: random.Random
    ) -> dict:
        roll = rng.randrange(probability.total_weight)
        cumulative = 0
        for entry in probability.entries:
            cumulative += entry.weight
            if roll < cumulative:
                return dict(entry.card)
        return dict(probability.entries[-1].card)

    def _apply_cards(
        self, state: GachaState, cards: Sequence[dict]
    ) -> Tuple[List[dict], Dict[int, int], Dict[int, int]]:
        response_cards = []
        changed_lb = {}
        changed_kmf = {}

        for card in cards:
            card_id = int(card["cardId"])
            response_card = dict(card)
            if card_id in state.owned_cards:
                quantity = (
                    state.limit_break.get(card_id, 0) + self.duplicate_material
                )
                state.limit_break[card_id] = quantity
                changed_lb[card_id] = quantity
                response_card["limitBreakNum"] = self.duplicate_material
            else:
                state.owned_cards.add(card_id)
                response_card["isNew"] = True

            kmf_id = card.get("knightmareFrameId")
            if kmf_id:
                kmf_id = int(kmf_id)
                if kmf_id in state.owned_kmfs:
                    quantity = state.kmf_keys.get(kmf_id, 0) + 1
                    state.kmf_keys[kmf_id] = quantity
                    changed_kmf[kmf_id] = quantity
                    response_card["keyNum"] = 1
                else:
                    state.owned_kmfs.add(kmf_id)
                    response_card["isNewKnightmareFrame"] = True

            response_cards.append(response_card)
        return response_cards, changed_lb, changed_kmf

    @staticmethod
    def _effects(
        cards: Sequence[dict],
        draw_count: int,
        guaranteed_slot: Optional[int],
        rng: random.Random,
    ) -> dict:
        highest = max(int(card["rarity"]) for card in cards)
        rows = []
        for index, card in enumerate(cards):
            rarity = int(card["rarity"])
            variant = rng.randrange(2, 7)
            if index == guaranteed_slot and rarity >= 3:
                rows.append([1, rarity, variant])
            else:
                rows.append([rarity, rarity, variant])
        return {
            "direction1": 2 if draw_count == 10 else 1,
            "direction2": rows,
            "direction3": 2 if highest >= 4 else 1,
            "direction4": 3 if highest >= 4 else 1,
        }

    def _item_entry(
        self, state: GachaState, item_id: str, now: datetime
    ) -> dict:
        if item_id == "PRESENTED_MONEY":
            quantity = state.free_sakuradite
        elif item_id == "MONEY":
            quantity = state.paid_sakuradite
        else:
            quantity = state.items.get(item_id, 0)
        return {
            "itemId": item_id,
            "environmentId": "COMMON",
            "quantity": quantity,
            "total": 0,
            "createdAt": now.isoformat(),
        }


__all__ = [
    "GachaEngine",
    "GachaError",
    "GachaKind",
    "GachaKindUnavailable",
    "GachaPool",
    "GachaState",
    "InsufficientFunds",
    "ProbabilityEntry",
    "ProbabilitySet",
    "load_fixture",
    "load_probability_payload",
    "restrict_pool",
]
