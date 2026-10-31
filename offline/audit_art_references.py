"""Audit image references in staged and locally overridden web sources."""

import argparse
import json
import posixpath
import re
from pathlib import Path

from web_audit import decode_text


IMAGE_PATTERN = re.compile(
    r"(?P<path>(?:/web/|\.{0,2}/?)?image/[^\"'()\s<>]+?"
    r"\.(?:webp|png|jpe?g|gif|svg))",
    re.IGNORECASE,
)
SOURCE_SUFFIXES = (".js", ".html", ".css")
PILOT_PATTERN = re.compile(
    r"^/web/image/pilots/pilot_\\d{6}(?:_(?:male|female))?_"
    r"(?:m|square|l|s|full|locket)\\.png$"
)


def normalize_reference(source_path, reference):
    reference = reference.split("?", 1)[0]
    if "<" in reference or ">" in reference or "%" in reference:
        return None
    if reference.startswith("/web/"):
        path = reference
    elif reference.startswith("image/"):
        path = "/web/" + reference
    else:
        path = posixpath.normpath(
            posixpath.join(posixpath.dirname(source_path), reference)
        )
    if not path.startswith("/web/image/"):
        return None
    return path


def audit(cache_directory, staging_directory):
    cache = Path(cache_directory).resolve(strict=True)
    staging = Path(staging_directory).resolve(strict=True)
    manifest = json.loads((cache / "manifest.json").read_text(encoding="utf-8"))
    preserved = {
        record["path"]
        for record in manifest
        if isinstance(record.get("path"), str)
        and record["path"].startswith("/web/image/")
    }
    staged_manifest = json.loads(
        (staging / "routes.json").read_text(encoding="utf-8")
    )
    staged = {
        row["path"]
        for row in staged_manifest["routes"]
        if row["path"].startswith("/web/image/")
    }
    local_root = staging / "local_overrides" / "web"

    references = {}
    for record in manifest:
        path = record.get("path")
        if not isinstance(path, str) or not path.endswith(SOURCE_SUFFIXES):
            continue
        if not path.startswith("/web/"):
            continue
        raw = (cache / (record["sha256"] + ".body")).read_bytes()
        try:
            text, _ = decode_text(raw)
        except Exception:
            continue
        for match in IMAGE_PATTERN.finditer(text):
            normalized = normalize_reference(path, match.group("path"))
            if normalized:
                references.setdefault(normalized, set()).add(path)

    for source in local_root.rglob("*"):
        if not source.is_file() or not source.name.endswith(SOURCE_SUFFIXES):
            continue
        source_path = "/web/" + source.relative_to(local_root).as_posix()
        text = source.read_text(encoding="utf-8", errors="ignore")
        for match in IMAGE_PATTERN.finditer(text):
            normalized = normalize_reference(source_path, match.group("path"))
            if normalized:
                references.setdefault(normalized, set()).add(source_path)

    missing = []
    available = []
    for path, sources in sorted(references.items()):
        local = local_root / path.removeprefix("/web/")
        exists = path in preserved or path in staged or local.is_file()
        row = {
            "path": path,
            "sources": sorted(sources),
            "preserved": path in preserved,
            "staged": path in staged,
            "local": local.is_file(),
        }
        if exists or PILOT_PATTERN.fullmatch(path):
            available.append(row)
        else:
            missing.append(row)
    return {
        "reference_count": len(references),
        "available_count": len(available),
        "missing_count": len(missing),
        "missing": missing,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cache", type=Path)
    parser.add_argument("staging", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = audit(args.cache, args.staging)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    print(
        "references=%d available=%d missing=%d"
        % (
            report["reference_count"],
            report["available_count"],
            report["missing_count"],
        )
    )


if __name__ == "__main__":
    main()
