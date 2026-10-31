import hashlib
import http.client
import threading
from server import LocalServer
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from account_store import AccountStore


class AccountStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.database = self.root / "save.sqlite"
        self.snapshot = self.root / "snapshot"
        self.snapshot.mkdir()
        self.data = {"gameUser": {"id": "test-local"}, "userItemList": [{"id": 1}]}
        self.write_snapshot(self.data)

    def write_snapshot(self, data):
        payload = json.dumps(data).encode()
        (self.snapshot / "mypage.json").write_bytes(payload)
        (self.snapshot / "metadata.json").write_text(json.dumps({
            "payload_sha256": hashlib.sha256(payload).hexdigest()}))

    def test_import_restart_idempotency_and_restore(self):
        store = AccountStore(self.database)
        account = store.import_snapshot(self.snapshot)
        self.assertEqual(account, store.import_snapshot(self.snapshot))
        self.assertEqual(AccountStore(self.database).state(account), self.data)
        backup = self.root / "backup.sqlite"
        store.backup(backup)
        restored = AccountStore.restore(backup, self.root / "restored.sqlite")
        self.assertEqual(restored.state(account), self.data)
        with self.assertRaises(FileExistsError):
            store.backup(backup)
        with self.assertRaises(FileExistsError):
            AccountStore.restore(backup, self.database)

    def test_local_account_endpoint(self):
        store = AccountStore(self.database)
        account = store.import_snapshot(self.snapshot)
        server = LocalServer(0, self.root / "shop.sqlite", self.database, account)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for token, expected in (("", 403), (server.token, 200)):
                conn = http.client.HTTPConnection(*server.server_address, timeout=5)
                try:
                    conn.request("GET", "/local/account",
                                 headers={"X-Offline-Token": token})
                    response = conn.getresponse()
                    body = json.loads(response.read())
                    self.assertEqual(response.status, expected)
                    if expected == 200:
                        self.assertEqual(body["models"], self.data)
                        self.assertFalse(body["complete_save"])
                finally:
                    conn.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_refuse_different_snapshot_without_mutation(self):
        store = AccountStore(self.database)
        account = store.import_snapshot(self.snapshot)
        self.write_snapshot({**self.data, "userItemList": []})
        with self.assertRaises(ValueError):
            store.import_snapshot(self.snapshot)
        self.assertEqual(store.state(account), self.data)

    def test_bad_checksum_and_missing_identity(self):
        store = AccountStore(self.database)
        (self.snapshot / "mypage.json").write_text("{}")
        with self.assertRaises(ValueError):
            store.import_snapshot(self.snapshot)
        self.write_snapshot({"gameUser": {}})
        with self.assertRaises(ValueError):
            store.import_snapshot(self.snapshot)
        with self.assertRaises(ValueError):
            store.state("unknown")

    def test_failed_import_rolls_back(self):
        store = AccountStore(self.database)
        self.write_snapshot({**self.data, "bad": float("nan")})
        with self.assertRaises(ValueError):
            store.import_snapshot(self.snapshot)
        with sqlite3.connect(self.database) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM accounts").fetchone()[0], 0)

    def test_unknown_version_and_missing_backup(self):
        store = AccountStore(self.database)
        with sqlite3.connect(self.database) as db:
            db.execute("PRAGMA user_version=99")
        with self.assertRaises(ValueError):
            AccountStore(self.database)
        with self.assertRaises(ValueError):
            AccountStore.restore(self.database, self.root / "restore.sqlite")
        self.assertFalse((self.root / "restore.sqlite").exists())
        with self.assertRaises(sqlite3.OperationalError):
            AccountStore.restore(self.root / "missing.sqlite", self.root / "restore.sqlite")
        self.assertFalse((self.root / "missing.sqlite").exists())


if __name__ == "__main__":
    unittest.main()
