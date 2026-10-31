"""Search preserved browser responses without executing them.

Usage:
    python offline/find_preserved_text.py <preserved-dir> <needle> [suffix]
"""
import json
import sys
from pathlib import Path

from web_audit import decode_text


def main():
    root = Path(sys.argv[1])
    needle = sys.argv[2]
    suffix = sys.argv[3] if len(sys.argv) > 3 else ".js"
    records = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    seen = set()
    for record in records:
        path = record.get("path", "")
        digest = record.get("sha256", "")
        if not path.startswith("/web/") or not path.endswith(suffix):
            continue
        key = (path, digest)
        if key in seen:
            continue
        seen.add(key)
        body = (root / (digest + ".body")).read_bytes()
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError:
            text = decode_text(body)[0]
        count = text.count(needle)
        if not count:
            continue
        print(f"{path} matches={count} rev={record.get('rev')}")
        start = 0
        for _ in range(min(count, 5)):
            index = text.find(needle, start)
            print(f"  {text[max(0, index - 160):index + 240]}")
            start = index + len(needle)


if __name__ == "__main__":
    main()
