"""Build local game-page payloads from the imported account and captures.

Only read models are assembled here. Gacha transactions stay in the stateful
service on port 18766.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import copy
import json
from pathlib import Path
import urllib.error
import urllib.request


JST = timezone(timedelta(hours=9))

# These views depend on native login-bonus/adventure callbacks that are not
# implemented in the loopback client. The local page model omits them so the
# main MyPage and gacha screens can render instead of hanging on a cutscene.
LOCAL_SKIPPED_LOGIN_KEYS = (
    "gachaAdvList",
    "receivedLoginBonusCampaignLotteryList",
    "birthdayItemId",
    "charaBirthdayLoginBonusList",
    "loginBonusComebackList",
    "loginBonusStartDashList",
    "loginBonusCampaignList",
    "loginBonusList",
    "loginBonusPeriod",
)


class GachaPageStore:
    def __init__(self, account_page, static_dir, state_url, timeout=3,
                 claim_state_path=None):
        self.account_page = account_page
        self.static_dir = Path(static_dir)
        self.state_url = state_url
        self.timeout = timeout
        self.claim_state_path = (
            Path(claim_state_path) if claim_state_path is not None else None
        )
        self.gacha_top = self._load("_api_page_GachaTop-", "gachaScheduleList")
        self.animation = self._load(
            "_api_page_GachaAnimation-", "userDeckList"
        )
        self.result = self._load("_api_page_GachaResult-", "gachaScheduleList")
        if not self.gacha_top:
            raise ValueError("Missing captured GachaTop page body")

    def resolve(self, path):
        if path == "/api/page/TopPage":
            return self.top_page()
        if path == "/api/page/MyPage":
            return self.my_page()
        if path == "/api/page/GachaTop":
            return self.gacha_top_page()
        if path == "/api/page/GachaAnimation":
            return self._captured_page(
                self.animation,
                ("eventList", "campaignList", "userDeckList", "viewIconList"),
            )
        if path == "/api/page/GachaResult":
            return self._captured_page(
                self.result,
                (
                    "eventList",
                    "campaignList",
                    "gachaScheduleList",
                    "viewIconList",
                ),
            )
        raise KeyError(path)

    @staticmethod
    def _now():
        return datetime.now(JST).isoformat()

    def _load(self, prefix, required_key):
        candidates = sorted(
            self.static_dir.glob(prefix + "*.body"),
            key=lambda item: item.stat().st_size,
            reverse=True,
        )
        for candidate in candidates:
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            if isinstance(data, dict) and required_key in data:
                return data
        return {}

    def _account(self):
        return json.loads(self.account_page.page_payload().decode("utf-8"))

    def _local(self):
        try:
            with urllib.request.urlopen(
                self.state_url, timeout=self.timeout
            ) as response:
                data = json.loads(response.read().decode("utf-8"))
            return data if isinstance(data, dict) else {}
        except (
            urllib.error.URLError,
            TimeoutError,
            OSError,
            UnicodeError,
            json.JSONDecodeError,
        ):
            return {}

    def _items(self, account, local):
        entries = {
            entry["itemId"]: dict(entry)
            for entry in account.get("userItemList", [])
            if isinstance(entry, dict) and isinstance(entry.get("itemId"), str)
        }
        if not local:
            return list(entries.values())
        now = self._now()
        for item_id, quantity in local.get("gameItems", {}).items():
            entry = entries.setdefault(
                item_id,
                {
                    "itemId": item_id,
                    "environmentId": "COMMON",
                    "quantity": 0,
                    "total": 0,
                    "createdAt": now,
                },
            )
            entry["quantity"] = quantity
        for item_id, quantity in (
            ("GOLD", local.get("gold")),
            ("SKIP_QUEST", local.get("skipTickets")),
            ("MONEY", local.get("paidSakuradite")),
            ("PRESENTED_MONEY", local.get("freeSakuradite")),
        ):
            if quantity is None:
                continue
            entry = entries.setdefault(
                item_id,
                {
                    "itemId": item_id,
                    "environmentId": "COMMON",
                    "quantity": 0,
                    "total": 0,
                    "createdAt": now,
                },
            )
            entry["quantity"] = quantity
        for item_id, quantity in self._claimed_items().items():
            entry = entries.setdefault(
                item_id,
                {
                    "itemId": item_id,
                    "environmentId": "COMMON",
                    "quantity": 0,
                    "total": 0,
                    "createdAt": self._now(),
                },
            )
            entry["quantity"] = int(entry.get("quantity", 0)) + quantity
        return list(entries.values())

    def _claimed_items(self):
        if getattr(self.account_page, "authoritative_local_state", False):
            return {}  # Receipts are already reflected in the stateful inventory.
        if self.claim_state_path is None or not self.claim_state_path.is_file():
            return {}
        try:
            data = json.loads(
                self.claim_state_path.read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {}
        totals = {}
        if not isinstance(data, dict):
            return totals
        for claim in data.values():
            if not isinstance(claim, dict) or claim.get("presentType") != "ITEM":
                continue
            item_id = claim.get("itemId")
            quantity = claim.get("cumulativeQuantity", claim.get("quantity"))
            if isinstance(item_id, str) and isinstance(quantity, int):
                totals[item_id] = totals.get(item_id, 0) + quantity
        return totals

    def _kinds(self, account, local):
        kinds = [
            dict(entry)
            for entry in account.get("userGachaKindList", [])
            if isinstance(entry, dict)
        ]
        by_id = {entry.get("gachaKindId"): entry for entry in kinds}
        for local_kind in local.get("gachaKinds", []):
            kind_id = local_kind.get("gachaKindId")
            entry = by_id.get(kind_id)
            if entry is None:
                definition = self._kind_definition(kind_id)
                if not definition:
                    continue
                entry = {
                    "gachaKindId": kind_id,
                    "gachaKind": definition,
                    "createdAt": self._now(),
                }
                kinds.append(entry)
                by_id[kind_id] = entry
            entry["totalCount"] = local_kind.get("totalCount", 0)
            entry["stockCount"] = local_kind.get("stockCount", 0)
            entry["lastDrawnOn"] = local_kind.get("lastDrawnOn")
        return kinds

    def _kind_definition(self, kind_id):
        for schedule in self.gacha_top.get("gachaScheduleList", []):
            for kind in schedule.get("gachaKindList", []):
                if kind.get("gachaKindId") == kind_id:
                    return kind
        return None

    def top_page(self):
        account = self._account()
        local = self._local()
        return {
            "resultCode": "success",
            "currentTime": self._now(),
            "user": self._user(),
            "gameUser": account.get("gameUser", {}),
            "userItemList": self._items(account, local),
        }

    def my_page(self):
        account = self._account()
        local = self._local()
        payload = dict(account)
        for key in LOCAL_SKIPPED_LOGIN_KEYS:
            payload.pop(key, None)
        payload["resultCode"] = "success"
        payload["currentTime"] = self._now()
        payload["user"] = self._user()
        payload["userItemList"] = self._items(account, local)
        # Home chat and its worker require models that are absent from the
        # preserved MyPage snapshot. Keep the page renderable without starting
        # an unsupported network-backed chat connection.
        payload["roomId"] = ""
        return payload

    def gacha_top_page(self):
        def privileged_schedules():
            schedules = copy.deepcopy(
                captured.get("gachaScheduleList", []))
            if local.get("gameItems", {}).get(
                    "LOCAL_UNLIMITED_TEN_PULL", 0) <= 0:
                return schedules
            for schedule in schedules:
                for kind in schedule.get("gachaKindList", []):
                    if "10" in str(kind.get("beanKind", "")):
                        kind["needPointKind"] = "FREE"
                        kind["needQuantity"] = 0
                        kind["localUnlimitedTenPull"] = True
            return schedules

        account = self._account()
        local = self._local()
        captured = self.gacha_top
        points = local.get("gachaPoints")
        limit_breaks = local.get("cardLimitBreaks")
        return {
            "resultCode": "success",
            "currentTime": self._now(),
            "user": {"tutorialId": "", "partId": 0},
            "gameUser": account.get("gameUser", captured.get("gameUser", {})),
            "userItemList": self._items(account, local),
            "userStatusList": account.get("userStatusList", []),
            "userGachaKindList": self._kinds(account, local),
            "userGachaPointList": points if points is not None else [],
            "userGachaGroupPointList": account.get(
                "userGachaGroupPointList", []
            ),
            "userCardList": account.get("userCardList", []),
            "userCardLimitBreakList": (
                limit_breaks if limit_breaks is not None else []
            ),
            "userCharaList": account.get("userCharaList", []),
            "userKnightmareFrameList": account.get(
                "userKnightmareFrameList", []
            ),
            "userKnightmareFrameCustomizeList": account.get(
                "userKnightmareFrameCustomizeList", []
            ),
            "itemList": account.get("itemList", []),
            "cardList": account.get("cardList", []),
            "charaList": account.get("charaList", []),
            "affiliationList": account.get("affiliationList", []),
            "userQuestList": account.get("userQuestList", []),
            "knightmareFrameList": account.get("knightmareFrameList", []),
            "knightmareFrameCustomizeList": account.get(
                "knightmareFrameCustomizeList", []
            ),
            "gachaScheduleList": privileged_schedules(),
            "gachaExchangeList": captured.get("gachaExchangeList", []),
            "userGachaGroupList": account.get("userGachaGroupList", []),
            "eventList": captured.get("eventList", []),
            "campaignList": captured.get("campaignList", []),
            "viewIconList": captured.get("viewIconList", []),
        }

    def _captured_page(self, captured, keys):
        payload = {key: captured.get(key, []) for key in keys}
        account = self._account()
        for key in keys:
            if key.startswith("user"):
                payload[key] = account.get(key, [])
        payload["resultCode"] = "success"
        payload["currentTime"] = self._now()
        return payload

    @staticmethod
    def _user():
        return {
            "id": "local-user",
            "snsUserId": "local-sns-user",
            "tutorialId": "",
            "partId": 0,
            "chapterId": 0,
            "relink": False,
        }


__all__ = ["GachaPageStore"]
