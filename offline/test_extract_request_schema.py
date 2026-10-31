import tempfile
import unittest
from pathlib import Path

from extract_request_schema import build_schema


LINK_LIST = (
    'define([],function(e){var a={},r={gachaDraw:"/gacha/draw",'
    'moneyInitial:"/money/init"};return e.linkList=[],a.pathSet=function(){'
    'for(var a in r)e.linkList[a]="/api"+r[a]},a}));'
)

PAGE = (
    'define([],function(e,t){function x(){'
    't.ajaxPost(e.linkList.gachaDraw,{gachaScheduleId:o.gachaScheduleId},done);'
    't.ajaxGet(e.linkList.moneyInitial,"",done);'
    't.pageModelGet(this.needModelIdObj);}'
    'return{needModelIdObj:[{id:"user"},{id:"userItemList"}],'
    'template:"text!template/gacha/GachaTop.html"};}));'
)


class RequestSchemaTests(unittest.TestCase):
    def test_extracts_links_calls_and_models(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bodies = root / "bodies"
            bodies.mkdir()
            (bodies / "links").write_text(LINK_LIST, encoding="utf-8")
            (bodies / "page").write_text(PAGE, encoding="utf-8")
            server = root / "server.py"
            server.write_text(
                'if self.path == "/api/gacha/draw": pass\n',
                encoding="utf-8",
            )
            manifest = root / "manifest.json"
            manifest.write_text("[]", encoding="utf-8")
            schema = build_schema(
                root, server, minimum_links=2,
                preserved_manifest=manifest,
            )
            self.assertEqual(schema["endpointCount"], 2)
            draw = next(
                item for item in schema["endpoints"]
                if item["key"] == "gachaDraw")
            self.assertTrue(draw["implementedLocally"])
            self.assertEqual(
                draw["calls"][0]["bodyExpression"],
                "{gachaScheduleId:o.gachaScheduleId}",
            )
            self.assertEqual(
                schema["pageModelRequests"][0]["page"], "GachaTop")
            self.assertEqual(
                schema["pageModelRequests"][0]["models"],
                ["user", "userItemList"],
            )


if __name__ == "__main__":
    unittest.main()
