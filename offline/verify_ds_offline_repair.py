"""HTTP verification for the loopback page-session and asset repairs."""
import argparse
import http.client
import json
from pathlib import Path
import tempfile
import threading

from server import LocalServer


ASSETS = (
    "/web/template/detail/QuestDetailPopup.html",
    "/web/image/common/number/rank_text_number2.webp",
    "/web/image/common/number/rank_text_number3.webp",
    "/web/image/common/number/rank_text_number4.webp",
    "/web/image/common/icon/icon_coloring_s.webp",
    "/web/image/common/detail/pnl_itemdetail.webp",
    "/web/image/common/detail/pnl_itemdetail_1.webp",
    "/web/image/common/detail/pnl_info.webp",
)

PAGES = (
    "/api/page/ComposeTop",
    "/api/page/ComposePilot",
    "/api/page/ComposeKmf",
    "/api/page/KmfDevelopment",
    "/api/page/KmfDismantle",
    "/api/page/KmfColoring",
    "/api/page/CarryingTop",
)


class StubPages:
    def resolve(self, path):
        return {"resultCode": "success", "path": path}


def request(server, path, headers=None):
    conn = http.client.HTTPConnection(*server.server_address, timeout=5)
    try:
        conn.request("GET", path, headers=headers or {})
        response = conn.getresponse()
        return response.status, response.read()
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("package", type=Path)
    args = parser.parse_args()
    package = args.package.resolve()
    config = json.loads(
        (package / "config/private-server.json").read_text("utf8"))
    web_root = package / config["webRoot"]

    with tempfile.TemporaryDirectory() as temporary:
        server = LocalServer(
            0,
            Path(temporary) / "page.sqlite",
            web_root=web_root,
            web_entry=config["webEntry"],
            gacha_pages=StubPages(),
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            page_results = {}
            for path in PAGES:
                status, body = request(server, path)
                payload = json.loads(body)
                if status != 200 or payload.get("path") != path:
                    raise AssertionError("Page route failed: %s" % path)
                page_results[path] = status

            host = "localhost:%d" % server.server_address[1]
            status, body = request(
                server, "/api/page/ComposeTop", {"Host": host})
            if status != 200 or json.loads(body).get("path") != PAGES[0]:
                raise AssertionError("localhost page fallback failed")

            asset_results = {}
            for path in ASSETS:
                status, body = request(server, path)
                if status != 200:
                    raise AssertionError("Asset route failed: %s" % path)
                if path.endswith(".webp"):
                    if not body.startswith(b"RIFF") or body[8:12] != b"WEBP":
                        raise AssertionError("Invalid WebP: %s" % path)
                elif b"popupInner" not in body or b"rankRewardWrap" not in body:
                    raise AssertionError("Invalid detail template")
                asset_results[path] = {
                    "status": status,
                    "bytes": len(body),
                }

            normalized = (
                "/web//web/image/common/badge/icon_badge_1.webp")
            status, body = request(server, normalized)
            if status != 200 or not body.startswith(b"RIFF"):
                raise AssertionError("Duplicate web-prefix normalization failed")
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    print(json.dumps({
        "pages": page_results,
        "assets": asset_results,
        "normalizedDuplicatePrefix": normalized,
        "localhostFallback": True,
    }, indent=2))


if __name__ == "__main__":
    main()
