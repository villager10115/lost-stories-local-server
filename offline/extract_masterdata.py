"""Extract static page models from exact cached responses with provenance."""
import argparse
import hashlib
import json
from pathlib import Path

from web_audit import decode_text


PAGE_STATIC_KEYS = {
    "/api/page/MyPage": (
        "affiliationList",
        "backgroundGroupList",
        "cardList",
        "charaList",
        "costumeList",
        "eventList",
        "itemList",
        "knightmareFrameCustomizeList",
        "knightmareFrameList",
        "levelList",
        "loginBonusCharaList",
        "loginBonusList",
        "loginBonusTotalList",
        "viewIconList",
    ),
    "/api/page/GachaTop": ("gachaExchangeList", "gachaScheduleList"),
    "/api/page/ShopTop": ("shopList",),
    "/api/page/QuestTop": ("anotherQuestDetailList", "partList"),
    "/api/page/MissionTop": ("challengeGroupList", "limitedChallengeGroupList"),
    "/api/page/DailyQuestTop": ("gimmickList", "npcList"),
    "/api/page/EventStoryTop": ("eventList", "gimmickList", "npcList"),
    "/api/page/RootEntangleTop": ("entangleChallengeQuestList", "gimmickList", "npcList"),
}


def page_slug(path):
    if not path.startswith("/api/page/") or path.count("/") != 3:
        raise ValueError("Expected a single /api/page/<name> path")
    return path.rsplit("/", 1)[-1]


def extract(cache, selections, output):
    cache = Path(cache)
    output = Path(output)
    manifest_path = output / "manifest.json"
    if manifest_path.exists():
        raise FileExistsError("Refusing to overwrite an existing extraction")
    records = json.loads((cache / "manifest.json").read_text(encoding="utf-8"))
    by_key = {(record["path"], record["sha256"]): record for record in records}
    output.mkdir(parents=True, exist_ok=True)
    pages = output / "pages"
    pages.mkdir()
    result = {
        "source_cache": str(cache.resolve()),
        "tables": [],
        "limitations": [
            "Only fields listed in PAGE_STATIC_KEYS are exported.",
            "Each table remains tied to the response timestamp shown in this manifest.",
            "Older page timestamps are not evidence that a table is current.",
        ],
    }
    for path, digest in selections:
        if path not in PAGE_STATIC_KEYS:
            raise ValueError("Unsupported page: " + path)
        record = by_key.get((path, digest))
        if record is None:
            raise ValueError("Exact response not found: %s %s" % (path, digest))
        raw = (cache / (digest + ".body")).read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError("Response checksum mismatch")
        data = json.loads(decode_text(raw)[0])
        if not isinstance(data, dict) or data.get("resultCode") != "success":
            raise ValueError("Response is not a successful page model")
        static = {}
        counts = {}
        for key in PAGE_STATIC_KEYS[path]:
            value = data.get(key)
            if not isinstance(value, list):
                raise ValueError("Missing static list %s in %s" % (key, path))
            static[key] = value
            counts[key] = len(value)
        slug = page_slug(path)
        target = pages / (slug + ".static.json")
        if target.exists():
            raise FileExistsError("Duplicate page selection")
        target.write_text(
            json.dumps(static, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        result["tables"].append({
            "path": path,
            "source_sha256": digest,
            "source_time": data.get("currentTime"),
            "file": "pages/" + target.name,
            "counts": counts,
            "bytes": target.stat().st_size,
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        })
    manifest_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cache", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--page", action="append", required=True,
        metavar="PATH=SHA256",
        help="Exact page response to extract; repeat for each page",
    )
    args = parser.parse_args()
    selections = []
    seen = set()
    for item in args.page:
        if "=" not in item:
            parser.error("--page must use PATH=SHA256")
        path, digest = item.rsplit("=", 1)
        if path in seen:
            parser.error("Duplicate page: " + path)
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            parser.error("Invalid SHA-256: " + digest)
        seen.add(path)
        selections.append((path, digest))
    result = extract(args.cache, selections, args.output)
    print("Extracted pages:", len(result["tables"]))
    for table in result["tables"]:
        print(table["path"], table["source_time"], table["counts"])


if __name__ == "__main__":
    main()
