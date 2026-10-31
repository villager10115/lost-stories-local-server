from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import json
import math
from pathlib import Path
from typing import Any, Optional, Sequence
import uuid

from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, StrictInt, StrictStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from .bootstrap import StarterProfile, ensure_local_user
from .kmf_color import (
    custom_color_state,
    with_custom_color,
    with_custom_color_enabled,
)
from .kmf_management_models import UserKmfDevelopment
from .kmf_rules import (
    customization_instance_id,
    revision_class_for_revision,
)
from .models import UserDeck, UserKmf, UserKmfKey, UserWallet


JST = timezone(timedelta(hours=9))
WAREHOUSE_CAPACITY = 250
MAX_BATCH_SIZE = 100


class KmfManagementError(ValueError):
    pass


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=JST)
    return value.astimezone(JST)


def _iso(value: Optional[datetime]) -> Optional[str]:
    return _aware(value).isoformat() if value is not None else None


def _customization_uid(user_kmf_id: str, customization_id: int) -> str:
    return customization_instance_id(user_kmf_id, customization_id)


@dataclass(frozen=True)
class KmfCatalog:
    frames: dict[int, dict]
    customizations: dict[int, tuple[dict, ...]]

    @classmethod
    def from_masterdata(cls, masterdata_dir: Path) -> "KmfCatalog":
        pages = masterdata_dir / "pages" / "MyPage.static.json"
        if not pages.is_file():
            raise KmfManagementError("KMF masterdata is unavailable")
        data = json.loads(pages.read_text(encoding="utf-8"))
        frames = {
            int(row["knightmareFrameId"]): row
            for row in data.get("knightmareFrameList", [])
            if row.get("knightmareFrameId") is not None
        }
        grouped: dict[int, list[dict]] = {}
        for row in data.get("knightmareFrameCustomizeList", []):
            frame_id = int(row.get("knightmareFrameId", 0))
            if frame_id:
                grouped.setdefault(frame_id, []).append(row)
        for rows in grouped.values():
            rows.sort(key=lambda row: (
                0 if row.get("selected") else 1,
                int(row.get("sortKey", 0)),
            ))
        return cls(
            frames=frames,
            customizations={
                frame_id: tuple(rows)
                for frame_id, rows in grouped.items()
            },
        )

    def frame(self, frame_id: int) -> dict:
        row = self.frames.get(int(frame_id))
        if row is None:
            raise KmfManagementError("KMF definition was not found")
        return row

    def default_customization(self, frame_id: int) -> dict:
        rows = self.customizations.get(int(frame_id), ())
        if not rows:
            raise KmfManagementError("KMF customization was not found")
        return rows[0]

    def tier(self, frame_id: int) -> dict:
        row = self.frame(frame_id)
        tier = row.get("knightmareFrameTier")
        if not isinstance(tier, dict):
            raise KmfManagementError("KMF development tier was not found")
        return tier


@lru_cache(maxsize=8)
def _cached_catalog(path: str, modified_ns: int, size: int) -> KmfCatalog:
    del modified_ns, size
    return KmfCatalog.from_masterdata(Path(path).parent.parent)


def load_catalog(masterdata_dir: Path | str) -> KmfCatalog:
    path = (Path(masterdata_dir) / "pages" / "MyPage.static.json").resolve()
    if not path.is_file():
        raise KmfManagementError("KMF masterdata is unavailable")
    stat = path.stat()
    return _cached_catalog(str(path), stat.st_mtime_ns, stat.st_size)


def _key_row(row: UserKmfKey) -> dict:
    return {
        "knightmareFrameId": row.knightmare_frame_id,
        "quantity": row.quantity,
        "createdAt": _iso(row.created_at),
    }


def _development_row(row: UserKmfDevelopment) -> dict:
    return {
        "frameNo": row.frame_no,
        "knightmareFrameId": row.knightmare_frame_id,
        "startedAt": _iso(row.started_at),
        "endAt": _iso(row.end_at),
        "receivedAt": _iso(row.received_at),
    }


