"""Serve only staged, manifest-verified native catalogs; never expose a directory."""
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit


class NativeCatalogStore:
    def __init__(self, directory, hash_directory=None):
        root = Path(directory).resolve(strict=True)
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        self.files = {}
        for name in ("catalog.json", "Binary_catalog.json", "Json_catalog.json"):
            path = (root / name).resolve(strict=True)
            if path.parent != root:
                raise ValueError("Catalog escaped staging directory")
            body = path.read_bytes()
            if hashlib.sha256(body).hexdigest() != manifest["outputs"][name]:
                raise ValueError("Staged catalog digest mismatch")
            self.files["/assets/" + name] = body
        self.hashes = {}
        if hash_directory is not None:
            hash_root = Path(hash_directory).resolve(strict=True)
            for name in ("catalog.hash", "Binary_catalog.hash", "Json_catalog.hash"):
                path = (hash_root / name).resolve(strict=True)
                if path.parent != hash_root:
                    raise ValueError("Catalog hash escaped directory")
                self.hashes["/assets/" + name] = path.read_bytes().strip()

    def resolve(self, target):
        try:
            url = urlsplit(target)
        except ValueError:
            return 400, b"Invalid catalog target", "text/plain"
        if (url.scheme or url.netloc or url.fragment or "%" in target
                or len(target) > 8192):
            return 400, b"Invalid catalog target", "text/plain"
        # Addressables appends time/rand cache busters to catalog and hash
        # requests. They never select a file or version.
        if url.query:
            try:
                pairs = parse_qsl(
                    url.query,
                    keep_blank_values=True,
                    strict_parsing=False,
                    max_num_fields=8,
                )
            except ValueError:
                return 400, b"Invalid catalog query", "text/plain"
            for key, value in pairs:
                if key == "hash" and re.fullmatch(
                    r"-?[0-9]{1,10}|[0-9a-fA-F]{32}", value
                ):
                    continue
                if key == "time" and re.fullmatch(r"[0-9]{1,24}", value):
                    continue
                if key == "rand" and re.fullmatch(
                    r"[0-9a-fA-F-]{1,64}", value
                ):
                    continue
                return 400, b"Invalid catalog query", "text/plain"
        body = self.hashes.get(url.path)
        if body is not None:
            return 200, body, "text/plain"
        body = self.files.get(url.path)
        if body is None:
            # Do not fabricate .hash files for rewritten catalogs.
            return 404, b"No staged catalog", "text/plain"
        return 200, body, "application/json"
