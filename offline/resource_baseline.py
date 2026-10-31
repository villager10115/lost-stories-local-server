"""Read-only exact-version audit for a candidate private-server resource baseline."""
import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from catalog_audit import bundles
from asset_store import valid_bundle_identity


def inspect_rows(rows, cache):
    cache = cache.resolve(strict=True)
    declarations = defaultdict(set)
    records = []
    for row in rows:
        options = row.get("options") or {}
        name, version = options.get("m_BundleName"), options.get("m_Hash")
        size = options.get("m_BundleSize")
        record = dict(row)
        record["matching_cache_files"] = {}
        valid = (valid_bundle_identity(name, version)
                 and type(size) is int and size > 0)
        if not valid:
            record["status"] = "invalid_options"
        else:
            declarations[row["id"]].add((name, version, size))
            filename = name + "_" + version
            path = cache / filename
            try:
                resolved = path.resolve(strict=True)
                if resolved.parent != cache:
                    record["status"] = "outside_cache"
                elif not resolved.is_file():
                    record["status"] = "not_file"
                else:
                    actual = resolved.stat().st_size
                    record["actual_size"] = actual
                    record["status"] = "exact_size" if actual == size else "size_mismatch"
                    if actual == size:
                        record["matching_cache_files"] = {"literal_bundle_name": filename}
            except FileNotFoundError:
                record["status"] = "missing"
            except OSError:
                record["status"] = "unreadable"
        records.append(record)
    conflicts = sorted(key for key, versions in declarations.items() if len(versions) > 1)
    return {
        "counts": dict(Counter(row["status"] for row in records)),
        "entries": len(records),
        "conflicting_ids": conflicts,
        "ready_by_name_and_size": bool(records) and not conflicts
            and all(row["status"] == "exact_size" for row in records),
        "limitations": "Names and sizes only; no Unity Hash128, payload or runtime compatibility verification.",
    }, records


def audit(catalogs, cache, output):
    sources, rows = [], []
    for path in catalogs:
        sources.append({"path": str(path.resolve()),
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        rows.extend(bundles(path))
    summary, records = inspect_rows(rows, cache)
    summary["catalogs"] = sources
    summary["cache"] = str(cache.resolve())
    output.mkdir(parents=True, exist_ok=True)
    for name, value in (("summary.json", summary), ("mapping.json", records),
                        ("issues.json", [r for r in records if r["status"] != "exact_size"])):
        # Never overwrite evidence from an earlier run.
        with (output / name).open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, action="append", required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    audit(args.catalog, args.cache, args.output)
