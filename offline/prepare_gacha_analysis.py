"""Build a read-only gacha baseline from exact cached responses."""
import argparse
import hashlib
import json
from pathlib import Path

from web_audit import decode_text


SOURCE_PATHS = (
    "/web/js/gacha/GachaAnimation.js",
    "/web/js/gacha/GachaTop.js",
    "/web/js/gacha/GachaResult.js",
    "/web/js/view/gacha/GachaBtnView.js",
    "/web/js/view/gacha/GachaSelectablePilotListView.js",
    "/web/js/view/gacha/GachaSelectPilotView.js",
    "/web/template/gacha/GachaProbability.html",
    "/web/template/gacha/GachaSelectPopup.html",
    "/web/template/gacha/GachaAnimation.html",
    "/web/template/gacha/GachaResult.html",
    "/web/css/gacha/GachaTop.css",
    "/web/css/gacha/GachaResult.css",
)


def _read(cache, record):
    raw = (cache / (record["sha256"] + ".body")).read_bytes()
    if hashlib.sha256(raw).hexdigest() != record["sha256"]:
        raise ValueError("Cached body checksum mismatch")
    text = decode_text(raw)[0]
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = None
    return raw, text, data


def _pick_latest_page(cache, manifest, path):
    candidates = [record for record in manifest if record["path"] == path]
    if not candidates:
        raise ValueError("Missing page response: " + path)
    ranked = []
    for record in candidates:
        _, _, data = _read(cache, record)
        if not isinstance(data, dict):
            continue
        ranked.append((data.get("currentTime") or "", record, data))
    if not ranked:
        raise ValueError("No valid page response for " + path)
    ranked.sort(key=lambda item: item[0])
    return ranked[-1][1], ranked[-1][2]


def _latest_resource(cache, manifest, path):
    candidates = [record for record in manifest if record["path"] == path]
    if not candidates:
        raise ValueError("Missing web resource: " + path)
    return candidates[-1]


def _draw_count(bean_kind):
    return 10 if "10" in (bean_kind or "") else 1


def build(cache, output):
    cache = Path(cache)
    output = Path(output)
    if output.exists():
        raise FileExistsError("Refusing to overwrite an existing gacha analysis")
    manifest = json.loads((cache / "manifest.json").read_text(encoding="utf-8"))
    gacha_record, gacha = _pick_latest_page(cache, manifest, "/api/page/GachaTop")
    mypage_record, mypage = _pick_latest_page(cache, manifest, "/api/page/MyPage")
    output.mkdir(parents=True)
    sources = output / "sources"
    sources.mkdir()

    source_manifest = []
    for path in SOURCE_PATHS:
        record = _latest_resource(cache, manifest, path)
        text = decode_text((cache / (record["sha256"] + ".body")).read_bytes())[0]
        name = path.rsplit("/", 1)[-1]
        target = sources / name
        target.write_text(text, encoding="utf-8")
        source_manifest.append({
            "path": path,
            "sha256": record["sha256"],
            "bytes": target.stat().st_size,
            "file": "sources/" + name,
        })

    modes = []
    schedules = []
    for schedule in gacha.get("gachaScheduleList", []):
        schedules.append({
            "id": schedule.get("id"),
            "scheduleId": schedule.get("scheduleId"),
            "gachaType": schedule.get("gachaType"),
            "enable": schedule.get("enable"),
            "displayOrder": schedule.get("displayOrder"),
            "gachaGroupId": schedule.get("gachaGroupId"),
            "gachaGroup": schedule.get("gachaGroup"),
            "schedule": schedule.get("schedule"),
            "displayCardIdList": schedule.get("displayCardIdList", []),
            "bonusCardIdList": schedule.get("bonusCardIdList", []),
        })
        for kind in schedule.get("gachaKindList", []):
            modes.append({
                "schedule_id": schedule.get("id"),
                "scheduleId": schedule.get("scheduleId"),
                "gachaType": schedule.get("gachaType"),
                "schedule_enable": schedule.get("enable"),
                "gachaKindId": kind.get("gachaKindId"),
                "beanKind": kind.get("beanKind"),
                "draw_count": _draw_count(kind.get("beanKind")),
                "gachaScheduleId": kind.get("gachaScheduleId"),
                "type": kind.get("type"),
                "needPointKind": kind.get("needPointKind"),
                "needQuantity": kind.get("needQuantity"),
                "itemId": kind.get("itemId"),
                "name": kind.get("name"),
            })

    observed = {"beanKind": set(), "needPointKind": set(), "type": set()}
    for record in manifest:
        if record["path"] != "/api/page/GachaTop":
            continue
        try:
            _, _, data = _read(cache, record)
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        for schedule in data.get("gachaScheduleList", []):
            for kind in schedule.get("gachaKindList", []):
                for key in observed:
                    value = kind.get(key)
                    if value is not None:
                        observed[key].add(str(value))

    result = {
        "source_cache": str(cache.resolve()),
        "gacha_top": {
            "source_sha256": gacha_record["sha256"],
            "source_time": gacha.get("currentTime"),
            "schedules": schedules,
        },
        "mypage": {
            "source_sha256": mypage_record["sha256"],
            "source_time": mypage.get("currentTime"),
            "userItemList": mypage.get("userItemList", []),
            "userGachaKindList": mypage.get("userGachaKindList", []),
        },
        "gacha_state": {
            "userGachaPointList": gacha.get("userGachaPointList", []),
            "userGachaGroupList": gacha.get("userGachaGroupList", []),
            "userGachaGroupPointList": gacha.get("userGachaGroupPointList", []),
            "userCardLimitBreakList": gacha.get("userCardLimitBreakList", []),
        },
        "draw_modes": modes,
        "observed_historical_values": {
            key: sorted(values) for key, values in observed.items()
        },
        "protocol_hints": {
            "draw_endpoint": "/api/gacha/draw",
            "probability_endpoint": "/api/gacha/probability",
            "draw_request": ["gachaScheduleId", "gachaBeanKind", "cardId optional for STEPSELECT10"],
            "draw_count_rule": "beanKind containing '10' means ten draws; otherwise one",
        },
        "sources": source_manifest,
    }
    (output / "gacha-mechanics.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cache", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build(args.cache, args.output)
    print("Gacha schedules:", len(result["gacha_top"]["schedules"]))
    print("Draw modes:", len(result["draw_modes"]))
    print("Observed bean kinds:", result["observed_historical_values"]["beanKind"])


if __name__ == "__main__":
    main()
