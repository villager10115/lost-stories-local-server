import tempfile
import unittest
from pathlib import Path

from resource_baseline import inspect_rows


def row(name="a" * 32, version="b" * 32, size=3):
    return {"catalog": "catalog.json", "id": "{Zero.Config.Environment.URL}/a.bundle",
            "options": {"m_BundleName": name, "m_Hash": version, "m_BundleSize": size}}


class BaselineTests(unittest.TestCase):
    def test_exact_and_wrong_size(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            (cache / ("a" * 32 + "_" + "b" * 32)).write_bytes(b"abc")
            summary, records = inspect_rows([row()], cache)
            self.assertTrue(summary["ready_by_name_and_size"])
            self.assertTrue(records[0]["matching_cache_files"])
            summary, records = inspect_rows([row(size=4)], cache)
            self.assertFalse(summary["ready_by_name_and_size"])
            self.assertEqual(records[0]["status"], "size_mismatch")

    def test_missing_version_conflicts_even_when_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            summary, records = inspect_rows([row(), row(version="c" * 32)], Path(directory))
            self.assertEqual(len(summary["conflicting_ids"]), 1)
            self.assertEqual(summary["counts"], {"missing": 2})
            self.assertFalse(summary["ready_by_name_and_size"])

    def test_invalid_name_and_empty_input(self):
        with tempfile.TemporaryDirectory() as directory:
            summary, records = inspect_rows([row(name="../escape")], Path(directory))
            self.assertEqual(records[0]["status"], "invalid_options")
            summary, _ = inspect_rows([], Path(directory))
            self.assertFalse(summary["ready_by_name_and_size"])


if __name__ == "__main__":
    unittest.main()
