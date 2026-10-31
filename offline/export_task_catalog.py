import argparse
import collections
import json
from pathlib import Path

from web_audit import decode_text


CATEGORY_LABELS = {
    "userWeeklyChallengeList": "weekly",
    "userDailyChallengeList": "daily",
    "userLimitedChallengeList": "limited",
    "userBeginnerChallengeList": "beginner",
    "userEntangleTotalChallengeList": "entangle",
    "userSideTotalChallengeList": "side_total",
    "userTotalChallengeList": "total",
}


def load_page(path):
    raw = Path(path).read_bytes()
    text, _encoding = decode_text(raw)
    data = json.loads(text)
    if not isinstance(data, dict) or data.get("resultCode") != "success":
        raise ValueError("MissionTop body is not a successful page response")
    return data


def flatten(page):
    rows = []
    for list_key, category in CATEGORY_LABELS.items():
        for entry in page.get(list_key, []):
            challenge = entry.get("challenge") or {}
            rows.append({
                "category": category,
                "listKey": list_key,
                "challengeId": entry.get("challengeId"),
                "groupId": challenge.get("groupId"),
                "bean": challenge.get("bean"),
                "parameter": challenge.get("parameter"),
                "count": challenge.get("count"),
                "displayName": challenge.get("displayName"),
                "rewardComment": challenge.get("rewardComment"),
                "presentType": challenge.get("presentType"),
                "itemId": challenge.get("genericCode"),
                "itemNum": challenge.get("itemNum"),
                "pageLink": challenge.get("pageLink"),
                "requiredOpenFunction": challenge.get("requiredOpenFunction"),
                "sortKey": challenge.get("sortKey"),
                "countable": challenge.get("countable"),
                "clearedCount": entry.get("clearedCount", 0),
                "clearedAt": entry.get("clearedAt"),
                "receivedAt": entry.get("receivedAt"),
                "challengeGroup": challenge.get("challengeGroup"),
                "limitedChallengeGroup":
                    challenge.get("limitedChallengeGroup"),
            })
    return rows


def summarize(rows):
    result = {}
    for category in CATEGORY_LABELS.values():
        category_rows = [row for row in rows if row["category"] == category]
        result[category] = {
            "total": len(category_rows),
            "receivedInCapture": sum(
                1 for row in category_rows if row.get("receivedAt")),
            "uniqueRewardItems": len({
                row.get("itemId") for row in category_rows if row.get("itemId")
            }),
            "rewardQuantities": dict(collections.Counter(
                row.get("itemId") for row in category_rows
                if row.get("itemId")
            ).most_common(20)),
        }
    return result


def write_markdown(rows, summary, path):
    lines = [
        "# Task catalog",
        "",
        f"Tasks: {len(rows)}",
        f"Unique challenge IDs: {len({row['challengeId'] for row in rows})}",
        "",
        "## Category summary",
        "",
        "| Category | Total | Received in capture | Reward item types |",
        "|---|---:|---:|---:|",
    ]
    for category, values in summary.items():
        lines.append(
            f"| {category} | {values['total']} | "
            f"{values['receivedInCapture']} | "
            f"{values['uniqueRewardItems']} |")
    lines.extend([
        "",
        "Historical `receivedAt` values below are capture evidence only. "
        "They must not be replayed as the new local account's claim history.",
        "",
        "## Tasks",
        "",
        "| Category | ID | Condition text | Reward text | Item | Num |",
        "|---|---:|---|---|---|---:|",
    ])
    for row in rows:
        def clean(value):
            return str(value or "").replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| {row['category']} | {row['challengeId']} | "
            f"{clean(row['displayName'])} | "
            f"{clean(row['rewardComment'])} | "
            f"{row['itemId'] or '-'} | {row['itemNum'] or 0} |")
    path.write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mission_top_body")
    parser.add_argument("--json-output", required=True)
    parser.add_argument("--markdown-output", required=True)
    args = parser.parse_args()
    page = load_page(args.mission_top_body)
    rows = flatten(page)
    summary = summarize(rows)
    result = {
        "taskCount": len(rows),
        "uniqueChallengeIds": len({
            row["challengeId"] for row in rows
        }),
        "summary": summary,
        "tasks": rows,
    }
    json_output = Path(args.json_output).resolve()
    markdown_output = Path(args.markdown_output).resolve()
    json_output.parent.mkdir(parents=True, exist_ok=True)
    markdown_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(rows, summary, markdown_output)
    print(json.dumps({
        "json": str(json_output),
        "markdown": str(markdown_output),
        "taskCount": len(rows),
        "uniqueChallengeIds": result["uniqueChallengeIds"],
        "categories": summary,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
