import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen


BASE_URL = "http://127.0.0.1:18865"
QUEST_RESOURCE_PREFIXES = (
    "/web/css/quest/",
    "/web/image/quest/",
    "/web/js/quest/",
    "/web/template/quest/",
)
CORE_RESOURCES = (
    "/web/js/quest/QuestTop.js",
    "/web/template/quest/QuestTop.html",
    "/web/css/quest/QuestTop.css",
    "/web/js/quest/DailyQuestTop.js",
    "/web/template/quest/DailyQuestTop.html",
    "/web/css/quest/DailyQuestTop.css",
)
DAILY_TYPES = (
    "CARD_REVISION_BISHOP_STAR",
    "CARD_REVISION_KNIGHT_QUEEN",
    "CARD_REVISION_ROOK_KING",
    "GOLD_CARD_EXP",
    "KMF_FAR",
    "KMF_NEAR",
)
MISSION_REWARD_ITEM_IMAGES = (
    "/web/image/item/main/item_card_crystal_bishop_silver.webp",
    "/web/image/item/main/item_card_crystal_bishop_gold.webp",
    "/web/image/item/main/item_card_crystal_star_silver.webp",
    "/web/image/item/main/item_card_crystal_star_gold.webp",
    "/web/image/item/main/item_card_crystal_knight_silver.webp",
    "/web/image/item/main/item_card_crystal_knight_gold.webp",
    "/web/image/item/main/item_card_crystal_king_bronze.webp",
    "/web/image/item/main/item_card_crystal_king_silver.webp",
    "/web/image/item/main/item_card_crystal_king_gold.webp",
)


