#!/usr/bin/env python3
"""Audit story-battle enemy enumeration without fabricating wave timing."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


GUIDE_EVIDENCE = {
    "5-7": {
        "url": "https://appmedia.jp/geass_ls/79889513",
        "retrieved": "2026-10-30",
        "facts": [
            "Stages 1-4 apply the Shitung Pe Barrier to floating and flying player KMFs.",
            "Stage 5 raises the attack/healing penalty to 50%, doubles damage taken, and makes KMF-skill activation 100% harder.",
            "EXTRA 5 contains Raspberry, three Ash units, Nara, and twelve Nara-unit bosses.",
            "Raspberry is invincible for 30 seconds and applies KMF-skill prohibition for five seconds every ten seconds.",
            "Nara applies a five-second retreat prohibition when it appears.",
        ],
    }
}


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def classify(enemy_ids, npc_by_id):
    enemies = []
    unknown = []
    for npc_id in enemy_ids:
        row = npc_by_id.get(npc_id)
        if row is None:
            unknown.append(npc_id)
            continue
        enemies.append(
            {
                "npcId": npc_id,
                "fullName": row.get("fullName", ""),
                "enFullName": row.get("enFullName", ""),
                "knightmareFrameCustomizeId": row.get(
                    "knightmareFrameCustomizeId"
                ),
                "hp": row.get("hp"),
                "attack": row.get("attack"),
                "moveType": row.get("moveType"),
                "bossFlag": bool(row.get("bossFlag")),
                "oneOnOneFlag": bool(row.get("oneOnOneFlag")),
                "enemyType": row.get("enemyType"),
            }
        )
    special = [
        row
        for row in enemies
        if row["bossFlag"]
        or row["oneOnOneFlag"]
        or row["enemyType"] != "NORMAL"
    ]
    return enemies, special, unknown


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--masterdata", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    args = parser.parse_args()

    catalog = load(args.catalog)
    master = load(args.masterdata)
    npc_by_id = {int(row["npcId"]): row for row in master["npcList"]}
    battles = [row for row in catalog["quests"] if not row.get("onlyStory")]

    records = []
    for quest in battles:
        ids = [int(value) for value in quest.get("uniqueEnemyNpcIdList", [])]
        enemies, special, unknown = classify(ids, npc_by_id)
        base_count = len(
            [value for value in quest.get("enemyBaseLocations", "").split(";") if value]
        )
        records.append(
            {
                "questId": int(quest["questId"]),
                "name": quest.get("name", ""),
                "chapterId": quest.get("chapterId"),
                "difficulty": quest.get("difficulty"),
                "enemyNum": int(quest.get("enemyNum", 0)),
                "waveIds": quest.get("waveIds", ""),
                "waveStartSecondValues": quest.get(
                    "waveStartSecondValues", ""
                ),
                "enemyBaseLocations": quest.get("enemyBaseLocations", ""),
                "enemyBaseCount": base_count,
                "uniqueEnemyNpcIdList": ids,
                "enemies": enemies,
                "specialEnemies": special,
                "unknownEnemyNpcIds": unknown,
                "hasSpecialEnemy": bool(special),
                "exactWaveDataRetained": False,
                "specialEnemyTiming": (
                    "UNKNOWN_NOT_IN_CATALOG"
                    if special
                    else "NO_SPECIAL_ENEMY_LISTED"
                ),
            }
        )

    special_records = [row for row in records if row["hasSpecialEnemy"]]
    current = next(row for row in records if row["questId"] == 418101)
    summary = {
        "retrieved": "2026-10-30",
        "battleCount": len(records),
        "battleCountByDifficulty": dict(
            Counter(row["difficulty"] for row in records)
        ),
        "battleWithSpecialEnemyCount": len(special_records),
        "battleWithUnknownEnemyIds": sum(
            bool(row["unknownEnemyNpcIds"]) for row in records
        ),
        "currentQuest": current,
        "guideEvidence": GUIDE_EVIDENCE,
        "limitations": [
            "uniqueEnemyNpcIdList enumerates enemy variants, not spawn order.",
            "waveIds and waveStartSecondValues do not contain per-enemy timestamps.",
            "BOSS and one-on-one flags identify special enemy types but not their spawn time.",
            "Exact enemy timing requires a battle/start capture or a stage-specific guide with explicit ordering.",
        ],
    }
    args.output_json.write_text(
        json.dumps(
            {"summary": summary, "battles": records},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    lines = [
        "# Story battle enemy enumeration audit",
        "",
        "Retrieved: 2026-10-30",
        "",
        "## Summary",
        "",
        "- Battle quests: %s" % len(records),
        "- NORMAL: %s" % summary["battleCountByDifficulty"].get("NORMAL", 0),
        "- EXTRA: %s" % summary["battleCountByDifficulty"].get("EXTRA", 0),
        "- Battles listing a boss or one-on-one enemy: %s"
        % len(special_records),
        "- Battles with an unknown enemy NPC id: %s"
        % summary["battleWithUnknownEnemyIds"],
        "",
        "The client catalog proves enemy types and flags. It does not contain "
        "the per-enemy spawn timestamps for story battles.",
        "",
        "## Current chapter node 418101",
        "",
        "- Name: %s" % current["name"],
        "- Enemy count: %s" % current["enemyNum"],
        "- Wave id: %s" % current["waveIds"],
        "- Enemy bases: %s" % (current["enemyBaseLocations"] or "(none)"),
        "- Special-enemy list: %s"
        % (
            ", ".join(
                "%(npcId)s %(fullName)s" % row
                for row in current["specialEnemies"]
            )
            or "(none)"
        ),
        "",
        "For 418101 the retained enumeration contains only `210003 Camden`, "
        "a non-boss ground/range enemy. The AppMedia 5-7 guide independently "
        "documents the chapter barrier but does not provide a boss timing for "
        "stage 1.",
        "",
        "## Special-enemy battles",
        "",
        "| Quest | Name | Difficulty | Enemies | Listed special types | Timing |",
        "| ---: | --- | --- | ---: | --- | --- |",
    ]
    for row in special_records:
        labels = ", ".join(
            "%s %s%s%s"
            % (
                enemy["npcId"],
                enemy["fullName"],
                " [BOSS]" if enemy["bossFlag"] else "",
                " [1v1]" if enemy["oneOnOneFlag"] else "",
            )
            for enemy in row["specialEnemies"]
        )
        lines.append(
            "| %(questId)s | %(name)s | %(difficulty)s | %(enemyNum)s | %(labels)s | UNKNOWN |"
            % {**row, "labels": labels}
        )

    lines += [
        "",
        "## Guide evidence",
        "",
        "- [AppMedia 5-7](%(url)s), retrieved %(retrieved)s."
        % GUIDE_EVIDENCE["5-7"],
    ]
    lines.extend("- " + fact for fact in GUIDE_EVIDENCE["5-7"]["facts"])
    lines += [
        "",
        "## Safe implementation boundary",
        "",
        "- Safe: serve the exact enemy roster and special-enemy flags.",
        "- Safe: use the exact captured waves for 512001 and 519001.",
        "- Not safe: invent the appearance order or timestamp of a boss from "
        "only `uniqueEnemyNpcIdList`.",
        "- Next evidence target: a `battle/start` sample per boss stage or an "
        "explicit stage guide giving spawn order/count/time.",
    ]
    args.output_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "battleCount": len(records),
                "specialBattleCount": len(special_records),
                "json": str(args.output_json),
                "markdown": str(args.output_md),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
