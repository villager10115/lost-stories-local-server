"""Replay selected preserved page models and merge the local account state."""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import threading
import uuid
from pathlib import Path

from web_audit import decode_text


JST = timezone(timedelta(hours=9))

PAGE_SELECTIONS = {
    "/api/page/MissionTop":
        "0057200d9f0eade63cc2c53a899b354d78a02a5964578f71381dda1f5f47292a",
    "/api/page/QuestTop":
        "a62ee10f43e80c01b6fa8b7227421f44c4cf825ed0ede0809e7a1803aebe2ec9",
    "/api/page/DailyQuestTop":
        "26d0cc331af2c64615974b79ec4b7e5b7f23cffbb68ec703eb9034cc1274dfe4",
    "/api/page/RootEntangleTop":
        "bc7eae73ebf5118ef0528ac3b1297fa2312ca9033cd4c5612b321f76efe833b8",
    "/api/page/EventStoryTop":
        "02f4c572f9409bfc34032e1b95f0cca5e006cd3fafb848c281e63ddd8e8c6d09",
    "/api/page/ComposeTop":
        "60eb0e3b8b5f0935e5c4e475465affaeb8c170b5399a144777fc559747d18149",
    "/api/page/ShopTop":
        "f7282b3b64d9c311a7fc80acded29a55603fddf334df12b5b03df9f9883282a2",
    "/api/page/GameConfig":
        "724a3886e1f2c5c4debb92980d02aa7406bd80b9e9e6f81dce1c41e626039030",
    "/api/page/GuildTop":
        "673780a4f30895bacaa667489a7e01e4986a3419016d234384fcf4aa000935d6",
}

COMMON_MODEL_LISTS = (
    "affiliationList",
    "backgroundGroupList",
    "campaignList",
    "cardList",
    "charaList",
    "costumeList",
    "eventList",
    "itemList",
    "knightmareFrameList",
    "knightmareFrameCustomizeList",
    "userBackgroundGroupList",
    "userCardList",
    "userCardLimitBreakList",
    "userCharaList",
    "userCostumeList",
    "userDeckList",
    "userExpeditionAreaList",
    "userItemList",
    "userKnightmareFrameDevelopmentList",
    "userKnightmareFrameList",
    "userKnightmareFrameKeyList",
    "userKnightmareFrameCustomizeList",
    "userQuestList",
    "userStatusList",
    "userSubscriptionList",
    "userTrainingList",
    "viewIconList",
)

CHALLENGE_LISTS = (
    "userBeginnerChallengeList",
    "userDailyChallengeList",
    "userEntangleTotalChallengeList",
    "userEventExpeditionAreaList",
    "userLimitedChallengeList",
    "userSideTotalChallengeList",
    "userTotalChallengeList",
    "userWeeklyChallengeList",
)

ACCOUNT_STATE_LISTS = COMMON_MODEL_LISTS + CHALLENGE_LISTS + (
    "userChapterList",
    "userDailyQuestList",
)

