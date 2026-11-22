"""Fixtures for the B tests: a local recording HTTP proxy."""

from __future__ import annotations

import http.server
import threading

import pytest


class _Proxy(http.server.ThreadingHTTPServer):
    daemon_threads = True


class _ProxyHandler(http.server.BaseHTTPRequestHandler):
    def _any(self) -> None:
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else b""
        self.server.seen.append({"method": self.command, "path": self.path,  # type: ignore[attr-defined]
                                 "host": self.headers.get("Host"), "body": body.decode()})
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    do_GET = do_POST = _any

    def log_message(self, *a) -> None:
        pass


@pytest.fixture
def proxy():
    """A forward proxy on 127.0.0.1 that answers 200 "ok" and records every request."""
    srv = _Proxy(("127.0.0.1", 0), _ProxyHandler)
    srv.seen = []  # type: ignore[attr-defined]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv
    srv.shutdown()
    srv.server_close()

