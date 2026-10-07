"""A tiny OpenAI-compatible chat server for tests (no network, no real key)."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeProvider:
    """Serves ``POST /v1/chat/completions``; records what it received."""

    def __init__(self, chunks=("Привет", ", ", "мир"), status=200, plain_json=False,
                 error_body=None):
        self.chunks = list(chunks)
        self.status = status
        self.plain_json = plain_json
        self.error_body = error_body
        self.requests: list[dict] = []
        provider = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # keep test output quiet
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
                provider.requests.append(
                    {"path": self.path, "auth": self.headers.get("Authorization"), "body": body}
                )
                if provider.status != 200:
                    payload = json.dumps(provider.error_body or {"error": {"message": "nope"}})
                    self.send_response(provider.status)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(payload.encode())
                    return
                if provider.plain_json:
                    payload = json.dumps(
                        {"choices": [{"message": {"content": "".join(provider.chunks)}}]}
                    )
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(payload.encode())
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                for chunk in provider.chunks:
                    event = {"choices": [{"delta": {"content": chunk}}]}
                    self.wfile.write(f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode())
                    self.wfile.flush()
                self.wfile.write(b": keep-alive\n\ndata: [DONE]\n\n")

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}/v1"

    def __enter__(self) -> "FakeProvider":
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._server.shutdown()
        self._server.server_close()
