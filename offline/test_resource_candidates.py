import gzip
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from resource_candidates import inspect


class CandidateTests(unittest.TestCase):
    def test_compression_equivalence_preserves_distinct_content(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "private" / "WebBodiesWithRevisions"
            source.mkdir(parents=True)
            (root / "reports").mkdir()
            path = "/web/json/test.json"
            records = []
            for body in (b'{"a":1}', gzip.compress(b'{"a":1}'), b'{"a":2}'):
                digest = hashlib.sha256(body).hexdigest()
                (source / (digest + ".body")).write_bytes(body)
                records.append({"path": path, "sha256": digest})
            (source / "manifest.json").write_text(json.dumps(records))
            (root / "reports" / "bundle-mapping.json").write_text("[]")
            (root / "private" / "resource-location.json").write_text(json.dumps({
                "blocked": [{"path": path, "rev": None, "classification": "cache_conflict"}]}))
            result = inspect(root, root)
            variant = result["variants"][0]
            self.assertEqual(variant["raw_variant_count"], 3)
            self.assertEqual(len(variant["decoded_groups"]), 2)
            self.assertEqual(variant["errors"], [])
            self.assertEqual(result["candidate_catalog_rows"], 0)


if __name__ == "__main__":
    unittest.main()
