"""Read-only cached frontend inspection. Scripts disabled until OS isolation is ready."""
import argparse
import hashlib
import json
import mimetypes
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


class StaticStore:
    def __init__(self, root, entry):
        self.root = Path(root)
        manifest = json.loads((self.root / "routes.json").read_text(encoding="utf-8"))
        selected = [e for e in manifest["entries"] if e["source"] == entry]
        if len(selected) != 1 or not selected[0]["direct_dependencies_complete"]:
            raise ValueError("Select an explicit entry with complete direct dependencies")
        self.entry = selected[0]["body"]
        self.routes = {(r["path"], r["rev"]): r["body"] for r in manifest["routes"]}
        self.conflicts = {(r["path"], r["rev"]) for r in manifest["conflicts"]}

    def resolve(self, target):
        url = urlsplit(target)
        if url.scheme or url.netloc:
            return 400, b"Absolute URL rejected", "text/plain"
        query = parse_qs(url.query)
        if any(key != "rev" for key in query) or len(query.get("rev", [])) > 1:
            return 400, b"Unsupported query", "text/plain"
        if url.path.startswith("/api/"):
            return 501, b"Offline API not implemented; no upstream forwarding", "text/plain"
        key = (url.path, query.get("rev", [None])[0])
        if url.path in ("/", "/web/index.html"):
            digest = self.entry
            mime = "text/html"
        elif key in self.conflicts:
            return 409, b"Ambiguous cached version", "text/plain"
        elif key in self.routes:
            digest = self.routes[key]
            mime = mimetypes.guess_type(url.path)[0] or "application/octet-stream"
        else:
            return 404, b"Missing exact cached version", "text/plain"
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("Invalid body name")
        body = (self.root / "bodies" / digest).read_bytes()
        if hashlib.sha256(body).hexdigest() != digest:
            raise ValueError("Body checksum mismatch")
        return 200, body, mime


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def send_body(self, status, body, mime):
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        # No scripts, frames, forms or native bridge. This is not an OS firewall.
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; style-src 'self' 'unsafe-inline'; "
                         "img-src 'self' data:; font-src 'self'; connect-src 'none'; "
                         "script-src 'none'; frame-ancestors 'none'; "
                         "base-uri 'none'; form-action 'none'; sandbox")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        authority = "127.0.0.1:%d" % self.server.server_address[1]
        if self.headers.get("Host") != authority:
            self.send_body(403, b"Invalid host", "text/plain")
            return
        try:
            if self.path.startswith("/api/") and getattr(self.server, "snapshot", None):
                status, body, mime = self.server.snapshot.resolve(self.path)
            else:
                status, body, mime = self.server.store.resolve(self.path)
        except (ValueError, OSError):
            self.send_body(500, b"Invalid staged content", "text/plain")
            return
        self.send_body(status, body, mime)

    def do_POST(self):
        self.send_body(501, b"No mutations or upstream forwarding", "text/plain")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--entry", required=True, help="Source SHA256 from routes.json")
    parser.add_argument("--port", type=int, default=18766)
    parser.add_argument("--snapshot", type=Path, help="Private read-only imported snapshot")
    args = parser.parse_args()
    store = StaticStore(args.root, args.entry)
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        server.store = store
        if args.snapshot:
            from snapshot_store import SnapshotStore
            server.snapshot = SnapshotStore(args.snapshot)
        print("Static inspection only; scripts disabled: http://127.0.0.1:%d/web/index.html"
              % server.server_address[1], flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
