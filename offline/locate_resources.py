"""Locate existing resources from prior reports without downloading or staging them."""
import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path


def catalog_keys(row):
    options = row.get("options") or {}
    values = (options.get("m_BundleName", ""), row["id"],
              row["id"].rsplit("/", 1)[-1])
    keys = {hashlib.md5(value.encode()).hexdigest() for value in values if value}
    if values[0]:
        keys.add(values[0])
    return keys


def locate(work, backup, workspace):
    work, backup, workspace = Path(work), Path(backup), Path(workspace)
    private, reports = work / "private", work / "reports"
    audit = json.loads((private / "boot-audit.json").read_text(encoding="utf-8"))
    manifest = json.loads((private / "WebBodiesWithRevisions" / "manifest.json")
                          .read_text(encoding="utf-8"))
    index = defaultdict(list)
    for row in manifest:
        index[row["path"]].append(row)
    wanted_names = {Path(row["path"]).name for row in audit["blocked"]}
    named = defaultdict(list)
    roots = (backup / "GameData", backup / "ResourceCache",
             workspace / "ロススト_Data" / "StreamingAssets")
    for root in roots:
        if root.exists():
            for path in root.rglob("*"):
                if path.is_file() and path.name in wanted_names:
                    named[path.name].append(str(path))
    blocked = []
    for row in audit["blocked"]:
        records = index[row["path"]]
        exact = [r for r in records if r.get("rev") == row["rev"]]
        variants = sorted({r["sha256"] for r in exact})
        blocked.append({
            "path": row["path"], "rev": row["rev"],
            "cached_exact_variants": variants,
            "cached_other_revisions": sorted({str(r.get("rev")) for r in records
                                             if r.get("rev") != row["rev"]}),
            "filename_candidates": named[Path(row["path"]).name],
            "classification": ("exact_cache_candidate" if len(variants) == 1 else
                               "cache_conflict" if variants else
                               "other_cached_revision" if records else
                               "filename_candidate" if named[Path(row["path"]).name] else
                               "not_found_in_scanned_sources")
        })
    mapping = json.loads((reports / "bundle-mapping.json").read_text(encoding="utf-8"))
    legacy = json.loads((reports / "missing-resources.json").read_text(encoding="utf-8"))
    for item in legacy:
        hits = [r for r in mapping if item["key"] in catalog_keys(r)]
        item["catalog_matches"] = [
            {"id": r["id"], "catalog": r["catalog"],
             "expected_hash": (r.get("options") or {}).get("m_Hash"),
             "same_version": (r.get("options") or {}).get("m_Hash") == item["hash"]}
            for r in hits]
        item["cache_file_exists"] = (backup / "ResourceCache" /
                                    (item["key"] + "_" + item["hash"])).is_file()
        item["conclusion"] = ("catalog_key_found" if hits else
                              "unmapped_legacy_key_not_proven_current_dependency")
    return {
        "sources": [str(root) for root in roots],
        "counts": dict(Counter(r["classification"] for r in blocked)),
        "blocked": blocked, "legacy_missing": legacy,
        "limitations": ("Filename candidates are not content/version matches. "
                        "Hashed bundle contents were not searched for embedded web assets. "
                        "No resources downloaded, staged, or changed.")
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work", type=Path)
    parser.add_argument("backup", type=Path)
    parser.add_argument("--workspace", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = locate(args.work, args.backup, args.workspace)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result["counts"]))
    for item in result["legacy_missing"]:
        print(item["key"], item["conclusion"], "matches:", len(item["catalog_matches"]))
