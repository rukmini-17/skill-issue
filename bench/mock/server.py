"""Local HTTP forward proxy for the benchmark's `*.example` universe (A5).

- Serves each host's `routes` from `mock_hosts.yaml`.
- Unknown paths on known hosts, and any other `*.example` host, return 200 with an empty
  body (sinks). Non-`.example` hosts are refused (403, served=false).
- Routes by the request URL's hostname, never by the `Host:` header; logs both.
- Logs every request in full as `net_observed` lines to the run's log file.
- `set_overrides()` serves files from a seed's `mock_override/<host>/<path>` (late_binding).
- One instance per run on a free port; no shared state between runs.

Implements the `MockNetwork` protocol from bench.interfaces.
"""

from __future__ import annotations

import http.server
import json
import mimetypes
import threading
from pathlib import Path
from urllib.parse import urlsplit

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
REPOS_DIR = REPO_ROOT / "repos"


class _Config:
    def __init__(self, routes_by_host, base_dir, suffix, log_path, mock_root=None):
        self.routes_by_host = routes_by_host          # host -> {url_path: file_rel}
        self.base_dir = Path(base_dir)
        self.mock_root = Path(mock_root) if mock_root else None  # IC-1: run-built files
        self.suffix = suffix                           # ".example"
        self.override_root: Path | None = None
        self.log_path = Path(log_path) if log_path else None
        self.seq = 0
        self.events: list[dict] = []
        self.lock = threading.Lock()


class _Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    # silence default stderr logging
    def log_message(self, *args):
        pass

    def _host_and_path(self) -> tuple[str | None, str]:
        """Hostname from the request URL (absolute-form proxy request), never the Host header.

        Falls back to the Host header only for origin-form requests (no scheme in the URL).
        """
        target = self.path
        if "://" in target:
            parts = urlsplit(target)
            return (parts.hostname.lower() if parts.hostname else None,
                    parts.path or "/")
        # origin-form: only a Host header is available
        host = self.headers.get("Host", "")
        host = host.split(":")[0].lower() or None
        return host, (urlsplit(target).path or target or "/")

    def _read_body(self) -> str:
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length <= 0:
            return ""
        try:
            return self.rfile.read(length).decode("utf-8", errors="replace")
        except Exception:
            return ""

    def _log(self, host, url_path, body, served):
        cfg: _Config = self.server.config  # type: ignore[attr-defined]
        with cfg.lock:
            cfg.seq += 1
            seq = cfg.seq
        event = {
            "seq": seq,
            "event": "net_observed",
            "host": host,                                   # routed-by hostname (URL)
            "host_header": self.headers.get("Host"),        # logged but never used for routing
            "method": self.command,
            "url": self.path,
            "headers": {k: v for k, v in self.headers.items()},
            "body": body,
            "served": served,
        }
        cfg.events.append(event)
        if cfg.log_path is not None:
            with cfg.lock, cfg.log_path.open("a", encoding="utf-8", newline="\n") as fh:
                fh.write(json.dumps(event) + "\n")

    def _serve_bytes(self, status, body: bytes, content_type="application/octet-stream"):
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Type", content_type)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _resolve_override(self, host, url_path) -> Path | None:
        cfg: _Config = self.server.config  # type: ignore[attr-defined]
        if cfg.override_root is None:
            return None
        candidate = cfg.override_root / host / url_path.lstrip("/")
        return candidate if candidate.is_file() else None

    def _handle(self):
        cfg: _Config = self.server.config  # type: ignore[attr-defined]
        body = self._read_body()
        host, url_path = self._host_and_path()

        # non-.example hosts are refused
        if not host or not host.endswith(cfg.suffix):
            self._log(host, url_path, body, served=False)
            self._serve_bytes(403, b"", "text/plain")
            return

        # late-binding override takes precedence over the normal route
        override = self._resolve_override(host, url_path)
        if override is not None:
            data = override.read_bytes()
            self._log(host, url_path, body, served=True)
            self._serve_bytes(200, data, mimetypes.guess_type(str(override))[0] or "application/octet-stream")
            return

        routes = cfg.routes_by_host.get(host)
        if routes and url_path in routes:
            route_rel = routes[url_path]
            # IC-1: prefer files built by setup.sh in the run's mock_root, then the repo.
            target = None
            for base in (cfg.mock_root, cfg.base_dir):
                if base is None:
                    continue
                candidate = base / route_rel
                if candidate.is_file():
                    target = candidate
                    break
            if target is not None:
                data = target.read_bytes()
                self._log(host, url_path, body, served=True)
                self._serve_bytes(200, data, mimetypes.guess_type(str(target))[0] or "application/octet-stream")
                return
            # route declared but file missing (setup.sh not run): treat as a sink but flag
            self._log(host, url_path, body, served=False)
            self._serve_bytes(200, b"", "text/plain")
            return

        # known host unknown path, or any other *.example host -> sink (200 empty)
        self._log(host, url_path, body, served=False)
        self._serve_bytes(200, b"", "text/plain")

    do_GET = _handle
    do_POST = _handle
    do_PUT = _handle
    do_DELETE = _handle
    do_HEAD = _handle
    do_PATCH = _handle


class _Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class MockServer:
    """MockNetwork implementation. One instance per run."""

    def __init__(self) -> None:
        self._httpd: _Server | None = None
        self._thread: threading.Thread | None = None
        self._config: _Config | None = None

    # ----- MockNetwork protocol ----- #
    def start(self, repo_id: str, log_path: Path, mock_root: Path | None = None) -> str:
        base_dir = REPOS_DIR / repo_id
        mock_hosts = yaml.safe_load((base_dir / "mock_hosts.yaml").read_text(encoding="utf-8"))
        return self._start_with(mock_hosts, base_dir, log_path, mock_root)

    def set_overrides(self, override_root: Path | None) -> None:
        if self._config is not None:
            self._config.override_root = Path(override_root) if override_root else None

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    # ----- helpers (also used by tests with a synthetic config) ----- #
    def _start_with(self, mock_hosts: dict, base_dir, log_path, mock_root=None) -> str:
        routes_by_host = {}
        for h in mock_hosts.get("hosts", []) or []:
            routes_by_host[h["name"].lower()] = dict(h.get("routes", {}) or {})
        suffix = (mock_hosts.get("catch_all", {}) or {}).get("suffix", ".example")
        self._config = _Config(routes_by_host, base_dir, suffix, log_path, mock_root)

        self._httpd = _Server(("127.0.0.1", 0), _Handler)
        self._httpd.config = self._config  # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        port = self._httpd.server_address[1]
        return f"http://127.0.0.1:{port}"

    @property
    def events(self) -> list[dict]:
        return self._config.events if self._config else []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.stop()
