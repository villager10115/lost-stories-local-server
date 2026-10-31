import json
import struct
import unittest
from catalog_audit import options_at


class CatalogTests(unittest.TestCase):
    def test_json_options(self):
        body = json.dumps({'m_BundleName': 'example', 'm_Hash': 'abc'}).encode('utf-16le')
        data = bytes([7, 3]) + b'asm' + bytes([4]) + b'type' + struct.pack('<i', len(body)) + body
        self.assertEqual(options_at(data, 0)['m_Hash'], 'abc')

    def test_missing_options(self):
        self.assertIsNone(options_at(b'', -1))

    def test_truncated_json(self):
        with self.assertRaises(ValueError):
            options_at(bytes([7, 0, 0]) + struct.pack('<i', 100), 0)


if __name__ == '__main__':
    unittest.main()
