#!/usr/bin/env python3
"""Audit generated story-battle enemy pools and fallback spawn schedules."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path("D:/codegeass/stateful_server"))
    parser.add_argument("--masterdata", type=Path,
                        default=Path("D:/LostStories_Offline/assets/masterdata"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    sys.path.insert(0, str(args.source.resolve()))
    from cgls.battle_data import BattleData

    data = BattleData(args.masterdata)
    stages = []
    for quest in data.story_catalog["quests"]:
        if quest.get("onlyStory"):
            continue
        fixture = data.get_fixture(quest["questId"])
        stage = fixture["questData"]
        events = stage["waveData"][0]["waveEventData"]
        npc_rows = {row["npcId"]: row for row in stage["npcStatusData"]}
        special = {npc_id for npc_id, row in npc_rows.items()
                   if row["isBoss"] or row["isOneOnOne"]}
        stages.append({
            "questId": quest["questId"],
            "chapterId": quest.get("chapterId"),
            "name": quest["name"],
            "mapDataNo": quest["mapDataNo"],
            "enemyNum": quest["enemyNum"],
            "enemyPool": [
                {
                    "npcId": npc_id,
                    "name": npc_rows[npc_id]["knightmareName"],
                    "special": npc_id in special,
                }
                for npc_id in quest["uniqueEnemyNpcIdList"]
            ],
            "spawnEvents": [
                {
                    "npcId": event["npcId"],
                    "timeMilliseconds": event["timeMilliSeconds"],
                    "enemyBaseIndex": int(event["parameters1"]),
                    "special": event["npcId"] in special,
                }
                for event in events
            ],
            "schedulePolicy": fixture.get("schedulePolicy", {
                "kind": "CAPTURED" if quest["questId"] in (512001, 519001)
                        else "CATALOG_GUIDE_FALLBACK",
            }),
        })

    report = {
        "generatedAt": "2026-10-30T13:30:00+08:00",
        "clientVersion": "1.6.11",
        "stageCount": len(stages),
        "specialStageCount": sum(any(row["special"] for row in stage["enemyPool"])
                                 for stage in stages),
        "schedulePolicy": {
            "kind": "CATALOG_GUIDE_FALLBACK",
            "firstSpawnMilliseconds": 3000,
            "normalIntervalMilliseconds": 6000,
            "specialEnemiesAtEnd": True,
            "specialEnemyBase": "last-enemy-base",
            "warning": "Exact wave timing is captured only for fixtures that include schedulePolicy.kind=CAPTURED.",
        },
        "guideSources": [
            "https://appmedia.jp/geass_ls/75587593",
            "https://appmedia.jp/geass_ls/75974279",
            "https://appmedia.jp/geass_ls/75516154",
            "https://smartgame-post.com/geass_loststories-beginner/",
            "https://benikikyonomori.com/code-geass-lost-stories-ch2-p22/",
        ],
        "stages": stages,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "story-stage-profiles.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8")

    by_chapter = Counter(stage["chapterId"] for stage in stages)
    special_by_chapter = Counter(
        stage["chapterId"] for stage in stages
        if any(row["special"] for row in stage["enemyPool"])
    )
    lines = [
        "# Story battle enemy and special-enemy audit",
        "",
        "Generated from client 1.6.11 static enumerations.",
        "",
        f"- Battles: {len(stages)}",
        f"- Battles with boss/one-on-one enemies: {report['specialStageCount']}",
        "- Normal spawn interval in fallback: 6.0 seconds",
        "- First spawn: 3.0 seconds",
        "- Special enemies: appended after regular enemies and sent from the last enemy base",
        "- Exact captured wave timing exists only for 512001 and 519001",
        "",
        "## Chapters",
        "",
        "| Chapter | Battles | With special enemy |",
        "| ---: | ---: | ---: |",
    ]
    for chapter in sorted(by_chapter):
        lines.append(f"| {chapter} | {by_chapter[chapter]} | {special_by_chapter[chapter]} |")
    lines += [
        "",
        "## Special-enemy examples",
        "",
        "| Quest | Stage | Enemy count | Special enemies | Final spawn |",
        "| ---: | --- | ---: | --- | ---: |",
    ]
    for stage in stages:
        special_pool = [row for row in stage["enemyPool"] if row["special"]]
        if not special_pool:
            continue
        special_events = [row for row in stage["spawnEvents"] if row["special"]]
        lines.append(
            "| %s | %s | %s | %s | %ss |" % (
                stage["questId"], stage["name"], stage["enemyNum"],
                ", ".join("%s:%s" % (row["npcId"], row["name"]) for row in special_pool),
                "%.1f" % (special_events[-1]["timeMilliseconds"] / 1000),
            )
        )
    (args.output / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf8")
    print(json.dumps({
        "stages": len(stages),
        "specialStages": report["specialStageCount"],
        "json": str(args.output / "story-stage-profiles.json"),
        "markdown": str(args.output / "REPORT.md"),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
