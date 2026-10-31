"""Build a client-compatible account model from local bootstrap state.

The class intentionally uses the extracted master tables instead of replaying
the captured account snapshot. Dynamic ownership comes from the loopback
stateful service.
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import urllib.error
import urllib.request
from urllib.parse import urlsplit
import uuid
from shop import (
    LOCAL_FREE_MONEY_TARGET_USER_ID,
    local_shop_models,
    purchase_counter_id,
)


JST = timezone(timedelta(hours=9))
NAMESPACE = uuid.UUID("f31c7d18-2f1b-4dc7-a75d-85e64ae6f6e1")

CHALLENGE_LIST_KEYS = (
    "userDailyChallengeList",
    "userWeeklyChallengeList",
    "userTotalChallengeList",
    "userBeginnerChallengeList",
    "userLimitedChallengeList",
    "userSideTotalChallengeList",
    "userEntangleTotalChallengeList",
)

STARTER_CHAPTER = {
    "chapterId": 50,
    "chapterType": "MAIN",
    "chapterNo": "7",
    "title": "あなたのいない日々",
    "partId": 6,
    "storyNum": 10,
    "battleNum": 10,
    "extraBattleNum": 5,
    "openDate": "2026-03-26T15:05:00+09:00",
}

DAILY_QUEST_TYPES = (
    {
        "name": "KMF_FAR",
        "dayOfWeekCoefficientMap": {"FRIDAY": "2.0"},
        "maxClearCount": 10,
        "maxAdditionalCount": 10,
        "targetItemIds": [
            "KMF_CHIP_FAR_BRONZE",
            "KMF_CHIP_FAR_SILVER",
            "KMF_CHIP_FAR_GOLD",
        ],
    },
    {
        "name": "CARD_REVISION_BISHOP_STAR",
        "dayOfWeekCoefficientMap": {"MONDAY": "2.0"},
        "maxClearCount": 10,
        "maxAdditionalCount": 10,
        "targetItemIds": [
            "CARD_CRYSTAL_BISHOP_BRONZE",
            "CARD_CRYSTAL_STAR_BRONZE",
            "CARD_CRYSTAL_BISHOP_SILVER",
            "CARD_CRYSTAL_STAR_SILVER",
            "CARD_CRYSTAL_BISHOP_GOLD",
            "CARD_CRYSTAL_STAR_GOLD",
        ],
    },
    {
        "name": "CARD_REVISION_ROOK_KING",
        "dayOfWeekCoefficientMap": {"WEDNESDAY": "2.0"},
        "maxClearCount": 10,
        "maxAdditionalCount": 10,
        "targetItemIds": [
            "CARD_CRYSTAL_ROOK_BRONZE",
            "CARD_CRYSTAL_KING_BRONZE",
            "CARD_CRYSTAL_ROOK_SILVER",
            "CARD_CRYSTAL_KING_SILVER",
            "CARD_CRYSTAL_ROOK_GOLD",
            "CARD_CRYSTAL_KING_GOLD",
        ],
    },
    {
        "name": "GOLD_CARD_EXP",
        "dayOfWeekCoefficientMap": {
            "SATURDAY": "2.0",
            "SUNDAY": "2.0",
        },
        "maxClearCount": 10,
        "maxAdditionalCount": 10,
        "targetItemIds": ["GOLD", "EXP", "EXP_P", "EXP_PP"],
    },
    {
        "name": "KMF_NEAR",
        "dayOfWeekCoefficientMap": {"THURSDAY": "2.0"},
        "maxClearCount": 10,
        "maxAdditionalCount": 10,
        "targetItemIds": [
            "KMF_CHIP_NEAR_BRONZE",
            "KMF_CHIP_NEAR_SILVER",
            "KMF_CHIP_NEAR_GOLD",
        ],
    },
    {
        "name": "CARD_REVISION_KNIGHT_QUEEN",
        "dayOfWeekCoefficientMap": {"TUESDAY": "2.0"},
        "maxClearCount": 10,
        "maxAdditionalCount": 10,
        "targetItemIds": [
            "CARD_CRYSTAL_KNIGHT_BRONZE",
            "CARD_CRYSTAL_QUEEN_BRONZE",
            "CARD_CRYSTAL_KNIGHT_SILVER",
            "CARD_CRYSTAL_QUEEN_SILVER",
            "CARD_CRYSTAL_KNIGHT_GOLD",
            "CARD_CRYSTAL_QUEEN_GOLD",
        ],
    },
)


class NewAccountPage:
    authoritative_local_state = True
    def __init__(self, masterdata_directory, state_url, timeout=3):
        self.masterdata_directory = Path(masterdata_directory).resolve(strict=True)
        self.state_url = state_url
        base = state_url.rstrip("/")
        if base.endswith("/api/local/page-state"):
            base = base[:-len("/page-state")]
        self.base_url = base
        self.timeout = timeout
        self.static = json.loads(
            (self.masterdata_directory / "pages" / "MyPage.static.json")
            .read_text(encoding="utf-8")
        )
        self.cards = {
            row["cardId"]: row for row in self.static.get("cardList", [])
        }
        self.costumes = {
            row["costumeId"]: row
            for row in self.static.get("costumeList", [])
        }
        self.charas = {
            row["charaId"]: row for row in self.static.get("charaList", [])
        }
        self.kmfs = {
            row["knightmareFrameId"]: row
            for row in self.static.get("knightmareFrameList", [])
        }
        customizations = self.static.get("knightmareFrameCustomizeList", [])
        self.customizations = {
            row["knightmareFrameCustomizeId"]: row
            for row in customizations
        }
        self.customizations_by_kmf = {}
        for row in customizations:
            self.customizations_by_kmf.setdefault(
                row["knightmareFrameId"], []
            ).append(row)
        for rows in self.customizations_by_kmf.values():
            rows.sort(key=lambda row: row.get("sortKey", 0))
        self.items = {
            row["itemId"]: row for row in self.static.get("itemList", [])
        }
        self.levels = {
            row["id"]: row for row in self.static.get("levelList", [])
        }
        daily_catalog_path = (
            self.masterdata_directory / "daily-quest-catalog.json"
        )
        self.daily_quest_templates = (
            json.loads(daily_catalog_path.read_text(encoding="utf-8"))
            .get("quests", [])
            if daily_catalog_path.is_file() else []
        )
        quest_top_static_path = (
            self.masterdata_directory / "pages" / "QuestTop.static.json"
        )
        quest_top_static = (
            json.loads(quest_top_static_path.read_text(encoding="utf-8"))
            if quest_top_static_path.is_file() else {}
        )
        self.main_story_parts = quest_top_static.get("partList", [])
        self.main_story_catalog = json.loads((Path(__file__).resolve().parents[1] /
            "stateful_server/fixtures/main_story_catalog.json").read_text(encoding="utf-8"))
        self.tutorial_catalog = json.loads((Path(__file__).resolve().parents[1] /
            "stateful_server/fixtures/tutorial_quests.json").read_text(encoding="utf-8"))

        all_quest_path = (Path(__file__).resolve().parents[1] /
            "stateful_server/fixtures/all_quest_catalog.json")
        self.all_quest_catalog = (json.loads(
            all_quest_path.read_text(encoding="utf-8"))
            if all_quest_path.is_file() else {"quests": []})
        for catalog in (self.all_quest_catalog, self.main_story_catalog):
            for quest in catalog.get("quests", []):
                self._with_local_skip_drop(quest)

    @staticmethod
    def _with_local_skip_drop(quest):
        if quest.get("questType") == "DAILY" or quest.get("onlyStory"):
            return quest
        drops = quest.setdefault("uniqueQuestDropRewardList", [])
        if not any(row.get("genericCode") == "SKIP_QUEST" for row in drops):
            drops.append({
                "presentType": "ITEM",
                "genericCode": "SKIP_QUEST",
                "num": 1,
            })
        return quest
    def _now(self):
        return datetime.now(JST).isoformat()

    @staticmethod
    def _get_json(url):
        with urllib.request.urlopen(url, timeout=3) as response:
            raw = response.read(4 * 1024 * 1024 + 1)
        if len(raw) > 4 * 1024 * 1024:
            raise ValueError("Local state response is too large")
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Local state response must be an object")
        return data

    def _state(self):
        return self._get_json(self.base_url + "/page-state")

    def _units(self):
        return self._get_json(self.base_url + "/units")

    @staticmethod
    def _stable_id(*values):
        return str(uuid.uuid5(NAMESPACE, ":".join(str(value) for value in values)))

    def _user_chapters(self, now):
        return [{
            "chapterId": STARTER_CHAPTER["chapterId"],
            "chapter": dict(STARTER_CHAPTER),
            "maxDamage": 0,
            "clearedAt": None,
            "createdAt": now,
        }]

    def _main_story_cleared_closure(self, progress):
        """Treat cleared later stages as evidence for missing earlier rows."""
        quests = {quest["questId"]: quest
                  for quest in self.main_story_catalog["quests"]}
        cleared = {
            int(quest_id) for quest_id, row in progress.items()
            if row.get("questStatus") == "CLEARED"
        }
        pending = [(quest_id, quests[quest_id].get("chapterId"))
                   for quest_id in cleared if quest_id in quests]
        while pending:
            quest_id, chapter_id = pending.pop()
            quest = quests.get(quest_id)
            if not quest or quest.get("difficulty") == "EXTRA":
                continue
            required = quest.get("requiredQuestId")
            try:
                required = int(required)
            except (TypeError, ValueError):
                continue
            prerequisite = quests.get(required)
            # Do not let a late save mark every earlier chapter as new.
            if (not prerequisite
                    or prerequisite.get("chapterId") != chapter_id):
                continue
            if required in cleared:
                continue
            cleared.add(required)
            pending.append((required, chapter_id))
        return cleared

    @staticmethod
    def _main_story_unlock_state(quest, effectively_cleared):
        required_quest_id = quest.get("requiredQuestId")
        if not required_quest_id:
            return "OPENED", False
        try:
            required_quest_id = int(required_quest_id)
        except (TypeError, ValueError):
            return "CANDIDATE", False
        if required_quest_id not in effectively_cleared:
            return "CANDIDATE", False
        # Inferred historical rows stay open without being advertised as the
        # current frontier. The first reachable node outside the closure is new.
        return "OPENED", int(quest["questId"]) not in effectively_cleared

    def _main_story_quests(self, now, state=None):
        state = state or {}
        progress = {
            row["questId"]: row for row in state.get("userQuestList", [])
            if isinstance(row, dict) and row.get("questId")
        }
        progress.update({
            row["questId"]: row for row in state.get("userStoryList", [])
            if isinstance(row, dict) and row.get("questId")
        })
        effectively_cleared = self._main_story_cleared_closure(progress)
        tutorial_id = state.get("tutorialId", "")
        rows = []
        tutorial_quests = [
            quest for quest in self.tutorial_catalog.get("quests", [])
            if quest.get("activeTutorialId") == tutorial_id]
        for quest in tutorial_quests + self.main_story_catalog["quests"]:
            quest_status, newly_unlocked = self._main_story_unlock_state(
                quest, effectively_cleared)
            row = {"questId": quest["questId"], "quest": copy.deepcopy(quest),
                   "questStatus": quest_status, "bestQuestRank": "NONE",
                   "isNew": newly_unlocked, "clearedAt": None, "createdAt": now,
                   "clearedMission1": False, "clearedMission2": False,
                   "clearedMission3": False}
            saved = progress.get(quest["questId"], {})
            for key in ("questStatus", "bestQuestRank", "isNew", "clearedAt", "createdAt",
                        "clearedMission1", "clearedMission2", "clearedMission3"):
                if key in saved:
                    row[key] = copy.deepcopy(saved[key])
            rows.append(row)
        return rows

    def _catalog_quest_rows(self, quest_types, state, now):
        progress = {
            row.get("questId"): row
            for row in (
                list(state.get("userQuestList", []))
                + list(state.get("userStoryList", [])))
            if isinstance(row, dict) and row.get("questId")
        }
        result = []
        for quest in self.all_quest_catalog.get("quests", []):
            if quest.get("questType") not in quest_types:
                continue
            stored_quest = copy.deepcopy(quest)
            if stored_quest.get("questType") == "DAILY":
                stored_quest["dailyType"]["maxClearCount"] = 10
                stored_quest["dailyType"]["maxAdditionalCount"] = 10
            row = {
                "questId": quest["questId"],
                "quest": stored_quest,
                "questStatus": "OPENED",
                "bestQuestRank": "NONE",
                "isNew": False,
                "clearedAt": None,
                "createdAt": now,
                "clearedMission1": False,
                "clearedMission2": False,
                "clearedMission3": False,
            }
            saved = progress.get(quest["questId"], {})
            for key in (
                    "questStatus", "bestQuestRank", "isNew", "clearedAt",
                    "createdAt", "clearedMission1", "clearedMission2",
                    "clearedMission3"):
                if key in saved:
                    row[key] = copy.deepcopy(saved[key])
            result.append(row)
        return result

    def quest_category_payload(self, quest_types, static_page):
        state = self._state()
        payload = json.loads(self.page_payload().decode("utf-8"))
        now = payload["currentTime"]
        battle_static = json.loads((self.masterdata_directory / "pages" /
            "DailyQuestTop.static.json").read_text(encoding="utf-8"))
        payload["npcList"] = copy.deepcopy(battle_static["npcList"])
        payload["gimmickList"] = copy.deepcopy(battle_static["gimmickList"])
        payload["userQuestList"] = self._catalog_quest_rows(
            set(quest_types), state, now)
        if static_page == "AnotherQuestTop":
            quest_top = json.loads((self.masterdata_directory / "pages" /
                "QuestTop.static.json").read_text(encoding="utf-8"))
            payload["anotherQuestDetailList"] = copy.deepcopy(
                quest_top.get("anotherQuestDetailList", []))
        chapters = {}
        for row in payload["userQuestList"]:
            quest = row["quest"]
            chapter_id = quest.get("chapterId")
            if chapter_id and chapter_id not in chapters:
                chapters[chapter_id] = {
                    "chapterId": chapter_id,
                    "chapter": {
                        "chapterId": chapter_id,
                        "chapterType": quest.get("questType"),
                        "chapterNo": "",
                        "title": quest.get("name", ""),
                    },
                    "maxDamage": 0,
                    "clearedAt": None,
                    "createdAt": now,
                }
        if chapters:
            payload["userChapterList"] = list(chapters.values())
        static_path = (
            self.masterdata_directory / "pages" / (static_page + ".static.json"))
        if static_path.is_file():
            static = json.loads(static_path.read_text(encoding="utf-8"))
            for key in ("eventList", "npcList", "gimmickList",
                        "entangleChallengeQuestList"):
                if key in static:
                    payload[key] = copy.deepcopy(static[key])
        payload["firstNavi"] = False
        return json.dumps(
            payload, ensure_ascii=False, allow_nan=False).encode("utf-8")

    def _user_daily_quests(self, now):
        current = datetime.fromisoformat(now)
        previous = (current - timedelta(days=1)).isoformat()
        return [{
            "dailyType": json.loads(json.dumps(daily_type)),
            "dailyClearCount": 0,
            "dailyAdditionalCount": 0,
            "recentClearedAt": previous,
            "recentAdditionalAt": previous,
            "createdAt": now,
            "dailyTypeName": daily_type["name"],
        } for daily_type in DAILY_QUEST_TYPES]

    def _user_daily_list(self, state, now):
        live = {
            row.get("dailyTypeName"): row
            for row in state.get("userDailyQuestList", [])
            if isinstance(row, dict)
        }
        result = []
        for default in self._user_daily_quests(now):
            row = copy.deepcopy(live.get(default["dailyTypeName"], default))
            row["dailyType"]["maxClearCount"] = 10
            row["dailyType"]["maxAdditionalCount"] = 10
            result.append(row)
        return result

    def _user_event_expedition_areas(self, now):
        result = []
        for event in self.static.get("eventList", []):
            if event.get("eventType") != "EXPEDITION_AREA":
                continue
            result.append({
                "eventId": event["eventId"],
                "sortieCount": 0,
                "totalSortieCount": 0,
                "sortieCountBySubscriptionBonus": 0,
                "maxTotalSortieCount": 5,
                "latestMaxTotalSortieCountUpdatedAt": now,
                "createdAt": now,
                "maxSortieCount": 1,
                "additionalSortieCount": 1,
                "stock": True,
            })
        return result

    def _user_quests(self, state, now):
        live_quests = {
            row.get("questId"): row
            for row in state.get("userQuestList", [])
            if isinstance(row, dict) and row.get("questId")
        }
        result = []
        for template in self.daily_quest_templates:
            quest_id = template["questId"]
            if quest_id in live_quests:
                row = copy.deepcopy(live_quests[quest_id])
                if row["quest"].get("dailyType"):
                    row["quest"]["dailyType"]["maxClearCount"] = 10
                    row["quest"]["dailyType"]["maxAdditionalCount"] = 10
                result.append(row)
            else:
                quest = copy.deepcopy(template["quest"])
                quest["dailyType"]["maxClearCount"] = 10
                quest["dailyType"]["maxAdditionalCount"] = 10
                result.append({
                    "questId": quest_id,
                    "quest": quest,
                    "questStatus": "OPENED",
                    "bestQuestRank": "NONE",
                    "isNew": False,
                    "createdAt": now,
                })
        return result

    def _game_user(self, state, user_cards, user_customizations):
        now = self._now()
        experience = int(state.get("battleExperience", 0))
        rank = max((key for key,row in self.levels.items()
                    if int(row.get("experience",0)) <= experience), default=1)
        current_level = self.levels.get(rank, {"experience": 0})
        next_level = self.levels.get(rank + 1, {"experience": 14})
        first_card = user_cards[0] if user_cards else None
        card_definition = self.cards.get(first_card["cardId"]) if first_card else None
        favorite = first_card["userCardId"] if first_card else ""
        home_customizations = user_customizations[:6]
        game_user = {
            "userId": state.get("userId", "local-user"),
            "name": state.get("displayName") or "Commander",
            "sex": "MALE",
            "birthMonth": 1,
            "birthDay": 1,
            "lastAccessDate": now,
            "experience": experience,
            "rank": rank,
            "totalExpForCurrentLevel": int(
                current_level.get("experience", 0)
            ),
            "totalExpForNextLevel": int(
                next_level.get("experience", 14)
            ),
            "favoriteUserCardId": favorite,
            "myPageCardId": first_card["cardId"] if first_card else 0,
            "myPageCard": card_definition or {},
            "loginBonusCount": 0,
            "loginBonusGetAt": now,
            "loginDayCount": 0,
            "continuousLoginDayCount": 0,
            "lastLoginDate": now,
            "secondLastLoginDate": now,
            "comment": "",
            "playerId": "local-player",
            "clearedNativeCacheAt": now,
            "closeFunctions": "",
            "loginBonusPattern": "",
            "loginBonusComebackPattern": "",
            "loginBonusStartDashPattern": "",
            "announcementViewAt": now,
            "userReviewStatus": "ACCEPTED",
            "freeGachaAt": now,
            "backgroundGroupId": 1001,
            "passwordNotice": False,
            "forceTopTransition": False,
            "sortieCount": 0,
            "sortieStartedAt": now,
            "maxSortieCount": 1,
            "arenaDefenseRewardGetAt": now,
            "emblemId": 0,
            "createdAt": now,
        }
        for index in range(1, 7):
            item = (
                home_customizations[index - 1]
                if index <= len(home_customizations)
                else None
            )
            game_user["homeUserKnightmareFrameCustomizeId%d" % index] = (
                item["userKnightmareFrameCustomizeId"] if item else ""
            )
            game_user["homeKnightmareFrameCustomizeId%d" % index] = (
                item["knightmareFrameCustomizeId"] if item else 0
            )
        return game_user

    def _user_cards(self, units, state):
        result = []
        now = self._now()
        selected_costumes = state.get("cardCostumes") or {}
        for item in units.get("userCardList", []):
            card = self.cards.get(int(item.get("cardId", 0)))
            if not card:
                continue
            current_costume = int(
                selected_costumes.get(item["userCardId"], 0) or 0
            )
            costume = self.costumes.get(current_costume)
            if (costume is None
                    or int(costume.get("charaId", 0))
                    != int(card.get("charaId", 0))):
                current_costume = 0
            result.append({
                "cardId": card["cardId"],
                "lbCount": int(item.get("lbCount", 0)),
                "revision": int(item.get("revision", 0)),
                "revisionClass": min(6, int(item.get("revision", 0)) // 3 + 1),
                "cost": int(card.get("cost", 0)),
                "blockNum": int(card.get("blockNum", 0)),
                "hp": int(card.get("hp", 0)),
                "nearAttackAdjust": int(card.get("nearAttackAdjust", 0)),
                "nearHitAccuracy": int(card.get("nearHitAccuracy", 0)),
                "nearAttackInterval": int(card.get("nearAttackInterval", 0)),
                "farAttackAdjust": int(card.get("farAttackAdjust", 0)),
                "farHitAccuracy": int(card.get("farHitAccuracy", 0)),
                "farAttackInterval": int(card.get("farAttackInterval", 0)),
                "defenseAdjust": int(card.get("defenseAdjust", 0)),
                "avoidRate": int(card.get("avoidRate", 0)),
                "level": max(1, int(item.get("level", 1))),
                "experience": max(0, int(item.get("experience", 0))),
                "bondsLevel": int(item.get("bondsLevel", 0)),
                "bondsPoint": int(item.get("bondsPoint", 0)),
                "relocationTime": int(card.get("relocationTime", 60000)),
                "strength": int(card.get("strength", 0)),
                "cardSkillLevel1": 1,
                "cardSkillLocked1": False,
                "cardSkillLevel2": 1,
                "cardSkillLocked2": True,
                "expeditionDeadFlg": False,
                "isNew": False,
                "isArchiveNew": False,
                "favorite": False,
                "createdAt": now,
                "userCardId": item["userCardId"],
                **({"costumeId": current_costume} if current_costume else {}),
                "bonusList": [],
                "unlockedFeatureIdList": [],
                **{key: copy.deepcopy(item[key]) for key in (
                    "hp", "cost", "blockNum", "nearAttackAdjust", "farAttackAdjust",
                    "nearHitAccuracy", "farHitAccuracy", "nearAttackInterval", "farAttackInterval",
                    "defenseAdjust", "avoidRate", "relocationTime", "strength", "unlockedFeatureIdList",
                    "cardSkillLevel1", "cardSkillLevel2", "cardSkillLocked1", "cardSkillLocked2") if key in item},
            })
        return result

    def _user_kmfs(self, units):
        result = []
        now = self._now()
        for item in units.get("userKnightmareFrameList", []):
            if int(item.get("knightmareFrameId", 0)) not in self.kmfs:
                continue
            result.append({
                "knightmareFrameId": int(item["knightmareFrameId"]),
                "first": False,
                "protection": False,
                "expeditionDeadFlg": False,
                "skillPoint": int(item.get("skillPoint", 0)),
                "isNew": False,
                "isInStorage": bool(item.get("isInStorage", False)),
                "favorite": False,
                "createdAt": now,
                "userKnightmareFrameId": item["userKnightmareFrameId"],
                "useCustomColor": bool(item.get("useCustomColor", False)),
                "customColorR": int(item.get("customColorR", 150)),
                "customColorG": int(item.get("customColorG", 150)),
                "customColorB": int(item.get("customColorB", 150)),
            })
        return result

    def _user_customizations(self, units, user_kmfs):
        result = []
        now = self._now()
        unit_by_kmf = {
            item["userKnightmareFrameId"]: item
            for item in units.get("userKnightmareFrameList", [])
        }
        for kmf in user_kmfs:
            unit = unit_by_kmf.get(kmf["userKnightmareFrameId"], {})
            customization_id = unit.get("customizationId")
            definition = self.customizations.get(customization_id)
            if definition is None:
                options = self.customizations_by_kmf.get(
                    kmf["knightmareFrameId"], []
                )
                definition = options[0] if options else None
            if definition is None:
                continue
            result.append({
                "userKnightmareFrameId": kmf["userKnightmareFrameId"],
                "knightmareFrameCustomizeId":
                    definition["knightmareFrameCustomizeId"],
                "selected": True,
                "locked": False,
                "revision": int(unit.get("revision", 0)),
                "revisionClass": min(4, int(unit.get("revision", 0)) // 3 + 1),
                "cost": int(definition.get("cost", 0)),
                "blockNum": int(definition.get("blockNum", 0)),
                "attackType": str(definition.get("attackType", "")),
                "attackTypeDescription":
                    definition.get("attackTypeDescription", ""),
                "attack": int(definition.get("attack", 0)),
                "defense": int(definition.get("defense", 0)),
                "strength": int(definition.get("strength", 0)),
                "knightmareFrameSkillLevel": 1,
                "createdAt": now,
                "userKnightmareFrameCustomizeId": self._stable_id(
                    kmf["userKnightmareFrameId"],
                    definition["knightmareFrameCustomizeId"],
                ),
                "bonusList": [],
                **{key:unit[key] for key in ("cost", "blockNum", "attack", "defense", "strength") if key in unit},
                **({"knightmareFrameSkillLevel":unit["skillLevel"]} if "skillLevel" in unit else {}),
            })
        return result

    def _user_items(self, state):
        result = []
        now = self._now()
        quantities = dict(state.get("gameItems") or {})
        for item_id, field in (("GOLD", "gold"), ("MONEY", "paidSakuradite"),
                               ("PRESENTED_MONEY", "freeSakuradite"),
                               ("SKIP_QUEST", "skipTickets")):
            quantities[item_id] = int(state.get(field, 0))
        for item_id, quantity in sorted(quantities.items()):
            definition = self.items.get(item_id, {})
            result.append({
                "itemId": item_id,
                "environmentId": "COMMON",
                "quantity": int(quantity),
                "total": 0,
                "createdAt": now,
                "displayName": definition.get("name", item_id),
            })
        return result

    def _user_statuses(self, state):
        stamina = int(state.get("stamina", 0))
        max_stamina = int(state.get("maxStamina", stamina))
        now = self._now()
        return [
            {
                "statusId": status_id,
                "point": point,
                "checkPeriod": period,
                "periodicPoint": periodic,
                "checkedAt": now,
                "createdAt": now,
            }
            for status_id, point, period, periodic in (
                ("ACP", stamina, 6, 1),
                ("MAX_ACP", max_stamina, 0, 0),
                ("UEP", 10, 1, 0),
                ("MAX_UEP", 10, 0, 0),
                ("MAX_DECK", 10, 0, 0),
                ("MAX_FRIEND", 15, 0, 0),
                ("BTP", 5, 1, 0),
                ("MAX_BTP", 5, 0, 0),
            )
        ]

    def _user_decks(self, state):
        result = []
        for deck in state.get("decks") or []:
            deck_no = int(deck.get("deckNo", 1))
            row = {
                "deckNo": deck_no,
                "deckType": "MAIN%d" % deck_no,
                "name": deck.get("name") or "Knights%d" % deck_no,
            }
            for index, slot in enumerate(deck.get("slots") or [], start=1):
                row["userCardId%d" % index] = slot.get("pilot", "")
                row["userKnightmareFrameId%d" % index] = slot.get("kmf", "")
            result.append(row)
        return result

    def _user_attribute_ranks(self, state):
        return [
            copy.deepcopy(row)
            for row in state.get("cardAttributeRanks", [])
            if isinstance(row, dict) and row.get("attribute")
        ]

    def page_payload(self):
        state = self._state()
        units = self._units()
        user_cards = self._user_cards(units, state)
        user_kmfs = self._user_kmfs(units)
        user_customizations = self._user_customizations(units, user_kmfs)
        now = self._now()
        chara_ids = {
            self.cards[card["cardId"]]["charaId"]
            for card in user_cards
            if card["cardId"] in self.cards
            and "charaId" in self.cards[card["cardId"]]
        }
        payload = {
            "resultCode": "success",
            "currentTime": now,
            "user": {
                "id": state.get("userId", "local-user"),
                "snsUserId": "local-sns-user",
                "tutorialId": state.get("tutorialId", ""),
                "partId": 6,
                "chapterId": 50,
                "relink": False,
            },
            "gameUser": self._game_user(
                state, user_cards, user_customizations
            ),
            "userCardList": user_cards,
            "localActiveBattle": state.get("localActiveBattle"),
            "userCardLimitBreakList": state.get("cardLimitBreaks", []),
            "userCardAttributeRankList": self._user_attribute_ranks(state),
            "userCharaList": [
                {
                    "charaId": chara_id,
                    "bookmarkCostume": bool(
                        (state.get("charaBookmarks") or {}).get(str(chara_id))),
                    "createdAt": now,
                }
                for chara_id in sorted(chara_ids)
            ],
            "userKnightmareFrameList": user_kmfs,
            "userKnightmareFrameCustomizeList": user_customizations,
            "userKnightmareFrameKeyList": copy.deepcopy(
                state.get("userKnightmareFrameKeyList", [])),
            "userKnightmareFrameDevelopmentList": copy.deepcopy(
                state.get("userKnightmareFrameDevelopmentList", [])),
            "userDeckList": self._user_decks(state),
            "userItemList": self._user_items(state),
            "userStatusList": self._user_statuses(state),
            "userQuestList": self._user_quests(state, now),
            "userDailyQuestList": self._user_daily_list(state, now),
            "userChapterList": self._user_chapters(now),
            "userBackgroundGroupList": [
                {
                    "backgroundGroupId": 1001,
                    "createdAt": now,
                }
            ],
            "userCostumeList": [
                copy.deepcopy(row)
                for row in state.get("costumes", [])
                if (isinstance(row, dict)
                    and int(row.get("costumeId", 0)) in self.costumes)
            ],
            "userSubscriptionList": [],
            "userTrainingList": [],
            "userExpeditionAreaList": [],
            "userEventExpeditionAreaList":
                self._user_event_expedition_areas(now),
            **{
                key: state.get(key, [])
                for key in CHALLENGE_LIST_KEYS
            },
            "floatingNotificationList": [],
            "guildMemberNum": 0,
            "presentCount": int(state.get("presentCount", 0)),
            "roomId": "",
            "userShopItemList": [],
            "userGachaGroupList": state.get("userGachaGroupList", []),
            "userGachaGroupPointList": [],
            "guildMemberList": [],
            "unapprovedList": [],
        }
        if state.get("userId") == LOCAL_FREE_MONEY_TARGET_USER_ID:
            payload.update(local_shop_models(
                {
                    shop_item_id: state.get("gameItems", {}).get(
                        purchase_counter_id(shop_item_id), 0)
                    for shop_item_id in (990001, 990002, 990003)
                },
                now,
            ))
        for key in (
            "affiliationList",
            "backgroundGroupList",
            "cardList",
            "charaList",
            "costumeList",
            "eventList",
            "itemList",
            "knightmareFrameList",
            "knightmareFrameCustomizeList",
            "levelList",
            "viewIconList",
            "campaignList",
        ):
            payload[key] = self.static.get(key, [])
        if getattr(self, "deck_provider", None):
            payload["userDeckList"] = self.deck_provider()
        return json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")

    def main_story_payload(self):
        payload = json.loads(self.page_payload().decode("utf-8"))
        payload["partList"] = copy.deepcopy(self.main_story_parts)
        payload["userChapterList"] = [{
            "chapterId": chapter["chapterId"], "chapter": copy.deepcopy(chapter),
            "maxDamage": 0, "clearedAt": None, "createdAt": payload["currentTime"],
        } for chapter in self.main_story_catalog["chapters"]]
        payload["userQuestList"] = self._main_story_quests(
            payload["currentTime"], self._state()
        )
        payload["locationList"] = copy.deepcopy(self.main_story_catalog["locations"])
        # These are global master tables, also retained by DailyQuestTop.
        # An empty list crashes the official pre-battle enemy detail popup.
        battle_static = json.loads((self.masterdata_directory / "pages" /
            "DailyQuestTop.static.json").read_text(encoding="utf-8"))
        payload["npcList"] = battle_static["npcList"]
        payload["gimmickList"] = battle_static["gimmickList"]
        payload["firstNavi"] = False
        return json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")

    def resolve(self, path):
        url = urlsplit(path)
        if url.scheme or url.netloc or url.fragment:
            raise KeyError(path)
        if url.path == "/api/page/MyPage":
            return 200, self.page_payload(), "application/json; charset=utf-8"
        if url.path == "/api/page/MainStoryTop":
            return (
                200,
                self.main_story_payload(),
                "application/json; charset=utf-8",
            )
        if url.path == "/api/page/RootEntangleTop":
            return (200, self.quest_category_payload(
                {"ENTANGLE", "ENTANGLE_CHALLENGE"}, "RootEntangleTop"),
                "application/json; charset=utf-8")
        if url.path == "/api/page/EventStoryTop":
            return (200, self.quest_category_payload(
                {"EVENT"}, "EventStoryTop"),
                "application/json; charset=utf-8")
        category_pages = {
            "/api/page/ChallengeQuestTop": ({"CHALLENGE"}, "ChallengeQuestTop"),
            "/api/page/ExpeditionTop": ({"EXPEDITION"}, "ExpeditionTop"),
            "/api/page/AnotherQuestTop": (
                {"ANOTHER_CHARA", "ANOTHER_SIDE"}, "AnotherQuestTop"),
            "/api/page/SideQuestTop": (
                {"SIDE", "SIDE_CHALLENGE"}, "SideQuestTop"),
            "/api/page/EventMultiFrontTop": (
                {"EVENT"}, "EventMultiFrontTop"),
            "/api/page/EventHighStrategicCommandTop": (
                {"STRATEGIC_COMMAND"}, "EventHighStrategicCommandTop"),
        }
        if url.path in category_pages:
            quest_types, static_page = category_pages[url.path]
            return (200, self.quest_category_payload(
                quest_types, static_page), "application/json; charset=utf-8")
        raise KeyError(path)


__all__ = ["NewAccountPage"]
