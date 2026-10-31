"""Decode Addressables bundle options without loading or executing game assemblies."""
import argparse
import base64
import hashlib
import json
import struct
from pathlib import Path


def options_at(data, offset):
    if offset < 0 or data[offset] != 7:
        return None
    pos = offset + 1
    for _ in range(2):
        length = data[pos]
        pos += 1 + length
    length, = struct.unpack_from("<i", data, pos)
    pos += 4
    if length < 0 or pos + length > len(data):
        raise ValueError("Invalid JSON object length")
    return json.loads(data[pos:pos + length].decode("utf-16le"))


def bundles(path):
    catalog = json.loads(path.read_text(encoding="utf-8-sig"))
    entries = base64.b64decode(catalog["m_EntryDataString"])
    extra = base64.b64decode(catalog["m_ExtraDataString"])
    count, = struct.unpack_from("<i", entries)
    if len(entries) != 4 + count * 28:
        raise ValueError("Unexpected entry table size")
    prefixes = catalog.get("m_InternalIdPrefixes") or []
    for index in range(count):
        internal, provider, _, _, offset, _, _ = struct.unpack_from(
            "<7i", entries, 4 + index * 28)
        name = catalog["m_InternalIds"][internal]
        if prefixes and "#" in name:
            prefix, suffix = name.split("#", 1)
            if prefix.isdigit():
                name = prefixes[int(prefix)] + suffix
        if ".bundle" not in name:
            continue
        options = options_at(extra, offset)
        yield {"catalog": path.name, "id": name,
               "provider": catalog["m_ProviderIds"][provider], "options": options}


def audit(catalog_dir, cache, output):
    rows = []
    files = {p.name for p in cache.iterdir() if p.is_file()}
    for path in sorted(catalog_dir.glob("*.json")):
        for row in bundles(path):
            options = row["options"] or {}
            bundle = options.get("m_BundleName", "")
            version = options.get("m_Hash", "")
            candidates = {}
            for label, value in (("bundle_name", bundle), ("internal_id", row["id"]),
                                 ("basename", row["id"].rsplit("/", 1)[-1])):
                if value:
                    candidates[label] = hashlib.md5(value.encode()).hexdigest() + "_" + version
            candidates["literal_bundle_name"] = bundle + "_" + version
            row["matching_cache_files"] = {
                key: value for key, value in candidates.items() if value in files}
            rows.append(row)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Bundle entries:", len(rows))
    print("Mapped entries:", sum(bool(r["matching_cache_files"]) for r in rows))
    if rows:
        print("Option field names:", sorted((rows[0]["options"] or {}).keys()))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalog_dir", type=Path)
    parser.add_argument("cache", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    audit(args.catalog_dir, args.cache, args.output)
