"""End-to-end smoke test for a fresh local account without account snapshots."""

from __future__ import annotations

import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request


WORKSPACE = Path(__file__).resolve().parents[1]
MASTERDATA = Path(
    r"D:\LostStories_Preservation_20261018\masterdata-20261018"
)
GACHA_STATIC = Path(
    r"D:\LostStories_Preservation_20261018\gacha-capture-live-1905\bodies"
)
PRESERVED = Path(
    r"D:\LostStories_Preservation_20261018\web-cache-extracted-20261018-1902"
)


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def fetch_json(url, headers=None, timeout=30):
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def wait_json(url, predicate, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            value = fetch_json(url, timeout=2)
            if predicate(value):
                return value
        except Exception:
            pass
        time.sleep(0.2)
    raise RuntimeError("Timed out waiting for " + url)


def run():
    if not MASTERDATA.is_dir():
        raise RuntimeError("Missing masterdata")
    if not GACHA_STATIC.is_dir():
        raise RuntimeError("Missing gacha capture")
    if not PRESERVED.is_dir():
        raise RuntimeError("Missing preserved pages")

    with tempfile.TemporaryDirectory(prefix="cgls-new-account-") as directory:
        root = Path(directory)
        state_port = free_port()
        page_port = free_port()
        state = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "cgls.app",
                "--database",
                str(root / "state.sqlite"),
                "--port",
                str(state_port),
            ],
            cwd=WORKSPACE / "stateful_server",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        page = None
        try:
            state_url = f"http://127.0.0.1:{state_port}"
            wait_json(
                state_url + "/api/local/state",
                lambda value: value.get("pilots") == 2,
            )
            print("stateful ready", flush=True)
            sys.path.insert(0, str(WORKSPACE / "offline"))
            from new_account_page import NewAccountPage

            started = time.monotonic()
            direct_payload = json.loads(
                NewAccountPage(
                    MASTERDATA,
                    state_url + "/api/local/page-state",
                ).page_payload().decode("utf-8")
            )
            print(
                "direct account model ready cards=%d kmfs=%d bytes=%d elapsed=%.2f"
                % (
                    len(direct_payload.get("userCardList", [])),
                    len(direct_payload.get("userKnightmareFrameList", [])),
                    len(json.dumps(direct_payload).encode("utf-8")),
                    time.monotonic() - started,
                ),
                flush=True,
            )
            from gacha_pages import GachaPageStore

            started = time.monotonic()
            direct_my_page = GachaPageStore(
                NewAccountPage(
                    MASTERDATA,
                    state_url + "/api/local/page-state",
                ),
                GACHA_STATIC,
                state_url + "/api/local/page-state",
            ).my_page()
            print(
                "direct MyPage ready keys=%d elapsed=%.2f"
                % (len(direct_my_page), time.monotonic() - started),
                flush=True,
            )
            page = subprocess.Popen(
                [
                    sys.executable,
                    "-u",
                    str(WORKSPACE / "offline" / "server.py"),
                    "--port",
                    str(page_port),
                    "--database",
                    str(root / "prototype.sqlite"),
                    "--masterdata",
                    str(MASTERDATA),
                    "--gacha-upstream",
                    state_url,
                    "--gacha-state-url",
                    state_url + "/api/local/page-state",
                    "--gacha-static",
                    str(GACHA_STATIC),
                    "--preserved-pages",
                    str(PRESERVED),
                    "--mission-claims",
                    str(root / "mission_claims.json"),
                ],
                cwd=WORKSPACE,
                stdout=open(root / "page.stdout.log", "w", encoding="utf-8"),
                stderr=open(root / "page.stderr.log", "w", encoding="utf-8"),
                text=True,
                env={**dict(__import__("os").environ), "CGLS_DEBUG": "1"},
            )
            wait_json(
                f"http://127.0.0.1:{page_port}/api/state",
                lambda value: value.get("offline") is True,
            )
            print("page ready", flush=True)
            headers = {
                "Host": f"127.0.0.1:{page_port}",
                "X-Web-Session-Id": "smoke",
            }
            base = f"http://127.0.0.1:{page_port}"
            print("requesting MyPage", flush=True)
            my_page = fetch_json(base + "/api/page/MyPage", headers)
            print("MyPage ready", flush=True)
            gacha = fetch_json(base + "/api/page/GachaTop", headers)
            print("GachaTop ready", flush=True)
            quest = fetch_json(base + "/api/page/QuestTop", headers)
            print("QuestTop ready", flush=True)
            deck = fetch_json(base + "/api/page/DeckFormation", headers)
            print("DeckFormation ready", flush=True)
            result = {
                "statefulUrl": state_url,
                "pageUrl": base,
                "myPageCards": len(my_page.get("userCardList", [])),
                "myPageKmfs": len(my_page.get("userKnightmareFrameList", [])),
                "myPageDecks": len(my_page.get("userDeckList", [])),
                "myPageAcp": next(
                    (
                        row.get("point")
                        for row in my_page.get("userStatusList", [])
                        if row.get("statusId") == "ACP"
                    ),
                    None,
                ),
                "gachaKinds": len(gacha.get("userGachaKindList", [])),
                "questModels": len(quest.get("userQuestList", [])),
                "deckModels": len(deck.get("userDeckList", [])),
            }
            if result["myPageCards"] != 2:
                raise RuntimeError("MyPage starter pilots mismatch")
            if result["myPageKmfs"] != 2:
                raise RuntimeError("MyPage starter KMF mismatch")
            if result["myPageDecks"] < 1:
                raise RuntimeError("MyPage default deck is missing")
            if result["deckModels"] < 1:
                raise RuntimeError("DeckFormation default deck is missing")
            print(json.dumps(result, ensure_ascii=False, indent=2))
        finally:
            for process in (page, state):
                if process is None:
                    continue
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            for name in ("page.stdout.log", "page.stderr.log"):
                log_path = root / name
                if log_path.exists():
                    content = log_path.read_text(
                        encoding="utf-8", errors="replace"
                    ).strip()
                    if content:
                        safe = content[-8000:].encode(
                            "utf-8", errors="replace"
                        ).decode("utf-8")
                        print(name + ":\n" + safe, flush=True)


if __name__ == "__main__":
    run()
