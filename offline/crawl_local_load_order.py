import argparse
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import urlopen

from playwright.sync_api import sync_playwright


LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:18865")
    parser.add_argument("--output", required=True)
    parser.add_argument("--wait-ms", type=int, default=12000)
    parser.add_argument("--browser")
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    requests = []
    responses = {}
    failures = []
    blocked = []
    console_errors = []
    sequence = 0

    browser_process = None
    profile_path = None
    with sync_playwright() as playwright:
        if args.browser:
            socket_handle = socket.socket()
            socket_handle.bind(("127.0.0.1", 0))
            debug_port = socket_handle.getsockname()[1]
            socket_handle.close()
            profile_path = tempfile.mkdtemp(prefix="cgls-load-order-")
            creation_flags = (
                subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            browser_process = subprocess.Popen([
                args.browser,
                "--headless=new",
                f"--remote-debugging-port={debug_port}",
                f"--user-data-dir={profile_path}",
                "--disable-background-networking",
                "--disable-component-update",
                "--no-first-run",
                "--no-default-browser-check",
                "about:blank",
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=creation_flags)
            deadline = time.time() + 20
            while time.time() < deadline:
                try:
                    with urlopen(
                            f"http://127.0.0.1:{debug_port}/json/version",
                            timeout=1) as response:
                        if response.status == 200:
                            break
                except OSError:
                    time.sleep(0.2)
            else:
                raise RuntimeError("Edge CDP endpoint did not become ready")
            browser = playwright.chromium.connect_over_cdp(
                f"http://127.0.0.1:{debug_port}")
            context = browser.contexts[0]
        else:
            browser = playwright.chromium.launch(
                headless=True, args=["--disable-background-networking"])
            context = browser.new_context()
        context.set_extra_http_headers(
            {"X-Web-Session-Id": str(int(time.time() * 1000))})

        def route_request(route):
            try:
                url = route.request.url
                parsed = urlsplit(url)
                if parsed.scheme in {"data", "blob", "about"}:
                    route.continue_()
                    return
                if (parsed.scheme in {"http", "https"}
                        and parsed.hostname in LOOPBACK_HOSTS):
                    route.continue_()
                    return
                blocked.append({
                    "url": url,
                    "method": route.request.method,
                    "resourceType": route.request.resource_type,
                })
                route.abort("blockedbyclient")
            except Exception as error:
                failures.append({
                    "url": route.request.url,
                    "method": route.request.method,
                    "failure": f"route handler: {error}",
                    "resourceType": route.request.resource_type,
                })

        context.route("**/*", route_request)

        def on_request(request):
            nonlocal sequence
            sequence += 1
            requests.append({
                "sequence": sequence,
                "time": time.time(),
                "method": request.method,
                "url": request.url,
                "resourceType": request.resource_type,
                "postData": request.post_data,
            })

        def on_response(response):
            try:
                address = response.server_addr
                if callable(address):
                    address = address()
                if not isinstance(address, dict):
                    address = {}
                responses[response.request.url] = {
                    "status": response.status,
                    "contentType": response.headers.get("content-type"),
                    "remoteAddress": address.get("ip"),
                    "remotePort": address.get("port"),
                }
            except Exception as error:
                failures.append({
                    "url": response.request.url,
                    "method": response.request.method,
                    "failure": f"response handler: {error}",
                    "resourceType": response.request.resource_type,
                })

        def on_failed(request):
            failures.append({
                "url": request.url,
                "method": request.method,
                "failure": request.failure,
                "resourceType": request.resource_type,
            })

        page = context.new_page()
        page.on("request", on_request)
        page.on("response", on_response)
        page.on("requestfailed", on_failed)
        page.on("console", lambda message: console_errors.append({
            "type": message.type,
            "text": message.text[:2000],
        }) if message.type == "error" else None)
        entry = args.base_url.rstrip("/") + "/web/index.html?time=" + str(
            int(time.time() * 1000))
        navigation = None
        try:
            navigation = page.goto(
                entry, wait_until="domcontentloaded", timeout=30000)
        except Exception as error:
            failures.append({
                "url": entry,
                "method": "GET",
                "failure": f"navigation: {error}",
                "resourceType": "document",
            })
        page.wait_for_timeout(args.wait_ms)
        state = page.evaluate(
            """() => ({
                href: location.href,
                title: document.title,
                text: String(document.body && document.body.innerText || "")
                    .replace(/\\s+/g, " ").trim().slice(0, 4000)
            })"""
        )
        browser.close()
    if browser_process is not None:
        try:
            browser_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            browser_process.kill()
    if profile_path is not None:
        shutil.rmtree(profile_path, ignore_errors=True)

    for request in requests:
        request["response"] = responses.get(request["url"])
    result = {
        "entry": entry,
        "navigationStatus": navigation.status if navigation else None,
        "state": state,
        "requestCount": len(requests),
        "requests": requests,
        "blockedExternalRequests": blocked,
        "failures": failures,
        "consoleErrors": console_errors,
    }
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "output": str(output),
        "navigationStatus": result["navigationStatus"],
        "requestCount": len(requests),
        "blockedExternalRequests": len(blocked),
        "failures": len(failures),
        "consoleErrors": len(console_errors),
        "route": state.get("href"),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
