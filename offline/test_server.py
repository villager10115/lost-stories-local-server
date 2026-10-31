import http.client
import hashlib
import json
import time
import tempfile
import threading
import unittest
from unittest.mock import Mock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from server import LocalServer
from server import Handler
from server import merge_battle_response_models


class ServerTests(unittest.TestCase):
    def test_respond_ignores_loopback_client_disconnects(self):
        handler = object.__new__(Handler)
        handler.command = "GET"
        handler.path = "/web/index.html"
        handler.headers = {}
        handler.server = Mock()
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock()
        handler.wfile = Mock()
        handler.wfile.write.side_effect = ConnectionAbortedError(10053, "closed")
        handler.respond(200, {})
        handler.wfile.write.assert_called_once()

    def test_battle_response_keeps_only_sortie_formation(self):
        models = {
            "gameUser": {"name": "Commander"},
            "userCardList": [
                {"userCardId": "card-a", "cardId": 1, "level": 9},
                {"userCardId": "card-b", "cardId": 2, "level": 8},
                {"userCardId": "card-extra", "cardId": 3},
            ],
            "userKnightmareFrameList": [
                {"userKnightmareFrameId": "kmf-a", "knightmareFrameId": 11},
                {"userKnightmareFrameId": "kmf-b", "knightmareFrameId": 12},
                {"userKnightmareFrameId": "kmf-extra", "knightmareFrameId": 13},
            ],
        }
        response = {
            "userCardList": [
                {"userCardId": "card-b", "experience": 7},
                {"userCardId": "card-a", "experience": 6},
            ],
            "battle": {"playerData": {"pilotStatusData": [
                {"userPilotId": "card-b", "userKnightmareId": "kmf-b"},
                {"userPilotId": "card-a", "userKnightmareId": "kmf-a"},
            ]}},
        }
        merged = merge_battle_response_models(
            response, models, "/api/battle/start")
        self.assertEqual(
            [row["userCardId"] for row in merged["userCardList"]],
            ["card-b", "card-a"],
        )
        self.assertEqual(
            [row["userKnightmareFrameId"]
             for row in merged["userKnightmareFrameList"]],
            ["kmf-b", "kmf-a"],
        )
        self.assertEqual(merged["userCardList"][0]["level"], 8)
        self.assertNotIn("card-extra", {
            row["userCardId"] for row in merged["userCardList"]})
        self.assertNotIn("userKnightmareFrameCustomizeList", merged)

    def test_asset_filelist_is_an_empty_local_table(self):
        with tempfile.TemporaryDirectory() as root:
            server = LocalServer(0, Path(root) / "save.sqlite")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                conn = http.client.HTTPConnection(
                    *server.server_address, timeout=5
                )
                conn.request("GET", "/assets/filelist.json")
                response = conn.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(
                    json.loads(response.read()), {"Records": []}
                )
                conn.close()

                conn = http.client.HTTPConnection(
                    *server.server_address, timeout=5
                )
                conn.request(
                    "GET",
                    "/web/json/event_banner/event_banner.json?bust=1&123",
                )
                response = conn.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(json.loads(response.read()), [])
                conn.close()

                conn = http.client.HTTPConnection(
                    *server.server_address, timeout=5
                )
                conn.request(
                    "GET",
                    "/web/json/announcement/announcement_digest.json?bust=1",
                )
                response = conn.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(json.loads(response.read()), [])
                conn.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

    def test_local_user_create_accepts_empty_bootstrap(self):
        with tempfile.TemporaryDirectory() as root:
            server = LocalServer(0, Path(root) / "save.sqlite")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                conn = http.client.HTTPConnection(
                    *server.server_address, timeout=5
                )
                conn.request("POST", "/api/user/create")
                response = conn.getresponse()
                self.assertEqual(response.status, 200)
                body = json.loads(response.read())
                self.assertEqual(body["resultCode"], "success")
                self.assertEqual(body["user"]["snsUserId"], "local-sns-user")
                conn.close()

                conn = http.client.HTTPConnection(
                    *server.server_address, timeout=5
                )
                conn.request(
                    "POST",
                    "/api/system/logger",
                    json.dumps({"error": "local test"}),
                    {"Content-Type": "application/json"},
                )
                response = conn.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(
                    json.loads(response.read())["resultCode"], "success"
                )
                conn.close()

                conn = http.client.HTTPConnection(
                    *server.server_address, timeout=5
                )
                conn.request(
                    "POST",
                    "/api/money/init",
                    "{}",
                    {"Content-Type": "application/json"},
                )
                response = conn.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(
                    json.loads(response.read())["resultCode"], "success"
                )
                conn.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

    def test_main_story_top_routes_to_local_account_page(self):
        class AccountStub:
            def resolve(self, path):
                if path.split("?", 1)[0] != "/api/page/MainStoryTop":
                    raise KeyError(path)
                return (
                    200,
                    json.dumps({
                        "resultCode": "success",
                        "userQuestList": [{"questId": 106201}],
                    }).encode("utf-8"),
                    "application/json; charset=utf-8",
                )

        with tempfile.TemporaryDirectory() as root:
            server = LocalServer(0, Path(root) / "save.sqlite")
            server.account_page = AccountStub()
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                conn = http.client.HTTPConnection(
                    *server.server_address, timeout=5
                )
                conn.request(
                    "GET",
                    "/api/page/MainStoryTop"
                    "?value=locationList&timeStamp=1792511724163",
                    headers={"X-Web-Session-Id": "main-story-test"},
                )
                response = conn.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(
                    json.loads(response.read())["userQuestList"][0]["questId"],
                    106201,
                )
                conn.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

    def test_major_activity_pages_route_to_preserved_models(self):
        class PreservedStub:
            def resolve(self, path):
                name = path.rsplit('/', 1)[-1]
                return (200, json.dumps({
                    'resultCode': 'success',
                    'page': name,
                    'entangleChallengeQuestList': [] if name == 'RootEntangleTop' else None,
                    'eventList': [] if name == 'EventStoryTop' else None,
                }).encode('utf-8'), 'application/json; charset=utf-8')

        with tempfile.TemporaryDirectory() as root:
            server = LocalServer(0, Path(root) / 'save.sqlite')
            server.preserved_pages = PreservedStub()
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                for name in ('RootEntangleTop', 'EventStoryTop'):
                    conn = http.client.HTTPConnection(
                        *server.server_address, timeout=5)
                    conn.request('GET', '/api/page/' + name,
                                 headers={'X-Web-Session-Id': 'activity-test'})
                    response = conn.getresponse()
                    self.assertEqual(response.status, 200)
                    self.assertEqual(json.loads(response.read())['page'], name)
                    conn.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

    def test_local_api(self):
        with tempfile.TemporaryDirectory() as root:
            server = LocalServer(0, Path(root) / "save.sqlite")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                def request(method, path, body=None, headers=None):
                    conn = http.client.HTTPConnection(*server.server_address, timeout=5)
                    conn.request(method, path, body, headers or {})
                    response = conn.getresponse()
                    status, data = response.status, response.read()
                    conn.close()
                    return status, data
                code, data = request("GET", "/api/state")
                self.assertEqual(code, 200)
                token = json.loads(data)["token"]
                body = json.dumps({"product": "demo_ticket", "order_id": "one"})
                self.assertEqual(request("POST", "/api/claim", body)[0], 403)
                malformed = {
                    "Content-Type": "application/json",
                    "X-Offline-Token": "\xe9",
                }
                self.assertEqual(request("POST", "/api/claim", body, malformed)[0], 403)
                headers = {"Content-Type": "application/json", "X-Offline-Token": token}
                self.assertEqual(request("POST", "/api/claim", body, headers)[0], 200)
                self.assertEqual(request("POST", "/api/claim", body, headers)[0], 200)
                self.assertEqual(server.shop.inventory(), {"demo_ticket": 1})
                headers["Origin"] = "https://example.com"
                self.assertEqual(request("POST", "/api/claim", body, headers)[0], 403)
                self.assertEqual(request("GET", "/", headers={"Host": "evil.test"})[0], 403)
                self.assertEqual(request("GET", "/unknown")[0], 404)
                # Send headers and body separately to reproduce an early-close race.
                for index in range(20):
                    conn = http.client.HTTPConnection(*server.server_address, timeout=5)
                    try:
                        conn.putrequest("POST", "/api/claim")
                        conn.putheader("Content-Length", str(len(body.encode())))
                        conn.putheader("Content-Type", "application/json")
                        conn.putheader("Origin", "https://example.com")
                        conn.endheaders()
                        time.sleep(0.01)
                        conn.send(body.encode())
                        response = conn.getresponse()
                        self.assertEqual(response.status, 403)
                        self.assertEqual(json.loads(response.read())["error"], "Invalid origin")
                    finally:
                        conn.close()
                self.assertEqual(server.shop.inventory(), {"demo_ticket": 1})
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

    def test_staged_web_entry(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            bodies = root / "bodies"
            bodies.mkdir()
            entry = b"<!doctype html><script>window.entry = true;</script>"
            dependency = b"body { color: black; }"
            entry_hash = hashlib.sha256(entry).hexdigest()
            dependency_hash = hashlib.sha256(dependency).hexdigest()
            (bodies / entry_hash).write_bytes(entry)
            (bodies / dependency_hash).write_bytes(dependency)
            manifest = {
                "entries": [{
                    "source": "source-entry",
                    "body": entry_hash,
                    "references": [{
                        "path": "/web/site.css",
                        "rev": "abc123",
                        "body": dependency_hash
                    }],
                    "direct_dependencies_complete": True
                }],
                "routes": [{
                    "path": "/web/site.css",
                    "rev": "abc123",
                    "body": dependency_hash
                }],
                "conflicts": []
            }
            (root / "routes.json").write_text(json.dumps(manifest))
            server = LocalServer(0, root / "save.sqlite", web_root=root,
                                 web_entry="source-entry")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                def request(path):
                    conn = http.client.HTTPConnection(
                        *server.server_address, timeout=5)
                    conn.request("GET", path)
                    response = conn.getresponse()
                    result = response.status, response.read(), dict(response.getheaders())
                    conn.close()
                    return result
                status, data, headers = request("/web/index.html?time=123")
                self.assertEqual((status, data), (200, entry))
                self.assertIn("'unsafe-eval'", headers["Content-Security-Policy"])
                self.assertIn("img-src 'self' data: blob:;",
                              headers["Content-Security-Policy"])
                self.assertIn("connect-src 'self';",
                              headers["Content-Security-Policy"])
                status, data, _ = request("/web/site.css")
                self.assertEqual((status, data), (200, dependency))
                status, data, _ = request("/web/site.css?t=1")
                self.assertEqual((status, data), (200, dependency))
                override = root / "local_overrides" / "web" / "site.css"
                override.parent.mkdir(parents=True)
                override.write_bytes(b"override")
                status, data, _ = request("/web/site.css")
                self.assertEqual((status, data), (200, b"override"))
                status, data, _ = request("/web//web/site.css")
                self.assertEqual((status, data), (200, b"override"))
                self.assertEqual(request("//web///web/site.css")[0], 200)
                self.assertEqual(request("/web/missing.css")[0], 404)

                entry_override = (
                    root / "local_overrides" / "web" / "index.html"
                )
                entry_override.write_bytes(b"entry-override")
                status, data, _ = request("/web/index.html?time=123")
                self.assertEqual((status, data), (200, b"entry-override"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

    def test_battle_skip_fills_empty_body_and_default_deck(self):
        received = []

        class StubBattleHandler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                received.append(json.loads(self.rfile.read(length) or b"{}"))
                payload = json.dumps({
                    "resultCode": "success",
                    "userCardList": [],
                    "userKnightmareFrameList": [],
                }).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        class AccountPageStub:
            def page_payload(self):
                return b"{}"

        from deck_store import DeckStore
        upstream = ThreadingHTTPServer(("127.0.0.1", 0), StubBattleHandler)
        upstream_thread = threading.Thread(
            target=upstream.serve_forever, daemon=True)
        upstream_thread.start()
        with tempfile.TemporaryDirectory() as root:
            decks = DeckStore(Path(root) / "decks.sqlite")
            decks.save(
                "local-account", "MAIN1",
                [{"userCardId": "card-a",
                  "userKnightmareFrameId": "kmf-a"}] )
            server = LocalServer(
                0, Path(root) / "save.sqlite", decks=decks,
                gacha_upstream="http://127.0.0.1:%d"
                               % upstream.server_address[1])
            server.new_account_page = AccountPageStub()
            thread = threading.Thread(
                target=server.serve_forever, daemon=True)
            thread.start()
            try:
                conn = http.client.HTTPConnection(
                    *server.server_address, timeout=5)
                conn.request("POST", "/api/battle/skip",
                             headers={"X-Request-Id": "skip-default"})
                response = conn.getresponse()
                self.assertEqual(response.status, 200)
                response.read()
                conn.close()
                self.assertEqual(received[0]["deckType"], "MAIN1")
                self.assertEqual(received[0]["userCardIdList"], ["card-a"])
                self.assertEqual(
                    received[0]["userKnightmareFrameIdList"], ["kmf-a"])
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
        upstream.shutdown()
        upstream.server_close()
        upstream_thread.join()

    def test_gacha_routes_forward_only_to_local_upstream(self):
        received = []

        class StubGachaHandler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length)
                received.append((self.path, body))
                payload = json.dumps({
                    "resultCode": "success",
                    "path": self.path,
                    "request": json.loads(body),
                }).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        upstream = ThreadingHTTPServer(("127.0.0.1", 0), StubGachaHandler)
        upstream_thread = threading.Thread(
            target=upstream.serve_forever, daemon=True
        )
        upstream_thread.start()

        with tempfile.TemporaryDirectory() as root:
            server = LocalServer(
                0,
                Path(root) / "save.sqlite",
                gacha_upstream="http://127.0.0.1:%d" % upstream.server_address[1],
            )
            server.new_account_page = object()
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                def request(path, body):
                    conn = http.client.HTTPConnection(
                        *server.server_address, timeout=5
                    )
                    conn.request(
                        "POST",
                        path,
                        body,
                        {
                            "Content-Type": "application/json",
                            "X-Web-Session-Id": "12345",
                        },
                    )
                    response = conn.getresponse()
                    result = response.status, json.loads(response.read())
                    conn.close()
                    return result

                draw_body = json.dumps({
                    "gachaScheduleId": 1005,
                    "gachaBeanKind": "RARE10",
                })
                status, data = request("/api/gacha/draw", draw_body)
                self.assertEqual(status, 200)
                self.assertEqual(data["path"], "/api/gacha/draw")
                self.assertEqual(data["request"]["gachaBeanKind"], "RARE10")

                probability_body = json.dumps({"gachaScheduleId": 1005})
                status, data = request(
                    "/api/gacha/probability", probability_body
                )
                self.assertEqual(status, 200)
                self.assertEqual(data["path"], "/api/gacha/probability")
                status, data = request(
                    "/api/page/PresentList",
                    json.dumps({"page": 1}),
                )
                self.assertEqual(status, 200)
                self.assertEqual(data["path"], "/api/page/PresentList")
                status, data = request(
                    "/api/present/receive",
                    json.dumps({"presentIds": ["present-1"]}),
                )
                self.assertEqual(status, 200)
                self.assertEqual(data["path"], "/api/present/receive")
                status, data = request(
                    "/api/gacha/selectCard",
                    json.dumps({
                        "gachaScheduleId": 1796,
                        "cardIds": [101011, 101053],
                    }),
                )
                self.assertEqual(status, 200)
                self.assertEqual(data["path"], "/api/gacha/selectCard")
                status, data = request(
                    "/api/gacha/exchange",
                    json.dumps({
                        "gachaExchangeId": 1638,
                        "num": 1,
                    }),
                )
                self.assertEqual(status, 200)
                self.assertEqual(data["path"], "/api/gacha/exchange")
                status, data = request(
                    "/api/challenge/receive/all", "{}")
                self.assertEqual(status, 200)
                self.assertEqual(data["path"], "/api/local/missions/claim")
                self.assertEqual(data["request"], {"scope": "normal"})
                status, data = request("/api/shop/buy", json.dumps({
                    "shopId": 99001,
                    "shopItemId": 990001,
                    "num": 1,
                }))
                self.assertEqual(status, 200)
                self.assertEqual(data["path"], "/api/shop/buy")
                self.assertEqual(len(received), 8)

                # Non-gacha POSTs still require the local session token.
                self.assertEqual(
                    request("/api/claim", json.dumps({"product": "x"}))[0],
                    403,
                )
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
        upstream.shutdown()
        upstream.server_close()
        upstream_thread.join()

    def test_gacha_upstream_failure_returns_502(self):
        with tempfile.TemporaryDirectory() as root:
            server = LocalServer(
                0,
                Path(root) / "save.sqlite",
                gacha_upstream="http://127.0.0.1:1",
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                conn = http.client.HTTPConnection(
                    *server.server_address, timeout=5
                )
                conn.request(
                    "POST",
                    "/api/gacha/probability",
                    json.dumps({"gachaScheduleId": 1005}),
                    {"Content-Type": "application/json"},
                )
                response = conn.getresponse()
                self.assertEqual(response.status, 502)
                self.assertEqual(
                    json.loads(response.read())["resultCode"], "error"
                )
                conn.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

    def test_card_progression_routes_forward_with_request_id(self):
        received = []

        class StubProgressionHandler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length)
                received.append((
                    self.path,
                    self.headers.get("X-Request-Id"),
                    json.loads(body),
                ))
                payload = json.dumps({
                    "resultCode": "success",
                    "path": self.path,
                }).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        upstream = ThreadingHTTPServer(("127.0.0.1", 0), StubProgressionHandler)
        upstream_thread = threading.Thread(
            target=upstream.serve_forever, daemon=True
        )
        upstream_thread.start()
        with tempfile.TemporaryDirectory() as root:
            server = LocalServer(
                0,
                Path(root) / "save.sqlite",
                gacha_upstream="http://127.0.0.1:%d" % upstream.server_address[1],
            )
            server.new_account_page = object()
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                def request(path, body, request_id="req-1"):
                    conn = http.client.HTTPConnection(
                        *server.server_address, timeout=5
                    )
                    headers = {
                        "Content-Type": "application/json",
                        "X-Web-Session-Id": "test-session",
                    }
                    if request_id is not None:
                        headers["X-Request-Id"] = request_id
                    conn.request("POST", path, json.dumps(body), headers)
                    response = conn.getresponse()
                    result = response.status, json.loads(response.read())
                    conn.close()
                    return result

                status, data = request(
                    "/api/card/enforce/experience",
                    {"userCardId": "card", "useItem": {"EXP": 1}},
                    "exp-1",
                )
                self.assertEqual((status, data["path"]),
                                 (200, "/api/card/enforce/experience"))
                status, data = request(
                    "/api/card/enforce/bonds",
                    {"userCardId": "card", "useItem": {"TRUST_EXP": 1}},
                    "bonds-1",
                )
                self.assertEqual((status, data["path"]),
                                 (200, "/api/card/enforce/bonds"))
                status, data = request(
                    "/api/card/enforce/revision",
                    {"userCardId": "card"},
                    "revision-1",
                )
                self.assertEqual((status, data["path"]),
                                 (200, "/api/card/enforce/revision"))
                status, data = request(
                    "/api/card/enforce/feature",
                    {"userCardId": "card", "cardFeatureId": 700001},
                    "feature-1",
                )
                self.assertEqual((status, data["path"]),
                                 (200, "/api/card/enforce/feature"))
                status, data = request(
                    "/api/knightmareFrameCustomize/enforce/revision",
                    {"userKnightmareFrameCustomizeId": "kmf-weapon"},
                    "kmf-revision-1",
                )
                self.assertEqual(
                    (status, data["path"]),
                    (200, "/api/knightmareFrameCustomize/enforce/revision"),
                )
                status, data = request(
                    "/api/knightmareFrame/color",
                    {
                        "userKnightmareFrameId": "kmf",
                        "customColorR": 12,
                        "customColorG": 34,
                        "customColorB": 56,
                    },
                    None,
                )
                self.assertEqual((status, data["path"]),
                                 (200, "/api/knightmareFrame/color"))
                status, data = request(
                    "/api/card/costume/dressUp",
                    {"userCardId": "card", "costumeId": 103008},
                    None,
                )
                self.assertEqual((status, data["path"]),
                                 (200, "/api/card/costume/dressUp"))
                status, data = request(
                    "/api/knightmareFrame/development/start",
                    {"frameNo": 1, "knightmareFrameId": 2602},
                    None,
                )
                self.assertEqual((status, data["path"]),
                                 (200, "/api/knightmareFrame/development/start"))
                status, data = request(
                    "/api/knightmareFrame/dismantle",
                    {"userKnightmareFrameIdList": ["kmf"]},
                    None,
                )
                self.assertEqual((status, data["path"]),
                                 (200, "/api/knightmareFrame/dismantle"))
                status, data = request(
                    "/api/knightmareFrame/carryIn",
                    {"userKnightmareFrameIdList": ["kmf"]},
                    None,
                )
                self.assertEqual((status, data["path"]),
                                 (200, "/api/knightmareFrame/carryIn"))
                self.assertEqual(
                    [row[:2] for row in received],
                    [("/api/card/enforce/experience", "exp-1"),
                     ("/api/card/enforce/bonds", "bonds-1"),
                     ("/api/card/enforce/revision", "revision-1"),
                     ("/api/card/enforce/feature", "feature-1"),
                     ("/api/knightmareFrameCustomize/enforce/revision",
                      "kmf-revision-1"),
                     ("/api/knightmareFrame/color", None),
                     ("/api/card/costume/dressUp", None),
                     ("/api/knightmareFrame/development/start", None),
                     ("/api/knightmareFrame/dismantle", None),
                     ("/api/knightmareFrame/carryIn", None)],
                )
                self.assertEqual(received[0][2]["useItem"], {"EXP": 1})
                self.assertEqual(received[3][2]["cardFeatureId"], 700001)
                self.assertEqual(received[4][2][
                    "userKnightmareFrameCustomizeId"], "kmf-weapon")
                self.assertEqual(received[5][2]["customColorG"], 34)
                self.assertEqual(received[6][2]["costumeId"], 103008)
                self.assertEqual(received[7][2]["frameNo"], 1)
                self.assertEqual(
                    received[8][2]["userKnightmareFrameIdList"], ["kmf"])
                self.assertEqual(
                    received[9][2]["userKnightmareFrameIdList"], ["kmf"])
                self.assertEqual(
                    request(
                        "/api/card/enforce/experience",
                        {"userCardId": "card", "useItem": {"EXP": 1}},
                        None,
                    )[0],
                    400,
                )
                self.assertEqual(len(received), 10)
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
        upstream.shutdown()
        upstream.server_close()
        upstream_thread.join()

    def test_page_routes_accept_loopback_without_stale_session(self):
        class StubPages:
            def resolve(self, path):
                return {"resultCode": "success", "path": path}

        with tempfile.TemporaryDirectory() as root:
            server = LocalServer(
                0,
                Path(root) / "save.sqlite",
                gacha_pages=StubPages(),
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                def get(path, headers=None):
                    conn = http.client.HTTPConnection(
                        *server.server_address, timeout=5
                    )
                    conn.request("GET", path, headers=headers or {})
                    response = conn.getresponse()
                    result = response.status, response.read()
                    conn.close()
                    return result

                status, data = get(
                    "/api/page/TopPage", {"X-Web-Session-Id": "game-session"}
                )
                self.assertEqual(status, 200)
                self.assertEqual(json.loads(data)["path"], "/api/page/TopPage")

                status, data = get(
                    "/api/page/TopPage", {"X-Offline-Token": "\xe9"}
                )
                self.assertEqual(status, 200)
                self.assertEqual(json.loads(data)["path"], "/api/page/TopPage")

                status, _ = get(
                    "/local/account", {"X-Offline-Token": "\xe9"}
                )
                self.assertEqual(status, 403)

                for page in ("ComposePilot", "ComposeKmf"):
                    path = "/api/page/" + page
                    self.assertEqual(get(path)[0], 200)
                    status, data = get(path + "?value=userCardList&timeStamp=1",
                                       {"X-Web-Session-Id": "game-session"})
                    self.assertEqual(status, 200)
                    self.assertEqual(json.loads(data)["path"], path)

                for page in (
                        "ComposeTop", "ComposePilot", "ComposeKmf",
                        "KmfDevelopment", "KmfDismantle", "KmfColoring",
                        "CarryingTop"):
                    path = "/api/page/" + page
                    status, data = get(path)
                    self.assertEqual(status, 200)
                    self.assertEqual(json.loads(data)["path"], path)

                host = "localhost:%d" % server.server_address[1]
                status, data = get(
                    "/api/page/ComposeTop", {"Host": host})
                self.assertEqual(status, 200)

                self.assertEqual(get("/api/page/GachaTop")[0], 200)

                status, data = get("/api/state")
                token = json.loads(data)["token"]
                status, data = get(
                    "/api/page/MyPage", {"X-Offline-Token": token}
                )
                self.assertEqual(status, 200)
                self.assertEqual(json.loads(data)["path"], "/api/page/MyPage")
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

    def test_deck_page_and_save_use_loopback_save(self):
        from deck_store import DeckStore
        class StubDecks(DeckStore):
            def __init__(self, database):
                super().__init__(database)
                self.saved = None

            def page_payload(self, account, models, extra_user_cards=(), extra_user_kmfs=()):
                return {"resultCode": "success", "userDeckList": [{"deckType": "MAIN1"}]}

            def save(self, account, deck_type, slots, name=None,
                     owned_cards=None, owned_kmfs=None, **kwargs):
                self.saved = (account, deck_type, slots, name)
                return super().save(account, deck_type, slots, name, owned_cards, owned_kmfs, **kwargs)

        with tempfile.TemporaryDirectory() as root:
            decks = StubDecks(Path(root) / "decks.sqlite")
            server = LocalServer(
                0,
                Path(root) / "save.sqlite",
                decks=decks,
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                def request(method, path, body=None, headers=None):
                    conn = http.client.HTTPConnection(
                        *server.server_address, timeout=5
                    )
                    conn.request(method, path, body, headers or {})
                    response = conn.getresponse()
                    result = response.status, response.read()
                    conn.close()
                    return result

                headers = {"X-Web-Session-Id": "game-session"}
                status, data = request(
                    "GET", "/api/page/DeckFormation", headers=headers
                )
                self.assertEqual(status, 200)
                self.assertEqual(
                    json.loads(data)["userDeckList"][0]["deckType"], "MAIN1"
                )
                self.assertEqual(
                    request("GET", "/api/page/DeckFormation")[0], 200
                )

                body = json.dumps({
                    "deckType": "MAIN1",
                    "name": "Main",
                    "slots": [{
                        "userCardId": "card-a",
                        "userKnightmareFrameId": "kmf-a",
                    }],
                })
                post_headers = {
                    **headers,
                    "Content-Type": "application/json",
                }
                status, data = request(
                    "POST", "/api/deck/save", body, post_headers
                )
                self.assertEqual(status, 200)
                self.assertEqual(json.loads(data)["resultCode"], "success")
                self.assertEqual(decks.saved[1], "MAIN1")
                self.assertEqual(decks.saved[2][0]["userCardId"], "card-a")
                native_body = json.dumps({"deckType": "MAIN1",
                    "userCardIdList": ["card-a", "", "card-b"],
                    "userKnightmareFrameIdList": ["kmf-a", "", "kmf-b"]})
                status, data = request("POST", "/api/deck/save", native_body, post_headers)
                self.assertEqual(status, 200)
                saved = json.loads(data)["userDeckList"][0]
                self.assertEqual(saved["userCardId3"], "card-b")
                self.assertIsNone(decks.saved[2][1])
                status, _ = request("POST", "/api/deck/save", json.dumps({
                    "deckType": "MAIN1", "userCardIdList": ["card-a"],
                    "userKnightmareFrameIdList": []}), post_headers)
                self.assertEqual(status, 400)
                self.assertEqual(
                    request(
                        "POST",
                        "/api/deck/save",
                        body,
                        {"Content-Type": "application/json"},
                    )[0],
                    200,
                )
            finally:
                server.shutdown()
                server.server_close()
                thread.join()


    def test_story_end_routes_with_session_and_returns_story_models(self):
        received = []

        class StoryHandler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length)
                received.append((self.path, body))
                payload = json.dumps({
                    "resultCode": "success",
                    "userQuestList": [{
                        "questId": 101003,
                        "questStatus": "CLEARED",
                    }],
                }).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        class AccountsStub:
            def state(self, _account):
                return {
                    "gameUser": {"userId": "local-user"},
                    "userItemList": [],
                    "userStatusList": [],
                    "userStoryList": [{
                        "questId": 101003,
                        "questStatus": "CLEARED",
                    }],
                }

        upstream = ThreadingHTTPServer(("127.0.0.1", 0), StoryHandler)
        upstream_thread = threading.Thread(
            target=upstream.serve_forever, daemon=True)
        upstream_thread.start()
        with tempfile.TemporaryDirectory() as root:
            server = LocalServer(
                0,
                Path(root) / "save.sqlite",
                gacha_upstream="http://127.0.0.1:%d" % upstream.server_address[1],
            )
            server.new_account_page = object()
            server.accounts = AccountsStub()
            server.account = "local-user"
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                conn = http.client.HTTPConnection(
                    *server.server_address, timeout=5)
                body = json.dumps({"questId": 101003})
                conn.request(
                    "POST",
                    "/api/quest/story/end",
                    body,
                    {
                        "Content-Type": "application/json",
                        "X-Web-Session-Id": "story-session",
                    },
                )
                response = conn.getresponse()
                self.assertEqual(response.status, 200)
                result = json.loads(response.read())
                conn.close()
                self.assertEqual(
                    received, [("/api/quest/story/end", body.encode())])
                self.assertEqual(
                    result["userQuestList"][0]["questStatus"], "CLEARED")
                self.assertEqual(
                    result["userStoryList"][0]["questId"], 101003)
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
        upstream.shutdown()
        upstream.server_close()
        upstream_thread.join()

if __name__ == "__main__":
    unittest.main()
