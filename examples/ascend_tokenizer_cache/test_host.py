"""Native Router + HTTP transport checks; the model endpoint is simulated."""

import json
import threading
import unittest
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from openjiuwen import Router
from run_host import execute


class HostTests(unittest.TestCase):
    def setUp(self):
        self.requests = []
        self.status = 200
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                payload = json.loads(
                    self.rfile.read(int(self.headers["Content-Length"]))
                )
                owner.requests.append((self.path, payload))
                self.send_response(owner.status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(
                    json.dumps(
                        {
                            "choices": [{"message": {"content": "fixture"}}],
                            "usage": {"prompt_tokens": 3},
                        }
                    ).encode()
                )

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.router = Router.from_config(
            {
                "algorithm": "passthrough",
                "state": {"backend": "memory"},
                "targets": {"models": ["first", "second"]},
            }
        )
        self.backends = {
            name: {
                "base_url": f"http://127.0.0.1:{self.server.server_port}",
                "model": "local-model",
            }
            for name in ["first", "second"]
        }
        self.messages = [{"role": "user", "content": "你好"}]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def test_native_selection_dispatch_preserves_messages(self):
        result = execute(self.router, self.backends, self.messages, "success")
        self.assertEqual(result["selected_model_id"], "first")
        path, payload = self.requests[-1]
        self.assertEqual(path, "/v1/chat/completions")
        self.assertEqual(payload["messages"], self.messages)
        self.assertEqual(payload["model"], "local-model")
        self.assertNotIn("tokenizer_cache_gb", payload)

    def test_rate_limit_feedback_excludes_unavailable_target(self):
        self.status = 429
        with self.assertRaises(urllib.error.HTTPError):
            execute(self.router, self.backends, self.messages, "limited")
        self.status = 200
        result = execute(self.router, self.backends, self.messages, "limited")
        self.assertEqual(result["selected_model_id"], "second")

    def test_unknown_target_does_not_dispatch(self):
        with self.assertRaisesRegex(ValueError, "no registered backend"):
            execute(self.router, {}, self.messages, "unknown")
        self.assertFalse(self.requests)


if __name__ == "__main__":
    unittest.main()
