import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from boot_audit import audit


class BootAuditTests(unittest.TestCase):
    def test_recursive_versions_plugins_and_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "bodies").mkdir()
            routes = []

            def asset(path, rev, source):
                body = source.encode()
                digest = hashlib.sha256(body).hexdigest()
                (root / "bodies" / digest).write_bytes(body)
                routes.append({"path": path, "rev": rev, "body": digest})
                return digest

            entry = asset("/web/index.html", None, "<html></html>")
            asset("/web/js/system/replacement.js", "entry",
                  'var fileTimeStamp={"js/main.js":"v1","js/child.js":"v2","template/a.html":"v3"};')
            asset("/web/js/common/baseConfig.js", None,
                  'var pathBlackList={main:"js/main",text:"js/lib/text"},pathWhiteList={};')
            asset("/web/js/base.js", None, 'require(["main"],function(){});')
            asset("/web/js/main.js", "v1", 'define(["./child","text!template/a.html"],function(){});')
            asset("/web/js/child.js", "wrong", 'define([]);')
            asset("/web/js/lib/text.js", None, 'define([]);')
            asset("/web/template/a.html", "v3", "<p>test</p>")
            refs = [{"path": r["path"], "rev": r["rev"]} for r in routes[1:4]]
            manifest = {"routes": routes, "conflicts": [], "entries": [
                {"source": "test", "body": entry, "references": refs,
                 "direct_dependencies_complete": True}]}
            (root / "routes.json").write_text(json.dumps(manifest))
            report = audit(root, "test")
            self.assertEqual(report["timestamp_count"], 3)
            self.assertEqual(len(report["blocked"]), 1)
            self.assertEqual(report["blocked"][0]["path"], "/web/js/child.js")
            self.assertEqual(report["blocked"][0]["rev"], "v2")
            self.assertTrue(any(r["path"] == "/web/template/a.html" and r["status"] == 200
                                for r in report["checked"]))


if __name__ == "__main__":
    unittest.main()
