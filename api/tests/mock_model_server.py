"""Fixed-output OpenAI-compatible fixture for local container lifecycle tests."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/health":
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status":"ok","fixture":true}')

    def do_POST(self):
        if self.path != "/v1/completions":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= 65536:
            self.send_error(400)
            return
        request = json.loads(self.rfile.read(length))
        if request.get("model") != "ci-fixture-model" or not 1 <= request.get("max_tokens", 0) <= 256:
            self.send_error(400)
            return
        body = json.dumps({
            "choices": [{"text": "Synthetic CI fixture response."}],
            "usage": {"completion_tokens": 4},
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format, *_args):
        return


ThreadingHTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
