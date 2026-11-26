"""A tiny fake OpenAI-compatible server for backend tests (no model).

``FakeOpenAI(replies)`` serves ``POST /v1/chat/completions`` from a queue. Each
reply is one of:

* a message dict (``{"role": "assistant", "content": ..., "tool_calls": [...]}``),
  returned as a normal completion (``finish_reason`` from ``_finish`` if present);
* ``Err(status, message)``, returned as an OpenAI-style error body (``body=`` sends a raw one);
* ``Raw(text)``, returned as is with status 200 (broken responses);
* a callable ``(request_json) -> reply``, for replies that depend on the request.

It also answers ``GET /v1/models``, ``GET /health`` (``health`` list: status
codes to return in order, then 200) and ``GET /props`` (llama.cpp). Requests
are recorded in ``.requests``.
"""

from __future__ import annotations

import http.server
import json
import threading
from dataclasses import dataclass


@dataclass
class Err:
    status: int
    message: str = "error"
    body: str | None = None          # raw body instead of the OpenAI-style error JSON


@dataclass
class Raw:
    text: str


class FakeOpenAI:
    def __init__(self, replies=None, health=None, model_id="m"):
        self.replies = list(replies or [])
        self.health = list(health or [])
        self.model_id = model_id
        self.requests: list[dict] = []
        self.gets: list[str] = []
        fake = self

        class H(http.server.BaseHTTPRequestHandler):
            def _send(self, status, body, ctype="application/json"):
                data = body if isinstance(body, bytes) else body.encode()
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                fake.gets.append(self.path)
                if self.path == "/v1/models":
                    self._send(200, json.dumps({"object": "list", "data": [
                        {"id": fake.model_id, "object": "model", "root": "/weights/x", "max_model_len": 32768}]}))
                elif self.path == "/health":
                    st = fake.health.pop(0) if fake.health else 200
                    self._send(st, json.dumps({"status": "ok" if st == 200 else "loading"}))
                elif self.path == "/props":
                    self._send(200, json.dumps({"model_path": "/nfs/opt/models/x.gguf",
                                                "default_generation_settings": {"n_ctx": 32768}}))
                else:
                    self._send(404, "{}")

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                req = json.loads(self.rfile.read(n) or b"{}")
                fake.requests.append(req)
                r = fake.replies.pop(0) if fake.replies else {"role": "assistant", "content": "done"}
                if callable(r):
                    r = r(req)
                if isinstance(r, Err) and r.body is not None:
                    self._send(r.status, r.body, "text/plain" if not r.body.startswith("{") else "application/json")
                elif isinstance(r, Err):
                    self._send(r.status, json.dumps({"error": {"message": r.message, "type": "x", "code": r.status}}))
                elif isinstance(r, Raw):
                    self._send(200, r.text)
                else:
                    msg = dict(r)
                    finish = msg.pop("_finish", "tool_calls" if msg.get("tool_calls") else "stop")
                    self._send(200, json.dumps({
                        "id": "x", "object": "chat.completion", "created": 0, "model": req.get("model", "m"),
                        "choices": [{"index": 0, "message": msg, "finish_reason": finish}],
                        "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}}))

            def log_message(self, *a):
                pass

        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.srv.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}/v1"

    def __enter__(self):
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self.srv.shutdown()
        self.srv.server_close()


def tool_call(name: str, args: dict | str, cid: str = "c1") -> dict:
    return {"id": cid, "type": "function",
            "function": {"name": name, "arguments": args if isinstance(args, str) else json.dumps(args)}}


def write_models(path, base_url: str, backend: str = "vllm", name: str = "fake", **extra) -> str:
    """Write a one-model models.yaml for the fake server; returns the model name."""
    import yaml
    entry = {"backend": backend, "base_url": base_url, "model": "m", "family": "qwen3",
             "quantization": "bf16", "retries": 2, "retry_backoff": 0.0, "timeout": 10, **extra}
    path.write_text(yaml.safe_dump({"models": {name: entry}}))
    return name
