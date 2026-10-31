"""Regression checks for in-memory, read-only preview omissions."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from preview_snapshot import PreviewSnapshotStore


class PreviewSnapshotTests(unittest.TestCase):
    def make_snapshot(self, root, data):
        payload = json.dumps(data).encode("utf-8")
        (root / "mypage.json").write_bytes(payload)
        (root / "metadata.json").write_text(json.dumps({
            "payload_sha256": hashlib.sha256(payload).hexdigest()
        }), encoding="utf-8")
        return payload

    def test_omissions_never_change_source_or_other_models(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = {"gameUser": {"id": "test"}, "userArena": {},
                    "loginBonusList": [1, 2], "birthdayItemId": 123,
                    "gachaAdvList": []}
            original = self.make_snapshot(root, data)
            metadata = (root / "metadata.json").read_bytes()
            store = PreviewSnapshotStore(root)
            result = json.loads(store.payload)
            self.assertEqual(result, {"gameUser": {"id": "test"}, "userArena": {}})
            self.assertEqual(store.omissions, {
                "gachaAdvList": 0, "birthdayItemId": 1, "loginBonusList": 2})
            self.assertEqual((root / "mypage.json").read_bytes(), original)
            self.assertEqual((root / "metadata.json").read_bytes(), metadata)
            self.assertNotIn("user", result)

    def test_missing_optional_fields_are_not_invented(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = {"gameUser": {"id": "test"}}
            self.make_snapshot(root, data)
            store = PreviewSnapshotStore(root)
            self.assertEqual(json.loads(store.payload), data)
            self.assertEqual(store.omissions, {})
            for path in ("/api/chat/list", "/api/money/init", "/api/system/logger"):
                with self.subTest(path=path):
                    self.assertEqual(store.resolve(path)[0], 501)
            self.assertEqual(store.resolve("/api/page/MyPage?timeStamp=123")[0], 200)
            self.assertEqual(store.resolve("/api/page/MyPage?unknown=1")[0], 400)

    def test_explicit_user_supplement_checks_identity_and_preserves_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = self.make_snapshot(root, {"gameUser": {"userId": "test"}})
            def source(user):
                raw = json.dumps({"user": user, "currentTime": "recorded"}).encode()
                path = root / (hashlib.sha256(raw).hexdigest() + ".body")
                path.write_bytes(raw)
                return path
            store = PreviewSnapshotStore(root, source({"id": "test"}))
            self.assertEqual(json.loads(store.payload)["user"], {"id": "test"})
            self.assertEqual((root / "mypage.json").read_bytes(), original)
            self.assertEqual(store.user_source["time"], "recorded")
            with self.assertRaisesRegex(ValueError, "account mismatch"):
                PreviewSnapshotStore(root, source({"id": "other"}))
            bad = source({"id": "test"})
            bad.write_bytes(b"{}")
            with self.assertRaisesRegex(ValueError, "checksum"):
                PreviewSnapshotStore(root, bad)

    def test_corrupt_snapshot_still_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_snapshot(root, {"gameUser": {}})
            (root / "mypage.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "checksum"):
                PreviewSnapshotStore(root)


if __name__ == "__main__":
    unittest.main()