def management_state(
    session: Session,
    user_id: str,
) -> dict[str, list[dict]]:
    keys = session.execute(
        select(UserKmfKey)
        .where(UserKmfKey.user_id == user_id)
        .order_by(UserKmfKey.knightmare_frame_id)
    ).scalars().all()
    developments = session.execute(
        select(UserKmfDevelopment)
        .where(UserKmfDevelopment.user_id == user_id)
        .order_by(UserKmfDevelopment.frame_no)
    ).scalars().all()
    return {
        "userKnightmareFrameKeyList": [_key_row(row) for row in keys],
        "userKnightmareFrameDevelopmentList": [
            _development_row(row) for row in developments
        ],
    }


class KmfManagementService:
    def __init__(
        self,
        session: Session,
        user_id: str,
        masterdata_dir: Path | str,
        clock=None,
    ):
        self.session = session
        self.user_id = user_id
        self.catalog = load_catalog(masterdata_dir)
        self.clock = clock or (lambda: datetime.now(JST))

    def _now(self) -> datetime:
        return _aware(self.clock())

    def _user_kmfs(self, user_kmf_ids: Sequence[str]) -> list[UserKmf]:
        if not user_kmf_ids:
            raise KmfManagementError("KMFを1機以上選択してください。")
        if len(user_kmf_ids) > MAX_BATCH_SIZE:
            raise KmfManagementError(
                "一度に操作できるKMFは100機までです。")
        if len(set(user_kmf_ids)) != len(user_kmf_ids):
            raise KmfManagementError("同じKMFが重複しています。")
        rows = self.session.execute(
            select(UserKmf).where(
                UserKmf.user_id == self.user_id,
                UserKmf.user_kmf_id.in_(list(user_kmf_ids)),
            )
        ).scalars().all()
        by_id = {row.user_kmf_id: row for row in rows}
        if len(by_id) != len(user_kmf_ids):
            raise KmfManagementError("所有していないKMFが含まれています。")
        return [by_id[user_kmf_id] for user_kmf_id in user_kmf_ids]

    def _customization(self, row: UserKmf) -> dict:
        definition = self.catalog.default_customization(row.mst_kmf_id)
        customization_id = int(
            definition["knightmareFrameCustomizeId"])
        revision = int(row.revision)
        result = {
            "userKnightmareFrameId": row.user_kmf_id,
            "knightmareFrameCustomizeId": customization_id,
            "selected": True,
            "locked": False,
            "revision": revision,
            "revisionClass": revision_class_for_revision(revision),
            "cost": int(definition.get("cost", 0)),
            "blockNum": int(definition.get("blockNum", 0)),
            "attackType": str(definition.get("attackType", "")),
            "attackTypeDescription": definition.get(
                "attackTypeDescription", ""),
            "attack": int(definition.get("attack", 0)),
            "defense": int(definition.get("defense", 0)),
            "strength": int(definition.get("strength", 0)),
            "knightmareFrameSkillLevel": 1,
            "createdAt": _iso(row.obtained_at),
            "userKnightmareFrameCustomizeId": _customization_uid(
                row.user_kmf_id, customization_id),
            "bonusList": [],
        }
        upgrades = row.upgrade_ranks or {}
        for key in ("cost", "blockNum", "attack", "defense", "strength"):
            if key in upgrades:
                result[key] = upgrades[key]
        return result

    def _unit(self, row: UserKmf, is_new: bool = False) -> dict:
        color = custom_color_state(row.upgrade_ranks)
        result = {
            "knightmareFrameId": row.mst_kmf_id,
            "first": bool((row.upgrade_ranks or {}).get("first")),
            "protection": bool(row.is_locked),
            "expeditionDeadFlg": False,
            "skillPoint": int(row.skill_point),
            "isNew": is_new,
            "isInStorage": bool(row.is_in_storage),
            "favorite": bool((row.upgrade_ranks or {}).get("favorite")),
            "createdAt": _iso(row.obtained_at),
            "userKnightmareFrameId": row.user_kmf_id,
            "useCustomColor": bool(color and color["enabled"]),
        }
        if color:
            result.update({
                "customColorR": color["r"],
                "customColorG": color["g"],
                "customColorB": color["b"],
            })
        return result

    def _item(self, item_id: str, quantity: int, now: datetime) -> dict:
        return {
            "itemId": item_id,
            "environmentId": "COMMON",
            "quantity": int(quantity),
            "total": 0,
            "createdAt": now.isoformat(),
        }

    def _key(self, frame_id: int) -> Optional[UserKmfKey]:
        return self.session.get(UserKmfKey, (self.user_id, int(frame_id)))

    def _development(self, frame_no: int) -> Optional[UserKmfDevelopment]:
        return self.session.get(
            UserKmfDevelopment, (self.user_id, int(frame_no)))

    def _key_response(self, frame_ids: Sequence[int]) -> list[dict]:
        result = []
        for frame_id in sorted(set(int(value) for value in frame_ids)):
            row = self._key(frame_id)
            if row is not None:
                result.append(_key_row(row))
        return result

    def _development_response(self) -> list[dict]:
        rows = self.session.execute(
            select(UserKmfDevelopment)
            .where(UserKmfDevelopment.user_id == self.user_id)
            .order_by(UserKmfDevelopment.frame_no)
        ).scalars().all()
        return [_development_row(row) for row in rows]

    def _wallet(self) -> UserWallet:
        wallet = self.session.get(UserWallet, self.user_id)
        if wallet is None:
            raise KmfManagementError("Wallet is unavailable")
        return wallet

    def start_development(self, frame_no: int, frame_id: int) -> dict:
        if not 1 <= frame_no <= 3:
            raise KmfManagementError("開発ラインが不正です。")
        tier = self.catalog.tier(frame_id)
        key = self._key(frame_id)
        if key is None or key.quantity < 1:
            raise KmfManagementError("固有コアルミナスが不足しています。")
        existing = self._development(frame_no)
        if existing is not None and existing.received_at is None:
            raise KmfManagementError("この開発ラインは使用中です。")
        gold = int(tier.get("needGold", 0))
        wallet = self._wallet()
        if wallet.gold < gold:
            raise KmfManagementError("ギアスコインが不足しています。")
        now = self._now()
        end_at = now + timedelta(minutes=int(tier.get("needMinutes", 0)))
        wallet.gold -= gold
        key.quantity -= 1
        if existing is None:
            existing = UserKmfDevelopment(
                user_id=self.user_id,
                frame_no=frame_no,
                knightmare_frame_id=int(frame_id),
                started_at=now,
                end_at=end_at,
                received_at=None,
            )
            self.session.add(existing)
        else:
            existing.knightmare_frame_id = int(frame_id)
            existing.started_at = now
            existing.end_at = end_at
            existing.received_at = None
        self.session.commit()
        return {
            "resultCode": "success",
            "currentTime": now.isoformat(),
            "userItemList": [self._item("GOLD", wallet.gold, now)],
            "userKnightmareFrameKeyList": self._key_response([frame_id]),
            "userKnightmareFrameDevelopmentList":
                self._development_response(),
        }

    def skip_development(self, frame_no: int) -> dict:
        development = self._development(frame_no)
        now = self._now()
        if development is None or development.received_at is not None:
            raise KmfManagementError("進行中の開発がありません。")
        if _aware(development.end_at) <= now:
            raise KmfManagementError("開発は既に完了しています。")
        remaining_minutes = max(1, math.ceil(
            (_aware(development.end_at) - now).total_seconds() / 60))
        cost = 5 * max(1, math.ceil(remaining_minutes / 15))
        wallet = self._wallet()
        available = wallet.free_sakuradite + wallet.paid_sakuradite
        if available < cost:
            raise KmfManagementError("サクラダイトが不足しています。")
        free_take = min(wallet.free_sakuradite, cost)
        wallet.free_sakuradite -= free_take
        wallet.paid_sakuradite -= cost - free_take
        development.end_at = now
        self.session.commit()
        return {
            "resultCode": "success",
            "currentTime": now.isoformat(),
            "userItemList": [
                self._item("PRESENTED_MONEY", wallet.free_sakuradite, now),
                self._item("MONEY", wallet.paid_sakuradite, now),
            ],
            "userKnightmareFrameDevelopmentList":
                self._development_response(),
            "gachaAnimation": {
                "cardList": [],
                "effects": {
                    "direction1": 1,
                    "direction2": [],
                    "direction3": 1,
                    "direction4": 1,
                },
            },
        }

    def receive_development(self, frame_no: int) -> dict:
        development = self._development(frame_no)
        now = self._now()
        if development is None or development.received_at is not None:
            raise KmfManagementError("受け取れる開発がありません。")
        if _aware(development.end_at) > now:
            raise KmfManagementError("開発はまだ完了していません。")
        active_count = len(self.session.execute(
            select(UserKmf).where(
                UserKmf.user_id == self.user_id,
                UserKmf.is_in_storage.is_(False),
            )
        ).scalars().all())
        if active_count >= WAREHOUSE_CAPACITY:
            raise KmfManagementError(
                "KMF所持数上限に達しているため、受け取れません。")
        customization = self.catalog.default_customization(
            development.knightmare_frame_id)
        unit = UserKmf(
            user_id=self.user_id,
            user_kmf_id=str(uuid.uuid4()),
            mst_kmf_id=development.knightmare_frame_id,
            customization_id=int(
                customization["knightmareFrameCustomizeId"]),
            upgrade_ranks={},
            revision_class=1,
            is_in_storage=False,
            obtained_at=now,
        )
        development.received_at = now
        self.session.add(unit)
        self.session.flush()
        result = {
            "resultCode": "success",
            "currentTime": now.isoformat(),
            "userKnightmareFrameList": [self._unit(unit, is_new=True)],
            "userKnightmareFrameCustomizeList":
                [self._customization(unit)],
            "userKnightmareFrameDevelopmentList":
                self._development_response(),
        }
        self.session.commit()
        return result

    def dismantle(self, user_kmf_ids: Sequence[str]) -> dict:
        rows = self._user_kmfs(user_kmf_ids)
        for row in rows:
            if row.is_locked:
                raise KmfManagementError("保護中のKMFは解体できません。")
            if bool((row.upgrade_ranks or {}).get("first")):
                raise KmfManagementError("初期配布KMFは解体できません。")
        now = self._now()
        counts: dict[int, int] = {}
        deleted = {"userKnightmareFrameList": [],
                   "userKnightmareFrameCustomizeList": []}
        selected = set(user_kmf_ids)
        for row in rows:
            counts[row.mst_kmf_id] = counts.get(row.mst_kmf_id, 0) + 1
            customization = self.catalog.default_customization(
                row.mst_kmf_id)
            deleted["userKnightmareFrameList"].append({
                "userKnightmareFrameId": row.user_kmf_id,
                "knightmareFrameId": row.mst_kmf_id,
            })
            deleted["userKnightmareFrameCustomizeList"].append({
                "userKnightmareFrameId": row.user_kmf_id,
                "userKnightmareFrameCustomizeId": _customization_uid(
                    row.user_kmf_id,
                    int(customization["knightmareFrameCustomizeId"]),
                ),
            })
            self.session.delete(row)
        for frame_id, quantity in counts.items():
            key = self._key(frame_id)
            if key is None:
                key = UserKmfKey(
                    user_id=self.user_id,
                    knightmare_frame_id=frame_id,
                    quantity=quantity,
                    created_at=now,
                )
                self.session.add(key)
            else:
                key.quantity += quantity
        decks = self.session.execute(
            select(UserDeck).where(UserDeck.user_id == self.user_id)
        ).scalars().all()
        for deck in decks:
            slots = []
            for slot in deck.slots or []:
                if isinstance(slot, dict) and slot.get("kmf") not in selected:
                    slots.append(slot)
            deck.slots = slots
        self.session.flush()
        result = {
            "resultCode": "success",
            "currentTime": now.isoformat(),
            "deleted": deleted,
            "userKnightmareFrameKeyList":
                self._key_response(list(counts)),
        }
        self.session.commit()
        return result

    def move_storage(
        self,
        user_kmf_ids: Sequence[str],
        target_in_storage: bool,
    ) -> dict:
        rows = self._user_kmfs(user_kmf_ids)
        if target_in_storage:
            moving = [row for row in rows if not row.is_in_storage]
            stored = len(self.session.execute(
                select(UserKmf).where(
                    UserKmf.user_id == self.user_id,
                    UserKmf.is_in_storage.is_(True),
                )
            ).scalars().all())
            if stored + len(moving) > WAREHOUSE_CAPACITY:
                raise KmfManagementError(
                    "倉庫に格納できるKMFは250体までです。")
            selected = set(user_kmf_ids)
            decks = self.session.execute(
                select(UserDeck).where(UserDeck.user_id == self.user_id)
            ).scalars().all()
            for deck in decks:
                deck.slots = [
                    slot for slot in (deck.slots or [])
                    if not (isinstance(slot, dict)
                            and slot.get("kmf") in selected)
                ]
        for row in rows:
            row.is_in_storage = bool(target_in_storage)
        self.session.commit()
        return {
            "resultCode": "success",
            "currentTime": self._now().isoformat(),
            "userKnightmareFrameList": [
                self._unit(row) for row in rows
            ],
        }



