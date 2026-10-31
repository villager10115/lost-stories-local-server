"""Run the repaired protocol against copies of the packaged saves, never the game.

The servers use ephemeral loopback ports and shut down gracefully. No official
network requests, game scripts, or native binaries are executed.
"""
import argparse
from contextlib import closing
import json
from pathlib import Path
import socket
import sqlite3
import sys
import tempfile
import threading
import time
import urllib.request

import uvicorn


def port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def run(package, source):
    sys.path.insert(0, str(source / "stateful_server"))
    sys.path.insert(0, str(source / "offline"))
    from cgls.app import create_app
    from server import LocalServer
    results = {}
    with tempfile.TemporaryDirectory(prefix="cgls-repair-") as temporary:
        root = Path(temporary)
        for src, name in ((package / "data/state/state.sqlite", "state.sqlite"),
                          (package / "data/page/decks.sqlite", "decks.sqlite"),
                          (package / "data/page/prototype.sqlite", "page.sqlite")):
            with closing(sqlite3.connect(str(src))) as a, closing(sqlite3.connect(str(root / name))) as b:
                a.backup(b)
                assert b.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        final_deck = None
        old_items = None
        for iteration in range(2):
            state_port = port()
            app = create_app(root / "state.sqlite",
                             source / "stateful_server/fixtures/gacha_1005.json")
            state = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1",
                                                 port=state_port, log_level="error"))
            state_thread = threading.Thread(target=state.run, daemon=True)
            state_thread.start()
            page = None
            page_thread = None
            def request(path, payload=None, is_state=False):
                base = (f"http://127.0.0.1:{state_port}" if is_state
                        else "http://" + page.authority)
                req = urllib.request.Request(base + path,
                    data=json.dumps(payload).encode() if payload is not None else None,
                    headers={"Content-Type": "application/json", "X-Web-Session-Id": "repair-test"})
                with urllib.request.urlopen(req, timeout=45) as response:
                    return json.loads(response.read())
            try:
                deadline = time.monotonic() + 20
                while not state.started and time.monotonic() < deadline:
                    time.sleep(.05)
                assert state.started, "state service failed to start"
                assets = package / "assets"
                state_url = f"http://127.0.0.1:{state_port}"
                page = LocalServer(0, root / "page.sqlite",
                    deck_database=root / "decks.sqlite", masterdata=assets / "masterdata",
                    gacha_upstream=state_url, gacha_state_url=state_url + "/api/local/page-state",
                    gacha_static=assets / "gacha-static", preserved_pages_cache=assets / "preserved-pages")
                page_thread = threading.Thread(target=page.serve_forever, daemon=True)
                page_thread.start()
                home = request("/api/page/MyPage")
                items = {r["itemId"]: r["quantity"] for r in home["userItemList"]}
                local = request("/api/local/state", is_state=True)
                assert items["GOLD"] == local["gold"]
                assert items["PRESENTED_MONEY"] == local["freeSakuradite"]
                assert request("/api/page/GachaTop")["userQuestList"] == home["userQuestList"]
                assert request("/api/page/ShopTop")["userShopItemList"] == []
                assert request("/api/page/GuildTop")["guildMemberList"] == []
                assert len(home["userDailyChallengeList"]) == 2
                decks = request("/api/page/DeckFormation")
                owned_cards = {r["userCardId"] for r in home["userCardList"]}
                owned_kmfs = {r["userKnightmareFrameId"] for r in home["userKnightmareFrameList"]}
                for deck in decks["userDeckList"]:
                    for i in range(1, 11):
                        assert not deck.get(f"userCardId{i}") or deck[f"userCardId{i}"] in owned_cards
                        assert not deck.get(f"userKnightmareFrameId{i}") or deck[f"userKnightmareFrameId{i}"] in owned_kmfs
                assert len(decks["userDeckList"]) == 17
                assert decks["userCardList"][0]["hp"] == home["userCardList"][0]["hp"]
                assert decks["userKnightmareFrameCustomizeList"]
                if iteration == 0:
                    old_items = local["gameItems"]
                    pilots = list(reversed(home["userCardList"]))
                    kmfs = list(reversed(home["userKnightmareFrameList"]))
                    save = request("/api/deck/save", {"deckType": "MAIN1",
                        "userCardIdList": [pilots[0]["userCardId"], "", pilots[1]["userCardId"]] + [""] * 7,
                        "userKnightmareFrameIdList": [kmfs[0]["userKnightmareFrameId"], "", kmfs[1]["userKnightmareFrameId"]] + [""] * 7})
                    final_deck = save["userDeckList"][0]
                    assert final_deck["userCardId3"] == pilots[1]["userCardId"]
                    claim = request("/api/challenge/receive/all", {})
                    assert {r["itemId"]: r["quantity"] for r in claim["results"]} == {
                        "GACHA_MEDAL": 50, "DAILY_QUEST_DROP_BOOST": 1}
                    assert all(r["receivedAt"] for r in claim["userDailyChallengeList"])
                    assert "userItemList" in claim
                retry = request("/api/challenge/receive/all", {})
                assert retry["results"] == []
                after = request("/api/page/MyPage")
                current_deck = next(r for r in after["userDeckList"] if r["deckType"] == "MAIN1")
                assert current_deck == final_deck
                local_after = request("/api/local/state", is_state=True)["gameItems"]
                assert local_after["GACHA_MEDAL"] == old_items.get("GACHA_MEDAL", 0) + 50
                assert local_after["DAILY_QUEST_DROP_BOOST"] == old_items.get("DAILY_QUEST_DROP_BOOST", 0) + 1
                for page_name in ("MyPage", "GachaTop", "MissionTop", "QuestTop", "DeckFormation"):
                    payload = request("/api/page/" + page_name)
                    amounts = {r["itemId"]: r["quantity"] for r in payload["userItemList"]}
                    assert amounts["GACHA_MEDAL"] == local_after["GACHA_MEDAL"], page_name
                    assert amounts["GOLD"] == local["gold"], page_name
                results["initial" if iteration == 0 else "restart"] = {
                    "passed": True, "decks": 17, "dailyMissions": 2,
                    "gold": local["gold"], "crossPageInventory": True,
                    "nativeDeckRequest": True, "foreignSlotsRemoved": True}
                print(json.dumps(results), flush=True)
            finally:
                if page:
                    page.shutdown()
                    page.server_close()
                    if page_thread:
                        page_thread.join(5)
                state.should_exit = True
                state_thread.join(10)
                assert not state_thread.is_alive(), "state did not shut down"
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    result = run(args.package, args.source)
    if args.report:
        args.report.write_text(json.dumps(result, indent=2), encoding="utf-8")
