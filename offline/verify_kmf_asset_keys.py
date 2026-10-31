"""Fail closed when persisted KMF progress selects a missing weapon bundle."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.request import Request, urlopen


MAX_REVISION_CLASS = 4
WEAPON_BUNDLE_RE = re.compile(
    r"/binary_assets_binary/images/knightmareframes/"
    r"(kmf_(\d+)_weapon_(\d+)\.bundle)$",
    re.IGNORECASE,
)


def revision_class_for_revision(revision: int) -> int:
    revision = int(revision)
    if revision < 0:
        raise ValueError("KMF revision must be nonnegative")
    return min(MAX_REVISION_CLASS, revision // 3 + 1)


def weapon_bundle_paths(mapping: list[dict]) -> dict[tuple[int, int], str]:
    result = {}
    for entry in mapping:
        identifier = str(entry.get("id", ""))
        match = WEAPON_BUNDLE_RE.search(identifier)
        if not match:
            continue
        result[(int(match.group(2)), int(match.group(3)))] = match.group(1)
    return result


def validate_units(
    units: dict,
    bundle_paths: dict[tuple[int, int], str],
    base_url: str | None = None,
) -> dict:
    errors = []
    checked = []
    rows = units.get("userKnightmareFrameList", [])
    if not isinstance(rows, list):
        raise ValueError("userKnightmareFrameList must be a list")

    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            errors.append("row %d is not an object" % index)
            continue
        customization_id = row.get("customizationId")
        if customization_id in (None, ""):
            customization_id = row.get("knightmareFrameCustomizeId")
        try:
            customization_id = int(customization_id)
            revision = int(row.get("revision", 0))
            actual_class = int(row.get("revisionClass", 0))
        except (TypeError, ValueError):
            errors.append("row %d has invalid numeric fields" % index)
            continue

        expected_class = revision_class_for_revision(revision)
        if actual_class != expected_class:
            errors.append(
                "KMF %d revision %d returned revisionClass %d; expected %d"
                % (customization_id, revision, actual_class, expected_class)
            )
            continue

        bundle_path = bundle_paths.get((customization_id, expected_class))
        if not bundle_path:
            errors.append(
                "missing bundle for KMF %d revisionClass %d"
                % (customization_id, expected_class)
            )
            continue

        item = {
            "knightmareFrameCustomizeId": customization_id,
            "revision": revision,
            "revisionClass": actual_class,
            "bundle": bundle_path,
        }
        if base_url:
            asset_url = (
                base_url.rstrip("/")
                + "/assets/binary_assets_binary/images/knightmareframes/"
                + bundle_path
            )
            item["url"] = asset_url
            try:
                request = Request(asset_url, method="GET")
                with urlopen(request, timeout=10) as response:
                    prefix = response.read(8)
                    if response.status != 200:
                        raise ValueError("HTTP %d" % response.status)
                    if not prefix:
                        raise ValueError("empty response")
            except Exception as error:
                errors.append("KMF %d asset fetch failed: %s" % (
                    customization_id, error))
                continue
        checked.append(item)

    return {
        "checked": checked,
        "rowCount": len(rows),
        "checkedCount": len(checked),
        "errorCount": len(errors),
        "errors": errors,
    }


def load_units(
    state_url: str | None,
    units_path: Path | None,
) -> dict:
    if units_path is not None:
        return json.loads(units_path.read_text(encoding="utf-8"))
    if not state_url:
        raise ValueError("Either --state-url or --units is required")
    url = state_url.rstrip("/") + "/api/local/units"
    with urlopen(url, timeout=10) as response:
        if response.status != 200:
            raise ValueError("state API returned HTTP %d" % response.status)
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-url")
    parser.add_argument("--units", type=Path)
    parser.add_argument("--bundle-mapping", type=Path, required=True)
    parser.add_argument("--base-url")
    args = parser.parse_args()

    try:
        units = load_units(args.state_url, args.units)
        mapping = json.loads(
            args.bundle_mapping.read_text(encoding="utf-8"))
        if not isinstance(mapping, list):
            raise ValueError("bundle mapping must be a list")
        result = validate_units(
            units,
            weapon_bundle_paths(mapping),
            args.base_url,
        )
    except Exception as error:
        print(json.dumps({
            "errorCount": 1,
            "errors": [str(error)],
        }, ensure_ascii=False, indent=2))
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["errorCount"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
