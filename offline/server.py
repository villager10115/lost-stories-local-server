"""Loopback-only shop prototype.

Only explicitly supported game operations are forwarded to another loopback
service. No official server is contacted by this process.
"""
import argparse
import json
import os
import re
import secrets
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from shop import PRODUCTS, Shop
from account_store import AccountStore
from account_page import AccountPage
from asset_store import AssetStore
from deck_store import DeckStore, DeckStoreError, DEFAULT_DECKS, _flatten_deck
from gacha_pages import GachaPageStore
from native_catalog_store import NativeCatalogStore
from new_account_page import NewAccountPage
from pilot_image_store import PilotImageStore
from preserved_pages import GENERIC_PAGE_PATHS, PreservedPageStore
from preserved_web import PreservedWebStore
from raw_media_store import RawMediaStore
from web_store import WebStore


WEB_CONTENT_SECURITY_POLICY = (
    "default-src 'none'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
    "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
    "font-src 'self' data:; connect-src 'self'; media-src 'self'; "
    "object-src 'none'; frame-src 'none'; frame-ancestors 'none'; "
    "base-uri 'self'; form-action 'none'"
)


def debug(message):
    if os.environ.get("CGLS_DEBUG"):
        print("[local-server] " + message, file=sys.stderr, flush=True)


def token_matches(provided, expected):
    """Compare ASCII session tokens without raising on malformed headers."""
    return (isinstance(provided, str) and isinstance(expected, str)
            and provided.isascii() and expected.isascii()
            and secrets.compare_digest(provided, expected))


def normalize_request_path(target):
    """Collapse accidental duplicate web prefixes without widening routes."""
    path, separator, query = target.partition("?")
    path = re.sub(r"/+", "/", path)
    path = re.sub(r"^/web(?:/web)+(?=/|$)", "/web", path,
                   count=1, flags=re.IGNORECASE)
    return path + (separator + query if separator else "")

LOCAL_PAGE_PATHS = frozenset({
    "/api/page/TopPage",
    "/api/page/MyPage",
    "/api/page/GachaTop",
    "/api/page/GachaAnimation",
    "/api/page/GachaResult",
    "/api/page/MissionTop",
    "/api/page/MainStoryTop",
    "/api/page/QuestBackground",
    "/api/page/QuestResult",
    "/api/page/QuestTop",
    "/api/page/DailyQuestTop",
    "/api/page/RootEntangleTop",
    "/api/page/EventStoryTop",
    "/api/page/ChallengeQuestTop",
    "/api/page/ExpeditionTop",
    "/api/page/AnotherQuestTop",
    "/api/page/SideQuestTop",
    "/api/page/EventMultiFrontTop",
    "/api/page/EventHighStrategicCommandTop",
    "/api/page/ComposeTop",
    "/api/page/ShopTop",
    "/api/page/GameConfig",
    "/api/page/GuildTop",
}) | GENERIC_PAGE_PATHS

PRESENT_PROXY_PATHS = frozenset({
    "/api/page/PresentList",
    "/api/page/PresentHistory",
    "/api/present/receive",
    "/api/present/receive/all",
})

CHALLENGE_RECEIVE_PATHS = {
    "/challenge/daily/receive": "daily",
    "/challenge/daily/receive/all": "daily",
    "/challenge/weekly/receive": "weekly",
    "/challenge/weekly/receive/all": "weekly",
    "/challenge/total/receive": "total",
    "/challenge/total/receive/all": "total",
    "/challenge/beginner/receive": "beginner",
    "/challenge/beginner/receive/all": "beginner",
    "/challenge/limited/receive": "limited",
    "/challenge/limited/receive/all": "limited",
    "/challenge/side/total/receive": "side",
    "/challenge/side/total/receive/all": "side",
    "/challenge/entangle/total/receive": "entangle",
    "/challenge/entangle/total/receive/all": "entangle",
    "/challenge/receive/all": "normal",
}
CHALLENGE_RECEIVE_PATHS.update({
    "/api" + path: scope for path, scope in list(CHALLENGE_RECEIVE_PATHS.items())
})


def _merge_rows_by_id(models, rows, key):
    index = {row.get(key): row for row in models if row.get(key)}
    return [{**index.get(row.get(key), {}), **row}
            for row in rows if row.get(key)]