class KmfColorService:
    def __init__(self, session: Session, user_id: str, clock=None):
        self.session = session
        self.user_id = user_id
        self.clock = clock or (lambda: datetime.now(JST))

    def _row(self, user_kmf_id: str) -> UserKmf:
        row = self.session.scalar(select(UserKmf).where(
            UserKmf.user_id == self.user_id,
            UserKmf.user_kmf_id == user_kmf_id,
        ))
        if row is None:
            rows = self.session.execute(select(UserKmf).where(
                UserKmf.user_id == self.user_id)).scalars().all()
            row = next((
                item for item in rows
                if item.customization_id is not None
                and _customization_uid(
                    item.user_kmf_id, item.customization_id) == user_kmf_id
            ), None)
        if row is None:
            raise KmfManagementError("所有していないKMFが指定されています。")
        return row

    def _save(self, row: UserKmf, upgrade_ranks: dict) -> dict:
        row.upgrade_ranks = upgrade_ranks
        now = _aware(self.clock())
        color = custom_color_state(row.upgrade_ranks)
        result = {
            "resultCode": "success",
            "currentTime": now.isoformat(),
            "userKnightmareFrameList": [{
                "userKnightmareFrameId": row.user_kmf_id,
                "knightmareFrameId": row.mst_kmf_id,
                "revision": row.revision,
                "revisionClass": revision_class_for_revision(row.revision),
                "isInStorage": row.is_in_storage,
                "useCustomColor": color["enabled"],
                "customColorR": color["r"],
                "customColorG": color["g"],
                "customColorB": color["b"],
            }],
        }
        self.session.commit()
        return result

    def set_color(
        self, user_kmf_id: str, red: int, green: int, blue: int,
    ) -> dict:
        row = self._row(user_kmf_id)
        return self._save(row, with_custom_color(
            row.upgrade_ranks, red, green, blue, enabled=True))

    def set_color_enabled(self, user_kmf_id: str, enabled: bool) -> dict:
        row = self._row(user_kmf_id)
        return self._save(row, with_custom_color_enabled(
            row.upgrade_ranks, enabled))


