"""Local-only FastAPI surface for the stateful gacha server.

The routes intentionally match the official client's paths and JSON field
names. There is no account authentication here; the server binds to loopback
and is meant for the local preservation environment.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
import uuid
from .cosmetics import CostumeError, costume_state, dress_up, set_bookmark
from typing import Dict, Optional, List

from fastapi import Depends, FastAPI, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, StrictInt, StrictStr, StrictBool
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .bootstrap import (
    StarterProfile,
    load_default_profile,
    normalize_kmf_revision_classes,
)
from .db import create_database_engine, create_session_factory, initialize_database
from .gacha import (
    JST,
    GachaError,
    InsufficientFunds,
    load_fixture,
    load_probability_payload,
)
from .gacha_service import (
    GachaService,
    GachaServiceError,
    ensure_local_user,
)
from .gacha_exchange import GachaExchangeError, exchange as redeem_gacha_exchange
from .gacha_selection import (
    GachaSelectionError,
    save_selection,
    user_gacha_groups,
)
from .kmf_rules import revision_class_for_revision
from .kmf_color import custom_color_fields, with_custom_color
from .models import (
    LocalBattleProgress,
    UserCardLimitBreak,
    UserGameItem,
    UserGachaKind,
    UserGachaPoint,
    UserKmf,
    User,
    UserWallet,
)
from .presents import (
    PresentError,
    grant_present,
    pending_present_count,
    present_page,
    receive_presents,
)
from .missions import MissionService
from .battles import BattleService, BattleError, battle_state, skip_ticket_count
from .battle_data import pilot_stats, pilot_skills, kmf_stats
import json
from .progression import (
    BondsService,
    ExperienceService,
    FeatureService,
    LimitBreakService,
    ProgressionError,
    RevisionService,
    card_attribute_rank_state,
)


class DrawRequest(BaseModel):
    gachaScheduleId: int
    gachaBeanKind: str


class ProbabilityRequest(BaseModel):
    gachaScheduleId: int


class DevStateRequest(BaseModel):
    free_sakuradite: Optional[int] = Field(default=None, ge=0)
    paid_sakuradite: Optional[int] = Field(default=None, ge=0)
    items: Optional[Dict[str, int]] = None


class BattleStartRequest(BaseModel):
    questId: StrictInt
    deckType: StrictStr
    userCardIdList: List[StrictStr] = Field(min_length=1, max_length=10)
    userKnightmareFrameIdList: List[StrictStr] = Field(min_length=1, max_length=10)
    usedDailyQuestDropBoostItem: StrictBool = False

    class Config:
        extra = "forbid"


class BattleSkipRequest(BaseModel):
    questId: Optional[StrictInt] = None
    deckType: Optional[StrictStr] = None
    userCardIdList: Optional[List[StrictStr]] = Field(
        default=None, max_length=10)
    userKnightmareFrameIdList: Optional[List[StrictStr]] = Field(
        default=None, max_length=10)
    usedDailyQuestDropBoostItem: StrictBool = False

    class Config:
        extra = "forbid"


class BattleEndRequest(BaseModel):
    userQuestResultId: StrictStr
    battleResult: dict

    class Config:
        extra = "forbid"


class RetireRequest(BaseModel):
    userQuestResultId: StrictStr

    class Config:
        extra = "forbid"


class MissionClaimRequest(BaseModel):
    scope: str
    challengeId: Optional[int] = None

    class Config:
        extra = "forbid"


LOCAL_FREE_MONEY_SHOP_ID = 99001
LOCAL_FREE_MONEY_SHOP_ITEM_ID = 990001
LOCAL_FREE_MONEY_PRODUCTS = {
    990001: {"paid": 3000, "free_cost": 0},
    990002: {"paid": 33000, "free_cost": 10},
    990003: {"paid": 360000, "free_cost": 100},
}
LOCAL_FREE_MONEY_TARGET_USER = "00000000-0000-0000-0000-000000000000"
SHOP_CATALOG = json.loads((Path(__file__).resolve().parents[1] /
    "fixtures/shop_catalog.json").read_text(encoding="utf-8"))
SHOP_ITEMS = {int(row["id"]): row for row in SHOP_CATALOG["items"]}


class ShopBuyRequest(BaseModel):
    shopId: StrictInt
    shopItemId: StrictInt
    num: StrictInt = Field(ge=1, le=99)

    class Config:
        extra = "forbid"


MissionClaimRequest.model_rebuild(force=True, _types_namespace=globals())


class LimitBreakRequest(BaseModel):
    userCardId: str
    limitBreakType: str

    class Config:
        extra = "forbid"


class CardRevisionRequest(BaseModel):
    userCardId: StrictStr

    class Config:
        extra = "forbid"


class CardFeatureRequest(BaseModel):
    userCardId: StrictStr
    cardFeatureId: StrictInt

    class Config:
        extra = "forbid"


class UseItemRequest(BaseModel):
    userCardId: str
    useItem: Dict[str, StrictInt]

    class Config:
        extra = "forbid"


class BookmarkCostumeRequest(BaseModel):
    charaId: StrictInt

    class Config:
        extra = "forbid"


class CostumeDressUpRequest(BaseModel):
    userCardId: StrictStr
    costumeId: Optional[StrictInt] = None

    class Config:
        extra = "forbid"


class PresentGrantRequest(BaseModel):
    itemId: str
    quantity: StrictInt
    presentComment: str = ""


class KmfStorageRequest(BaseModel):
    userKmfId: StrictStr
    isInStorage: StrictBool

    class Config:
        extra = "forbid"


class KmfColorRequest(BaseModel):
    userKmfId: StrictStr
    red: StrictInt = Field(ge=0, le=255)
    green: StrictInt = Field(ge=0, le=255)
    blue: StrictInt = Field(ge=0, le=255)

    class Config:
        extra = "forbid"


class PresentListRequest(BaseModel):
    page: StrictInt = 1


class PresentReceiveRequest(BaseModel):
    presentIds: Optional[list[str]] = None
    total: Optional[StrictInt] = None


class GachaSelectCardRequest(BaseModel):
    gachaScheduleId: int
    cardIds: list[int]


class GachaExchangeRequest(BaseModel):
    gachaExchangeId: int
    num: StrictInt = 1


def create_app(
    database_path,
    fixture_path,
    schedule_id: int = 1005,
    starter_profile: Optional[StarterProfile] = None,
    masterdata_dir=None,
) -> FastAPI:
    engine = create_database_engine(database_path)
    initialize_database(engine)
    session_factory = create_session_factory(engine)
    with session_factory() as bootstrap_session:
        initial_save_exists = bootstrap_session.execute(
            select(User).limit(1)
        ).first() is not None
    normalize_kmf_revision_classes(session_factory)
    rate_override_path = Path(fixture_path).with_name(
        "gacha_rate_override.json")
    pool = load_fixture(
        fixture_path,
        schedule_id,
        rate_override_path=rate_override_path,
    )
    profile = starter_profile or load_default_profile()
    battle_cards = {}
    battle_weapons = {}
    if masterdata_dir and (Path(masterdata_dir) / "pages/MyPage.static.json").is_file():
        battle_cards = {row['cardId']:row for row in json.loads(
            (Path(masterdata_dir) / "pages/MyPage.static.json").read_text('utf8')).get('cardList', [])}
        battle_weapons = {row['knightmareFrameCustomizeId']:row for row in json.loads(
            (Path(masterdata_dir) / "pages/MyPage.static.json").read_text('utf8')).get('knightmareFrameCustomizeList', [])}

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        engine.dispose()

    app = FastAPI(
        title="CGLS local stateful gacha",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.pool = pool
    app.state.fixture_path = str(fixture_path)
    app.state.schedule_id = schedule_id
    app.state.starter_profile = profile
    app.state.initial_save_exists = initial_save_exists
    from .stories import install_routes as install_story_routes, story_state
    install_story_routes(app, session_factory, profile)
    from .kmf_management import (
        install_routes as install_kmf_management_routes,
        install_color_routes as install_kmf_color_routes,
        management_state,
    )
    install_kmf_management_routes(
        app, session_factory, profile, masterdata_dir)
    install_kmf_color_routes(app, session_factory, profile)
    from .kmf_enforce import install_routes as install_kmf_enforce_routes
    install_kmf_enforce_routes(
        app, session_factory, profile, masterdata_dir)

    def get_session():
        with session_factory() as session:
            yield session

    def game_error(status_code: int, title: str, text: str) -> JSONResponse:
        return JSONResponse(
            status_code=status_code,
            content={
                "resultCode": "error",
                "title": title,
                "errorTxt": text,
            },
        )

    @app.get("/api/health")
    def health():
        return {
            "status": "ok",
            "scheduleId": schedule_id,
            "localOnly": True,
        }

    @app.post("/api/gacha/draw")
    def draw(request: DrawRequest, session: Session = Depends(get_session)):
        try:
            requested_pool = load_fixture(
                fixture_path,
                request.gachaScheduleId,
                rate_override_path=rate_override_path,
            )
        except KeyError:
            try:
                requested_pool = load_fixture(
                    fixture_path,
                    request.gachaScheduleId,
                    probability_schedule_id=schedule_id,
                    rate_override_path=rate_override_path,
                )
            except KeyError:
                return game_error(
                    404,
                    "スカウトエラー",
                    "この卡池尚未载入本地概率数据。",
                )
        user = ensure_local_user(session, profile=profile)
        service = GachaService(session, requested_pool, user.id)
        try:
            return service.draw(request.gachaBeanKind)
        except InsufficientFunds as exc:
            return game_error(400, "スカウトできません", str(exc))
        except (GachaError, GachaServiceError) as exc:
            return game_error(400, "スカウトエラー", str(exc))

    @app.post("/api/gacha/probability")
    def probability(request: ProbabilityRequest):
        try:
            return load_probability_payload(
                fixture_path,
                request.gachaScheduleId,
                rate_override_path=rate_override_path,
            )
        except KeyError:
            try:
                return load_probability_payload(
                    fixture_path,
                    request.gachaScheduleId,
                    probability_schedule_id=schedule_id,
                    rate_override_path=rate_override_path,
                )
            except KeyError:
                return game_error(
                    404,
                    "スカウトエラー",
                    "この卡池尚未载入本地概率数据。",
                )

    @app.get("/api/local/save-status")
    def local_save_status(session: Session = Depends(get_session)):
        user = session.execute(
            select(User).order_by(User.created_at)
        ).scalars().first()
        if user is None:
            return {
                "resultCode": "success",
                "hasSave": False,
                "hadSaveAtStart": initial_save_exists,
                "checkedAt": datetime.now(JST).isoformat(),
            }

        progress = session.get(LocalBattleProgress, (user.id, 0))
        tutorial_id = str((progress.state or {}).get("tutorialId") or "") \
            if progress else ""
        return {
            "resultCode": "success",
            "hasSave": True,
            "hadSaveAtStart": initial_save_exists,
            "userId": user.id,
            "displayName": user.display_name,
            "sex": "MALE",
            "playerId": "local-player",
            "tutorialId": tutorial_id,
            "profileId": (
                user.bootstrap_state.profile_id
                if user.bootstrap_state else None
            ),
            "pilotCount": len(user.pilots),
            "kmfCount": len(user.kmfs),
            "deckCount": len(user.decks),
            "createdAt": user.created_at,
            "checkedAt": datetime.now(JST).isoformat(),
        }

    @app.get("/api/local/state")
    def local_state(session: Session = Depends(get_session)):
        user = ensure_local_user(session, profile=profile)
        wallet = user.wallet
        return {
            "userId": user.id,
            "displayName": user.display_name,
            "bootstrapProfile": (
                user.bootstrap_state.profile_id
                if user.bootstrap_state else None
            ),
            "bootstrapVersion": (
                user.bootstrap_state.profile_version
                if user.bootstrap_state else None
            ),
            "freeSakuradite": wallet.free_sakuradite if wallet else 0,
            "paidSakuradite": wallet.paid_sakuradite if wallet else 0,
            "gold": wallet.gold if wallet else 0,
            "skipTickets": skip_ticket_count(session, user.id, wallet),
            "stamina": wallet.stamina if wallet else 0,
            "maxStamina": wallet.max_stamina if wallet else 0,
            "gameItems": {
                row.item_id: row.quantity for row in user.game_items
            },
            "gachaPoints": {
                row.gacha_schedule_id: row.point
                for row in user.gacha_points
            },
            "pilots": len(user.pilots),
            "kmfs": len(user.kmfs),
            "decks": len(user.decks),
            "drawLogs": len(user.gacha_logs),
            "presentCount": pending_present_count(session, user.id),
        }

    @app.get("/api/local/page-state")
    def local_page_state(session: Session = Depends(get_session)):
        user = ensure_local_user(session, profile=profile)
        wallet = user.wallet
        items = session.execute(
            select(UserGameItem).where(UserGameItem.user_id == user.id)
        ).scalars().all()
        points = session.execute(
            select(UserGachaPoint).where(UserGachaPoint.user_id == user.id)
        ).scalars().all()
        kinds = session.execute(
            select(UserGachaKind).where(UserGachaKind.user_id == user.id)
        ).scalars().all()
        limit_breaks = session.execute(
            select(UserCardLimitBreak).where(
                UserCardLimitBreak.user_id == user.id
            )
        ).scalars().all()
        mission_state = MissionService(
            session_factory,
            user.id,
            masterdata_dir=masterdata_dir,
        ).state()
        daily_battles = []
        battle_service = None
        if masterdata_dir and (Path(masterdata_dir) / "pages/MyPage.static.json").is_file():
            battle_service = BattleService(session_factory, user.id, masterdata_dir)
            daily_battles = battle_service.daily_all(session)
        costume_models = costume_state(session, user.id, masterdata_dir)
        return {
            **management_state(session, user.id),
            **mission_state,
            **costume_models,
            "userStoryList": story_state(session, user.id),
            **battle_state(session, user.id, battle_service),
            "userDailyQuestList": daily_battles,
            "userId": user.id,
            "displayName": user.display_name,
            "bootstrapProfile": (
                user.bootstrap_state.profile_id
                if user.bootstrap_state else None
            ),
            "bootstrapVersion": (
                user.bootstrap_state.profile_version
                if user.bootstrap_state else None
            ),
            "freeSakuradite": wallet.free_sakuradite if wallet else 0,
            "paidSakuradite": wallet.paid_sakuradite if wallet else 0,
            "gold": wallet.gold if wallet else 0,
            "skipTickets": skip_ticket_count(session, user.id, wallet),
            "stamina": wallet.stamina if wallet else 0,
            "maxStamina": wallet.max_stamina if wallet else 0,
            "gameItems": {row.item_id: row.quantity for row in items},
            "gachaPoints": [
                {
                    "gachaScheduleId": row.gacha_schedule_id,
                    "point": row.point,
                }
                for row in points
            ],
            "gachaKinds": [
                {
                    "gachaKindId": row.gacha_kind_id,
                    "scheduleId": row.schedule_id,
                    "totalCount": row.total_count,
                    "stockCount": row.stock_count,
                    "lastDrawnOn": row.last_drawn_on,
                }
                for row in kinds
            ],
            "cardLimitBreaks": [
                {"cardId": row.card_id, "quantity": row.quantity}
                for row in limit_breaks
            ],
            "cardAttributeRanks": card_attribute_rank_state(
                session, user.id),
            "presentCount": pending_present_count(session, user.id),
            "userGachaGroupList": user_gacha_groups(session, user.id),
            "decks": [
                {
                    "deckNo": row.deck_no,
                    "name": row.deck_name,
                    "slots": row.slots,
                }
                for row in user.decks
            ],
        }

    @app.post("/api/gacha/selectCard")
    def gacha_select_card(
        request: GachaSelectCardRequest,
        session: Session = Depends(get_session),
    ):
        user = ensure_local_user(session, profile=profile)
        try:
            return save_selection(
                session,
                fixture_path,
                user.id,
                request.gachaScheduleId,
                request.cardIds,
            )
        except GachaSelectionError as exc:
            return game_error(400, "スカウトエラー", str(exc))

    @app.post("/api/gacha/exchange")
    def gacha_exchange(
        request: GachaExchangeRequest,
        session: Session = Depends(get_session),
    ):
        user = ensure_local_user(session, profile=profile)
        try:
            return redeem_gacha_exchange(
                session,
                user.id,
                masterdata_dir,
                request.gachaExchangeId,
                request.num,
            )
        except GachaExchangeError as exc:
            return game_error(400, "交換エラー", str(exc))

    @app.post("/api/page/PresentList")
    def present_list(
        request: PresentListRequest,
        session: Session = Depends(get_session),
    ):
        user = ensure_local_user(session, profile=profile)
        try:
            return present_page(
                session, user.id, page=request.page, history=False)
        except PresentError as exc:
            return game_error(400, "プレゼント", str(exc))

    @app.post("/api/page/PresentHistory")
    def present_history(
        request: PresentListRequest,
        session: Session = Depends(get_session),
    ):
        user = ensure_local_user(session, profile=profile)
        try:
            return present_page(
                session, user.id, page=request.page, history=True)
        except PresentError as exc:
            return game_error(400, "プレゼント", str(exc))

    @app.post("/api/present/receive")
    def present_receive(
        request: PresentReceiveRequest,
        session: Session = Depends(get_session),
    ):
        user = ensure_local_user(session, profile=profile)
        try:
            return receive_presents(
                session, user.id, present_ids=request.presentIds)
        except PresentError as exc:
            return game_error(400, "プレゼント", str(exc))

    @app.post("/api/present/receive/all")
    def present_receive_all(
        request: PresentReceiveRequest,
        session: Session = Depends(get_session),
    ):
        user = ensure_local_user(session, profile=profile)
        try:
            return receive_presents(
                session,
                user.id,
                receive_all=True,
                total=request.total,
            )
        except PresentError as exc:
            return game_error(400, "プレゼント", str(exc))

    @app.post("/api/local/presents/grant")
    def present_grant(
        request: PresentGrantRequest,
        session: Session = Depends(get_session),
    ):
        user = ensure_local_user(session, profile=profile)
        try:
            row = grant_present(
                session,
                user.id,
                request.itemId,
                request.quantity,
                request.presentComment,
            )
            return {
                "resultCode": "success",
                "presentId": row.present_id,
                "presentCount": pending_present_count(session, user.id),
            }
        except PresentError as exc:
            return game_error(400, "プレゼント", str(exc))

    @app.get("/api/local/units")
    def local_units(session: Session = Depends(get_session)):
        user = ensure_local_user(session, profile=profile)
        return {
            "userCardList": [
                {
                    **(pilot_stats(battle_cards[row.mst_pilot_id], row.level, row.awakening_level)
                       if row.mst_pilot_id in battle_cards else {}),
                    **(pilot_skills(battle_cards[row.mst_pilot_id], row)
                       if row.mst_pilot_id in battle_cards else {}),
                    "unlockedFeatureIdList": row.unlocked_feature_ids,
                    "userCardId": row.user_card_id,
                    "cardId": row.mst_pilot_id,
                    "charaId": row.mst_chara_id,
                    "level": row.level,
                    "experience": row.experience,
                    "lbCount": row.limit_break,
                    "revision": row.awakening_level,
                    "revisionClass": min(6, row.awakening_level // 3 + 1),
                    "bondsLevel": row.bonds_level,
                    "bondsPoint": row.bonds_point,
                }
                for row in user.pilots
                if row.user_card_id
            ],
            "userKnightmareFrameList": [
                {
                    **(kmf_stats(battle_weapons[row.customization_id], row.revision)
                       if row.customization_id in battle_weapons else {}),
                    "userKnightmareFrameId": row.user_kmf_id,
                    "knightmareFrameId": row.mst_kmf_id,
                    "customizationId": row.customization_id,
                    "skillPoint": row.skill_point,
                    "revision": row.revision,
                    "revisionClass": revision_class_for_revision(row.revision),
                    "isInStorage": row.is_in_storage,
                    **custom_color_fields(row.upgrade_ranks),
                }
                for row in user.kmfs
            ],
            "userDeckList": [
                {
                    "deckNo": row.deck_no,
                    "name": row.deck_name,
                    "slots": row.slots,
                }
                for row in user.decks
            ],
        }

    def owned_kmf(session, user_id, user_kmf_id):
        row = session.scalar(select(UserKmf).where(
            UserKmf.user_id == user_id,
            UserKmf.user_kmf_id == user_kmf_id,
        ))
        if row is None:
            raise ValueError("KMFが存在しません")
        return row

    def kmf_response(row):
        return {
            "resultCode": "success",
            "userKnightmareFrameList": [{
                "userKnightmareFrameId": row.user_kmf_id,
                "knightmareFrameId": row.mst_kmf_id,
                "customizationId": row.customization_id,
                "revision": row.revision,
                "revisionClass": revision_class_for_revision(row.revision),
                "isInStorage": row.is_in_storage,
                **custom_color_fields(row.upgrade_ranks),
            }],
        }

    @app.post("/api/local/kmf/storage")
    def local_kmf_storage(
        request: KmfStorageRequest,
        session: Session = Depends(get_session),
    ):
        user = ensure_local_user(session, profile=profile)
        try:
            row = owned_kmf(session, user.id, request.userKmfId)
            row.is_in_storage = request.isInStorage
            session.commit()
            return kmf_response(row)
        except ValueError as exc:
            session.rollback()
            return game_error(400, "KMF格納", str(exc))

    @app.post("/api/local/kmf/color")
    def local_kmf_color(
        request: KmfColorRequest,
        session: Session = Depends(get_session),
    ):
        user = ensure_local_user(session, profile=profile)
        try:
            row = owned_kmf(session, user.id, request.userKmfId)
            row.upgrade_ranks = with_custom_color(
                row.upgrade_ranks, request.red, request.green, request.blue,
                enabled=True,
            )
            session.commit()
            return kmf_response(row)
        except ValueError as exc:
            session.rollback()
            return game_error(400, "KMFカラー", str(exc))

    @app.post("/api/card/enforce/limitBreak")
    def limit_break(request: LimitBreakRequest,
                    x_request_id: Optional[str] = Header(default=None),
                    session: Session = Depends(get_session)):
        user_id = ensure_local_user(session, profile=profile).id
        session.commit()
        try:
            return LimitBreakService(
                session_factory, user_id).with_cards(battle_cards).apply(
                request.userCardId, request.limitBreakType, x_request_id)
        except ProgressionError as exc:
            return game_error(400, "限界突破", str(exc))

    @app.post("/api/card/enforce/revision")
    def card_revision(request: CardRevisionRequest,
                      x_request_id: Optional[str] = Header(default=None),
                      session: Session = Depends(get_session)):
        user_id = ensure_local_user(session, profile=profile).id
        session.commit()
        try:
            return RevisionService(
                session_factory, user_id, battle_cards).apply(
                request.userCardId, x_request_id)
        except ProgressionError as exc:
            return game_error(400, "パイロット覚醒", str(exc))

    @app.post("/api/card/enforce/feature")
    def card_feature(request: CardFeatureRequest,
                     x_request_id: Optional[str] = Header(default=None),
                     session: Session = Depends(get_session)):
        user_id = ensure_local_user(session, profile=profile).id
        session.commit()
        try:
            return FeatureService(
                session_factory, user_id, battle_cards).apply(
                request.userCardId, request.cardFeatureId, x_request_id)
        except ProgressionError as exc:
            return game_error(400, "パイロット特性", str(exc))

    @app.post("/api/card/enforce/experience")
    def experience(request: UseItemRequest,
                   x_request_id: Optional[str] = Header(default=None),
                   session: Session = Depends(get_session)):
        user_id = ensure_local_user(session, profile=profile).id
        session.commit()
        try:
            return ExperienceService(
                session_factory, user_id).with_cards(battle_cards).apply(
                request.userCardId, request.useItem, x_request_id)
        except ProgressionError as exc:
            return game_error(400, "パイロット強化", str(exc))

    @app.post("/api/card/enforce/bonds")
    def bonds(request: UseItemRequest,
              x_request_id: Optional[str] = Header(default=None),
              session: Session = Depends(get_session)):
        user_id = ensure_local_user(session, profile=profile).id
        session.commit()
        try:
            return BondsService(
                session_factory, user_id).with_cards(battle_cards).apply(
                request.userCardId, request.useItem, x_request_id)
        except ProgressionError as exc:
            return game_error(400, "信頼度", str(exc))

    @app.post("/api/chara/addBookmarkCostume")
    def add_bookmark_costume(
        request: BookmarkCostumeRequest,
        session: Session = Depends(get_session),
    ):
        user_id = ensure_local_user(session, profile=profile).id
        session.commit()
        try:
            return set_bookmark(
                session, user_id, request.charaId, True, masterdata_dir)
        except CostumeError as exc:
            return game_error(400, "コスチューム", str(exc))

    @app.post("/api/chara/removeBookmarkCostume")
    def remove_bookmark_costume(
        request: BookmarkCostumeRequest,
        session: Session = Depends(get_session),
    ):
        user_id = ensure_local_user(session, profile=profile).id
        session.commit()
        try:
            return set_bookmark(
                session, user_id, request.charaId, False, masterdata_dir)
        except CostumeError as exc:
            return game_error(400, "コスチューム", str(exc))

    @app.post("/api/card/costume/dressUp")
    def costume_dress_up(
        request: CostumeDressUpRequest,
        session: Session = Depends(get_session),
    ):
        user_id = ensure_local_user(session, profile=profile).id
        session.commit()
        try:
            return dress_up(
                session,
                user_id,
                request.userCardId,
                request.costumeId,
                masterdata_dir,
            )
        except CostumeError as exc:
            return game_error(400, "コスチューム", str(exc))

    @app.post("/api/local/missions/claim")
    def mission_claim(request: MissionClaimRequest,
                      session: Session = Depends(get_session)):
        user_id = ensure_local_user(session, profile=profile).id
        session.commit()
        try:
            return MissionService(
                session_factory,
                user_id,
                masterdata_dir=masterdata_dir,
            ).claim(
                request.scope, request.challengeId)
        except ValueError as exc:
            return game_error(400, "ミッション", str(exc))

    @app.post("/api/shop/buy")
    def shop_buy(request: ShopBuyRequest,
                 session: Session = Depends(get_session)):
        user = ensure_local_user(session, profile=profile)
        if user.id != LOCAL_FREE_MONEY_TARGET_USER:
            return game_error(400, "ショップ", "この商品は現在のアカウント専用です。")
        local_product = LOCAL_FREE_MONEY_PRODUCTS.get(request.shopItemId)
        shop_item = SHOP_ITEMS.get(request.shopItemId)
        if local_product is not None:
            if request.shopId != LOCAL_FREE_MONEY_SHOP_ID:
                return game_error(400, "ショップ", "ローカル未対応の商品です。")
        elif shop_item is None or request.shopId != int(shop_item["shopId"]):
            return game_error(400, "ショップ", "ローカル未対応の商品です。")
        now = datetime.now(JST).isoformat()
        session.commit()
        session.execute(text("BEGIN IMMEDIATE"))
        try:
            user = ensure_local_user(session, profile=profile)
            wallet = session.get(UserWallet, user.id)
            if wallet is None:
                raise ValueError("Wallet is unavailable")
            counter_id = "LOCAL_SHOP_COUNT_%s" % request.shopItemId
            counter = session.get(UserGameItem, (user.id, counter_id))
            if counter is None:
                counter = UserGameItem(
                    user_id=user.id, item_id=counter_id, quantity=0)
                session.add(counter)
            granted_item_ids = set()
            granted_kmfs = []
            if local_product is not None:
                free_cost = int(local_product["free_cost"]) * request.num
                paid_grant = int(local_product["paid"]) * request.num
                if wallet.free_sakuradite < free_cost:
                    raise ValueError("免费石头不足")
                wallet.free_sakuradite -= free_cost
                wallet.paid_sakuradite += paid_grant
            else:
                limit = int(shop_item.get("limitedNumber") or 0)
                if limit and counter.quantity + request.num > limit:
                    raise ValueError("购买次数已达上限")
                unit_cost = int(shop_item["needNumber"])
                cost = unit_cost * request.num
                consume_type = shop_item["consumeType"]
                if consume_type == "PURCHASED_MONEY":
                    if wallet.paid_sakuradite < cost:
                        raise ValueError("氪金石头不足")
                    wallet.paid_sakuradite -= cost
                elif consume_type == "ITEM":
                    need_item_id = shop_item["needItemId"]
                    cost_row = session.get(
                        UserGameItem, (user.id, need_item_id))
                    if cost_row is None or cost_row.quantity < cost:
                        raise ValueError("ショップ交換素材が不足しています")
                    cost_row.quantity -= cost
                    granted_item_ids.add(need_item_id)
                else:
                    raise ValueError("未対応の消費種別です")
                item_type = shop_item["shopItemType"]
                if item_type == "KMF":
                    frame_id = int(shop_item["genericId"])
                    existing = session.scalar(select(UserKmf).where(
                        UserKmf.user_id == user.id,
                        UserKmf.mst_kmf_id == frame_id))
                    if existing is not None:
                        raise ValueError("該当KMFは既に所持しています")
                    if masterdata_dir is None:
                        raise ValueError("KMF masterdata is unavailable")
                    static = json.loads((Path(masterdata_dir) /
                        "pages/MyPage.static.json").read_text(encoding="utf-8"))
                    customs = [row for row in static.get(
                        "knightmareFrameCustomizeList", [])
                        if int(row.get("knightmareFrameId", 0)) == frame_id]
                    if not customs:
                        raise ValueError("KMF customization is unavailable")
                    customization = sorted(
                        customs, key=lambda row: row.get("sortKey", 0))[0]
                    user_kmf_id = str(uuid.uuid5(
                        uuid.NAMESPACE_URL, "%s:%s" % (user.id, frame_id)))
                    session.add(UserKmf(
                        user_id=user.id, user_kmf_id=user_kmf_id,
                        mst_kmf_id=frame_id,
                        customization_id=int(
                            customization["knightmareFrameCustomizeId"]),
                        revision_class=1))
                    granted_kmfs.append({
                        "userKnightmareFrameId": user_kmf_id,
                        "knightmareFrameId": frame_id,
                        "awakeRankFrameNo": 1,
                        "revision": 0, "revisionClass": 1,
                        "isInStorage": False, "createdAt": now})
                elif item_type == "ITEM":
                    item_id = shop_item["genericId"]
                    row = session.get(UserGameItem, (user.id, item_id))
                    if row is None:
                        row = UserGameItem(
                            user_id=user.id, item_id=item_id, quantity=0)
                        session.add(row)
                    row.quantity += int(shop_item.get("num") or 1) * request.num
                    granted_item_ids.add(item_id)
                elif item_type == "SET":
                    for code in (shop_item.get("rewardCode") or "").split(","):
                        parts = code.split("_")
                        if len(parts) < 3 or parts[0] != "ITEM":
                            raise ValueError("未対応のセット商品です")
                        item_id = "_".join(parts[1:-1])
                        quantity = int(parts[-1]) * request.num
                        row = session.get(UserGameItem, (user.id, item_id))
                        if row is None:
                            row = UserGameItem(
                                user_id=user.id, item_id=item_id, quantity=0)
                            session.add(row)
                        row.quantity += quantity
                        granted_item_ids.add(item_id)
                else:
                    raise ValueError("未対応の商品種別です")
            counter.quantity += request.num
            session.flush()
            item_rows = [
                {"itemId": "MONEY", "quantity": wallet.paid_sakuradite,
                 "environmentId": "COMMON", "createdAt": now},
                {"itemId": "PRESENTED_MONEY", "quantity": wallet.free_sakuradite,
                 "environmentId": "COMMON", "createdAt": now},
                {"itemId": counter_id, "quantity": counter.quantity,
                 "environmentId": "COMMON", "createdAt": now},
            ]
            for item_id in sorted(granted_item_ids):
                row = session.get(UserGameItem, (user.id, item_id))
                item_rows.append({
                    "itemId": item_id, "quantity": row.quantity,
                    "environmentId": "COMMON", "createdAt": now})
            response = {
                "resultCode": "success",
                "currentTime": now,
                "userItemList": item_rows,
                **({'userKnightmareFrameList': granted_kmfs}
                   if granted_kmfs else {}),
                "userShopItemList": [{
                    "shopItemId": request.shopItemId,
                    "num": counter.quantity,
                    "opened": True,
                    "recentExchangedAt": now,
                    "createdAt": now,
                }],
            }
            session.commit()
            return response
        except Exception as exc:
            session.rollback()
            return game_error(400, "ショップ", str(exc))

    @app.post("/api/battle/start")
    def battle_start(request: BattleStartRequest,
                     x_request_id: Optional[str] = Header(default=None),
                     session: Session = Depends(get_session)):
        user = ensure_local_user(session, profile=profile)
        try:
            return BattleService(session_factory, user.id, masterdata_dir).start(
                request.model_dump(), x_request_id)
        except (BattleError, ValueError) as exc:
            return game_error(400, "出撃できません", str(exc))

    @app.post("/api/battle/end")
    def battle_end(request: BattleEndRequest, session: Session = Depends(get_session)):
        user = ensure_local_user(session, profile=profile)
        try:
            return BattleService(session_factory, user.id, masterdata_dir).finish(
                request.userQuestResultId, request.battleResult)
        except (BattleError, ValueError) as exc:
            return game_error(400, "バトル結果エラー", str(exc))

    @app.post("/api/battle/skip")
    def battle_skip(request: Optional[BattleSkipRequest] = None,
                    x_request_id: Optional[str] = Header(default=None),
                    session: Session = Depends(get_session)):
        user = ensure_local_user(session, profile=profile)
        payload = (request.model_dump(exclude_none=True)
                   if request is not None else {})
        try:
            return BattleService(session_factory, user.id, masterdata_dir).skip(
                payload, x_request_id or uuid.uuid4().hex)
        except (BattleError, ValueError) as exc:
            # The native click handler treats resultCode=error as a completed
            # response and can restore its page without an HTTP parse failure.
            return game_error(200, "スキップエラー", str(exc))

    @app.post("/api/local/battle/retire")
    def retire_interrupted_battle(request: RetireRequest, session: Session = Depends(get_session)):
        user = ensure_local_user(session, profile=profile)
        try:
            return BattleService(session_factory, user.id, masterdata_dir).finish(
                request.userQuestResultId, {'result':'RETIRE'})
        except BattleError as exc:
            return game_error(400, "バトル終了エラー", str(exc))

    @app.get("/api/local/battle-state")
    def local_battle_state(session: Session = Depends(get_session)):
        user = ensure_local_user(session, profile=profile)
        service = BattleService(session_factory, user.id, masterdata_dir)
        return {**battle_state(session,user.id,service),
                'userDailyQuestList':service.daily_all(session)}

    @app.get("/api/local/battle-catalog")
    def local_battle_catalog(session: Session = Depends(get_session)):
        user = ensure_local_user(session, profile=profile)
        return BattleService(
            session_factory, user.id, masterdata_dir).catalog_status()

    @app.get("/api/local/battle-catalog/{quest_id}")
    def local_battle_catalog_detail(
            quest_id: int, session: Session = Depends(get_session)):
        user = ensure_local_user(session, profile=profile)
        detail = BattleService(
            session_factory, user.id, masterdata_dir).catalog_detail(quest_id)
        if detail is None:
            return game_error(404, "バトルカタログ", "未知のクエストです。")
        return detail

    @app.post("/api/local/dev-state")
    def dev_state(
        request: DevStateRequest, session: Session = Depends(get_session)
    ):
        user = ensure_local_user(session, profile=profile)
        wallet = user.wallet
        if request.free_sakuradite is not None:
            wallet.free_sakuradite = request.free_sakuradite
        if request.paid_sakuradite is not None:
            wallet.paid_sakuradite = request.paid_sakuradite
        for item_id, quantity in (request.items or {}).items():
            if quantity < 0:
                return game_error(400, "ローカル設定", "数量不能为负数。")
            row = session.get(UserGameItem, (user.id, item_id))
            if row is None:
                row = UserGameItem(
                    user_id=user.id,
                    item_id=item_id,
                    quantity=quantity,
                )
                session.add(row)
            else:
                row.quantity = quantity
        session.commit()
        return {
            "ok": True,
            "freeSakuradite": wallet.free_sakuradite,
            "paidSakuradite": wallet.paid_sakuradite,
            "gameItems": {
                row.item_id: row.quantity for row in user.game_items
            },
        }

    return app


def main() -> None:
    import argparse
    import uvicorn

    default_fixture = (
        Path(__file__).resolve().parents[1] / "fixtures" / "gacha_1005.json"
    )
    default_database = (
        Path(__file__).resolve().parents[1] / "local_state.sqlite"
    )
    parser = argparse.ArgumentParser(description="CGLS local gacha server")
    parser.add_argument("--database", default=str(default_database))
    parser.add_argument("--fixture", default=str(default_fixture))
    parser.add_argument("--port", type=int, default=18766)
    parser.add_argument(
        "--starter-profile",
        help="JSON profile used only when creating or repairing an empty account",
    )
    parser.add_argument(
        "--empty-account",
        action="store_true",
        help="Create a zero-resource account with no starter units",
    )
    parser.add_argument(
        "--masterdata",
        help="Package masterdata directory used by gacha exchange",
    )
    args = parser.parse_args()

    if args.empty_account and args.starter_profile:
        parser.error("--empty-account and --starter-profile are mutually exclusive")
    profile = (
        StarterProfile.empty()
        if args.empty_account
        else StarterProfile.from_file(args.starter_profile)
        if args.starter_profile
        else load_default_profile()
    )
    app = create_app(
        args.database,
        args.fixture,
        starter_profile=profile,
        masterdata_dir=args.masterdata,
    )
    uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
