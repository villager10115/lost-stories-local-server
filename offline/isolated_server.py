"""Executable cached frontend, restricted to a network-disabled Windows Sandbox."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
from http.server import ThreadingHTTPServer
from urllib.parse import urlsplit

from static_server import StaticStore, Handler
from snapshot_store import SnapshotStore
from account_store import AccountStore
from account_page import AccountPage


def require_isolation():
    if os.name != "nt" or os.environ.get("USERNAME", "").lower() != "wdagutilityaccount":
        raise RuntimeError("Executable preview is restricted to Windows Sandbox")
    # Fail closed if interface discovery fails or any non-loopback adapter is up.
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command",
         "$ErrorActionPreference='Stop'; "
         "$a=@(Get-NetAdapter -IncludeHidden | Where-Object Status -eq 'Up'); "
         "if($a.Count -ne 0){exit 2}"],
        capture_output=True, timeout=30)
    if result.returncode:
        raise RuntimeError("Network isolation check failed; refusing to execute cached scripts")


def bridge_prefix(version):
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("Explicit three-part client version required")
    return ('<script src="/offline/native_bridge.js"></script>'
            '<script src="/offline/bridge_binding.js"></script>'
            '<script>window.offlineBridge=installOfflineBridge('
            + json.dumps(version) + ');</script>').encode()


class ExecutableStore(StaticStore):
    def __init__(self, root, entry, version):
        super().__init__(root, entry)
        self.prefix = bridge_prefix(version)
        self.scripts = {
            "/offline/" + name: (Path(__file__).parent / name).read_bytes()
            for name in ("native_bridge.js", "bridge_binding.js")
        }

    def resolve(self, target):
        path = urlsplit(target).path
        if target in self.scripts:
            return 200, self.scripts[target], "application/javascript"
        status, body, mime = super().resolve(target)
        if status == 200 and path in ("/", "/web/index.html"):
            # Install before every original script, preserving classic global lexical bindings.
            body = self.prefix + body
        if mime in ("text/javascript", "application/javascript"):
            mime = "application/javascript; charset=utf-8"
        elif mime == "text/html":
            mime = "text/html; charset=utf-8"
        return status, body, mime


class ExecutableHandler(Handler):
    def send_body(self, status, body, mime):
        # Log route only: no query strings, tokens or snapshot payloads.
        print(json.dumps({"method": self.command,
                          "path": urlsplit(self.path).path[:256],
                          "status": status}), flush=True)
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        # Backbone templates require eval; only enable it inside verified OS isolation.
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
                         "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                         "font-src 'self' data:; connect-src 'self'; media-src 'self'; "
                         "object-src 'none'; frame-src 'none'; frame-ancestors 'none'; "
                         "base-uri 'self'; form-action 'none'")
        self.end_headers()
        self.wfile.write(body)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--entry", required=True)
    parser.add_argument("--app-version", required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--snapshot", type=Path)
    source.add_argument("--account-database", type=Path,
                        help="Private writable database copy inside Sandbox")
    parser.add_argument("--account", help="Selected local account fingerprint")
    args = parser.parse_args()
    if bool(args.account_database) != bool(args.account):
        parser.error("--account-database and --account must be specified together")
    require_isolation()
    store = ExecutableStore(args.root, args.entry, args.app_version)
    snapshot = (AccountPage(AccountStore(args.account_database), args.account)
                if args.account_database else SnapshotStore(args.snapshot))
    with ThreadingHTTPServer(("127.0.0.1", 18766), ExecutableHandler) as server:
        server.store, server.snapshot = store, snapshot
        print("ISOLATION VERIFIED; http://127.0.0.1:18766/web/index.html#MyPage", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