def fetch(path, session=False):
    headers = {"X-Web-Session-Id": "quest-directory-alignment"} \
        if session else {}
    request = Request(BASE_URL + path, headers=headers)
    with urlopen(request, timeout=40) as response:
        return response.status, response.read()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--package-root",
        default=r"D:\LostStories_Private_Client_20261019",
    )
    args = parser.parse_args()
    root = Path(args.package_root).resolve(strict=True)
    static_root = root / "assets" / "static-preview"
    routes = json.loads(
        (static_root / "routes.json").read_text(encoding="utf-8")
    )["routes"]
    route_by_path = {row["path"]: row for row in routes}
    structure = json.loads(
        (
            root / "logs" / "engine-compare-live-20261020-183200" /
            "NETWORK_STRUCTURE.json"
        ).read_text(encoding="utf-8")
    )
    official_urls = {
        row.get("officialUrl", "").split("?", 1)[0]
        for row in structure["requests"]
    }
    official_quest_resources = sorted(
        (
            row for row in structure["requests"]
            if any(
                row.get("localPath", "").startswith(prefix)
                for prefix in QUEST_RESOURCE_PREFIXES
            )
        ),
        key=lambda row: row["order"],
    )
    assert len(official_quest_resources) == 65

    monitored_resources = []
    group_counts = {}
    group_directories = {}
    for row in official_quest_resources:
        path = row["localPath"]
        parts = path.split("/")
        group = parts[2]
        route = route_by_path[path]
        cache_path = static_root / "bodies" / route["body"]
        expected = hashlib.sha256(cache_path.read_bytes()).hexdigest()
        status, body = fetch(row["officialUrl"])
        actual = hashlib.sha256(body).hexdigest()
        assert status == 200
        assert actual == expected
        assert len(body) == row["probe"]["bytesRead"]
        if "?rev=" in row["officialUrl"]:
            official_revision = (
                row["officialUrl"].split("?rev=", 1)[1].split("&", 1)[0]
            )
            assert official_revision == route["rev"]

        group_counts[group] = group_counts.get(group, 0) + 1
        directory = path.rsplit("/", 1)[0]
        group_directories.setdefault(group, set()).add(directory)
        monitored_resources.append({
            "order": row["order"],
            "group": group,
            "path": path,
            "officialUrl": row["officialUrl"],
            "revision": route.get("rev", ""),
            "bytes": len(body),
            "sha256": actual,
            "matchesOfficialCache": True,
        })

    directory_structure = {}
    for group in sorted(group_directories):
        directories = sorted(group_directories[group])
        directory_structure[group] = {
            "fileCount": group_counts[group],
            "directories": directories,
        }

    core = []
    for path in CORE_RESOURCES:
        route = route_by_path[path]
        cache_path = static_root / "bodies" / route["body"]
        expected = hashlib.sha256(cache_path.read_bytes()).hexdigest()
        status, body = fetch(path + "?rev=" + route["rev"])
        actual = hashlib.sha256(body).hexdigest()
        assert status == 200
        assert actual == expected
        assert path in official_urls
        core.append({
            "path": path,
            "revision": route["rev"],
            "sha256": actual,
            "matchesOfficialCache": True,
        })

    _, raw = fetch("/api/page/QuestTop", session=True)
    quest_top = json.loads(raw)
    chapter = quest_top["userChapterList"][0]["chapter"]
    main_image = (
        "/web/image/quest/top/main/btn_main_%02d%02d.webp"
        % (chapter["partId"], chapter["chapterId"])
    )
    event = next(
        row for row in quest_top["eventList"]
        if row["eventType"] == "EXPEDITION_AREA"
    )
    ordered_images = (
        "/web/image/quest/top/event/btn_expedition_s_event_%d_off_JP.webp"
        % event["eventId"],
        "/web/image/quest/top/event/btn_expedition_s_event_%d_JP.webp"
        % event["eventId"],
        main_image,
        "/web/image/quest/top/btn_main_JP.webp",
        "/web/image/quest/top/pnl_ttl_main_JP.webp",
        "/web/image/quest/top/btn_challenge_s_JP.webp",
        "/web/image/quest/top/btn_daily_JP.webp",
        "/web/image/quest/top/btn_sidestory_JP.webp",
        "/web/image/quest/top/btn_entangle_JP.webp",
    )

    image_checks = []
    for path in ordered_images:
        status, body = fetch(path)
        assert status == 200
        assert body.startswith(b"RIFF") and body[8:12] == b"WEBP"
        image_checks.append({
            "path": path,
            "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
        })

    for path in (
        "/web/image/quest/top/main/btn_main_0101.webp",
        "/web/image/quest/top/btn_main_JP.webp",
    ):
        status, body = fetch(path)
        assert status == 200
        assert body.startswith(b"RIFF") and body[8:12] == b"WEBP"

    daily_images = [
        path for path in sorted(official_urls)
        if path.startswith("/web/image/quest/daily/")
    ]
    for path in daily_images:
        status, body = fetch(path)
        assert status == 200
        assert body.startswith(b"RIFF") and body[8:12] == b"WEBP"

    mission_image_checks = []
    for path in MISSION_REWARD_ITEM_IMAGES:
        status, body = fetch(path)
        assert status == 200
        assert body.startswith(b"RIFF") and body[8:12] == b"WEBP"
        mission_image_checks.append({
            "path": path,
            "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
        })

    _, daily_raw = fetch("/api/page/DailyQuestTop", session=True)
    daily = json.loads(daily_raw)
    quests = daily["userQuestList"]
    counts = {}
    for row in quests:
        name = row["quest"]["dailyType"]["name"]
        counts[name] = counts.get(name, 0) + 1
    assert set(counts) == set(DAILY_TYPES)
    assert counts == {
        "CARD_REVISION_BISHOP_STAR": 6,
        "CARD_REVISION_KNIGHT_QUEEN": 6,
        "CARD_REVISION_ROOK_KING": 6,
        "GOLD_CARD_EXP": 6,
        "KMF_FAR": 3,
        "KMF_NEAR": 3,
    }

    result = {
        "chapter": chapter,
        "coreResources": core,
        "officialQuestResourceCount": len(monitored_resources),
        "officialQuestResourceGroups": group_counts,
        "officialQuestDirectoryStructure": directory_structure,
        "officialQuestResourceOrder": monitored_resources,
        "questTopImageOrder": image_checks,
        "dailyQuestImageCount": len(daily_images),
        "dailyQuestTypes": counts,
        "missionRewardItemImages": mission_image_checks,
    }
    output = root / "assets" / "quest-structure"
    output.mkdir(parents=True, exist_ok=True)
    (output / "QUEST_DIRECTORY_ALIGNMENT.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    lines = [
        "# Quest directory alignment",
        "",
        (
            "Official monitor order and local hashes match for all "
            f"{len(monitored_resources)} monitored Quest resources."
        ),
        "",
        "## Monitored resource groups",
        "",
        f"- CSS: {group_counts['css']}",
        f"- images: {group_counts['image']}",
        f"- JavaScript: {group_counts['js']}",
        f"- templates: {group_counts['template']}",
        "",
        "## Monitored directory structure",
        "",
    ]
    for group in ("css", "image", "js", "template"):
        lines.extend((f"### {group}", ""))
        group_rows = [
            row for row in monitored_resources if row["group"] == group
        ]
        for directory in sorted({
            row["path"].rsplit("/", 1)[0] for row in group_rows
        }):
            file_count = sum(
                row["path"].rsplit("/", 1)[0] == directory
                for row in group_rows
            )
            lines.append(f"- `{directory}`: {file_count} files")
        lines.append("")
    lines.extend((
        "## Official monitored order",
        "",
    ))
    for group in ("css", "image", "js", "template"):
        lines.extend(("", f"### {group}", ""))
        lines.extend(
            f"- {row['order']} `{row['path']}`"
            for row in monitored_resources
            if row["group"] == group
        )
    lines.extend(("", "## QuestTop image order", ""))
    lines.extend("- " + row["path"] for row in image_checks)
    lines.extend(("", "## Daily quest types", ""))
    lines.extend(
        "- %s: %d" % (name, count) for name, count in counts.items()
    )
    lines.extend(("", "## Mission reward item images", ""))
    lines.extend(
        "- `%s`" % row["path"] for row in mission_image_checks
    )
    (output / "QUEST_DIRECTORY_ALIGNMENT.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
