"""Real-HTTP acceptance for the eight local enhancement modules.

The verifier creates disposable state/page/deck databases, starts the source
state and page servers on loopback, and exercises the exact routes used by the
retained WebView client.  It never opens a packaged formal save or starts the
game.
"""
from __future__ import annotations

from contextlib import redirect_stderr
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time
from typing import Any, Callable
import urllib.error
import urllib.request
import uuid

import uvicorn


PAGE_PATHS = (
    "/api/page/ComposeTop",
    "/api/page/ComposePilot",
    "/api/page/CostumeTop",
    "/api/page/ComposeKmf",
    "/api/page/KmfColoring",
    "/api/page/KmfDevelopment",
    "/api/page/KmfDismantle",
    "/api/page/CarryingTop",
)


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object in %s" % path)
    return data


def _collect_need_item_ids(value: Any, result: set[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key.startswith("needItemId") and isinstance(child, str) and child:
                result.add(child)
            elif key == "needGenericCode" and isinstance(child, str) and child:
                result.add(child)
            else:
                _collect_need_item_ids(child, result)
    elif isinstance(value, list):
        for child in value:
            _collect_need_item_ids(child, result)



def _seed_disposable_account(
    app,
    masterdata_dir: Path,
    masterdata: dict[str, Any],
) -> dict[str, Any]:
    from cgls.bootstrap import ensure_local_user
    from sqlalchemy import select
    from cgls.models import (
        UserCardLimitBreak,
        UserGameItem,
        UserKmfKey,
        UserPilot,
        UserWallet,
    )

    progression = _read_json(
        Path(__file__).resolve().parents[1]
        / "stateful_server"
        / "fixtures"
        / "card_progression.json"
    )
    item_ids = {str(value) for value in progression.get("itemExpArr", {})}
    item_ids.add("TRUST_EXP")
    _collect_need_item_ids(masterdata, item_ids)
    for row in masterdata.get("itemList", []):
        item_id = row.get("itemId") if isinstance(row, dict) else None
        if isinstance(item_id, str) and item_id:
            item_ids.add(item_id)

    with app.state.session_factory() as session:
        user = ensure_local_user(session)
        owned_card_ids = {pilot.mst_pilot_id for pilot in user.pilots}
        feature_card = next(
            (
                row for row in masterdata.get("cardList", [])
                if isinstance(row, dict)
                and row.get("cardFeatureList")
                and int(row.get("cardId", 0) or 0) not in owned_card_ids
            ),
            None,
        )
        if feature_card is None:
            raise AssertionError("MasterData has no feature-bearing pilot")
        session.add(UserPilot(
            user_id=user.id,
            user_card_id="verification-feature-%s" % feature_card["cardId"],
            mst_pilot_id=int(feature_card["cardId"]),
            mst_chara_id=int(feature_card.get("charaId", 0) or 0),
            level=25,
            skill_levels=[1, 1],
            unlocked_feature_ids=[],
        ))
        session.flush()
        wallet = session.get(UserWallet, user.id)
        wallet.gold = 100_000_000
        wallet.free_sakuradite = 100_000
        wallet.paid_sakuradite = 100_000
        for item_id in sorted(item_ids):
            row = session.get(UserGameItem, (user.id, item_id))
            if row is None:
                row = UserGameItem(
                    user_id=user.id,
                    item_id=item_id,
                    quantity=99_999,
                )
                session.add(row)
            else:
                row.quantity = max(row.quantity, 99_999)
        for pilot in user.pilots:
            row = session.get(
                UserCardLimitBreak, (user.id, pilot.mst_pilot_id))
            if row is None:
                row = UserCardLimitBreak(
                    user_id=user.id,
                    card_id=pilot.mst_pilot_id,
                    quantity=99_999,
                )
                session.add(row)
            else:
                row.quantity = max(row.quantity, 99_999)
        feature_limit = session.get(
            UserCardLimitBreak,
            (user.id, int(feature_card["cardId"])),
        )
        if feature_limit is None:
            session.add(UserCardLimitBreak(
                user_id=user.id,
                card_id=int(feature_card["cardId"]),
                quantity=99_999,
            ))
        else:
            feature_limit.quantity = max(feature_limit.quantity, 99_999)
        frame_ids = {
            int(row.mst_kmf_id)
            for row in user.kmfs
            if row.mst_kmf_id
        }
        for frame_id in sorted(frame_ids):
            key = session.get(UserKmfKey, (user.id, frame_id))
            if key is None:
                key = UserKmfKey(
                    user_id=user.id,
                    knightmare_frame_id=frame_id,
                    quantity=10,
                )
                session.add(key)
            else:
                key.quantity = max(key.quantity, 10)
        session.commit()
        return {
            "userId": user.id,
            "candidateFrameIds": sorted(frame_ids),
            "seedItemCount": len(item_ids),
            "seedPilotCount": len(session.execute(
                select(UserPilot).where(UserPilot.user_id == user.id)
            ).scalars().all()),
        }


def _start_state(app, preferred_port: int = 0):
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=preferred_port,
        log_level="critical",
        access_log=False,
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 20
    while not server.started and time.monotonic() < deadline:
        if not thread.is_alive():
            raise RuntimeError("State server exited during startup")
        time.sleep(0.05)
    if not server.started:
        raise TimeoutError("State server did not start")
    return server, thread, "http://127.0.0.1:%d" % server.servers[0].sockets[0].getsockname()[1]


def _stop_state(server, thread) -> None:
    server.should_exit = True
    thread.join(15)
    if thread.is_alive():
        raise RuntimeError("State server did not stop")


def _request(
    records: list[dict[str, Any]],
    url: str,
    path: str,
    body: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-Offline-Token": "stale-token-from-before-restart",
    }
    data = None
    method = "GET"
    if body is not None:
        method = "POST"
        headers["X-Web-Session-Id"] = "local-enhancement-verification"
        data = json.dumps(body, separators=(",", ":")).encode("utf-8")
    if request_id:
        headers["X-Request-Id"] = request_id
    request = urllib.request.Request(
        url + path,
        data=data,
        headers=headers,
        method=method,
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    status = None
    raw = b""
    try:
        with opener.open(request, timeout=30) as response:
            status = response.status
            raw = response.read()
    except urllib.error.HTTPError as exc:
        status = exc.code
        raw = exc.read()
    records.append({
        "method": method,
        "path": path,
        "status": status,
    })
    if status != 200:
        raise AssertionError(
            "%s %s returned %s: %r" % (method, path, status, raw[:500]))
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise AssertionError(
            "%s %s did not return JSON" % (method, path)) from exc
    if not isinstance(payload, dict):
        raise AssertionError("%s %s returned a non-object" % (method, path))
    if payload.get("resultCode") not in (None, "success"):
        raise AssertionError(
            "%s %s returned resultCode=%r: %r"
            % (method, path, payload.get("resultCode"), payload))
    return payload


def _find_page_pilot_feature(
    compose_pilot: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    cards = {
        int(row["cardId"]): row
        for row in compose_pilot.get("cardList", [])
        if isinstance(row, dict) and row.get("cardId") is not None
    }
    for pilot in compose_pilot.get("userCardList", []):
        card = cards.get(int(pilot.get("cardId", 0) or 0))
        if not isinstance(card, dict):
            continue
        unlocked = set(pilot.get("unlockedFeatureIdList") or [])
        for feature in card.get("cardFeatureList", []) or []:
            if (isinstance(feature, dict)
                    and int(feature.get("cardFeatureId", 0) or 0) > 0
                    and int(feature.get("cardFeatureId", 0)) not in unlocked):
                return pilot, feature
    raise AssertionError("No unlockable pilot feature was exposed")


def _find_costume(
    costume_page: dict[str, Any],
    card: dict[str, Any],
) -> int:
    chara_id = int(card.get("charaId", 0) or 0)
    for row in costume_page.get("costumeList", []) or []:
        if (isinstance(row, dict)
                and row.get("type") == "CHARA"
                and int(row.get("charaId", 0) or 0) == chara_id):
            return int(row["costumeId"])
    for row in costume_page.get("costumeList", []) or []:
        if (isinstance(row, dict)
                and row.get("type") == "CARD"
                and int(row.get("cardId", 0) or 0) == card.get("cardId")):
            return int(row["costumeId"])
    raise AssertionError("No usable costume was exposed for the selected pilot")


def _database_rows(database: Path, sql: str, parameters=()):
    with sqlite3.connect(str(database)) as connection:
        return connection.execute(sql, parameters).fetchall()


def _run_scenario(
    package: Path,
    source: Path,
    work: Path,
) -> dict[str, Any]:
    sys.path[:0] = [
        str(source / "offline"),
        str(source / "stateful_server"),
    ]
    from cgls.app import create_app
    from server import LocalServer

    masterdata_dir = package / "assets" / "masterdata"
    masterdata = _read_json(masterdata_dir / "pages" / "MyPage.static.json")
    state_database = work / "state.sqlite"
    page_database = work / "page.sqlite"
    deck_database = work / "decks.sqlite"
    fixture = source / "stateful_server" / "fixtures" / "gacha_1005.json"

    app = create_app(
        state_database,
        fixture,
        masterdata_dir=masterdata_dir,
    )
    seed = _seed_disposable_account(app, masterdata_dir, masterdata)
    state_server, state_thread, state_url = _start_state(app)
    page_server = LocalServer(
        0,
        page_database,
        deck_database=deck_database,
        masterdata=masterdata_dir,
        gacha_upstream=state_url,
        gacha_static=package / "assets" / "gacha-static",
        gacha_state_url=state_url + "/api/local/page-state",
        preserved_pages_cache=package / "assets" / "preserved-pages",
    )
    page_thread = threading.Thread(
        target=page_server.serve_forever, daemon=True)
    page_thread.start()
    page_url = "http://" + page_server.authority
    records: list[dict[str, Any]] = []
    evidence: dict[str, Any] = {}
    captured = io.StringIO()

    try:
        with redirect_stderr(captured):
            pages = {
                path: _request(records, page_url, path)
                for path in PAGE_PATHS
            }

            compose_pilot = pages["/api/page/ComposePilot"]
            cards_by_id = {
                int(row["cardId"]): row
                for row in compose_pilot.get("cardList", [])
                if isinstance(row, dict) and row.get("cardId") is not None
            }
            pilot = next(
                row for row in compose_pilot["userCardList"]
                if row.get("level", 0) < 99
            )
            user_card_id = pilot["userCardId"]
            initial_level = int(pilot["level"])
            experience_request = uuid.uuid4().hex
            experience = _request(
                records,
                page_url,
                "/api/card/enforce/experience",
                {
                    "userCardId": user_card_id,
                    "useItem": {"EXP_PP": 1},
                },
                experience_request,
            )
            pilot_after_experience = experience["userCardList"][0]
            assert "bonusList" in pilot_after_experience
            assert int(pilot_after_experience["level"]) > initial_level
            level_row = _database_rows(
                state_database,
                "select level, experience from user_pilots "
                "where user_card_id=?",
                (user_card_id,),
            )[0]
            assert int(level_row[0]) == int(pilot_after_experience["level"])
            evidence["pilot_experience"] = {
                "requestId": experience_request,
                "before": initial_level,
                "after": int(level_row[0]),
                "experience": int(level_row[1]),
            }

            feature_pilot, feature = _find_page_pilot_feature(compose_pilot)
            feature_user_card_id = feature_pilot["userCardId"]
            feature_request = uuid.uuid4().hex
            feature_response = _request(
                records,
                page_url,
                "/api/card/enforce/feature",
                {
                    "userCardId": feature_pilot["userCardId"],
                    "cardFeatureId": int(feature["cardFeatureId"]),
                },
                feature_request,
            )
            unlocked = list(
                feature_response["userCardList"][0]["unlockedFeatureIdList"])
            assert int(feature["cardFeatureId"]) in unlocked
            feature_row = _database_rows(
                state_database,
                "select unlocked_feature_ids from user_pilots "
                "where user_card_id=?",
                (feature_pilot["userCardId"],),
            )[0][0]
            assert str(feature["cardFeatureId"]) in feature_row
            evidence["pilot_feature"] = {
                "requestId": feature_request,
                "cardFeatureId": int(feature["cardFeatureId"]),
                "stored": feature_row,
            }

            revision_candidates = [
                row for row in compose_pilot["userCardList"]
                if int(cards_by_id.get(int(row.get("cardId", 0) or 0), {})
                       .get("rarity", {}).get("maxRevision", 0) or 0)
                > int(row.get("revision", 0))
            ]
            if revision_candidates:
                revision_pilot = revision_candidates[0]
                before_revision = int(revision_pilot.get("revision", 0))
                revision_request = uuid.uuid4().hex
                revision_response = _request(
                    records,
                    page_url,
                    "/api/card/enforce/revision",
                    {"userCardId": revision_pilot["userCardId"]},
                    revision_request,
                )
                after_revision = int(
                    revision_response["userCardList"][0]["revision"])
                assert after_revision == before_revision + 1
                revision_row = _database_rows(
                    state_database,
                    "select awakening_level from user_pilots "
                    "where user_card_id=?",
                    (revision_pilot["userCardId"],),
                )[0][0]
                assert int(revision_row) == after_revision
                evidence["pilot_revision"] = {
                    "requestId": revision_request,
                    "before": before_revision,
                    "after": after_revision,
                    "stored": int(revision_row),
                }

            costume_page = pages["/api/page/CostumeTop"]
            costume_card = cards_by_id[int(pilot["cardId"])]
            costume_id = _find_costume(costume_page, costume_card)
            costume_response = _request(
                records,
                page_url,
                "/api/card/costume/dressUp",
                {
                    "userCardId": user_card_id,
                    "costumeId": costume_id,
                },
            )
            costume_rows = _database_rows(
                state_database,
                "select costume_id from user_card_costumes "
                "where user_card_id=?",
                (user_card_id,),
            )
            assert costume_rows and int(costume_rows[-1][0]) == costume_id
            assert int(costume_response["userCardList"][0]
                       .get("costumeId", 0)) == costume_id
            evidence["costume"] = {
                "costumeId": costume_id,
                "userCardId": user_card_id,
            }

            compose_kmf = pages["/api/page/ComposeKmf"]
            customization = next(
                row for row in compose_kmf[
                    "userKnightmareFrameCustomizeList"]
                if row.get("userKnightmareFrameCustomizeId")
            )
            user_kmf_id = customization["userKnightmareFrameId"]
            user_customize_id = customization[
                "userKnightmareFrameCustomizeId"]
            before_kmf_revision = int(customization.get("revision", 0))
            kmf_request = uuid.uuid4().hex
            kmf_response = _request(
                records,
                page_url,
                "/api/knightmareFrameCustomize/enforce/revision",
                {"userKnightmareFrameCustomizeId": user_customize_id},
                kmf_request,
            )
            kmf_after = next(
                row for row in kmf_response[
                    "userKnightmareFrameCustomizeList"]
                if row["userKnightmareFrameCustomizeId"]
                == user_customize_id
            )
            after_kmf_revision = int(kmf_after["revision"])
            assert after_kmf_revision == before_kmf_revision + 1
            kmf_revision_row = _database_rows(
                state_database,
                "select revision from user_kmfs "
                "where user_kmf_id=?",
                (user_kmf_id,),
            )[0][0]
            assert int(kmf_revision_row) == after_kmf_revision
            evidence["kmf_enforce"] = {
                "requestId": kmf_request,
                "before": before_kmf_revision,
                "after": after_kmf_revision,
                "stored": int(kmf_revision_row),
            }

            color_response = _request(
                records,
                page_url,
                "/api/knightmareFrame/color",
                {
                    "userKnightmareFrameCustomizeId": user_customize_id,
                    "red": 17,
                    "green": 83,
                    "blue": 191,
                },
            )
            colored = color_response["userKnightmareFrameList"][0]
            assert (
                colored["customColorR"],
                colored["customColorG"],
                colored["customColorB"],
            ) == (17, 83, 191)
            color_row = _database_rows(
                state_database,
                "select upgrade_ranks from user_kmfs "
                "where user_kmf_id=?",
                (user_kmf_id,),
            )[0][0]
            assert '"r": 17' in color_row and '"g": 83' in color_row \
                and '"b": 191' in color_row
            evidence["kmf_color"] = {
                "userKmfId": user_kmf_id,
                "rgb": [17, 83, 191],
                "stored": json.loads(color_row)["localColor"],
            }

            development_frame = seed["candidateFrameIds"][0]
            developed_ids = []
            for frame_no in (1, 2):
                _request(
                    records,
                    page_url,
                    "/api/knightmareFrame/development/start",
                    {
                        "frameNo": frame_no,
                        "knightmareFrameId": development_frame,
                    },
                )
                _request(
                    records,
                    page_url,
                    "/api/knightmareFrame/development/skip",
                    {"frameNo": frame_no},
                )
                received = _request(
                    records,
                    page_url,
                    "/api/knightmareFrame/development/receive",
                    {"frameNo": frame_no},
                )
                created = received["userKnightmareFrameList"][0]
                developed_ids.append(created["userKnightmareFrameId"])
                count = _database_rows(
                    state_database,
                    "select count(*) from user_kmfs "
                    "where user_kmf_id=?",
                    (created["userKnightmareFrameId"],),
                )[0][0]
                assert int(count) == 1
            evidence["kmf_development"] = {
                "frameId": development_frame,
                "createdUserKmfIds": developed_ids,
            }

            carried_in = _request(
                records,
                page_url,
                "/api/knightmareFrame/carryIn",
                {"userKnightmareFrameIdList": [user_kmf_id]},
            )
            assert carried_in["userKnightmareFrameList"][0]["isInStorage"]
            storage_in = _database_rows(
                state_database,
                "select is_in_storage from user_kmfs "
                "where user_kmf_id=?",
                (user_kmf_id,),
            )[0][0]
            assert int(storage_in) == 1
            carried_out = _request(
                records,
                page_url,
                "/api/knightmareFrame/carryOut",
                {"userKnightmareFrameIdList": [user_kmf_id]},
            )
            assert not carried_out["userKnightmareFrameList"][0]["isInStorage"]
            storage_out = _database_rows(
                state_database,
                "select is_in_storage from user_kmfs "
                "where user_kmf_id=?",
                (user_kmf_id,),
            )[0][0]
            assert int(storage_out) == 0
            evidence["kmf_storage"] = {
                "userKmfId": user_kmf_id,
                "carryInStored": int(storage_in),
                "carryOutStored": int(storage_out),
            }

            dismantle_id = developed_ids[0]
            _request(
                records,
                page_url,
                "/api/deck/save",
                {
                    "deckType": "MAIN1",
                    "userCardIdList": [user_card_id],
                    "userKnightmareFrameIdList": [dismantle_id],
                },
            )
            dismantled = _request(
                records,
                page_url,
                "/api/knightmareFrame/dismantle",
                {"userKnightmareFrameIdList": [dismantle_id]},
            )
            assert dismantled["deleted"]["userKnightmareFrameList"][0][
                "userKnightmareFrameId"] == dismantle_id
            count = _database_rows(
                state_database,
                "select count(*) from user_kmfs "
                "where user_kmf_id=?",
                (dismantle_id,),
            )[0][0]
            assert int(count) == 0
            deck_rows = _database_rows(
                state_database,
                "select slots from user_decks",
            )
            assert all(dismantle_id not in row[0] for row in deck_rows)
            evidence["kmf_dismantle"] = {
                "userKmfId": dismantle_id,
                "remainingRows": int(count),
                "deckReferences": sum(
                    row[0].count(dismantle_id) for row in deck_rows),
            }

            units = _request(records, state_url, "/api/local/units")
            assert any(
                row["userCardId"] == user_card_id
                and int(row.get("level", 0)) == int(level_row[0])
                for row in units["userCardList"])
            assert any(
                row["userKnightmareFrameId"] == user_kmf_id
                and int(row["revision"]) == after_kmf_revision
                for row in units["userKnightmareFrameList"])
    finally:
        try:
            page_server.shutdown()
            page_server.server_close()
            page_thread.join(10)
        finally:
            _stop_state(state_server, state_thread)
            app.state.engine.dispose()

    captured_text = captured.getvalue()
    unexpected_logs = [
        line for line in captured_text.splitlines()
        if "local_http_failure" in line or "Traceback" in line
    ]
    if unexpected_logs:
        raise AssertionError(
            "Unexpected service diagnostics:\n" + "\n".join(unexpected_logs))

    restart_app = create_app(
        state_database,
        fixture,
        masterdata_dir=masterdata_dir,
    )
    restart_state, restart_thread, restart_state_url = _start_state(restart_app)
    restart_page = LocalServer(
        0,
        page_database,
        deck_database=deck_database,
        masterdata=masterdata_dir,
        gacha_upstream=restart_state_url,
        gacha_static=package / "assets" / "gacha-static",
        gacha_state_url=restart_state_url + "/api/local/page-state",
        preserved_pages_cache=package / "assets" / "preserved-pages",
    )
    restart_page_thread = threading.Thread(
        target=restart_page.serve_forever, daemon=True)
    restart_page_thread.start()
    restart_url = "http://" + restart_page.authority
    try:
        restart_pages = {
            path: _request(records, restart_url, path)
            for path in PAGE_PATHS
        }
        restart_pilot = next(
            row for row in restart_pages["/api/page/ComposePilot"][
                "userCardList"]
            if row["userCardId"] == user_card_id)
        assert int(restart_pilot["level"]) == int(level_row[0])
        assert int(restart_pilot.get("costumeId", 0)) == costume_id
        restart_feature_pilot = next(
            row for row in restart_pages["/api/page/ComposePilot"][
                "userCardList"]
            if row["userCardId"] == feature_user_card_id)
        assert int(feature["cardFeatureId"]) in set(
            restart_feature_pilot["unlockedFeatureIdList"])
        restart_kmf_page = restart_pages["/api/page/ComposeKmf"]
        restart_kmf = next(
            row for row in restart_kmf_page[
                "userKnightmareFrameCustomizeList"]
            if row["userKnightmareFrameCustomizeId"] == user_customize_id)
        assert int(restart_kmf["revision"]) == after_kmf_revision
        restart_coloring = restart_pages["/api/page/KmfColoring"]
        restart_colored_unit = next(
            row for row in restart_coloring["userKnightmareFrameList"]
            if row["userKnightmareFrameId"] == user_kmf_id)
        assert (
            restart_colored_unit["customColorR"],
            restart_colored_unit["customColorG"],
            restart_colored_unit["customColorB"],
        ) == (17, 83, 191)
        assert any(
            row["userKnightmareFrameId"] == developed_ids[1]
            for row in restart_coloring["userKnightmareFrameList"])
        assert not any(
            row["userKnightmareFrameId"] == developed_ids[0]
            for row in restart_coloring["userKnightmareFrameList"])
        evidence["restart"] = {
            "pilotLevel": int(restart_pilot["level"]),
            "featureUserCardId": feature_user_card_id,
            "featureIds": list(
                restart_feature_pilot["unlockedFeatureIdList"]),
            "costumeId": costume_id,
            "kmfRevision": int(restart_kmf["revision"]),
            "kmfColor": [
                restart_colored_unit["customColorR"],
                restart_colored_unit["customColorG"],
                restart_colored_unit["customColorB"],
            ],
            "developedUserKmfId": developed_ids[1],
            "dismantledUserKmfId": developed_ids[0],
        }
    finally:
        try:
            restart_page.shutdown()
            restart_page.server_close()
            restart_page_thread.join(10)
        finally:
            _stop_state(restart_state, restart_thread)
            restart_app.state.engine.dispose()

    bad = [row for row in records if row["status"] != 200]
    return {
        "passed": not bad,
        "package": str(package),
        "source": str(source),
        "database": str(state_database),
        "seed": seed,
        "requestCount": len(records),
        "requests": records,
        "unexpectedHttpStatuses": bad,
        "serviceDiagnostics": captured_text,
        "evidence": evidence,
    }


def main() -> int:
    if len(sys.argv) < 3:
        print(
            "usage: verify_enhancement_all_modules.py "
            "<package-root> <source-root> [output-json]",
            file=sys.stderr,
        )
        return 2
    package = Path(sys.argv[1]).resolve(strict=True)
    source = Path(sys.argv[2]).resolve(strict=True)
    output = (
        Path(sys.argv[3]).resolve()
        if len(sys.argv) > 3
        else None
    )
    with tempfile.TemporaryDirectory(
            prefix="cgls-enhancement-verification-") as temp:
        report = _run_scenario(package, source, Path(temp))
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
