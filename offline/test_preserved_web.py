import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import brotli

from preserved_web import PreservedWebStore


class PreservedWebTests(unittest.TestCase):
    def test_identical_decoded_revisions_are_not_a_content_conflict(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); records = []
            text = b'define(function () { return { init: function () {} }; });'
            for revision, raw in [('abc123', brotli.compress(text)), ('1', text)]:
                digest = hashlib.sha256(raw).hexdigest()
                (root / (digest + '.body')).write_bytes(raw)
                records.append({'path': '/web/js/example.js', 'rev': revision, 'sha256': digest})
            (root / 'manifest.json').write_text(json.dumps(records), 'utf8')
            store = PreservedWebStore(root)
            self.assertEqual(store.resolve('/web/js/example.js')[1], text)

    def test_revisions_do_not_use_cache_offsets_or_cross_contaminate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); records = []
            for revision, body, offset in [('abc123', b'official', 1), ('1', b'local', 999)]:
                digest = hashlib.sha256(body).hexdigest()
                (root / (digest + '.body')).write_bytes(body)
                records.append({'path': '/web/js/quest/QuestResult.js', 'rev': revision,
                                'sha256': digest, 'source_block': 'data_1:' + str(offset)})
            (root / 'manifest.json').write_text(json.dumps(records), 'utf8')
            store = PreservedWebStore(root)
            self.assertEqual(store.resolve('/web/js/quest/QuestResult.js')[0], 409)
            self.assertEqual(store.resolve('/web/js/quest/QuestResult.js?rev=abc123')[1], b'official')
            self.assertEqual(store.resolve('/web/js/quest/QuestResult.js?rev=1')[1], b'local')
            self.assertEqual(store.resolve('/web/js/quest/QuestResult.js?rev=abc123')[1], b'official')
            self.assertEqual(store.resolve('/web/js/quest/QuestResult.js?rev=other')[0], 404)
            self.assertEqual(store.resolve('/web/js/quest/QuestResult.js?rev=1&rev=abc123')[0], 400)
            records[1]['rev'] = 'abc123'
            (root / 'manifest.json').write_text(json.dumps(records), 'utf8')
            self.assertEqual(PreservedWebStore(root).resolve('/web/js/quest/QuestResult.js?rev=abc123')[0], 409)

    def test_serves_exact_image_and_decodes_text(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = b"RIFF\x00\x00\x00\x00WEBP"
            text = brotli.compress(b"body { color: white; }")
            image_digest = hashlib.sha256(image).hexdigest()
            text_digest = hashlib.sha256(text).hexdigest()
            (root / (image_digest + ".body")).write_bytes(image)
            (root / (text_digest + ".body")).write_bytes(text)
            (root / "manifest.json").write_text(json.dumps([
                {
                    "path": "/web/image/art.webp",
                    "sha256": image_digest,
                    "source_block": "data_1:1",
                },
                {
                    "path": "/web/css/page.css",
                    "sha256": text_digest,
                    "source_block": "data_1:2",
                },
            ]), encoding="utf-8")
            store = PreservedWebStore(root)
            self.assertEqual(store.resolve("/web/image/art.webp?v=1")[1], image)
            status, body, content_type = store.resolve("/web/css/page.css")
            self.assertEqual(status, 200)
            self.assertEqual(body, b"body { color: white; }")
            self.assertIn("text/css", content_type)
            self.assertEqual(store.resolve("/web/image/missing.webp")[0], 404)
            self.assertEqual(store.resolve("/web/../secret")[0], 404)


if __name__ == "__main__":
    unittest.main()
