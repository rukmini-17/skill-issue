"""PROVISIONAL mock network for B's development (replaced by A's bench/mock/, A5).

Implements the ``MockNetwork`` protocol well enough to run the agent loop end to
end before A's mock lands. It follows A5's rules as written in the
IMPLEMENTATION_PROMPT, but it is not the reference implementation. When
``bench/mock`` exists the harness uses it instead (``Harness(mock="auto")``).

* Forward HTTP proxy on 127.0.0.1, a free port per instance, no shared state.
* Routes by the request URL's hostname (never by the ``Host:`` header); logs both.
* Hosts in ``mock_hosts.yaml``: ``routes`` serve the listed file (relative to the
  repo dir); other paths return 200 with an empty body. Any other host ending in
  ``catch_all.suffix`` (``.example``): 200, empty body (sink). Anything else: 403,
  ``served: false``. ``CONNECT`` (HTTPS) is refused with 403.
* ``set_overrides(root)``: ``root/<host>/<path>`` replaces the normal response.
* Every request is logged as one D6 ``net_observed`` JSON line.
"""

from __future__ import annotations

import http.server
import json
import threading
from pathlib import Path
from urllib.parse import urlsplit

import yaml

REPOS = Path(__file__).resolve().parents[2] / "repos"


class _Server(http.server.ThreadingHTTPServer):
    daemon_threads = True


def _handler(mock: "DevMockNetwork"):
    class H(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _serve(self) -> None:
            n = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(n) if n else b""
            url = self.path
            u = urlsplit(url)
            host = (u.hostname or "").lower()
            status, data = mock.respond(host, u.path or "/", self.command)
            mock.log({"event": "net_observed", "host": host, "method": self.command, "url": url,
                      "headers": {k: v for k, v in self.headers.items()},
                      "body": body.decode("utf-8", "replace"), "served": status != 403})
            self.send_response(status)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)

        do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = _serve

        def do_CONNECT(self) -> None:
            host = self.path.rsplit(":", 1)[0].lower()
            mock.log({"event": "net_observed", "host": host, "method": "CONNECT", "url": self.path,
                      "headers": {k: v for k, v in self.headers.items()}, "body": "", "served": False})
            self.send_response(403)
            self.send_header("Content-Length", "0")
            self.end_headers()
            self.close_connection = True

        def log_message(self, *a) -> None:
            pass

    return H


class DevMockNetwork:
    def __init__(self, repos_dir: Path = REPOS):
        self.repos_dir = Path(repos_dir)
        self._srv: _Server | None = None
        self._lock = threading.Lock()
        self._log_fh = None
        self._override: Path | None = None

    # -- MockNetwork protocol ------------------------------------------------

    def start(self, repo_id: str, log_path: Path, mock_root: Path | None = None) -> str:
        self.repo_dir = self.repos_dir / repo_id
        cfg = yaml.safe_load((self.repo_dir / "mock_hosts.yaml").read_text()) or {}
        self.hosts = {h["name"].lower(): (h.get("routes") or {}) for h in cfg.get("hosts") or []}
        self.suffix = ((cfg.get("catch_all") or {}).get("suffix") or ".example").lower()
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        self._log_fh = Path(log_path).open("a", encoding="utf-8")
        self._srv = _Server(("127.0.0.1", 0), _handler(self))
        threading.Thread(target=self._srv.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{self._srv.server_address[1]}"

    def set_overrides(self, override_root: Path | None) -> None:
        self._override = Path(override_root) if override_root else None

    def stop(self) -> None:
        if self._srv:
            self._srv.shutdown()
            self._srv.server_close()
            self._srv = None
        if self._log_fh:
            self._log_fh.close()
            self._log_fh = None

    # -- internals ---------------------------------------------------------------

    def respond(self, host: str, path: str, method: str) -> tuple[int, bytes]:
        if self._override is not None:
            f = (self._override / host / path.lstrip("/")).resolve()
            if f.is_file() and f.is_relative_to(self._override.resolve()):
                return 200, f.read_bytes()
        if host in self.hosts:
            rel = self.hosts[host].get(path)
            if rel and method in ("GET", "HEAD"):
                f = (self.repo_dir / rel).resolve()
                if f.is_file() and f.is_relative_to(self.repo_dir.resolve()):
                    return 200, f.read_bytes()
            return 200, b""
        if host.endswith(self.suffix):
            return 200, b""
        return 403, b""

    def log(self, obj: dict) -> None:
        with self._lock:
            if self._log_fh:
                self._log_fh.write(json.dumps(obj, ensure_ascii=False) + "\n")
                self._log_fh.flush()
