"""Serve the staged frontend copy to the native client.

One captured entry is chosen explicitly. Requests for the entry and its direct
dependencies are pinned to that entry's revisions so a page can never mix
bodies from different captures. Every other path is served only when the staged
copy holds a single body for it; ambiguous paths fail closed.
"""
import argparse
import hashlib
import json
import mimetypes
import re
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

mimetypes.add_type("image/webp", ".webp")

ENTRY_PATHS = ("/web", "/web/", "/web/index.html")
# Native WebRequestQuery uses ?time=, require.js urlArgs uses ?rev=,
# and Environment.HashRequestQueryWithRand also appends ?rand=.
ALLOWED_QUERY = {"rev": re.compile(r"[0-9a-fA-F]{1,64}"),
                 "time": re.compile(r"[0-9]{1,16}"),
                 "t": re.compile(r"[0-9]{1,16}"),
                 "rand": re.compile(r"[0-9a-fA-F-]{1,64}"),
                 "bust": re.compile(r"[0-9]{1,16}"),
                 "v": re.compile(r"[0-9]{1,8}")}
MIME_CHARSET = {"text/html": "utf-8", "text/css": "utf-8",
                "text/javascript": "utf-8", "application/javascript": "utf-8",
                "application/json": "utf-8", "image/svg+xml": "utf-8"}


class WebStore:
    def __init__(self, root, entry):
        self.root = Path(root).resolve(strict=True)
        manifest = json.loads((self.root / "routes.json").read_text(encoding="utf-8"))
        selected = [e for e in manifest["entries"] if e["source"] == entry]
        if len(selected) != 1:
            raise ValueError("Select exactly one staged entry by source digest")
        if not selected[0]["direct_dependencies_complete"]:
            raise ValueError("Entry lacks complete direct dependencies")
        self.entry = selected[0]["body"]
        # Pin the entry's direct dependencies to their captured revisions.
        self.pinned = {r["path"]: r["rev"] for r in selected[0]["references"]}
        self.routes = {}
        for row in manifest["routes"]:
            self.routes.setdefault(row["path"], {})[row["rev"]] = row["body"]
        self.bodies = self.root / "bodies"
        self.local_overrides = self.root / "local_overrides"

    @staticmethod
    def entries(root):
        manifest = json.loads((Path(root) / "routes.json").read_text(encoding="utf-8"))
        return manifest["entries"]

    def _body(self, digest):
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("Invalid body name")
        path = (self.bodies / digest).resolve(strict=True)
        if path.parent != self.bodies.resolve():
            raise ValueError("Body escaped staging directory")
        body = path.read_bytes()
        if hashlib.sha256(body).hexdigest() != digest:
            raise ValueError("Body checksum mismatch")
        return body

    def _mime(self, path):
        mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
        if mime in MIME_CHARSET:
            return mime + "; charset=" + MIME_CHARSET[mime]
        return mime

    def resolve(self, target):
        invalid = (400, b"Invalid web target", "text/plain")
        if len(target) > 8192 or "%" in target or "\\" in target:
            return invalid
        try:
            url = urlsplit(target)
        except ValueError:
            return invalid
        if url.scheme or url.netloc or url.fragment:
            return invalid
        path = url.path
        if path in ENTRY_PATHS:
            if self.local_overrides.is_dir():
                override = (self.local_overrides / "web" / "index.html").resolve()
                if (
                    override.is_file()
                    and self.local_overrides.resolve() in override.parents
                ):
                    return 200, override.read_bytes(), "text/html; charset=utf-8"
            # Entry is selected explicitly; ?time= cache-busters never reselect it.
            return 200, self._body(self.entry), "text/html; charset=utf-8"
        if not path.startswith("/web/"):
            return 404, b"Not a staged web path", "text/plain"
        if self.local_overrides.is_dir() and path.startswith("/web/"):
            override = (self.local_overrides / path.lstrip("/")).resolve()
            override_root = self.local_overrides.resolve()
            if override.is_file() and override_root in override.parents:
                return 200, override.read_bytes(), self._mime(path)
        for part in path.split("/")[1:]:
            if part in ("", ".", ".."):
                return invalid
        requested = None
        if url.query:
            try:
                pairs = parse_qsl(url.query, keep_blank_values=True,
                                  strict_parsing=False, max_num_fields=8)
            except ValueError:
                return invalid
            seen = set()
            for key, value in pairs:
                if key in seen:
                    return invalid
                seen.add(key)
                if key.isdigit() and value == "":
                    continue
                if key not in ALLOWED_QUERY:
                    return invalid
                if not ALLOWED_QUERY[key].fullmatch(value):
                    return invalid
                if key == "rev":
                    requested = value
        variants = self.routes.get(path)
        if not variants:
            return 404, b"Missing staged web path", "text/plain"
        digest = None
        if path in self.pinned and self.pinned[path] in variants:
            # Keep the served page internally consistent even if a caller asks
            # for a revision captured from a different app version.
            digest = variants[self.pinned[path]]
        elif requested is not None and requested in variants:
            digest = variants[requested]
        elif len(variants) == 1:
            digest = next(iter(variants.values()))
        if digest is None:
            return 409, b"Ambiguous staged revision", "text/plain"
        return 200, self._body(digest), self._mime(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--entry")
    args = parser.parse_args()
    for entry in WebStore.entries(args.root):
        print(entry["source"], "deps_complete=" + str(entry["direct_dependencies_complete"]))
    if args.entry:
        store = WebStore(args.root, args.entry)
        print("Selected entry body:", store.entry, "pinned:", len(store.pinned),
              "paths:", len(store.routes))


if __name__ == "__main__":
    main()