def merge_battle_response_models(result, models, target_path):
    """Keep battle responses scoped to the actual formation, not all saves."""
    result["gameUser"] = models.get("gameUser", {})
    cards = result.get("userCardList")
    if isinstance(cards, list):
        result["userCardList"] = _merge_rows_by_id(
            models.get("userCardList", []), cards, "userCardId")

    if target_path == "/api/battle/start":
        player_data = result.get("battle", {}).get("playerData", {})
        kmf_ids = [row.get("userKnightmareId") for row in
                   player_data.get("pilotStatusData", [])
                   if row.get("userKnightmareId")]
        if kmf_ids:
            rows = result.get("userKnightmareFrameList") or [
                {"userKnightmareFrameId": kmf_id} for kmf_id in kmf_ids]
            result["userKnightmareFrameList"] = _merge_rows_by_id(
                models.get("userKnightmareFrameList", []), rows,
                "userKnightmareFrameId")
    elif isinstance(result.get("userKnightmareFrameList"), list):
        result["userKnightmareFrameList"] = _merge_rows_by_id(
            models.get("userKnightmareFrameList", []),
            result["userKnightmareFrameList"], "userKnightmareFrameId")

    if isinstance(result.get("userKnightmareFrameCustomizeList"), list):
        result["userKnightmareFrameCustomizeList"] = _merge_rows_by_id(
            models.get("userKnightmareFrameCustomizeList", []),
            result["userKnightmareFrameCustomizeList"],
            "userKnightmareFrameCustomizeId")
    else:
        result.pop("userKnightmareFrameCustomizeList", None)
    return result


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port, database, account_database=None, account=None,
                 asset_mapping=None, asset_cache=None, native_catalogs=None,
                 native_hashes=None,
                 web_root=None, web_entry=None, gacha_upstream=None,
                 gacha_static=None, gacha_state_url=None, gacha_pages=None,
                 preserved_pages_cache=None, mission_claims_path=None,
                 deck_database=None, decks=None, masterdata=None, raw_media=None):
        if (asset_mapping is None) != (asset_cache is None):
            raise ValueError("Asset mapping and cache must be specified together")
        if (web_root is None) != (web_entry is None):
            raise ValueError("Web root and entry must be specified together")
        self.assets = AssetStore(asset_mapping, asset_cache) if asset_mapping else None
        self.raw_media = RawMediaStore(raw_media) if raw_media else None
        self.pilot_images = PilotImageStore(self.assets) if self.assets else None
        self.native_catalogs = (
            NativeCatalogStore(native_catalogs, native_hashes)
            if native_catalogs else None
        )
        self.web = WebStore(web_root, web_entry) if web_root else None
        self.preserved_web = (
            PreservedWebStore(preserved_pages_cache)
            if preserved_pages_cache is not None
            else None
        )
        if (account_database is None) != (account is None):
            raise ValueError("Account database and account must be specified together")
        self.accounts = AccountStore(account_database) if account_database else None
        self.account = account
        if self.accounts:
            self.accounts.state(account)  # Fail startup for an unknown account.
        self.new_account_page = None
        if self.accounts:
            self.account_page = AccountPage(self.accounts, account)
        elif masterdata:
            self.new_account_page = NewAccountPage(
                masterdata,
                gacha_state_url
                or "http://127.0.0.1:18766/api/local/page-state",
            )
            self.account_page = self.new_account_page
        else:
            self.account_page = None
        if gacha_pages is not None:
            self.gacha_pages = gacha_pages
        elif self.account_page is not None and gacha_static is not None:
            self.gacha_pages = GachaPageStore(
                self.account_page,
                gacha_static,
                gacha_state_url
                or "http://127.0.0.1:18766/api/local/page-state",
                claim_state_path=mission_claims_path,
            )
        else:
            self.gacha_pages = None
        self.preserved_pages = (
            PreservedPageStore(
                preserved_pages_cache,
                self.account_page,
                claim_state_path=mission_claims_path,
            )
            if preserved_pages_cache is not None and self.account_page is not None
            else None
        )
        self.decks = decks
        if self.decks is None and self.account_page is not None:
            seed_decks = []
            if self.new_account_page is not None:
                seed_decks = self.account_models().get("userDeckList", [])
                by_type = {d["deckType"]: d for d in seed_decks}
                seed_decks = [by_type.get(kind, {"deckType": kind})
                              for kind in DEFAULT_DECKS]
            elif self.preserved_pages is not None:
                seed_decks = (
                    self.preserved_pages.pages.get("/api/page/GameConfig", {})
                    .get("userDeckList")
                    or []
                )
            if deck_database is not None:
                deck_path = Path(deck_database)
            elif account_database is not None:
                deck_path = Path(account_database).with_name("decks.sqlite")
            else:
                deck_path = Path(database).with_name("decks.sqlite")
            self.decks = DeckStore(deck_path, seed_decks)
        if self.new_account_page is not None and self.decks is not None:
            self.decks.reconcile_ownership(self.account or "local-account",
                                            self.account_models())
            self.new_account_page.deck_provider = lambda: [
                _flatten_deck(d["deckType"], d["slots"], d.get("name"),
                              d.get("createdAt"))
                for d in self.decks.list(self.account or "local-account")]
        self.shop = Shop(database)
        self.gacha_upstream = (
            gacha_upstream.rstrip("/") if gacha_upstream else None
        )
        self.token = secrets.token_urlsafe(32)
        self.extra_units_url = None
        if gacha_state_url:
            self.extra_units_url = gacha_state_url.rstrip("/")
            if self.extra_units_url.endswith("/api/local/page-state"):
                self.extra_units_url = (
                    self.extra_units_url[:-len("/page-state")] + "/units"
                )
        super().__init__(("127.0.0.1", port), Handler)

    @property
    def authority(self):
        return "127.0.0.1:%d" % self.server_address[1]

    @property
    def local_authorities(self):
        port = self.server_address[1]
        return frozenset({
            "127.0.0.1:%d" % port,
            "localhost:%d" % port,
        })

    def host_matches(self, value):
        return (value or "").strip().lower() in self.local_authorities

    def origin_matches(self, value):
        if value is None:
            return True
        return value.strip().lower() in {
            "http://" + authority for authority in self.local_authorities
        }


    def account_models(self):
        if self.accounts is not None and self.account is not None:
            return self.accounts.state(self.account)
        if self.new_account_page is not None:
            return json.loads(
                self.new_account_page.page_payload().decode("utf-8")
            )
        return {}

    def default_battle_deck(self, deck_type="MAIN1"):
        if self.decks is None:
            return None
        account = self.account or "local-account"
        deck = next((row for row in self.decks.list(account)
                       if row.get("deckType") == deck_type), None)
        slots = [slot for slot in (deck or {}).get("slots", [])
                 if isinstance(slot, dict)
                 and slot.get("userCardId")
                 and slot.get("userKnightmareFrameId")]
        if not slots:
            return None
        return {
            "deckType": deck_type,
            "userCardIdList": [slot["userCardId"] for slot in slots],
            "userKnightmareFrameIdList": [
                slot["userKnightmareFrameId"] for slot in slots],
        }

    def local_save_status(self):
        if not self.gacha_upstream:
            return None
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({})
        )
        with opener.open(
            self.gacha_upstream + "/api/local/save-status", timeout=2
        ) as response:
            raw = response.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError("Save status response is too large")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("Save status response is not an object")
        return payload

    def extra_units(self):
        if not self.extra_units_url:
            return {}, {}
        try:
            with urllib.request.urlopen(self.extra_units_url, timeout=1.5) as response:
                raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                return {}, {}
            payload = json.loads(raw)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, UnicodeError):
            return {}, {}
        cards = payload.get("userCardList") if isinstance(payload, dict) else None
        kmfs = payload.get("userKnightmareFrameList") if isinstance(payload, dict) else None
        return (
            [item for item in cards if isinstance(item, dict)] if isinstance(cards, list) else [],
            [item for item in kmfs if isinstance(item, dict)] if isinstance(kmfs, list) else [],
        )

    def owned_ids(self):
        if self.account_page is None:
            return None, None
        models = self.account_models()
        extra_cards, extra_kmfs = self.extra_units()
        cards = {
            item.get("userCardId") for item in models.get("userCardList") or []
            if isinstance(item, dict) and item.get("userCardId")
        }
        kmfs = {
            item.get("userKnightmareFrameId")
            for item in models.get("userKnightmareFrameList") or []
            if isinstance(item, dict) and item.get("userKnightmareFrameId")
        }
        cards.update(
            item.get("userCardId") for item in extra_cards
            if item.get("userCardId")
        )
        kmfs.update(
            item.get("userKnightmareFrameId") for item in extra_kmfs
            if item.get("userKnightmareFrameId")
        )
        return cards, kmfs


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Do not log request bodies, session headers or arbitrary URL strings.
        pass

    def respond(self, status, data, content_type="application/json; charset=utf-8",
                csp=None):
        if status >= 400:
            # Failure diagnostics exclude query strings, credentials, bodies and headers.
            from urllib.parse import urlsplit
            try:
                target_path = urlsplit(self.path).path
            except ValueError:
                target_path = '[invalid-target]'
            reason = data.get('error') if isinstance(data, dict) else None
            if reason not in ('Invalid host', 'Invalid origin', 'Invalid local session'):
                reason = None
            print(json.dumps({'event': 'local_http_failure', 'method': self.command,
                              'path': target_path[:1024], 'status': status,
                              'hostMatches': self.server.host_matches(
                                  self.headers.get('Host')),
                              'reason': reason}, ensure_ascii=True), file=sys.stderr, flush=True)
        body = data if isinstance(data, bytes) else json.dumps(data).encode("utf-8")
        debug("respond %s %s %d bytes" % (self.path, status, len(body)))
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", csp or (
                "default-src 'none'; script-src 'self'; connect-src 'self'; "
                "frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
            ))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            # The native WebView routinely cancels stale page loads.
            return

    def allowed_host(self):
        if not self.server.host_matches(self.headers.get("Host")):
            self.respond(403, {"error": "Invalid host"})
            return False
        return True

    def page_session_ok(self):
        token = self.headers.get("X-Offline-Token", "")
        if token_matches(token, self.server.token):
            return True
        # This process owns one configured local save. A stale WebView token
        # from a previous process must not lock the only local player out.
        client = (self.client_address[0] if self.client_address else "")
        return (client in ("127.0.0.1", "::1")
                and self.server.host_matches(self.headers.get("Host")))

    def do_HEAD(self):
        self.path = normalize_request_path(self.path)
        if self.path.startswith("/assets/"):
            # Resource probes must use the same catalog/media/bundle routing
            # as GET; respond() already suppresses the body for HEAD.
            self.do_GET()
        else:
            if self.allowed_host():
                self.respond(404, b"No resource", "text/plain")

    def do_GET(self):
        self.path = normalize_request_path(self.path)
        if not self.allowed_host():
            return
        page_path = self.path.split("?", 1)[0]
        if self.path == "/":
            self.respond(200, (Path(__file__).parent / "shop.html").read_bytes(),
                         "text/html; charset=utf-8")
        elif self.path == "/app.js":
            self.respond(200, (Path(__file__).parent / "app.js").read_bytes(),
                         "text/javascript; charset=utf-8")
        elif self.path.split("?", 1)[0] == "/assets/filelist.json":
            if self.server.raw_media is not None:
                self.respond(*self.server.raw_media.resolve(self.path))
            else:
                self.respond(200, {"Records": []})
        elif self.path.startswith(("/assets/Movie/", "/assets/Sound/")):
            if self.server.raw_media is not None:
                self.respond(*self.server.raw_media.resolve(self.path))
            else:
                self.respond(503, b"No preserved media configured", "text/plain")
        elif self.path.startswith("/assets/"):
            catalog_path = self.path.split("?", 1)[0]
            is_catalog = catalog_path in {
                "/assets/catalog.json", "/assets/Binary_catalog.json", "/assets/Json_catalog.json",
                "/assets/catalog.hash", "/assets/Binary_catalog.hash", "/assets/Json_catalog.hash",
            }
            catalog = (self.server.native_catalogs.resolve(self.path)
                       if self.server.native_catalogs and is_catalog else None)
            if catalog and catalog[0] != 404:
                self.respond(*catalog)
            elif self.server.assets is None:
                self.respond(503, {"error": "No asset cache configured"})
            else:
                self.respond(*self.server.assets.resolve(self.path))
        elif self.path.startswith("/web/image/pilots/"):
            if self.server.pilot_images is None:
                self.respond(503, b"No pilot image cache", "text/plain")
            else:
                self.respond(*self.server.pilot_images.resolve(self.path))
        elif self.path.split("?", 1)[0] == "/web/json/event_banner/event_banner.json":
            self.respond(200, [], "application/json")
        elif page_path == "/web/json/announcement/announcement_digest.json":
            self.respond(200, [], "application/json")
        elif self.path == "/web" or self.path.startswith("/web/"):
            if self.server.web is not None:
                status, body, content_type = self.server.web.resolve(self.path)
                if status in (404, 409):
                    preserved = (
                        self.server.preserved_web.resolve(self.path)
                        if self.server.preserved_web is not None
                        else None
                    )
                    if preserved is not None and preserved[0] == 200:
                        status, body, content_type = preserved
                self.respond(status, body, content_type, WEB_CONTENT_SECURITY_POLICY)
            elif self.server.preserved_web is not None:
                status, body, content_type = self.server.preserved_web.resolve(
                    self.path
                )
                self.respond(status, body, content_type, WEB_CONTENT_SECURITY_POLICY)
            else:
                self.respond(404, {"error": "No staged web client configured"})
        elif page_path in LOCAL_PAGE_PATHS:
            debug("page start " + page_path)
            if not self.page_session_ok():
                self.respond(403, {"error": "Invalid local session"})
            else:
                payload = None
                try:
                    if self.server.gacha_pages is not None:
                        payload = self.server.gacha_pages.resolve(page_path)
                except KeyError:
                    pass
                if payload is None and page_path == "/api/page/DeckFormation" \
                        and self.server.decks is not None:
                    models = self.server.account_models()
                    extra_cards, extra_kmfs = self.server.extra_units()
                    payload = self.server.decks.page_payload(
                        self.server.account or "local-account",
                        models,
                        extra_user_cards=extra_cards,
                        extra_user_kmfs=extra_kmfs,
                    )
                if payload is None and self.server.preserved_pages is not None:
                    try:
                        payload = self.server.preserved_pages.resolve(page_path)
                    except KeyError:
                        pass
                    if isinstance(payload, tuple):
                        self.respond(*payload)
                        return
                if payload is None and page_path in ("/api/page/QuestBackground", "/api/page/QuestResult"):
                    models = self.server.account_models()
                    if self.server.new_account_page:
                        static = json.loads((self.server.new_account_page.masterdata_directory /
                                             'pages/DailyQuestTop.static.json').read_text('utf8'))
                        models['npcList'] = static['npcList']
                    payload = self.server.decks.page_payload(
                        self.server.account or "local-account", models,
                    ) if self.server.decks else models
                if payload is None and page_path in (
                        "/api/page/MyPage",
                        "/api/page/MainStoryTop",
                        "/api/page/RootEntangleTop",
                        "/api/page/EventStoryTop",
                        "/api/page/ChallengeQuestTop",
                        "/api/page/ExpeditionTop",
                        "/api/page/AnotherQuestTop",
                        "/api/page/SideQuestTop",
                        "/api/page/EventMultiFrontTop",
                        "/api/page/EventHighStrategicCommandTop",
                ) \
                        and self.server.account_page:
                    self.respond(*self.server.account_page.resolve(self.path))
                    return
                if payload is None:
                    self.respond(404, {"error": "Unsupported local page"})
                else:
                    debug("page resolved " + page_path)
                    self.respond(200, payload)
        elif page_path == "/api/local/save-status":
            if not self.page_session_ok():
                self.respond(403, {"error": "Invalid local session"})
                return
            try:
                payload = self.server.local_save_status()
            except (urllib.error.URLError, TimeoutError, OSError,
                    ValueError, UnicodeError):
                self.respond(503, {"error": "Local save status unavailable"})
                return
            if payload is None:
                self.respond(503, {"error": "Local save status unavailable"})
            else:
                self.respond(200, payload)
        elif self.path == "/local/account":
            if not token_matches(
                    self.headers.get("X-Offline-Token", ""),
                    self.server.token):
                self.respond(403, {"error": "Invalid local session"})
            elif self.server.accounts is None:
                self.respond(503, {"error": "No local account configured"})
            else:
                self.respond(200, {"local": True, "complete_save": False,
                                   "models": self.server.accounts.state(self.server.account)})
        elif self.path == "/api/state":
            self.respond(200, {"offline": True, "prototype": True,
                               "token": self.server.token, "products": PRODUCTS,
                               "inventory": self.server.shop.inventory()})
        else:
            self.respond(404, {"error": "Not implemented; no upstream forwarding"})

    def complete_skip_payload(self, raw_body):
        try:
            payload = json.loads(raw_body or b"{}")
        except (ValueError, UnicodeError) as exc:
            raise ValueError("Invalid battle skip JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("Battle skip body must be an object")
        deck_type = payload.get("deckType") or "MAIN1"
        payload["deckType"] = deck_type
        if not payload.get("userCardIdList") and not payload.get(
                "userKnightmareFrameIdList"):
            default_deck = self.server.default_battle_deck(deck_type)
            if default_deck is not None:
                payload["userCardIdList"] = default_deck[
                    "userCardIdList"]
                payload["userKnightmareFrameIdList"] = default_deck[
                    "userKnightmareFrameIdList"]
        return json.dumps(payload, separators=(",", ":")).encode("utf-8")

    def do_POST(self):
        self.path = normalize_request_path(self.path)
        bootstrap_path = self.path.split("?", 1)[0]
        if bootstrap_path in (
            "/api/user/create",
            "/api/system/logger",
            "/api/money/init",
        ):
            if not self.allowed_host():
                return
            lengths = self.headers.get_all("Content-Length", [])
            if lengths:
                try:
                    length = int(lengths[0])
                    if 0 < length <= 4096:
                        self.rfile.read(length)
                except ValueError:
                    pass
            if bootstrap_path == "/api/user/create":
                self.respond(200, {
                    "resultCode": "success",
                    "user": {
                        "id": "local-user",
                        "snsUserId": "local-sns-user",
                    },
                })
            else:
                self.respond(200, {"resultCode": "success"})
            return
        # Consume a bounded body before rejecting credentials. Closing with unread
        # bytes can reset a Windows socket and discard the rejection response.
        # Never drain unlimited or ambiguously framed input.
        try:
            lengths = self.headers.get_all("Content-Length", [])
            if (self.headers.get("Transfer-Encoding") is not None
                    or len(lengths) != 1 or not lengths[0].isascii()
                    or not lengths[0].isdecimal()):
                raise ValueError("Invalid framing")
            length = int(lengths[0])
            batch_path = bootstrap_path in {
                "/api/knightmareFrame/dismantle",
                "/api/knightmareFrame/carryIn",
                "/api/knightmareFrame/carryOut",
            }
            limit = 32768 if (
                bootstrap_path == "/api/deck/saveList" or batch_path
            ) else 4096
            if length == 0:
                if bootstrap_path != "/api/battle/skip":
                    raise ValueError("Invalid body length")
                raw_body = b"{}"
            else:
                if length > limit:
                    raise ValueError("Invalid body length")
                self.connection.settimeout(5)
                raw_body = self.rfile.read(length)
                if len(raw_body) != length:
                    raise ValueError("Incomplete body")
        except ValueError:
            self.respond(400, {"error": "Expected bounded JSON"})
            return
        except TimeoutError:
            self.respond(408, {"error": "Body timeout"})
            return
        if not self.allowed_host():
            return
        origin = self.headers.get("Origin")
        if not self.server.origin_matches(origin):
            self.respond(403, {"error": "Invalid origin"})
            return
        from formation_routes import handle as handle_formation
        if handle_formation(self, bootstrap_path, raw_body):
            return
        if self.path.split("?", 1)[0] == "/api/deck/save":
            if not self.page_session_ok():
                self.respond(403, {"error": "Invalid local session"})
                return
            if self.server.decks is None:
                self.respond(503, {"error": "No local deck store configured"})
                return
            if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() \
                    != "application/json":
                self.respond(400, {"error": "Expected JSON"})
                return
            try:
                payload = json.loads(raw_body)
                if not isinstance(payload, dict):
                    raise ValueError("Expected object")
                owned_cards, owned_kmfs = self.server.owned_ids()
                slots = payload.get("slots")
                if "userCardIdList" in payload or "userKnightmareFrameIdList" in payload:
                    cards = payload.get("userCardIdList")
                    kmfs = payload.get("userKnightmareFrameIdList")
                    if (not isinstance(cards, list) or not isinstance(kmfs, list)
                            or len(cards) != len(kmfs) or not 1 <= len(cards) <= 10):
                        raise DeckStoreError("Expected paired pilot/KMF arrays")
                    if "slots" in payload:
                        raise DeckStoreError("Ambiguous deck format")
                    slots = [None if c in (None, "") and k in (None, "")
                             else {"userCardId": c, "userKnightmareFrameId": k}
                             for c, k in zip(cards, kmfs)]
                deck = self.server.decks.save(
                    self.server.account or "local-account",
                    payload.get("deckType"),
                    slots,
                    name=payload.get("name"),
                    owned_cards=owned_cards,
                    owned_kmfs=owned_kmfs,
                )
            except DeckStoreError as exc:
                self.respond(400, {
                    "resultCode": "error",
                    "title": "編成エラー",
                    "errorTxt": str(exc),
                })
            except (ValueError, TypeError, UnicodeError):
                self.respond(400, {
                    "resultCode": "error",
                    "title": "編成エラー",
                    "errorTxt": "編成データを読み込めませんでした。",
                })
            else:
                models = self.server.account_models()
                saved = _flatten_deck(deck["deckType"], deck["slots"],
                                      deck.get("name"), deck.get("createdAt"))
                self.respond(200, {"resultCode": "success", "deck": deck,
                    "userDeckList": [saved],
                    "userCardList": models.get("userCardList", []),
                    "userKnightmareFrameList": models.get("userKnightmareFrameList", [])})
            return
        if self.path.split("?", 1)[0] in (
            "/api/gacha/draw",
            "/api/gacha/probability",
            "/api/gacha/selectCard",
            "/api/gacha/exchange",
        ):
            self.forward_gacha(raw_body)
            return
        if bootstrap_path in PRESENT_PROXY_PATHS:
            if not self.page_session_ok():
                self.respond(403, {"error": "Invalid local session"})
                return
            if self.headers.get("Content-Type", "").split(
                    ";", 1)[0].strip().lower() != "application/json":
                self.respond(400, {"error": "Expected JSON"})
                return
            self.forward_gacha(raw_body, target_path=bootstrap_path)
            return
        if bootstrap_path in (
            "/api/battle/start",
            "/api/battle/end",
            "/api/battle/skip",
            "/api/local/battle/retire",
        ):
            if not self.page_session_ok():
                self.respond(403, {"error": "Invalid local session"})
                return
            if self.server.new_account_page is None:
                self.respond(503, {"resultCode": "error", "errorTxt": "Local battle account is unavailable"})
                return
            forward_body = raw_body
            if bootstrap_path == "/api/battle/skip":
                try:
                    forward_body = self.complete_skip_payload(raw_body)
                except ValueError:
                    self.respond(400, {"error": "Expected JSON"})
                    return
            elif self.headers.get("Content-Type", "").split(
                    ";", 1)[0].strip().lower() != "application/json":
                self.respond(400, {"error": "Expected JSON"})
                return
            self.forward_gacha(forward_body, target_path=bootstrap_path,
                               preserve_request_id="X-Request-Id" in self.headers)
            return
        if bootstrap_path == "/api/quest/story/end":
            if not self.page_session_ok():
                self.respond(403, {"error": "Invalid local session"})
                return
            if self.server.new_account_page is None:
                self.respond(503, {"resultCode": "error",
                    "errorTxt": "Local story account is unavailable"})
                return
            if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
                self.respond(400, {"error": "Expected JSON"})
                return
            self.forward_gacha(raw_body, target_path=bootstrap_path)
            return
        if bootstrap_path == "/api/shop/buy":
            if not self.page_session_ok():
                self.respond(403, {"error": "Invalid local session"})
                return
            if self.server.new_account_page is None:
                self.respond(503, {"resultCode": "error",
                    "errorTxt": "Local shop account is unavailable"})
                return
            if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
                self.respond(400, {"error": "Expected JSON"})
                return
            self.forward_gacha(raw_body, target_path=bootstrap_path)
            return
        if bootstrap_path in (
            "/api/card/enforce/limitBreak",
            "/api/card/enforce/experience",
            "/api/card/enforce/bonds",
            "/api/card/enforce/revision",
            "/api/card/enforce/feature",
            "/api/knightmareFrameCustomize/enforce/revision",
        ):
            if not self.page_session_ok():
                self.respond(403, {"error": "Invalid local session"})
                return
            if self.server.new_account_page is None:
                self.respond(503, {"resultCode": "error",
                    "errorTxt": "Card progression requires a local stateful account"})
                return
            if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
                self.respond(400, {"error": "Expected JSON"})
                return
            self.forward_gacha(raw_body, target_path=bootstrap_path,
                               preserve_request_id=True)
            return
        if bootstrap_path in (
            "/api/local/kmf/storage",
            "/api/local/kmf/color",
            "/api/knightmareFrame/development/start",
            "/api/knightmareFrame/development/skip",
            "/api/knightmareFrame/development/receive",
            "/api/knightmareFrame/dismantle",
            "/api/knightmareFrame/carryIn",
            "/api/knightmareFrame/carryOut",
            "/api/knightmareFrame/color",
            "/api/knightmareFrame/useColor",
            "/api/knightmareFrame/notUseColor",
        ):
            if not self.page_session_ok():
                self.respond(403, {"error": "Invalid local session"})
                return
            if self.server.new_account_page is None:
                self.respond(503, {"resultCode": "error",
                    "errorTxt": "KMF changes require a local stateful account"})
                return
            if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
                self.respond(400, {"error": "Expected JSON"})
                return
            self.forward_gacha(raw_body, target_path=bootstrap_path)
            return
        if bootstrap_path in (
            "/api/card/costume/dressUp",
            "/api/chara/addBookmarkCostume",
            "/api/chara/removeBookmarkCostume",
        ):
            if not self.page_session_ok():
                self.respond(403, {"error": "Invalid local session"})
                return
            if self.server.new_account_page is None:
                self.respond(503, {"resultCode": "error",
                    "errorTxt": "Costume changes require a local stateful account"})
                return
            if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
                self.respond(400, {"error": "Expected JSON"})
                return
            self.forward_gacha(raw_body, target_path=bootstrap_path)
            return
        challenge_path = self.path.split("?", 1)[0]
        if challenge_path in CHALLENGE_RECEIVE_PATHS:
            if not self.page_session_ok():
                self.respond(403, {"error": "Invalid local session"})
                return
            if self.server.new_account_page is not None:
                try:
                    request_data = json.loads(raw_body)
                    if not isinstance(request_data, dict) or set(request_data) - {"challengeId"}:
                        raise ValueError("Unexpected mission fields")
                    claim = {"scope": CHALLENGE_RECEIVE_PATHS[challenge_path]}
                    if "challengeId" in request_data:
                        claim["challengeId"] = request_data["challengeId"]
                except (ValueError, TypeError):
                    self.respond(400, {"resultCode": "error", "errorTxt": "Invalid mission request"})
                    return
                self.forward_gacha(json.dumps(claim).encode(),
                                   target_path="/api/local/missions/claim")
                return
            if self.server.preserved_pages is None:
                self.respond(503, {"error": "No preserved mission data"})
                return
            try:
                request_data = json.loads(raw_body or b"{}")
                challenge_id = request_data.get("challengeId")
                if challenge_id is not None:
                    challenge_id = int(challenge_id)
                result = self.server.preserved_pages.claim(
                    CHALLENGE_RECEIVE_PATHS[challenge_path],
                    challenge_id,
                )
            except (ValueError, TypeError, KeyError, UnicodeError):
                self.respond(400, {"error": "Invalid challenge request"})
            else:
                self.respond(200, result)
            return
        if not token_matches(self.headers.get("X-Offline-Token", ""),
                          self.server.token):
            self.respond(403, {"error": "Invalid local session"})
            return
        if self.path != "/api/claim":
            self.respond(404, {"error": "Not implemented; no upstream forwarding"})
            return
        if (self.headers.get("Content-Type", "").split(";")[0] != "application/json"
                or self.headers.get("Transfer-Encoding")):
            self.respond(400, {"error": "Expected bounded JSON"})
            return
        try:
            payload = json.loads(raw_body)
            if not isinstance(payload, dict) or not isinstance(payload.get("product"), str):
                raise ValueError("Invalid product")
            result = self.server.shop.claim(payload["product"], payload.get("order_id"))
            self.respond(200, result)
        except (ValueError, UnicodeError):
            self.respond(400, {"error": "Invalid product, order or JSON"})
        except TimeoutError:
            self.respond(408, {"error": "Body timeout"})

    def forward_gacha(self, raw_body, target_path=None, preserve_request_id=False):
        if not self.server.gacha_upstream:
            self.respond(503, {
                "resultCode": "error",
                "title": "ローカル抽卡",
                "errorTxt": "本地抽卡上游未配置。",
            })
            return
        target = self.server.gacha_upstream + (target_path or self.path)
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if preserve_request_id:
            ids = self.headers.get_all("X-Request-Id", [])
            if (len(ids) != 1 or not 1 <= len(ids[0]) <= 128
                    or not ids[0].isascii() or not ids[0].isprintable()
                    or not ids[0].strip()):
                self.respond(400, {"resultCode": "error",
                    "errorTxt": "A single X-Request-Id is required"})
                return
            headers["X-Request-Id"] = ids[0]
        request = urllib.request.Request(
            target,
            data=raw_body,
            method="POST",
            headers=headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                status = response.status
                content_type = response.headers.get(
                    "Content-Type", "application/json; charset=utf-8"
                )
                body = response.read(4 * 1024 * 1024 + 1)
        except urllib.error.HTTPError as exc:
            status = exc.code
            content_type = exc.headers.get(
                "Content-Type", "application/json; charset=utf-8"
            )
            body = exc.read(4 * 1024 * 1024 + 1)
        except (urllib.error.URLError, TimeoutError, OSError):
            self.respond(502, {
                "resultCode": "error",
                "title": "ローカル抽卡",
                "errorTxt": "本地抽卡服务未启动。",
            })
            return
        if len(body) > 4 * 1024 * 1024:
            self.respond(502, {
                "resultCode": "error",
                "title": "ローカル抽卡",
                "errorTxt": "本地抽卡响应过大。",
            })
            return
        if status == 200 and target_path in ("/api/battle/start", "/api/battle/end", "/api/battle/skip", "/api/local/battle/retire"):
            result = json.loads(body)
            models = self.server.account_models()
            result = merge_battle_response_models(
                result, models, target_path)
            body = json.dumps(result, ensure_ascii=False).encode("utf8")
        if status == 200 and target_path == "/api/quest/story/end":
            result = json.loads(body)
            models = self.server.account_models()
            for key in ("gameUser", "userItemList", "userStatusList"):
                result[key] = models.get(key, {} if key == "gameUser" else [])
            result["userStoryList"] = models.get("userStoryList", [])
            body = json.dumps(result, ensure_ascii=False).encode("utf8")
        if target_path in ("/api/battle/start", "/api/battle/end", "/api/battle/skip", "/api/local/battle/retire") and status in (400, 404, 409, 422):
            # The original QuestBackground callback handles resultCode=error,
            # restores WebView visibility and leaves the native loading scene.
            result = json.loads(body)
            if result.get("resultCode") != "error":
                result = {"resultCode": "error", "title": "バトルエラー",
                          "errorTxt": "バトル要求の形式が正しくありません。"}
            body = json.dumps(result, ensure_ascii=False).encode("utf8")
            status = 200
        self.respond(status, body, content_type)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=18765)
    parser.add_argument("--database", type=Path,
                        default=Path(__file__).parent / "saves" / "prototype.sqlite")
    parser.add_argument("--account-database", type=Path)
    parser.add_argument("--account", help="Local account fingerprint from import")
    parser.add_argument("--asset-mapping", type=Path)
    parser.add_argument("--asset-cache", type=Path)
    parser.add_argument("--raw-media", type=Path)
    parser.add_argument("--native-catalogs", type=Path)
    parser.add_argument("--native-hashes", type=Path)
    parser.add_argument("--web-root", type=Path)
    parser.add_argument("--web-entry",
                        help="Explicit source digest from the staged web manifest")
    parser.add_argument(
        "--gacha-upstream",
        default="http://127.0.0.1:18766",
        help="Loopback stateful gacha service",
    )
    parser.add_argument(
        "--gacha-static",
        type=Path,
        help="Captured page bodies used to assemble GachaTop and animation pages",
    )
    parser.add_argument(
        "--gacha-state-url",
        default="http://127.0.0.1:18766/api/local/page-state",
        help="Read-only local page-state endpoint",
    )
    parser.add_argument(
        "--preserved-pages",
        type=Path,
        help="Decoded-body cache used for MissionTop and QuestTop pages",
    )
    parser.add_argument(
        "--mission-claims",
        type=Path,
        help="Persistent local mission claim timestamps",
    )
    parser.add_argument(
        "--deck-database",
        type=Path,
        help="Local deck overlay database (defaults beside the account database)",
    )
    parser.add_argument(
        "--masterdata",
        type=Path,
        help="Extracted masterdata directory used when no imported account is configured",
    )
    args = parser.parse_args()
    with LocalServer(args.port, args.database, args.account_database, args.account,
                     args.asset_mapping, args.asset_cache, args.native_catalogs,
                     args.native_hashes,
                     args.web_root, args.web_entry,
                     args.gacha_upstream, args.gacha_static,
                     args.gacha_state_url,
                     preserved_pages_cache=args.preserved_pages,
                     mission_claims_path=args.mission_claims,
                     deck_database=args.deck_database,
                     masterdata=args.masterdata, raw_media=args.raw_media) as server:
        print("DEMO ONLY: http://" + server.authority, flush=True)
        print("Ctrl+C to stop. No official account integration.", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
