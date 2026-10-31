"""Locally persisted mission definitions, progress and item rewards."""

import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import uuid

from sqlalchemy import select, text

from .models import MissionReceipt, UserGameItem
from .models import LocalBattleProgress


JST = timezone(timedelta(hours=9))
DAILY_LOGIN_DEFINITIONS = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" /
     "daily_login_missions.json").read_text(encoding="utf-8")
)["dailyLoginChallenges"]

CHALLENGE_LIST_KEYS = (
    "userDailyChallengeList",
    "userWeeklyChallengeList",
    "userTotalChallengeList",
    "userBeginnerChallengeList",
    "userLimitedChallengeList",
    "userSideTotalChallengeList",
    "userEntangleTotalChallengeList",
)

SCOPE_LISTS = {
    "daily": ("userDailyChallengeList",),
    "weekly": ("userWeeklyChallengeList",),
    "total": ("userTotalChallengeList",),
    "beginner": ("userBeginnerChallengeList",),
    "limited": ("userLimitedChallengeList",),
    "side": ("userSideTotalChallengeList",),
    "entangle": ("userEntangleTotalChallengeList",),
    "normal": CHALLENGE_LIST_KEYS,
}

PERIOD_PREFIX = {
    "userWeeklyChallengeList": "weekly",
    "userTotalChallengeList": "total",
    "userBeginnerChallengeList": "beginner",
    "userLimitedChallengeList": "limited",
    "userSideTotalChallengeList": "side",
    "userEntangleTotalChallengeList": "entangle",
}

_CATALOG_CACHE = {}


def _load_task_catalog(masterdata_dir):
    if masterdata_dir is None:
        return {}
    path = Path(masterdata_dir) / "task-catalog.json"
    if not path.is_file():
        return {}
    cache_key = str(path.resolve())
    if cache_key in _CATALOG_CACHE:
        return _CATALOG_CACHE[cache_key]

    data = json.loads(path.read_text(encoding="utf-8"))
    grouped = {key: [] for key in CHALLENGE_LIST_KEYS}
    for row in data.get("tasks", []):
        list_key = row.get("listKey")
        challenge_id = row.get("challengeId")
        if list_key not in grouped or not isinstance(challenge_id, int):
            continue
        grouped[list_key].append(row)
    _CATALOG_CACHE[cache_key] = grouped
    return grouped


def _challenge_from_catalog(row):
    challenge = copy.deepcopy(row.get("challenge")) \
        if isinstance(row.get("challenge"), dict) else {}
    mapping = {
        "id": row.get("challengeId"),
        "groupId": row.get("groupId"),
        "bean": row.get("bean"),
        "parameter": row.get("parameter"),
        "count": row.get("count"),
        "displayName": row.get("displayName"),
        "rewardComment": row.get("rewardComment"),
        "presentType": row.get("presentType"),
        "genericCode": row.get("itemId"),
        "itemNum": row.get("itemNum"),
        "pageLink": row.get("pageLink"),
        "requiredOpenFunction": row.get("requiredOpenFunction"),
        "sortKey": row.get("sortKey"),
        "countable": row.get("countable"),
        "challengeGroup": row.get("challengeGroup"),
        "limitedChallengeGroup": row.get("limitedChallengeGroup"),
    }
    for key, value in mapping.items():
        if value is not None:
            challenge[key] = value
    return challenge


