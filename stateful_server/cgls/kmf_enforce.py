"""Official KMF weapon revision flow backed by the local save database."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, StrictStr
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .battle_data import kmf_stats
from .bootstrap import StarterProfile, ensure_local_user
from .kmf_management import KmfCatalog, KmfManagementError, load_catalog
from .kmf_rules import (
    customization_instance_id,
    revision_class_for_revision,
)
from .models import (
    ProgressionReceipt,
    UserGameItem,
    UserKmf,
    UserWallet,
)


JST = timezone(timedelta(hours=9))
MAX_KMF_REVISION = 9


class KmfEnforceError(ValueError):
    pass


def _validate_request_id(request_id):
    if (not isinstance(request_id, str) or not 1 <= len(request_id) <= 128
            or not request_id.isascii() or not request_id.isprintable()
            or not request_id.strip()):
        raise KmfEnforceError("X-Request-Id is required")


def _fingerprint(user_kmf_customize_id):
    return hashlib.sha256(json.dumps(
        ["kmf-revision", user_kmf_customize_id],
        sort_keys=True,
        separators=(",", ":"),
    ).encode()).hexdigest()


def _iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=JST)
    return value.astimezone(JST).isoformat()


def _item_response(item_id: str, quantity: int, now: str) -> dict:
    return {
        "itemId": item_id,
        "environmentId": "COMMON",
        "quantity": int(quantity),
        "total": 0,
        "createdAt": now,
    }


def _definition_for(row: UserKmf, catalog: KmfCatalog) -> dict:
    customization_id = row.customization_id
    definitions = catalog.customizations.get(int(row.mst_kmf_id), ())
    for definition in definitions:
        if int(definition.get("knightmareFrameCustomizeId", 0)) == int(
                customization_id or 0):
            return definition
    if customization_id is None and definitions:
        return definitions[0]
    raise KmfEnforceError("KMF customization is unavailable")


def _customization_response(row: UserKmf, definition: dict,
                            revision: int) -> dict:
    stats = kmf_stats(definition, revision)
    return {
        "userKnightmareFrameId": row.user_kmf_id,
        "knightmareFrameCustomizeId":
            int(definition["knightmareFrameCustomizeId"]),
        "selected": True,
        "locked": False,
        "revision": int(revision),
        "revisionClass": revision_class_for_revision(revision),
        "cost": int(stats["cost"]),
        "blockNum": int(stats["blockNum"]),
        "attackType": str(definition.get("attackType", "")),
        "attackTypeDescription": definition.get(
            "attackTypeDescription", ""),
        "attack": int(stats["attack"]),
        "defense": int(stats["defense"]),
        "strength": int(stats["strength"]),
        "knightmareFrameSkillLevel": int(stats["skillLevel"]),
        "createdAt": _iso(row.obtained_at),
        "userKnightmareFrameCustomizeId": customization_instance_id(
            row.user_kmf_id,
            int(definition["knightmareFrameCustomizeId"]),
        ),
        "bonusList": [],
    }


class KmfEnforceService:
    def __init__(
        self,
        sessions,
        user_id: str,
        masterdata_dir: Path | str,
        clock=None,
    ):
        self.sessions = sessions
        self.user_id = user_id
        self.catalog = load_catalog(masterdata_dir)
        self.clock = clock or (lambda: datetime.now(JST))

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None:
            return value.replace(tzinfo=JST)
        return value.astimezone(JST)

    def _owned_row(self, session: Session,
                   customize_id: str) -> UserKmf:
        rows = session.execute(
            select(UserKmf).where(UserKmf.user_id == self.user_id)
        ).scalars().all()
        for row in rows:
            if row.user_kmf_id == customize_id:
                return row
            if row.customization_id is not None and \
                    customization_instance_id(
                        row.user_kmf_id, row.customization_id) == customize_id:
                return row
        raise KmfEnforceError("所有していないKMFが指定されています。")

    def apply_revision(self, customize_id: str, request_id: str) -> dict:
        _validate_request_id(request_id)
        fingerprint = _fingerprint(customize_id)
        with self.sessions() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            try:
                receipt = session.get(
                    ProgressionReceipt, (self.user_id, request_id))
                if receipt is not None:
                    if receipt.request_hash != fingerprint:
                        raise KmfEnforceError(
                            "Request ID was already used for a different action")
                    return receipt.response

                row = self._owned_row(session, customize_id)
                if row.is_in_storage:
                    raise KmfEnforceError(
                        "倉庫に格納中のKMFは改造できません。")
                if row.is_locked:
                    raise KmfEnforceError("保護中のKMFは改造できません。")
                definition = _definition_for(row, self.catalog)
                current = int(row.revision)
                if current >= MAX_KMF_REVISION:
                    raise KmfEnforceError("最大まで改造済みです。")
                next_revision = current + 1
                revision = definition.get("revisionGroup", {}).get(
                    "revision%s" % next_revision)
                if not isinstance(revision, dict):
                    raise KmfEnforceError(
                        "Missing KMF revision definition")

                gold_cost = int(revision.get("needGold", 0))
                material_costs: dict[str, int] = {}
                for index in range(1, 5):
                    item_id = revision.get("needItemId%s" % index)
                    quantity = revision.get("needQuantity%s" % index)
                    if item_id is None and quantity is None:
                        continue
                    if (not isinstance(item_id, str) or not item_id
                            or not isinstance(quantity, int) or quantity <= 0):
                        raise KmfEnforceError(
                            "Invalid KMF revision material definition")
                    material_costs[item_id] = (
                        material_costs.get(item_id, 0) + quantity)

                wallet = session.get(UserWallet, self.user_id)
                if wallet is None or wallet.gold < gold_cost:
                    raise KmfEnforceError(
                        "改造に必要なギアスコインが足りません。")
                materials = {}
                for item_id, quantity in material_costs.items():
                    material = session.get(
                        UserGameItem, (self.user_id, item_id))
                    if material is None or material.quantity < quantity:
                        raise KmfEnforceError(
                            "改造に必要な素材が足りません。")
                    materials[item_id] = material

                wallet.gold -= gold_cost
                for item_id, quantity in material_costs.items():
                    materials[item_id].quantity -= quantity
                row.revision = next_revision
                row.revision_class = revision_class_for_revision(next_revision)

                now = self._now().isoformat()
                response = {
                    "resultCode": "success",
                    "currentTime": now,
                    "userItemList": [
                        _item_response("GOLD", wallet.gold, now),
                        *[
                            _item_response(
                                item_id, materials[item_id].quantity, now)
                            for item_id in material_costs
                        ],
                    ],
                    "userKnightmareFrameCustomizeList": [
                        _customization_response(
                            row, definition, next_revision)
                    ],
                }
                session.add(ProgressionReceipt(
                    user_id=self.user_id,
                    request_id=request_id,
                    request_hash=fingerprint,
                    response=response,
                ))
                session.commit()
                return response
            except Exception:
                session.rollback()
                raise


class KmfEnforceRequest(BaseModel):
    userKnightmareFrameCustomizeId: StrictStr = Field(
        min_length=1, max_length=64)

    class Config:
        extra = "forbid"


def install_routes(
    app: FastAPI,
    session_factory,
    profile: StarterProfile,
    masterdata_dir: Path | str | None,
) -> None:
    if masterdata_dir is None:
        return

    def error(text: str) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={
                "resultCode": "error",
                "title": "KMF改造",
                "errorTxt": text,
            },
        )

    @app.post("/api/knightmareFrameCustomize/enforce/revision")
    def enforce_revision(
        request: KmfEnforceRequest,
        x_request_id: Optional[str] = Header(default=None),
    ):
        with session_factory() as session:
            user_id = ensure_local_user(session, profile=profile).id
            session.commit()
        try:
            return KmfEnforceService(
                session_factory, user_id, masterdata_dir).apply_revision(
                    request.userKnightmareFrameCustomizeId,
                    x_request_id,
                )
        except (KmfEnforceError, KmfManagementError, ValueError) as exc:
            return error(str(exc))
