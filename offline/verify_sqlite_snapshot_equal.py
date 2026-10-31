"""Compare SQLite files by integrity, foreign keys, and logical dump."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import sys


def inspect(path: Path) -> dict:
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = len(db.execute("PRAGMA foreign_key_check").fetchall())
        dump = "\n".join(db.iterdump()).encode("utf8")
    return {
        "integrity": integrity,
        "foreignKeyErrors": foreign_keys,
        "logicalSha256": hashlib.sha256(dump).hexdigest(),
    }


def main() -> int:
    if len(sys.argv) < 3 or (len(sys.argv) - 3) % 2:
        raise SystemExit(
            "Usage: verify_sqlite_snapshot_equal.py CURRENT_ROOT SNAPSHOT_ROOT "
            "CURRENT_REL SNAPSHOT_REL [...]"
        )
    current_root, snapshot_root = map(Path, sys.argv[1:3])
    rows = []
    for index in range(3, len(sys.argv), 2):
        current = current_root / sys.argv[index]
        snapshot = snapshot_root / sys.argv[index + 1]
        current_state = inspect(current)
        snapshot_state = inspect(snapshot)
        equal = current_state["logicalSha256"] == snapshot_state["logicalSha256"]
        rows.append(
            {
                "current": str(current),
                "snapshot": str(snapshot),
                "currentIntegrity": current_state["integrity"],
                "currentForeignKeyErrors": current_state["foreignKeyErrors"],
                "snapshotIntegrity": snapshot_state["integrity"],
                "snapshotForeignKeyErrors": snapshot_state["foreignKeyErrors"],
                "logicalEqual": equal,
            }
        )
    print(json.dumps(rows, indent=2))
    return 0 if all(
        row["currentIntegrity"] == "ok"
        and row["snapshotIntegrity"] == "ok"
        and row["currentForeignKeyErrors"] == 0
        and row["snapshotForeignKeyErrors"] == 0
        and row["logicalEqual"]
        for row in rows
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
