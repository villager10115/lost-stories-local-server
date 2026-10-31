"""Create a temporary state database for an HTTP progression smoke test."""
import argparse
import json
import sqlite3
from pathlib import Path


def prepare(source, destination):
    source = Path(source)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(source)
    dst = sqlite3.connect(destination)
    try:
        src.backup(dst)
        user_id = dst.execute("select id from users order by id limit 1").fetchone()[0]
        dst.execute("delete from user_pilots where user_card_id = ?",
                    ("SMOKE-RARE4",))
        dst.execute(
            """insert into user_pilots
               (user_id, user_card_id, mst_pilot_id, mst_chara_id, level,
                experience, awakening_level, limit_break, bonds_level,
                bonds_point, skill_levels, unlocked_feature_ids, obtained_at)
               values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
            (user_id, "SMOKE-RARE4", 405001, 405, 25, 771, 0, 0, 3, 131,
             "[]", "[]"),
        )
        for item_id, quantity in {
            "EXP": 10, "EXP_P": 5, "EXP_PP": 2, "TRUST_EXP": 10
        }.items():
            dst.execute(
                """insert into user_game_items
                   (user_id, item_id, quantity, updated_at)
                   values (?, ?, ?, datetime('now'))
                   on conflict(user_id, item_id)
                   do update set quantity = excluded.quantity,
                                 updated_at = excluded.updated_at""",
                (user_id, item_id, quantity),
            )
        dst.commit()
        integrity = dst.execute("pragma integrity_check").fetchone()[0]
        foreign_keys = dst.execute("pragma foreign_key_check").fetchall()
        if integrity != "ok" or foreign_keys:
            raise RuntimeError("Temporary progression database is invalid")
        print(json.dumps({
            "database": str(destination),
            "userId": user_id,
            "userCardId": "SMOKE-RARE4",
            "integrity": integrity,
            "foreignKeyErrors": len(foreign_keys),
        }, indent=2))
    finally:
        dst.close()
        src.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    prepare(args.source, args.destination)
