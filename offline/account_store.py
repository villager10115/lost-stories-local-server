"""Local authoritative save foundation. No networking or official credentials.

Snapshot models remain opaque until their gameplay contracts are implemented.
This store does not claim that a MyPage response is a complete game save.
"""
import argparse
from contextlib import closing, contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3

from snapshot_store import SnapshotStore


class AccountStore:
    VERSION = 1

    def __init__(self, database):
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, self.VERSION):
                raise ValueError("Unsupported save version")
            db.execute("""CREATE TABLE IF NOT EXISTS accounts(
                id TEXT PRIMARY KEY, source_sha256 TEXT NOT NULL,
                complete_save INTEGER NOT NULL DEFAULT 0)""")
            db.execute("""CREATE TABLE IF NOT EXISTS models(
                account TEXT NOT NULL REFERENCES accounts(id),
                name TEXT NOT NULL, payload TEXT NOT NULL,
                PRIMARY KEY(account, name))""")
            db.execute("PRAGMA user_version=1")

    @contextmanager
    def transaction(self):
        with closing(sqlite3.connect(self.database, timeout=10)) as db:
            db.execute("PRAGMA foreign_keys=ON")
            with db:
                db.execute("BEGIN IMMEDIATE")
                yield db

    def import_snapshot(self, root):
        snapshot = SnapshotStore(root)
        data = json.loads(snapshot.payload)
        if not isinstance(data, dict) or not isinstance(data.get("gameUser"), dict):
            raise ValueError("Missing account identity")
        user = data["gameUser"]
        identity = user.get("userId", user.get("id"))
        if identity is None:
            raise ValueError("Missing account identity")
        account = hashlib.sha256(str(identity).encode()).hexdigest()
        digest = hashlib.sha256(snapshot.payload).hexdigest()
        with self.transaction() as db:
            existing = db.execute(
                "SELECT source_sha256 FROM accounts WHERE id=?", (account,)
            ).fetchone()
            if existing:
                if existing[0] != digest:
                    raise ValueError("Refusing to overwrite an existing account")
                return account
            db.execute("INSERT INTO accounts(id, source_sha256) VALUES (?, ?)",
                       (account, digest))
            db.executemany("INSERT INTO models VALUES (?, ?, ?)",
                           [(account, name, json.dumps(value, ensure_ascii=False,
                                                       allow_nan=False))
                            for name, value in data.items()])
        return account

    def state(self, account):
        with closing(sqlite3.connect(self.database, timeout=10)) as db:
            with db:
                db.execute("BEGIN")
                if not db.execute("SELECT 1 FROM accounts WHERE id=?", (account,)).fetchone():
                    raise ValueError("Unknown local account")
                return {name: json.loads(payload) for name, payload in db.execute(
                    "SELECT name, payload FROM models WHERE account=?", (account,))}

    def backup(self, destination):
        """Use SQLite backup, not a live database file copy; never overwrite."""
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb"):
            pass
        try:
            with closing(sqlite3.connect(self.database, timeout=10)) as source:
                with closing(sqlite3.connect(destination)) as target:
                    source.backup(target)
                    if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                        raise ValueError("Backup integrity check failed")
        except Exception:
            destination.unlink(missing_ok=True)
            raise

    @classmethod
    def restore(cls, source, destination):
        """Validate a private backup and restore only to a new database."""
        source = Path(source)
        with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as db:
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Invalid backup")
            if db.execute("PRAGMA user_version").fetchone()[0] != cls.VERSION:
                raise ValueError("Unsupported backup version")
            db.execute("SELECT id, source_sha256, complete_save FROM accounts LIMIT 0")
            db.execute("SELECT account, name, payload FROM models LIMIT 0")
            if db.execute("PRAGMA foreign_key_check").fetchone():
                raise ValueError("Invalid backup references")
            destination = Path(destination)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb"):
                pass
            try:
                with closing(sqlite3.connect(destination)) as target:
                    db.backup(target)
            except Exception:
                destination.unlink(missing_ok=True)
                raise
        return cls(destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("import").add_argument("snapshot", type=Path)
    commands.add_parser("backup").add_argument("destination", type=Path)
    commands.add_parser("restore").add_argument("source", type=Path)
    args = parser.parse_args()
    if args.command == "restore":
        AccountStore.restore(args.source, args.database)
    else:
        store = AccountStore(args.database)
        if args.command == "import":
            account = store.import_snapshot(args.snapshot)
            print("Local account:", account)
        else:
            store.backup(args.destination)
    print("Local save operation completed; snapshot coverage is not a complete save.")


if __name__ == "__main__":
    main()
