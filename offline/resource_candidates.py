"""Inspect report-selected bundle candidates and decoded cache variants, read-only."""
import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from web_audit import decode_text


def inspect(work, cache):
    work, cache = Path(work), Path(cache)
    source = work / "private" / "WebBodiesWithRevisions"
    location = json.loads((work / "private" / "resource-location.json").read_text(encoding="utf-8"))
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    mapping = json.loads((work / "reports" / "bundle-mapping.json").read_text(encoding="utf-8"))
    wanted = defaultdict(list)
    for item in location["blocked"]:
        wanted[Path(item["path"]).stem.lower()].append(item["path"])
    candidates = []
    for row in mapping:
        stem = Path(row["id"]).stem.lower()
        if stem in wanted:
            candidates.append((row, wanted[stem]))
    bundles = []
    if candidates:
        import UnityPy
        for row, paths in candidates:
            for filename in set(row["matching_cache_files"].values()):
                record = {"id": row["id"], "cache_file": filename,
                          "possible_web_paths": paths, "objects": []}
                try:
                    environment = UnityPy.load(str(cache / filename))
                    for obj in environment.objects:
                        if obj.type.name == "TextAsset":
                            data = obj.read()
                            value = data.m_Script
                            payload = value.encode("utf-8", errors="surrogateescape") if isinstance(value, str) else bytes(value)
                            record["objects"].append({"name": data.m_Name, "type": "TextAsset",
                                "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest(),
                                "webp": payload[:4] == b"RIFF" and payload[8:12] == b"WEBP"})
                        else:
                            record["objects"].append({"type": obj.type.name})
                except Exception as exc:
                    record["error"] = type(exc).__name__
                bundles.append(record)
    variants = []
    for item in location["blocked"]:
        if item["classification"] not in ("cache_conflict", "other_cached_revision"):
            continue
        records = [r for r in manifest if r["path"] == item["path"]]
        groups = defaultdict(list)
        errors = []
        seen = set()
        for row in records:
            if row["sha256"] in seen:
                continue
            seen.add(row["sha256"])
            try:
                raw = (source / (row["sha256"] + ".body")).read_bytes()
                if hashlib.sha256(raw).hexdigest() != row["sha256"]:
                    raise ValueError("Checksum mismatch")
                decoded, encoding = decode_text(raw)
                digest = hashlib.sha256(decoded.encode("utf-8")).hexdigest()
                groups[digest].append({"source": row["sha256"], "encoding": encoding})
            except Exception as exc:
                errors.append({"source": row["sha256"], "error": type(exc).__name__})
        variants.append({"path": item["path"], "requested_rev": item["rev"],
                         "raw_variant_count": len(seen), "decoded_groups": dict(groups),
                         "errors": errors})
    return {"bundle_candidates": bundles, "candidate_catalog_rows": len(candidates),
            "variants": variants,
            "limitations": "Bundle selection uses matching filename stems only, not an exhaustive embedded-asset search. No version equivalence inferred, no files staged."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work", type=Path)
    parser.add_argument("cache", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = inspect(args.work, args.cache)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("Catalog candidates:", report["candidate_catalog_rows"], "Bundles inspected:", len(report["bundle_candidates"]))
    for item in report["variants"]:
        print(item["path"], "raw:", item["raw_variant_count"], "decoded:", len(item["decoded_groups"]), "errors:", len(item["errors"]))
