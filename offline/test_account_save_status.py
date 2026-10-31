import http.client
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from server import LocalServer


class AccountSaveStatusProxyTests(unittest.TestCase):
    def test_save_status_requires_session_and_forwards_to_state_service(self):
        paths = []

        class StubStateHandler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):
                paths.append(self.path)
                payload = json.dumps({
                    "resultCode": "success",
                    "hasSave": True,
                    "hadSaveAtStart": True,
                    "displayName": "Commander",
                }).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        upstream = ThreadingHTTPServer(
            ("127.0.0.1", 0), StubStateHandler)
        upstream_thread = threading.Thread(
            target=upstream.serve_forever, daemon=True)
        upstream_thread.start()

        with tempfile.TemporaryDirectory() as root:
            server = LocalServer(
                0,
                Path(root) / "save.sqlite",
                gacha_upstream="http://127.0.0.1:%d" %
                    upstream.server_address[1],
            )
            thread = threading.Thread(
                target=server.serve_forever, daemon=True)
            thread.start()
            try:
                def request(headers=None):
                    conn = http.client.HTTPConnection(
                        *server.server_address, timeout=5)
                    conn.request(
                        "GET", "/api/local/save-status", headers=headers or {})
                    response = conn.getresponse()
                    body = json.loads(response.read())
                    conn.close()
                    return response.status, body

                status, _ = request()
                self.assertEqual(status, 200)
                self.assertEqual(paths, ["/api/local/save-status"])

                status, body = request(
                    {"X-Web-Session-Id": "account-guard"})
                self.assertEqual(status, 200)
                self.assertTrue(body["hasSave"])
                self.assertTrue(body["hadSaveAtStart"])
                self.assertEqual(paths, [
                    "/api/local/save-status", "/api/local/save-status"])
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
                upstream.shutdown()
                upstream.server_close()
                upstream_thread.join()


if __name__ == "__main__":
    unittest.main()
