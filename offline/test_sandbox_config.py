import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from sandbox_config import configuration


class SandboxConfigTests(unittest.TestCase):
    def test_readonly_mapping_and_no_network_or_autorun(self):
        with tempfile.TemporaryDirectory() as directory:
            staging = Path(directory) / "input & assets"
            staging.mkdir()
            root = ET.fromstring(configuration(staging))
            self.assertEqual(root.findtext("Networking"), "Disable")
            self.assertEqual(root.findtext("ClipboardRedirection"), "Disable")
            self.assertEqual(root.findtext("MappedFolders/MappedFolder/ReadOnly"), "true")
            self.assertEqual(root.findtext("MappedFolders/MappedFolder/HostFolder"),
                             str(staging.resolve()))
            self.assertEqual(len(root.findall("MappedFolders/MappedFolder")), 1)
            self.assertIsNone(root.find("LogonCommand"))

    def test_invalid_mapping(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(FileNotFoundError):
                configuration(root / "missing")
            file = root / "file.txt"
            file.write_text("test")
            with self.assertRaises(ValueError):
                configuration(file)
            with self.assertRaises(ValueError):
                configuration(Path(root.anchor))


if __name__ == "__main__":
    unittest.main()
