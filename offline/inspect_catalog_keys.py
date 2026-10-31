"""Read-only inspection of Addressables catalog key data.

Usage:
    python offline/inspect_catalog_keys.py <catalog.json> <substring>
"""
import base64
import json
import sys
from pathlib import Path


def main():
    catalog_path = Path(sys.argv[1])
    needle = sys.argv[2].encode("utf-8")
    catalog = json.loads(catalog_path.read_text(encoding="utf-8-sig"))

    for field, value in catalog.items():
        if not field.endswith("DataString") or not isinstance(value, str):
            continue
        data = base64.b64decode(value)
        positions = []
        start = 0
        while True:
            found = data.find(needle, start)
            if found < 0:
                break
            positions.append(found)
            start = found + 1
        print(f"{field}: {len(data)} bytes, matches={len(positions)}")
        for position in positions[:10]:
            left = max(0, position - 24)
            right = min(len(data), position + len(needle) + 24)
            print(f"  {position}: {data[left:right]!r}")

    prefixes = catalog.get("m_InternalIdPrefixes") or []
    internal = catalog.get("m_InternalIds") or []
    matches = [value for value in internal if needle.decode() in value]
    print(f"m_InternalIds: matches={len(matches)}")
    for value in matches[:10]:
        print(f"  {value}")
    print(f"m_InternalIdPrefixes: {prefixes[:5]} (count={len(prefixes)})")


if __name__ == "__main__":
    main()