PAGE_REQUIRED_LISTS = {
    "/api/page/MissionTop": (
        "campaignList",
        "challengeGroupList",
        "eventList",
        "limitedChallengeGroupList",
        "userBeginnerChallengeList",
        "userDailyChallengeList",
        "userEntangleTotalChallengeList",
        "userEventExpeditionAreaList",
        "userExpeditionAreaList",
        "userLimitedChallengeList",
        "userQuestList",
        "userSideTotalChallengeList",
        "userTotalChallengeList",
        "userWeeklyChallengeList",
        "viewIconList",
        "itemList",
        "cardList",
        "charaList",
        "knightmareFrameList",
        "knightmareFrameCustomizeList",
        "backgroundGroupList",
        "userBackgroundGroupList",
    ),
    "/api/page/QuestTop": (
        "anotherQuestDetailList",
        "campaignList",
        "eventList",
        "partList",
        "userBeginnerChallengeList",
        "userChapterList",
        "userDailyChallengeList",
        "userDailyQuestList",
        "userEventExpeditionAreaList",
        "userExpeditionAreaList",
        "userLimitedChallengeList",
        "userQuestList",
        "userSideTotalChallengeList",
        "userTotalChallengeList",
        "userTrainingList",
        "userWeeklyChallengeList",
        "viewIconList",
        "backgroundGroupList",
        "userBackgroundGroupList",
    ),
    "/api/page/DailyQuestTop": (
        "campaignList",
        "eventList",
        "gimmickList",
        "npcList",
        "viewIconList",
        "userBeginnerChallengeList",
        "userCardList",
        "userCardLimitBreakList",
        "userChapterList",
        "userCharaList",
        "userDailyChallengeList",
        "userDailyQuestList",
        "userDeckList",
        "userItemList",
        "userKnightmareFrameList",
        "userKnightmareFrameCustomizeList",
        "userLimitedChallengeList",
        "userQuestList",
        "userStatusList",
        "userSubscriptionList",
        "userTotalChallengeList",
        "userTrainingList",
        "userWeeklyChallengeList",
        "itemList",
        "cardList",
        "charaList",
        "affiliationList",
        "knightmareFrameList",
        "knightmareFrameCustomizeList",
        "backgroundGroupList",
        "userBackgroundGroupList",
    ),
    "/api/page/ComposeTop": COMMON_MODEL_LISTS,
    "/api/page/RootEntangleTop": COMMON_MODEL_LISTS + CHALLENGE_LISTS + (
        "entangleChallengeQuestList",
        "gimmickList",
        "npcList",
    ),
    "/api/page/EventStoryTop": COMMON_MODEL_LISTS + CHALLENGE_LISTS + (
        "eventList",
        "gimmickList",
        "npcList",
    ),
    "/api/page/ComposePilot": COMMON_MODEL_LISTS + ("userCardAttributeRankList",),
    "/api/page/ComposeKmf": COMMON_MODEL_LISTS + ("userKnightmareFrameKeyList",),
    "/api/page/ShopTop": COMMON_MODEL_LISTS,
    "/api/page/GameConfig": COMMON_MODEL_LISTS,
    "/api/page/GuildTop": COMMON_MODEL_LISTS + (
        "emblemList",
        "guildMemberList",
        "userDailyChallengeList",
        "userWeeklyChallengeList",
        "userTotalChallengeList",
        "userBeginnerChallengeList",
        "userLimitedChallengeList",
        "userTrainingList",
    ),
}

GENERIC_PAGE_PATHS = frozenset({
    "/api/page/ArchiveTop",
    "/api/page/ArenaTop",
    "/api/page/BgmSetting",
    "/api/page/ChangeBackground",
    "/api/page/ComposePilot",
    "/api/page/ComposeKmf",
    "/api/page/CostumeTop",
    "/api/page/KmfColoring",
    "/api/page/CarryingTop",
    "/api/page/KmfDevelopment",
    "/api/page/KmfDismantle",
    "/api/page/DeckFormation",
    "/api/page/Help",
    "/api/page/ItemTop",
    "/api/page/MyProfileTop",
    "/api/page/TrainingTop",
})


CLAIM_SCOPES = {
    "daily": ("userDailyChallengeList",),
    "weekly": ("userWeeklyChallengeList",),
    "total": ("userTotalChallengeList",),
    "beginner": ("userBeginnerChallengeList",),
    "limited": ("userLimitedChallengeList",),
    "side": ("userSideTotalChallengeList",),
    "entangle": ("userEntangleTotalChallengeList",),
    "normal": (
        "userDailyChallengeList",
        "userWeeklyChallengeList",
        "userTotalChallengeList",
        "userBeginnerChallengeList",
        "userSideTotalChallengeList",
        "userEntangleTotalChallengeList",
    ),
}


