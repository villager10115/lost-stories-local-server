from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TableSpec:
    name: str
    page: str
    field: str
    id_field: str


TABLE_SPECS = (
    TableSpec("cards", "MyPage", "cardList", "cardId"),
    TableSpec("characters", "MyPage", "charaList", "charaId"),
    TableSpec("kmfs", "MyPage", "knightmareFrameList", "knightmareFrameId"),
    TableSpec(
        "kmf_customizations",
        "MyPage",
        "knightmareFrameCustomizeList",
        "knightmareFrameCustomizeId",
    ),
    TableSpec("items", "MyPage", "itemList", "itemId"),
    TableSpec("affiliations", "MyPage", "affiliationList", "affiliationId"),
    TableSpec(
        "background_groups", "MyPage", "backgroundGroupList", "backgroundGroupId"
    ),
    TableSpec("costumes", "MyPage", "costumeList", "costumeId"),
    TableSpec("levels", "MyPage", "levelList", "id"),
    TableSpec("gacha_schedules", "GachaTop", "gachaScheduleList", "id"),
    TableSpec("gacha_exchanges", "GachaTop", "gachaExchangeList", "gachaExchangeId"),
    TableSpec("shops", "ShopTop", "shopList", "shopId"),
    TableSpec("quest_parts", "QuestTop", "partList", "partId"),
    TableSpec(
        "another_quest_details",
        "QuestTop",
        "anotherQuestDetailList",
        "anotherQuestDetailId",
    ),
    TableSpec("challenge_groups", "MissionTop", "challengeGroupList", "id"),
    TableSpec(
        "limited_challenge_groups",
        "MissionTop",
        "limitedChallengeGroupList",
        "id",
    ),
)


class MasterDataRepository:
    def __init__(self, directory):
        self.directory = Path(directory).resolve(strict=True)
        manifest = json.loads(
            (self.directory / "manifest.json").read_text(encoding="utf-8")
        )
        self.sources = {}
        self.raw_pages = {}
        for record in manifest["tables"]:
            path = (self.directory / record["file"]).resolve(strict=True)
            if self.directory not in path.parents:
                raise ValueError("Master data file escaped extraction directory")
            body = path.read_bytes()
            if hashlib.sha256(body).hexdigest() != record["sha256"]:
                raise ValueError("Master data file checksum mismatch")
            page = path.name.removesuffix(".static.json")
            if page in self.raw_pages:
                raise ValueError("Duplicate page in master data extraction")
            data = json.loads(body)
            if not isinstance(data, dict):
                raise ValueError("Master data page must be an object")
            self.raw_pages[page] = data
            self.sources[page] = {
                "path": record["path"],
                "source_sha256": record["source_sha256"],
                "source_time": record["source_time"],
            }
        self.tables = {}
        self.indexes = {}
        for spec in TABLE_SPECS:
            page = self.raw_pages.get(spec.page)
            if page is None:
                raise ValueError("Missing master data page: " + spec.page)
            rows = page.get(spec.field)
            if not isinstance(rows, list):
                raise ValueError(
                    "Missing master table: %s.%s" % (spec.page, spec.field)
                )
            index = {}
            for row in rows:
                if not isinstance(row, dict):
                    raise ValueError("Master row must be an object")
                if spec.id_field not in row:
                    raise ValueError(
                        "Missing ID field %s in %s" % (spec.id_field, spec.name)
                    )
                identity = row[spec.id_field]
                if identity in index:
                    raise ValueError(
                        "Duplicate ID %r in %s" % (identity, spec.name)
                    )
                index[identity] = row
            self.tables[spec.name] = rows
            self.indexes[spec.name] = index

    def rows(self, name: str) -> list[dict[str, Any]]:
        return self.tables[name]

    def get(self, name: str, identity: Any) -> dict[str, Any] | None:
        return self.indexes[name].get(identity)

    def source(self, page: str) -> dict[str, Any]:
        return dict(self.sources[page])
