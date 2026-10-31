import hashlib
import http.client
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

from account_page import AccountPage
from account_store import AccountStore
from server import LocalServer


class AccountPageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        snapshot = self.root / "snapshot"
        snapshot.mkdir()
        self.data = {"gameUser": {"id": "fictional"}, "userItemList": []}
        payload = json.dumps(self.data).encode()
        (snapshot / "mypage.json").write_bytes(payload)
        (snapshot / "metadata.json").write_text(json.dumps({
            "payload_sha256": hashlib.sha256(payload).hexdigest()}))
        self.store = AccountStore(self.root / "account.sqlite")
        self.account = self.store.import_snapshot(snapshot)
        self.page = AccountPage(self.store, self.account)

    def test_query_validation_and_database_reads(self):
        for route in ("/api/page/MyPage",
                      "/api/page/MyPage?value=gameUser%2CuserItemList&timeStamp=123"):
            status, body, _ = self.page.resolve(route)
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body), self.data)
        # Test fixture mutation only; not an exposed arbitrary-write endpoint.
        with sqlite3.connect(self.store.database) as db:
            db.execute("UPDATE models SET payload=? WHERE account=? AND name=?",
                       (json.dumps([{"id": 42}]), self.account, "userItemList"))
        self.assertEqual(json.loads(self.page.resolve("/api/page/MyPage")[1])
                         ["userItemList"], [{"id": 42}])
        for route in ("/api/page/MyPage?value=", "/api/page/MyPage?timeStamp=no",
                      "/api/page/MyPage?value=gameUser&value=gameUser",
                      "https://example.invalid/api/page/MyPage"):
            self.assertEqual(self.page.resolve(route)[0], 400)
        self.assertEqual(self.page.resolve("/api/payment")[0], 501)

    def test_authenticated_http_and_restart(self):
        previous_token = None
        for _ in range(2):
            server = LocalServer(0, self.root / "shop.sqlite",
                                 self.store.database, self.account)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                for token, expected in ((previous_token or "", 200),
                                        (server.token, 200)):
                    conn = http.client.HTTPConnection(*server.server_address, timeout=5)
                    try:
                        conn.request("GET", "/api/page/MyPage?timeStamp=123",
                                     headers={"X-Offline-Token": token})
                        response = conn.getresponse()
                        body = response.read()
                        self.assertEqual(response.status, expected)
                        if expected == 200:
                            self.assertEqual(json.loads(body), self.data)
                    finally:
                        conn.close()
                previous_token = server.token
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

    def test_unknown_account_rejected(self):
        with self.assertRaises(ValueError):
            AccountPage(self.store, "unknown")


if __name__ == "__main__":
    unittest.main()
