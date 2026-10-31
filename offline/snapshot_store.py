"""Explicit, read-only MyPage snapshot import. No network or payment actions."""
import hashlib
import json
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit
import re
from web_audit import decode_text


def import_snapshot(source, digest, output):
    source, output = Path(source), Path(output)
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    matches = [r for r in manifest
               if r["path"] == "/api/page/MyPage" and r["sha256"] == digest]
    if not matches:
        raise ValueError("Snapshot is not a cached MyPage response")
    raw = (source / (digest + ".body")).read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("Snapshot checksum mismatch")
    data = json.loads(decode_text(raw)[0])
    if not isinstance(data, dict) or not isinstance(data.get("gameUser"), dict):
        raise ValueError("Missing account identity")
    user = data["gameUser"]
    identity = user.get("userId", user.get("id"))
    if identity is None:
        raise ValueError("Unknown account identity")
    # Preserve exactly one response; never merge historical incremental lists.
    payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
    output.mkdir(parents=True, exist_ok=True)
    target = output / "mypage.json"
    if target.exists():
        raise FileExistsError("Refusing to overwrite an imported snapshot")
    target.write_bytes(payload)
    metadata = {
        "source_sha256": digest,
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
        "account_fingerprint": hashlib.sha256(str(identity).encode()).hexdigest(),
        "snapshot_time": data.get("currentTime"),
        "read_only": True,
        "complete_save": False,
    }
    (output / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return metadata


class SnapshotStore:
    def __init__(self, root):
        root = Path(root)
        self.metadata = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
        self.payload = (root / "mypage.json").read_bytes()
        if hashlib.sha256(self.payload).hexdigest() != self.metadata["payload_sha256"]:
            raise ValueError("Imported snapshot checksum mismatch")

    def page_payload(self):
        return self.payload

    def resolve(self, path):
        # Replay one complete snapshot; value is a requested-model hint, not a
        # selector for another historical response. Never merge cached versions.
        invalid = (400, b'{"error":"Invalid snapshot request"}', "application/json")
        if len(path) > 8192:
            return invalid
        try:
            url = urlsplit(path)
            if url.scheme or url.netloc or url.fragment:
                return invalid
            if url.path != "/api/page/MyPage":
                return 501, b'{"error":"Offline endpoint not implemented"}', "application/json"
            pairs = (parse_qsl(url.query, keep_blank_values=True,
                               strict_parsing=True, max_num_fields=2)
                     if url.query else [])
        except ValueError:
            return invalid
        seen = set()
        for key, value in pairs:
            if key in seen:
                return invalid
            seen.add(key)
            if key == "timeStamp":
                if not re.fullmatch(r"[0-9]{1,16}", value):
                    return invalid
            elif key == "value":
                if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*(?:,[A-Za-z][A-Za-z0-9_]*)*", value):
                    return invalid
            else:
                return invalid
        return 200, self.page_payload(), "application/json; charset=utf-8"