class DevelopmentStartRequest(BaseModel):
    frameNo: StrictInt = Field(ge=1, le=3)
    knightmareFrameId: StrictInt = Field(gt=0)


class DevelopmentActionRequest(BaseModel):
    frameNo: StrictInt = Field(ge=1, le=3)


class KmfIdListRequest(BaseModel):
    userKnightmareFrameIdList: list[StrictStr] = Field(
        min_length=1, max_length=MAX_BATCH_SIZE)


class KmfColorActionRequest(BaseModel):
    userKnightmareFrameId: Optional[StrictStr] = None
    userKnightmareFrameCustomizeId: Optional[StrictStr] = None
    userKmfId: Optional[StrictStr] = None
    red: Optional[StrictInt] = Field(default=None, ge=0, le=255)
    green: Optional[StrictInt] = Field(default=None, ge=0, le=255)
    blue: Optional[StrictInt] = Field(default=None, ge=0, le=255)
    customColorR: Optional[StrictInt] = Field(default=None, ge=0, le=255)
    customColorG: Optional[StrictInt] = Field(default=None, ge=0, le=255)
    customColorB: Optional[StrictInt] = Field(default=None, ge=0, le=255)

    class Config:
        extra = "forbid"

    def identifier(self) -> str:
        value = (
            self.userKnightmareFrameId
            or self.userKnightmareFrameCustomizeId
            or self.userKmfId
        )
        if not value:
            raise KmfManagementError("KMFが指定されていません。")
        return value

    def rgb(self) -> tuple[int, int, int]:
        red = self.red if self.red is not None else self.customColorR
        green = self.green if self.green is not None else self.customColorG
        blue = self.blue if self.blue is not None else self.customColorB
        if red is None or green is None or blue is None:
            raise KmfManagementError("カラーが指定されていません。")
        return red, green, blue


