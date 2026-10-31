import json
import tempfile
import unittest
from pathlib import Path

from engine_compare import build_report


class EngineCompareTests(unittest.TestCase):
    def test_correlates_real_click_with_engine_operations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            click = {
                "kind": "click",
                "id": 1,
                "client": "official",
                "time": "2026-10-20T10:00:01.000000Z",
                "client_x": 12,
                "client_y": 34,
                "duration_ms": 90,
                "moved": 0,
            }
            down = dict(click, kind="click_down", client_x=11, client_y=33)
            command = {
                "source": "official",
                "operation": "command",
                "timestamp": 1792490401500,
                "path": "request",
                "rawMessage": "native://request?x=1",
            }
            request = {
                "source": "official",
                "operation": "request",
                "timestamp": 1792490401600,
                "url": "https://app.lost-stories.net/api/page/MyPage",
                "method": "GET",
            }
            (root / "click-events.jsonl").write_text(
                "\n".join(json.dumps(item) for item in (down, click)) + "\n",
                encoding="utf-8",
            )
            (root / "engine-events.jsonl").write_text(
                "\n".join(json.dumps(item) for item in (command, request)) + "\n",
                encoding="utf-8",
            )
            report = build_report(root)
            self.assertEqual(report["clickCount"], 1)
            self.assertEqual(len(report["actions"][0]["operations"]), 2)
            self.assertTrue((root / "ENGINE_COMPARISON.md").exists())


if __name__ == "__main__":
    unittest.main()
