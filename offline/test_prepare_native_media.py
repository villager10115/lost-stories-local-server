import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from prepare_native_media import prepare


class NativeMediaPreparationTests(unittest.TestCase):
    def setup_case(self, root):
        src = root / 'source'
        (src / 'Movie').mkdir(parents=True)
        body = b'preserved-exact-movie'
        (src / 'Movie/Opening.usm').write_bytes(body)
        record = {'Type': 2, 'Path': 'Movie/Opening.usm', 'Hash': hashlib.sha1(body).hexdigest().upper(),
                  'Size': len(body), 'Labels': ['default', 'prologue']}
        (src / 'filelist.json').write_text(json.dumps({'Records': [record]}))
        return src, record, body

    def test_cold_start_metadata_and_second_run(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); src, row, body = self.setup_case(root)
            dst = root / 'native'; opening = root / 'client/LocalMovie/Opening.usm'
            result = prepare(src, dst, root / 'backup', opening)
            self.assertEqual(result['copied'], 1)
            self.assertEqual(opening.read_bytes(), body)
            info = (dst / 'Movie/Opening.usm.info').read_text().split(';')
            self.assertEqual(info, ['2', row['Hash'], str(len(body)), 'default,prologue'])
            again = prepare(src, dst, root / 'backup2', opening)
            self.assertEqual((again['copied'], again['metadataRepaired']), (0, 0))

    def test_bad_source_cannot_replace_or_index_existing_payload(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); src, _, _ = self.setup_case(root)
            (src / 'Movie/Opening.usm').write_bytes(b'corrupt')
            dst = root / 'native'; (dst / 'Movie').mkdir(parents=True)
            (dst / 'Movie/Opening.usm').write_bytes(b'keep-existing')
            with self.assertRaisesRegex(ValueError, 'checksum'):
                prepare(src, dst, root / 'backup')
            self.assertEqual((dst / 'Movie/Opening.usm').read_bytes(), b'keep-existing')
            self.assertFalse((dst / 'Movie/Opening.usm.info').exists())

    def test_repairs_metadata_and_preserves_replaced_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); src, _, body = self.setup_case(root)
            dst = root / 'native'; (dst / 'Movie').mkdir(parents=True)
            (dst / 'Movie/Opening.usm').write_bytes(b'old')
            (dst / 'Movie/Opening.usm.info').write_text('stale')
            prepare(src, dst, root / 'backup')
            self.assertEqual((root / 'backup/Movie/Opening.usm').read_bytes(), b'old')
            self.assertEqual((root / 'backup/Movie/Opening.usm.info').read_text(), 'stale')
            self.assertEqual((dst / 'Movie/Opening.usm').read_bytes(), body)


if __name__ == '__main__':
    unittest.main()
