"""Run a disposable browser against local copies; block non-local page traffic."""
import argparse
import json
from pathlib import Path
import threading
from urllib.parse import urlsplit
from http.server import ThreadingHTTPServer
from playwright.sync_api import sync_playwright
from isolated_server import ExecutableStore, ExecutableHandler
from preview_snapshot import PreviewSnapshotStore

def run(work, output, user_source=None, banner_source=None):
    work, output = Path(work), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    source = work / "private" / "SandboxRun01"
    config = json.loads((source / "launch.json").read_text())
    server = ThreadingHTTPServer(("127.0.0.1", 0), ExecutableHandler)
    server.store = ExecutableStore(source / "web", config["entry"], config["version"])
    server.snapshot = PreviewSnapshotStore(source / "snapshot", user_source=user_source)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = "http://127.0.0.1:" + str(server.server_address[1])
    report = {"errors": [], "failed": [], "external_blocked": [],
              "preview_omissions": server.snapshot.omissions,
              "user_source": server.snapshot.user_source,
              "banner_source": str(banner_source) if banner_source else None,
              "banner_policy": "explicit preview overlay; historical compatibility unverified"}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", headless=False,
                chromium_sandbox=True,
                args=["--headless=new", "--disable-background-networking"])
            context = browser.new_context(viewport={"width":1920,"height":1080},
                                          service_workers="block")
            def route_handler(route):
                u = urlsplit(route.request.url)
                if u.scheme in ("http", "https") and (u.scheme + "://" + u.netloc) == origin:
                    if banner_source and u.path == "/web/json/event_banner/event_banner.json":
                        route.fulfill(status=200, content_type="application/json",
                                      body=Path(banner_source).read_bytes())
                    else:
                        route.continue_()
                else:
                    report["external_blocked"].append(u.scheme + "://" + u.netloc + u.path)
                    route.abort()
            context.route("**/*", route_handler)
            context.route_web_socket("**/*", lambda ws: ws.close())
            page = context.new_page()
            context.add_init_script("""
                window.offlineCommandTrace = [];
                window.offlineErrors = [];
                window.offlinePreviewMocks = [];
                window.addEventListener("error", event => {
                    window.offlineErrors.push(String(event.message) + " " + String(event.error?.stack));
                });
                const watch = setInterval(() => {
                    if (!window.requirejs || !requirejs.defined("command")) return;
                    clearInterval(watch);
                    const command = requirejs("command");
                    const original = command.sendCommand;
                    command.sendCommand = function(name, ...args) {
                        if (window.offlineCommandTrace.length < 200)
                            window.offlineCommandTrace.push(String(name).slice(0, 80));
                        // UI-only test doubles: no Unity scene or asset is loaded.
                        const previewCallbacks = new Set([
                            "PUSH_HOME", "LOAD_3D_BG", "FADE_IN_3D_BG",
                            "LOAD_2D_BG", "FADE_IN_2D_BG"
                        ]);
                        if (previewCallbacks.has(name)) {
                            window.offlinePreviewMocks.push(name);
                            queueMicrotask(() => nativeCallback());
                            return;
                        }
                        return original.call(this, name, ...args);
                    };
                }, 10);
            """)
            page.on("pageerror", lambda error: report["errors"].append(str(error)[:2000]))
            page.on("response", lambda response: report["failed"].append(
                {"path":urlsplit(response.url).path,"status":response.status})
                if response.status >= 400 else None)
            page.goto(origin + "/web/index.html#MyPage", wait_until="domcontentloaded")
            page.wait_for_timeout(12000)
            report["title"] = page.title()
            report["body_excerpt"] = page.locator("body").inner_text()[:3000]
            report["bridge"] = page.evaluate("window.offlineBridge?.diagnostics()")
            report["commands"] = page.evaluate("window.offlineCommandTrace")
            report["captured_errors"] = page.evaluate("window.offlineErrors")
            report["preview_mocks"] = page.evaluate("window.offlinePreviewMocks")
            report["state"] = page.evaluate("""() => {
                const common = window.requirejs?.defined('backboneCommon') && requirejs('backboneCommon');
                return {location: common?.location, hasGameUser: !!common?.storage?.gameUser,
                        contentLength: document.querySelector('#mainContent')?.innerHTML.length};
            }""")
            page.screenshot(path=str(output / "screen.png"), full_page=True)
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        (output / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8")
    print(json.dumps(report, ensure_ascii=True))

if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--user-source", type=Path, help="Explicit same-account cached user supplement; preview only")
    parser.add_argument("--banner-source", type=Path, help="Explicit downloaded banner JSON; preview only")
    args=parser.parse_args()
    run(args.work,args.output,args.user_source,args.banner_source)