def install_routes(
    app: FastAPI,
    session_factory,
    profile: StarterProfile,
    masterdata_dir: Path | str | None,
) -> None:
    if masterdata_dir is None:
        return

    def get_session():
        with session_factory() as session:
            yield session

    def error(title: str, text: str) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={
                "resultCode": "error",
                "title": title,
                "errorTxt": text,
            },
        )

    def run(session: Session, title: str, operation):
        try:
            user = ensure_local_user(session, profile=profile)
            user_id = user.id
            session.commit()
            return operation(KmfManagementService(
                session, user_id, masterdata_dir))
        except KmfManagementError as exc:
            session.rollback()
            return error(title, str(exc))

    @app.post("/api/knightmareFrame/development/start")
    def development_start(
        request: DevelopmentStartRequest,
        session: Session = Depends(get_session),
    ):
        return run(
            session,
            "KMF開発",
            lambda service: service.start_development(
                request.frameNo, request.knightmareFrameId),
        )

    @app.post("/api/knightmareFrame/development/skip")
    def development_skip(
        request: DevelopmentActionRequest,
        session: Session = Depends(get_session),
    ):
        return run(
            session,
            "KMF開発",
            lambda service: service.skip_development(request.frameNo),
        )

    @app.post("/api/knightmareFrame/development/receive")
    def development_receive(
        request: DevelopmentActionRequest,
        session: Session = Depends(get_session),
    ):
        return run(
            session,
            "KMF開発",
            lambda service: service.receive_development(request.frameNo),
        )

    @app.post("/api/knightmareFrame/dismantle")
    def dismantle(
        request: KmfIdListRequest,
        session: Session = Depends(get_session),
    ):
        return run(
            session,
            "KMF解体",
            lambda service: service.dismantle(
                request.userKnightmareFrameIdList),
        )

    @app.post("/api/knightmareFrame/carryIn")
    def carry_in(
        request: KmfIdListRequest,
        session: Session = Depends(get_session),
    ):
        return run(
            session,
            "KMF搬入",
            lambda service: service.move_storage(
                request.userKnightmareFrameIdList, True),
        )

    @app.post("/api/knightmareFrame/carryOut")
    def carry_out(
        request: KmfIdListRequest,
        session: Session = Depends(get_session),
    ):
        return run(
            session,
            "KMF搬出",
            lambda service: service.move_storage(
                request.userKnightmareFrameIdList, False),
        )


