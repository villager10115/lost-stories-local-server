"""Audit cached web dependencies and account snapshot shapes without exposing values."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from html.parser import HTMLParser
import brotli


def decode_text(body):
    if body.startswith(b"\x1f\x8b"):
        body = gzip.decompress(body)
    else:
        try:
            return body.decode("utf-8"), "identity"
        except UnicodeDecodeError:
            body = brotli.decompress(body)
            return body.decode("utf-8"), "br"
    return body.decode("utf-8"), "gzip"


class References(HTMLParser):
    def __init__(self):
        super().__init__()
        self.references = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        key = "src" if tag == "script" else "href" if tag == "link" else None
        if key and attrs.get(key):
            self.references.append(attrs[key])


def audit(source, output):
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    paths = {r["path"] for r in manifest}
    report = {"entry_variants": [], "account_snapshots": [], "decode_errors": []}
    seen = set()
    for record in manifest:
        if record["path"] not in ("/web/index.html", "/api/page/MyPage"):
            continue
        key = (record["path"], record["sha256"])
        if key in seen:
            continue
        seen.add(key)
        body = (source / (record["sha256"] + ".body")).read_bytes()
        if hashlib.sha256(body).hexdigest() != record["sha256"]:
            raise ValueError("Cached body checksum mismatch")
        try:
            text, encoding = decode_text(body)
        except (ValueError, brotli.error, OSError):
            report["decode_errors"].append(record["sha256"])
            continue
        if record["path"] == "/web/index.html":
            parser = References()
            parser.feed(text)
            refs = []
            for ref in parser.references:
                url = urlsplit(urljoin("https://" + record["host"] + record["path"], ref))
                refs.append({"path": url.path, "same_host": url.hostname == record["host"],
                             "cached_path": url.path in paths})
            report["entry_variants"].append({"sha256": record["sha256"],
                                             "encoding": encoding, "references": refs})
        else:
            data = json.loads(text)
            game_user = data.get("gameUser")
            identity = None
            if isinstance(game_user, dict):
                identity = game_user.get("userId", game_user.get("id"))
            fingerprint = (hashlib.sha256(str(identity).encode()).hexdigest()
                           if identity is not None else None)
            report["account_snapshots"].append({
                "sha256": record["sha256"], "account_fingerprint": fingerprint,
                "current_time": data.get("currentTime"),
                "list_counts": {k: len(v) for k, v in data.items() if isinstance(v, list)},
                "field_shapes": {k: sorted(v[0]) if v and isinstance(v[0], dict) else []
                                 for k, v in data.items()
                                 if k in ("userItemList", "userCardList", "userDeckList")
                                 and isinstance(v, list)}
            })
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Entry variants:", len(report["entry_variants"]))
    snapshots = report["account_snapshots"]
    print("Account snapshots:", len(snapshots))
    print("Distinct known account fingerprints:",
          len({s["account_fingerprint"] for s in snapshots if s["account_fingerprint"]}))
    missing = sorted({r["path"] for e in report["entry_variants"]
                      for r in e["references"] if not r["cached_path"]})
    print("Missing direct entry dependency paths:", json.dumps(missing))
    print("Decode errors:", len(report["decode_errors"]))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    audit(args.source, args.output)
