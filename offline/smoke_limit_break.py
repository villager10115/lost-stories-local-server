"""Exercise limit breaks over HTTP using copies of packaged saves only."""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

import uvicorn

from smoke_private_repair import port


def run(package, source):
    sys.path.insert(0, str(source / "stateful_server"))
    from cgls.app import create_app
    from server import LocalServer
    from web_store import WebStore
    from preserved_web import PreservedWebStore

    originals = sorted((package / "data").rglob("*.sqlite"))
    before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in originals}
    results = {}
    with tempfile.TemporaryDirectory(prefix="cgls-limit-break-") as temporary:
        root = Path(temporary)
        for src, name in [(package / "data/state/state.sqlite", "state.sqlite"),
                          (package / "data/page/decks.sqlite", "decks.sqlite"),
                          (package / "data/page/prototype.sqlite", "page.sqlite")]:
            with closing(sqlite3.connect(src.as_uri() + "?mode=ro", uri=True)) as a, \
                    closing(sqlite3.connect(str(root / name))) as b:
                a.backup(b)
                assert b.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        with closing(sqlite3.connect(str(root / "state.sqlite"))) as db:
            uid, card = db.execute("SELECT user_id, user_card_id FROM user_pilots "
                                  "WHERE mst_pilot_id=103004 AND limit_break=0").fetchone()
            db.execute("UPDATE user_wallets SET gold=10000 WHERE user_id=?", (uid,))
            db.execute("INSERT INTO user_card_limit_breaks "
                "(user_id,card_id,quantity,created_at,updated_at) VALUES (?,103004,70,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP) "
                "ON CONFLICT(user_id,card_id) DO UPDATE SET quantity=70", (uid,))
            db.execute("INSERT INTO user_game_items (user_id,item_id,quantity,updated_at) VALUES (?, 'LIMIT_BREAK_RANK_3', 110,CURRENT_TIMESTAMP) "
                       "ON CONFLICT(user_id,item_id) DO UPDATE SET quantity=110", (uid,))
            db.commit()

        first_responses = {}
        for iteration in range(2):
            state_port = port()
            app = create_app(root / "state.sqlite", source / "stateful_server/fixtures/gacha_1005.json")
            state = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=state_port, log_level="error"))
            state_thread = threading.Thread(target=state.run, daemon=True)
            state_thread.start()
            page = page_thread = None
            try:
                deadline = time.monotonic() + 20
                while not state.started and time.monotonic() < deadline:
                    time.sleep(.05)
                assert state.started
                assets = package / "assets"
                url = f"http://127.0.0.1:{state_port}"
                page = LocalServer(0, root / "page.sqlite", deck_database=root / "decks.sqlite",
                    masterdata=assets / "masterdata", gacha_upstream=url,
                    gacha_state_url=url + "/api/local/page-state", gacha_static=assets / "gacha-static",
                    preserved_pages_cache=assets / "preserved-pages")
                page_thread = threading.Thread(target=page.serve_forever, daemon=True)
                page_thread.start()

                def request(path, payload=None, key=None, session=True, extra_headers=None):
                    headers = {"Content-Type": "application/json"}
                    if session:
                        headers["X-Web-Session-Id"] = "limit-break-test"
                    if key is not None:
                        headers["X-Request-Id"] = key
                    headers.update(extra_headers or {})
                    req = urllib.request.Request("http://" + page.authority + path,
                        data=json.dumps(payload).encode() if payload is not None else None, headers=headers)
                    try:
                        with urllib.request.urlopen(req, timeout=45) as response:
                            return response.status, json.loads(response.read())
                    except urllib.error.HTTPError as exc:
                        return exc.code, json.loads(exc.read())

                path = "/api/card/enforce/limitBreak"
                payload = {"userCardId": card, "limitBreakType": "UNIQUE"}
                assert request(path, payload)[0] == 400
                assert request(path, payload, "no-session", session=False)[0] == 403
                assert request(path, payload, "bad-origin", extra_headers={"Origin": "http://example.invalid"})[0] == 403
                assert request(path, {**payload, "gold": 0}, "override")[0] == 422
                for kind in ["UNIQUE", "COMMON"]:
                    status, response = request(path, {**payload, "limitBreakType": kind}, "smoke-" + kind)
                    assert status == 200, response
                    if iteration == 0:
                        first_responses[kind] = response
                    else:
                        assert response == first_responses[kind]
                assert request(path, {**payload, "limitBreakType": "COMMON"}, "smoke-UNIQUE")[0] == 400

                for name in ["MyPage", "GachaTop", "DeckFormation", "ComposeTop"]:
                    status, body = request("/api/page/" + name)
                    assert status == 200
                    pilot = next(r for r in body["userCardList"] if r["userCardId"] == card)
                    assert pilot["lbCount"] == 2 and pilot["level"] == 1 and "hp" in pilot
                    items = {r["itemId"]: r["quantity"] for r in body["userItemList"]}
                    assert items["GOLD"] == 7000 and items["LIMIT_BREAK_RANK_3"] == 85
                    assert next(r for r in body["userCardLimitBreakList"] if r["cardId"] == 103004)["quantity"] == 60
                results["restart" if iteration else "firstRun"] = {
                    "passed": True, "lbCount": 2, "gold": 7000, "uniqueMaterials": 60,
                    "commonMaterials": 85, "crossPageState": True, "requestIdForwarding": True,
                    "invalidRequestsRejected": True}
            finally:
                if page:
                    page.shutdown()
                    page.server_close()
                    page_thread.join(5)
                state.should_exit = True
                state_thread.join(10)
                assert not state_thread.is_alive()

    after = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in originals}
    assert before == after, "Original packaged saves changed"
    results["originalSaveHashesUnchanged"] = True
    config = json.loads((package / "config/private-server.json").read_text(encoding="utf-8"))
    stores = [WebStore(package / config["webRoot"], config["webEntry"]),
              PreservedWebStore(package / config["preservedPages"])]
    paths = ["/web/js/compose/ComposePilot.js", "/web/template/compose/ComposePilot.html",
             "/web/css/compose/ComposeCommon.css", "/web/js/view/compose/ComposePilotLimitbreakView.js",
             "/web/js/view/compose/LimitbreakAnimationView.js", "/web/template/compose/LimitBreakResultTemp.html"]
    results["composeResources"] = {p: any(s.resolve(p)[0] == 200 for s in stores) for p in paths}
    assert all(results["composeResources"].values()), results["composeResources"]
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    result = run(args.package, args.source)
    if args.report:
        args.report.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
