import json
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen


EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
BASE_URL = "http://127.0.0.1:18865"


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main():
    # This is an opt-in live browser diagnostic, not a unittest. Keep its
    # optional browser dependency out of server test discovery.
    from playwright.sync_api import sync_playwright
    if not EDGE.is_file():
        raise SystemExit("Microsoft Edge was not found")
    port = free_port()
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    with tempfile.TemporaryDirectory(prefix="cgls-art-guards-") as profile:
        process = subprocess.Popen(
            [
                str(EDGE),
                "--headless=new",
                f"--remote-debugging-port={port}",
                f"--user-data-dir={profile}",
                "--no-first-run",
                "--no-default-browser-check",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation_flags,
        )
        try:
            deadline = time.time() + 20
            while time.time() < deadline:
                try:
                    with urlopen(
                        f"http://127.0.0.1:{port}/json/version",
                        timeout=1,
                    ) as response:
                        if response.status == 200:
                            break
                except OSError:
                    time.sleep(0.2)
            else:
                raise RuntimeError("Edge CDP endpoint did not become ready")

            with sync_playwright() as playwright:
                browser = playwright.chromium.connect_over_cdp(
                    f"http://127.0.0.1:{port}")
                context = browser.contexts[0]
                context.set_extra_http_headers(
                    {"X-Web-Session-Id": "artifact-guard-test"})
                page = context.new_page()
                page.goto(
                    f"{BASE_URL}/web/index.html?time=1792500000",
                    wait_until="domcontentloaded",
                    timeout=30000,
                )
                page.wait_for_timeout(1200)
                result = page.evaluate(
                    """async () => {
                        const webp = await fetch(
                          '/web/image/gacha/title/attention_scout_1795.webp')
                          .then(response => response.arrayBuffer());
                        return {
                          webpGuard: !!window.Blob.__localWebpSniffer,
                          emptyGuard: !!window.URL.__localEmptyBlobGuard,
                          webpType: new Blob(
                            [webp], {type: 'image/png'}).type,
                          emptyUrl: URL.createObjectURL(
                            new Blob([], {type: 'image/png'}))
                        };
                    }"""
                )
                browser.close()
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()

    expected = (
        result["webpGuard"] is True
        and result["emptyGuard"] is True
        and result["webpType"] == "image/webp"
        and result["emptyUrl"].startswith("data:image/gif;base64,")
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not expected:
        raise SystemExit("Artifact guard verification failed")


if __name__ == "__main__":
    main()
