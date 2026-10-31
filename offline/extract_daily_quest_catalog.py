import argparse
import json
from pathlib import Path

from web_audit import decode_text


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mission_top_body")
    parser.add_argument("output")
    args = parser.parse_args()

    source = Path(args.mission_top_body).resolve(strict=True)
    raw = source.read_bytes()
    data = json.loads(decode_text(raw)[0])
    quests = []
    for entry in data.get("userQuestList", []):
        quest = entry.get("quest")
        if not isinstance(quest, dict) or quest.get("questType") != "DAILY":
            continue
        quests.append({
            "questId": entry["questId"],
            "quest": quest,
        })
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps({"quests": quests}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({
        "output": str(output),
        "count": len(quests),
        "types": sorted({
            row["quest"].get("dailyType", {}).get("name")
            for row in quests
        }),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