class MissionService:
    def __init__(self, session_factory, user_id, masterdata_dir=None,
                 clock=None):
        self.sessions = session_factory
        self.user_id = user_id
        self.clock = clock or (lambda: datetime.now(JST))
        self.catalog = _load_task_catalog(masterdata_dir)
        self._definitions = {
            key: self._build_definitions(key) for key in CHALLENGE_LIST_KEYS
        }
        self._baseline = {}
        with self.sessions() as session:
            has_gameplay = session.scalar(select(LocalBattleProgress).where(
                LocalBattleProgress.user_id == self.user_id).limit(1)) is not None
        if has_gameplay:
            for list_key, rows in self.catalog.items():
                for row in rows:
                    self._baseline[(list_key, row["challengeId"])] = {
                        "clearedCount": int(row.get("clearedCount") or 0),
                        "clearedAt": row.get("clearedAt"),
                        "receivedAt": row.get("receivedAt"),
                    }

    def _baseline_for(self, list_key, challenge_id):
        # Retained daily and weekly counters belong to an old period.
        if list_key in (
                "userDailyChallengeList", "userWeeklyChallengeList"):
            return {}
        return self._baseline.get((list_key, challenge_id), {})

    def _build_definitions(self, list_key):
        definitions = [
            _challenge_from_catalog(row)
            for row in self.catalog.get(list_key, [])
        ]
        if list_key != "userDailyChallengeList":
            return definitions

        login_by_id = {
            row["id"]: copy.deepcopy(row) for row in DAILY_LOGIN_DEFINITIONS
        }
        seen = set()
        result = []
        for definition in definitions:
            challenge_id = definition.get("id")
            seen.add(challenge_id)
            result.append(copy.deepcopy(login_by_id.get(
                challenge_id, definition)))
        for challenge_id, definition in login_by_id.items():
            if challenge_id not in seen:
                result.append(copy.deepcopy(definition))
        return result

    def _period(self, list_key, now):
        if list_key == "userDailyChallengeList":
            return now.date().isoformat()
        if list_key == "userWeeklyChallengeList":
            year, week, _day = now.isocalendar()
            return "w:%04d-%02d" % (year, week)
        return PERIOD_PREFIX[list_key]

    def _receipt(self, session, list_key, challenge_id, period, now):
        receipt = session.get(
            MissionReceipt,
            (self.user_id, challenge_id, period),
        )
        if receipt is None and list_key == "userDailyChallengeList":
            receipt = session.get(
                MissionReceipt,
                (self.user_id, challenge_id, now.date().isoformat()),
            )
        return receipt

    def _cleared_count(self, list_key, definition):
        if list_key == "userDailyChallengeList" and definition.get("id") in {
                row["id"] for row in DAILY_LOGIN_DEFINITIONS}:
            return int(definition.get("count", 1))
        baseline = self._baseline_for(list_key, definition.get("id"))
        if baseline:
            return int(baseline.get("clearedCount") or 0)
        return 0

    def _rows(self, session, list_key, now):
        rows = []
        period = self._period(list_key, now)
        for definition in self._definitions[list_key]:
            challenge_id = definition["id"]
            receipt = self._receipt(
                session, list_key, challenge_id, period, now)
            cleared_count = self._cleared_count(list_key, definition)
            baseline = self._baseline_for(list_key, challenge_id)
            rows.append({
                "challengeId": challenge_id,
                "challenge": copy.deepcopy(definition),
                "clearedCount": cleared_count,
                "clearedAt": (baseline.get("clearedAt")
                              if cleared_count else None),
                "receivedAt": (
                    receipt.result.get("createdAt") if receipt
                    else baseline.get("receivedAt")
                ),
            })
        return rows

    def state(self):
        now = self.clock().astimezone(JST)
        with self.sessions() as session:
            return {
                list_key: self._rows(session, list_key, now)
                for list_key in CHALLENGE_LIST_KEYS
            }

    def claim(self, scope, challenge_id=None):
        list_keys = SCOPE_LISTS.get(scope)
        if list_keys is None:
            raise ValueError("This mission group is not implemented locally")
        target_ids = {
            definition["id"]
            for list_key in list_keys
            for definition in self._definitions[list_key]
        }
        if challenge_id is not None and challenge_id not in target_ids:
            raise ValueError("Unknown local mission")

        now = self.clock().astimezone(JST)
        stamp = now.isoformat()
        granted_item_ids = set()
        with self.sessions() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            try:
                results = []
                for list_key in list_keys:
                    period = self._period(list_key, now)
                    for definition in self._definitions[list_key]:
                        current_id = definition["id"]
                        if challenge_id is not None \
                                and current_id != challenge_id:
                            continue
                        receipt = self._receipt(
                            session, list_key, current_id, period, now)
                        if receipt is not None:
                            continue
                        baseline = self._baseline_for(list_key, current_id)
                        if baseline.get("receivedAt"):
                            continue
                        if self._cleared_count(list_key, definition) < int(
                                definition.get("count") or 1):
                            continue
                        if definition.get("presentType") != "ITEM":
                            raise ValueError(
                                "This mission reward type is not implemented")

                        item_id = definition["genericCode"]
                        quantity = int(definition.get("itemNum") or 1)
                        item = session.get(
                            UserGameItem, (self.user_id, item_id))
                        if item is None:
                            item = UserGameItem(
                                user_id=self.user_id,
                                item_id=item_id,
                                quantity=0,
                            )
                            session.add(item)
                        item.quantity += quantity
                        granted_item_ids.add(item_id)
                        result = {
                            "instanceId": str(uuid.uuid4()),
                            "toUserId": self.user_id,
                            "presentType": "ITEM",
                            "itemId": item_id,
                            "quantity": quantity,
                            "originType": "CHALLENGE",
                            "createdAt": stamp,
                            "presentDate": stamp,
                            "presentComment":
                                definition.get("rewardComment", ""),
                            "expiredAt": (
                                now + timedelta(days=90)
                            ).replace(
                                hour=23,
                                minute=59,
                                second=59,
                                microsecond=0,
                            ).isoformat(),
                            "category": list_key,
                        }
                        session.add(MissionReceipt(
                            user_id=self.user_id,
                            challenge_id=current_id,
                            period=period,
                            result=result,
                        ))
                        results.append(result)
                session.commit()
            except Exception:
                session.rollback()
                raise

        updated = self.state()
        with self.sessions() as session:
            items = session.scalars(select(UserGameItem).where(
                UserGameItem.user_id == self.user_id,
                UserGameItem.item_id.in_(granted_item_ids),
            )).all() if granted_item_ids else []
            item_rows = [
                {
                    "itemId": item.item_id,
                    "environmentId": "COMMON",
                    "quantity": item.quantity,
                    "total": 0,
                    "createdAt": stamp,
                }
                for item in items
            ]
        return {
            "resultCode": "success",
            "currentTime": stamp,
            "results": results,
            "userItemList": item_rows,
            **updated,
        }
