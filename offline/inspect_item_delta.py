import argparse
import json
import sqlite3
from pathlib import Path


def connect_readonly(path):
    uri = Path(path).resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def table_columns(connection, table):
    return [
        row["name"] for row in connection.execute(
            f'PRAGMA table_info("{table}")')
    ]


def all_tables(connection):
    return [
        row["name"] for row in connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
    ]


def inspect(path):
    connection = connect_readonly(path)
    try:
        return {
            table: {
                "columns": table_columns(connection, table),
                "rows": connection.execute(
                    f'SELECT COUNT(*) FROM "{table}"').fetchone()[0],
            }
            for table in all_tables(connection)
        }
    finally:
        connection.close()


def primary_key_columns(connection, table):
    rows = list(connection.execute(f'PRAGMA table_info("{table}")'))
    primary = [
        row["name"] for row in sorted(rows, key=lambda item: item["pk"])
        if row["pk"]
    ]
    if primary:
        return primary
    columns = [row["name"] for row in rows]
    value_names = {
        "quantity", "count", "point", "level", "experience",
        "awakening_level", "limit_break", "bonds_level", "bonds_point",
        "free_sakuradite", "paid_sakuradite", "gold", "skip_tickets",
        "stamina", "max_stamina", "created_at", "updated_at", "seeded_at",
        "result", "response", "request_hash", "slots", "skill_levels",
        "unlocked_feature_ids", "upgrade_ranks", "skill_point", "revision",
    }
    keys = [name for name in columns if name not in value_names]
    return keys or columns[:1]


def normalized_rows(connection, table):
    key_columns = primary_key_columns(connection, table)
    rows = {}
    for row in connection.execute(f'SELECT * FROM "{table}"'):
        data = dict(row)
        key = tuple(data.get(column) for column in key_columns)
        rows[key] = data
    return key_columns, rows


def compare_tables(current_path, before_path):
    current = connect_readonly(current_path)
    before = connect_readonly(before_path)
    changes = []
    try:
        before_tables = set(all_tables(before))
        for table in all_tables(current):
            if table not in before_tables:
                changes.append({"table": table, "change": "table_added"})
                continue
            key_columns, current_rows = normalized_rows(current, table)
            _, before_rows = normalized_rows(before, table)
            for key in sorted(set(current_rows) | set(before_rows), key=str):
                old = before_rows.get(key)
                new = current_rows.get(key)
                if old == new:
                    continue
                changed = {}
                for column in sorted(set(new or {}) | set(old or {})):
                    before_value = old.get(column) if old else None
                    current_value = new.get(column) if new else None
                    if before_value == current_value:
                        continue
                    changed[column] = {
                        "before": before_value,
                        "current": current_value,
                        "delta": (
                            current_value - before_value
                            if isinstance(current_value, (int, float))
                            and isinstance(before_value, (int, float))
                            else None
                        ),
                    }
                changes.append({
                    "table": table,
                    "keyColumns": key_columns,
                    "key": list(key),
                    "change": (
                        "row_added" if old is None
                        else "row_removed" if new is None
                        else "row_changed"
                    ),
                    "columns": changed,
                })
    finally:
        current.close()
        before.close()
    return changes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("current")
    parser.add_argument("--before")
    arguments = parser.parse_args()
    print(json.dumps({
        "current": inspect(arguments.current),
        "before": inspect(arguments.before) if arguments.before else None,
        "changes": (
            compare_tables(arguments.current, arguments.before)
            if arguments.before else None
        ),
    }, indent=2))


if __name__ == "__main__":
    main()