class PreservedPageStore:
    def __init__(self, cache_directory, account_page=None, selections=None,
                 claim_state_path=None):
        self.cache_directory = Path(cache_directory).resolve(strict=True)
        self.account_page = account_page
        self.selections = dict(selections or PAGE_SELECTIONS)
        self.pages = {
            path: self._load(digest)
            for path, digest in self.selections.items()
        }
        self.claim_state_path = (
            Path(claim_state_path) if claim_state_path is not None else None
        )
        self.claims = {}
        self._claim_lock = threading.RLock()
        if self.claim_state_path and self.claim_state_path.is_file():
            data = json.loads(self.claim_state_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self.claims = {
                    key: value for key, value in data.items()
                    if isinstance(key, str) and isinstance(value, dict)
                }

    def _load(self, digest):
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError("Invalid preserved page digest")
        body_path = self.cache_directory / (digest + ".body")
        raw = body_path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError("Preserved page checksum mismatch")
        text, _ = decode_text(raw)
        data = json.loads(text)
        if not isinstance(data, dict) or data.get("resultCode") != "success":
            raise ValueError("Preserved page is not a successful response")
        return data

    def _account(self):
        if self.account_page is None:
            return {}
        data = json.loads(self.account_page.page_payload().decode("utf-8"))
        return data if isinstance(data, dict) else {}

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

    @staticmethod
    def _now():
        return datetime.now(JST).isoformat()

    def _save_claims(self):
        if self.claim_state_path is None:
            return
        self.claim_state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.claim_state_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(self.claims, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.claim_state_path)

    def _apply_claims(self, payload, now):
        item_totals = {}
        for list_key in CHALLENGE_LISTS:
            for entry in payload.get(list_key, []):
                claim = self.claims.get(
                    "%s:%s" % (list_key, entry.get("challengeId"))
                )
                if claim and isinstance(claim.get("receivedAt"), str):
                    entry["receivedAt"] = claim["receivedAt"]
                if claim and claim.get("presentType") == "ITEM":
                    item_id = claim.get("itemId")
                    quantity = claim.get("cumulativeQuantity", claim.get("quantity"))
                    if isinstance(item_id, str) and isinstance(quantity, int):
                        item_totals[item_id] = item_totals.get(item_id, 0) + quantity
        if item_totals:
            entries = {
                entry.get("itemId"): entry
                for entry in payload.get("userItemList", [])
                if isinstance(entry, dict)
            }
            for item_id, quantity in item_totals.items():
                entry = entries.get(item_id)
                if entry is None:
                    entry = {
                        "itemId": item_id,
                        "environmentId": "COMMON",
                        "quantity": 0,
                        "total": 0,
                        "createdAt": now,
                    }
                    payload.setdefault("userItemList", []).append(entry)
                    entries[item_id] = entry
                entry["quantity"] = int(entry.get("quantity", 0)) + quantity
        return payload

    def resolve(self, path):
        if path not in self.pages and path not in GENERIC_PAGE_PATHS:
            raise KeyError(path)
        account = self._account()
        payload = dict(account)
        if path in self.pages:
            payload.update(copy.deepcopy(self.pages[path]))
        if path == "/api/page/ShopTop":
            for key in (
                    "shopList", "userShopItemList",
                    "weeklyShopResetAt", "monthlyShopResetAt"):
                if key in account:
                    payload[key] = copy.deepcopy(account[key])
        for key in ACCOUNT_STATE_LISTS:
            if key in account:
                payload[key] = copy.deepcopy(account[key])
        if getattr(self.account_page, "authoritative_local_state", False):
            # Captures contribute definitions only. Never replay ownership,
            # purchase history, membership, currency or identity into a new user.
            for key, value in list(payload.items()):
                if key.startswith("user") and isinstance(value, list):
                    payload[key] = copy.deepcopy(account.get(key, []))
            for key in ("gameUser", "guild", "guildMember", "guildMemberList",
                        "unapprovedList", "guildMemberNum", "presentCount", "roomId"):
                if key in account:
                    payload[key] = copy.deepcopy(account[key])
                elif key in payload:
                    payload.pop(key)
        payload["resultCode"] = "success"
        payload["currentTime"] = self._now()
        payload["user"] = self._user()
        account_user = account.get("user")
        if isinstance(account_user, dict):
            payload["user"].update(copy.deepcopy(account_user))
        required = PAGE_REQUIRED_LISTS.get(path, COMMON_MODEL_LISTS)
        for key in required:
            if not isinstance(payload.get(key), list):
                payload[key] = []
        if not isinstance(payload.get("gameUser"), dict):
            payload["gameUser"] = {}
        if path == "/api/page/ShopTop":
            payload["shopList"] = list(payload.get("shopList", [])) + copy.deepcopy(
                payload.get("localShopList", []))
            payload["userShopItemList"] = (
                list(payload.get("userShopItemList", [])) + copy.deepcopy(
                    payload.get("localUserShopItemList", [])))
            known = {row.get("shopItemId") for row in payload["userShopItemList"]}
            for shop in payload["shopList"]:
                for item in shop.get("shopItemList", []):
                    if item.get("id") in known:
                        continue
                    known.add(item.get("id"))
                    payload["userShopItemList"].append({
                        "shopItemId": item.get("id"), "num": 0,
                        "opened": True, "recentExchangedAt": None,
                        "createdAt": payload["currentTime"]})
        if path == "/api/page/MissionTop":
            active_limited_ids = {
                group.get("id")
                for group in payload.get("limitedChallengeGroupList", [])
                if isinstance(group, dict)
            }
            payload["userLimitedChallengeList"] = [
                entry for entry in payload.get("userLimitedChallengeList", [])
                if isinstance(entry, dict)
                and (entry.get("challenge") or {})
                    .get("limitedChallengeGroup", {})
                    .get("id") in active_limited_ids
            ]
        if getattr(self.account_page, "authoritative_local_state", False):
            return payload
        return self._apply_claims(payload, payload["currentTime"])

    @staticmethod
    def _is_ready(list_key, entry, now):
        challenge = entry.get("challenge") or {}
        count = challenge.get("count")
        if not isinstance(count, int):
            return False
        if int(entry.get("clearedCount", 0)) < count:
            return False
        received = entry.get("receivedAt")
        if not received:
            return True
        try:
            received_at = datetime.fromisoformat(received.replace("Z", "+00:00"))
        except ValueError:
            return True
        if list_key == "userDailyChallengeList":
            return received_at.date() != now.date()
        if list_key == "userWeeklyChallengeList":
            return now - received_at >= timedelta(days=7)
        return False

    def claim(self, scope, challenge_id=None):
        with self._claim_lock:
            previous = copy.deepcopy(self.claims)
            try:
                return self._claim(scope, challenge_id)
            except Exception:
                self.claims = previous
                raise

    def _claim(self, scope, challenge_id=None):
        list_keys = CLAIM_SCOPES.get(scope)
        if list_keys is None:
            raise KeyError(scope)
        payload = self.resolve("/api/page/MissionTop")
        current = datetime.fromisoformat(payload["currentTime"])
        results = []
        for list_key in list_keys:
            for entry in payload.get(list_key, []):
                if challenge_id is not None:
                    if int(entry.get("challengeId", -1)) != challenge_id:
                        continue
                if not self._is_ready(list_key, entry, current):
                    continue
                challenge = entry.get("challenge") or {}
                if challenge.get("presentType") != "ITEM":
                    raise ValueError("Unsupported local reward type")
                stamp = current.isoformat()
                key = "%s:%s" % (list_key, entry.get("challengeId"))
                previous = self.claims.get(key, {})
                self.claims[key] = {
                    "receivedAt": stamp,
                    "itemId": challenge.get("genericCode"),
                    "quantity": int(challenge.get("itemNum", 1)),
                    "presentType": challenge.get("presentType"),
                    "cumulativeQuantity": int(previous.get("cumulativeQuantity",
                        previous.get("quantity", 0))) + int(challenge.get("itemNum", 1)),
                }
                entry["receivedAt"] = stamp
                results.append({
                    "instanceId": str(uuid.uuid4()),
                    "originType": "CHALLENGE",
                    "createdAt": stamp,
                    "itemId": challenge.get("genericCode"),
                    "quantity": int(challenge.get("itemNum", 1)),
                    "presentType": challenge.get("presentType"),
                    "genericCode": challenge.get("genericCode"),
                    "displayName": challenge.get("displayName"),
                })
        self._save_claims()
        updated = self.resolve("/api/page/MissionTop")
        return {"resultCode": "success", "currentTime": current.isoformat(),
                "results": results, "userItemList": updated.get("userItemList", []),
                **{key: updated.get(key, []) for key in list_keys}}


__all__ = ["GENERIC_PAGE_PATHS", "PAGE_SELECTIONS", "PreservedPageStore"]
