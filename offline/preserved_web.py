"""Serve preserved web assets by exact URL path with checksum verification."""

import hashlib
import json
import mimetypes
import re
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

from web_audit import decode_text


mimetypes.add_type("image/webp", ".webp")

TEXT_MIME_TYPES = {
    "application/javascript",
    "application/json",
    "image/svg+xml",
    "text/css",
    "text/html",
    "text/javascript",
    "text/plain",
}


class PreservedWebStore:
    def __init__(self, cache_directory):
        self.cache_directory = Path(cache_directory).resolve(strict=True)
        manifest = json.loads(
            (self.cache_directory / "manifest.json").read_text(encoding="utf-8")
        )
        self.routes = {}
        for record in manifest:
            path = record.get("path")
            if not isinstance(path, str) or not path.startswith("/web/"):
                continue
            # Cache block offsets are storage locations, not version ordering.
            variants = self.routes.setdefault(path, {})
            variants.setdefault(record.get("rev"), {})[record.get("sha256")] = record
        self.cache = {}

    def resolve(self, target):
        try:
            url = urlsplit(target)
            pairs = parse_qsl(url.query, max_num_fields=8)
        except ValueError:
            return 400, b"Invalid preserved target", "text/plain"
        path = url.path
        if (
            url.scheme or url.netloc or url.fragment or len(target) > 8192
            or
            not path.startswith("/web/")
            or "\\" in path
            or "%" in path
            or any(part in ("", ".", "..") for part in path.split("/")[1:])
        ):
            return 404, b"Unknown preserved web path", "text/plain"
        variants = self.routes.get(path)
        if variants is None:
            return 404, b"Missing preserved web path", "text/plain"
        requested = [value for key, value in pairs if key == "rev"]
        if len(requested) > 1:
            return 400, b"Duplicate revision", "text/plain"
        if requested and requested[0] in variants:
            candidates = variants[requested[0]]
        elif requested and any(rev is not None for rev in variants):
            return 404, b"Missing preserved revision", "text/plain"
        else:
            candidates = {digest: record for records in variants.values()
                          for digest, record in records.items()}
        if len(candidates) != 1:
            # Brotli encodings can differ while decoded script bytes are equal.
            # Verify every raw body, then allow only byte-identical decoded data.
            results = [self._load_record(path, record) for record in candidates.values()]
            if results and all(result[0] == 200 and result == results[0] for result in results):
                return results[0]
            return 409, b"Ambiguous preserved revision", "text/plain"
        record = next(iter(candidates.values()))
        return self._load_record(path, record)

    def _load_record(self, path, record):
        digest = record.get("sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            return 500, b"Invalid preserved web checksum", "text/plain"
        cache_key = (path, digest)
        if cache_key in self.cache:
            return 200, self.cache[cache_key][0], self.cache[cache_key][1]
        try:
            body_path = (self.cache_directory / (digest + ".body")).resolve(strict=True)
            if body_path.parent != self.cache_directory:
                return 500, b"Preserved body outside cache", "text/plain"
            raw = body_path.read_bytes()
        except OSError:
            return 503, b"Preserved body unavailable", "text/plain"
        if hashlib.sha256(raw).hexdigest() != digest:
            return 500, b"Preserved web checksum mismatch", "text/plain"
        mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
        if mime in TEXT_MIME_TYPES:
            try:
                raw.decode("utf-8")
            except UnicodeDecodeError:
                try:
                    raw = decode_text(raw)[0].encode("utf-8")
                except Exception:
                    return 500, b"Could not decode preserved web text", "text/plain"
            mime += "; charset=utf-8"
        self.cache[cache_key] = (raw, mime)
        return 200, raw, mime


__all__ = ["PreservedWebStore"]
