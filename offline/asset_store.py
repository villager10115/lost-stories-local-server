"""Exact catalog-to-cache resource serving. No upstream fallback or fuzzy matching."""
import json
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit


def valid_bundle_identity(name, version):
    """Accept observed Addressables names, including the built-in shader suffix."""
    return (isinstance(name, str) and isinstance(version, str)
            and re.fullmatch(r"[0-9a-f]{32}(?:_unitybuiltinshaders)?", name) is not None
            and re.fullmatch(r"[0-9a-f]{32}", version) is not None)


class AssetStore:
    PREFIX = "{Zero.Config.Environment.URL}/"

    def __init__(self, mapping, cache):
        self.cache = Path(cache).resolve(strict=True)
        if not self.cache.is_dir():
            raise ValueError("Cache must be a directory")
        self.routes = {}
        self.conflicts = set()
        declared_versions = {}
        for row in json.loads(Path(mapping).read_text(encoding="utf-8")):
            identifier = row.get("id", "")
            if not identifier.startswith(self.PREFIX):
                continue
            relative = identifier[len(self.PREFIX):]
            if not re.fullmatch(r"[\w./-]+", relative):
                continue
            if any(part in ("", ".", "..") for part in relative.split("/")):
                continue
            options = row.get("options") or {}
            name, version = options.get("m_BundleName", ""), options.get("m_Hash", "")
            if not valid_bundle_identity(name, version):
                continue
            route = "/assets/" + relative
            signature = (name, version, options.get("m_BundleSize"))
            if route in declared_versions and declared_versions[route] != signature:
                self.conflicts.add(route)
            declared_versions[route] = signature
            expected = name + "_" + version
            candidates = set((row.get("matching_cache_files") or {}).values())
            size = options.get("m_BundleSize")
            if candidates != {expected} or type(size) is not int or size <= 0:
                continue
            route = "/assets/" + relative
            record = (expected, size)
            if route in self.routes and self.routes[route] != record:
                self.conflicts.add(route)
            self.routes[route] = record

    def resolve(self, target):
        """Return exact, bounded-to-cache bytes; missing/conflicting versions fail closed."""
        invalid = (400, b"Invalid asset target", "text/plain")
        if len(target) > 8192:
            return invalid
        try:
            url = urlsplit(target)
        except ValueError:
            return invalid
        if url.scheme or url.netloc or url.fragment:
            return invalid
        # The shipped catalog includes fourthtitle/定着.bundle. Decode UTF-8
        # path bytes, but never encoded ASCII separators, dots or percent signs.
        if re.search(r"%(?:[0-7][0-9a-f]|(?![0-9a-f]{2}))", url.path, re.I):
            return invalid
        try:
            path = unquote(url.path, encoding="utf-8", errors="strict")
        except UnicodeError:
            return invalid
        if not re.fullmatch(r"[\w./-]+", path):
            return invalid
        # ResourceManager.ConvertRequest appends location.Hash(typeof(object)),
        # a signed Int32 cache-buster, NOT the bundle version Hash128.
        # Keep selection exclusively bound to the exact catalog declaration.
        if url.query:
            if not re.fullmatch(r"hash=-?(?:0|[1-9][0-9]{0,9})", url.query):
                return invalid
            value = int(url.query[5:])
            if not -(2 ** 31) <= value < 2 ** 31:
                return invalid
        if path in self.conflicts:
            return 409, b"Conflicting catalog versions", "text/plain"
        record = self.routes.get(path)
        if record is None:
            return 404, b"No exact cached resource; no upstream forwarding", "text/plain"
        filename, size = record
        path = self.cache / filename
        try:
            if path.resolve(strict=True).parent != self.cache:
                return 503, b"Resource escaped cache", "text/plain"
            if path.stat().st_size != size:
                return 503, b"Resource size mismatch", "text/plain"
            body = path.read_bytes()
            if len(body) != size:
                return 503, b"Resource changed during read", "text/plain"
        except OSError:
            return 503, b"Cached resource unavailable", "text/plain"
        return 200, body, "application/octet-stream"