def install_color_routes(app: FastAPI, session_factory, profile: StarterProfile) -> None:
    def get_session():
        with session_factory() as session:
            yield session

    def error(title: str, text: str) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={
                "resultCode": "error",
                "title": title,
                "errorTxt": text,
            },
        )

    def run(session: Session, title: str, operation):
        try:
            user = ensure_local_user(session, profile=profile)
            session.commit()
            return operation(KmfColorService(session, user.id))
        except KmfManagementError as exc:
            session.rollback()
            return error(title, str(exc))

    @app.post("/api/knightmareFrame/color")
    def set_color(
        request: KmfColorActionRequest,
        session: Session = Depends(get_session),
    ):
        def apply(service: KmfColorService):
            red, green, blue = request.rgb()
            return service.set_color(
                request.identifier(), red, green, blue)

        return run(session, "KMFカラー", apply)

    @app.post("/api/knightmareFrame/useColor")
    def use_color(
        request: KmfColorActionRequest,
        session: Session = Depends(get_session),
    ):
        return run(
            session,
            "KMFカラー",
            lambda service: service.set_color_enabled(
                request.identifier(), True),
        )

    @app.post("/api/knightmareFrame/notUseColor")
    def not_use_color(
        request: KmfColorActionRequest,
        session: Session = Depends(get_session),
    ):
        return run(
            session,
            "KMFカラー",
            lambda service: service.set_color_enabled(
                request.identifier(), False),
        )
