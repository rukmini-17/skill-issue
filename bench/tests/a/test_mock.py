"""A5 mock-network tests: routes, sinks, refusal, override, Host-header routing, logging."""

import http.client
import json
from pathlib import Path

import pytest

from bench.mock import MockServer


def _mock_hosts():
    return {
        "hosts": [
            {"name": "registry.example", "role": "allowed_registry",
             "routes": {"/lodash": "files/lodash.json"}},
            {"name": "changelogs.example", "role": "allowed_docs", "routes": {}},
        ],
        "catch_all": {"suffix": ".example"},
    }


@pytest.fixture
def server(tmp_path):
    base = tmp_path / "repo"
    (base / "files").mkdir(parents=True)
    (base / "files" / "lodash.json").write_text('{"name":"lodash"}', encoding="utf-8")
    log = tmp_path / "net.log"
    srv = MockServer()
    url = srv._start_with(_mock_hosts(), base, log)
    srv._base = base          # for tests
    srv._log = log
    srv._url = url
    try:
        yield srv
    finally:
        srv.stop()


def _request(proxy_url, url, method="GET", headers=None, body=None):
    host_port = proxy_url.replace("http://", "")
    conn = http.client.HTTPConnection(host_port, timeout=5)
    try:
        conn.request(method, url, body=body, headers=headers or {})
        resp = conn.getresponse()
        return resp.status, resp.read()
    finally:
        conn.close()


def test_known_route_serves_file(server):
    status, body = _request(server._url, "http://registry.example/lodash")
    assert status == 200
    assert body == b'{"name":"lodash"}'
    assert server.events[-1]["served"] is True


def test_unknown_path_on_known_host_is_sink(server):
    status, body = _request(server._url, "http://registry.example/does-not-exist")
    assert status == 200 and body == b""
    assert server.events[-1]["served"] is False


def test_unknown_example_host_is_sink(server):
    status, body = _request(server._url, "http://telemetry.example/collect",
                            method="POST", body="x=1")
    assert status == 200 and body == b""


def test_non_example_host_refused(server):
    status, body = _request(server._url, "http://real-evil.com/x")
    assert status == 403
    assert server.events[-1]["served"] is False


def test_routes_by_url_host_not_host_header(server):
    # URL host is a sink; Host header points at the host with the real route.
    status, body = _request(server._url, "http://evil.example/lodash",
                            headers={"Host": "registry.example"})
    assert status == 200 and body == b""          # routed by URL host (evil.example sink), not Host
    ev = server.events[-1]
    assert ev["host"] == "evil.example"
    assert ev["host_header"] == "registry.example"


def test_override_takes_precedence(server, tmp_path):
    override = tmp_path / "override"
    (override / "registry.example").mkdir(parents=True)
    (override / "registry.example" / "lodash").write_text("POISONED", encoding="utf-8")
    server.set_overrides(override)
    status, body = _request(server._url, "http://registry.example/lodash")
    assert status == 200 and body == b"POISONED"
    server.set_overrides(None)
    status, body = _request(server._url, "http://registry.example/lodash")
    assert body == b'{"name":"lodash"}'


def test_start_against_real_repo(tmp_path):
    # Exercises the MockNetwork.start(repo_id, log_path) path against a real mock_hosts.yaml.
    # Sink + refusal behaviour needs no built route files.
    srv = MockServer()
    url = srv.start("shop-web", tmp_path / "net.log")
    try:
        status, body = _request(url, "http://real-evil.com/x")
        assert status == 403
        status, body = _request(url, "http://telemetry.example/collect", method="POST", body="k=v")
        assert status == 200 and body == b""
    finally:
        srv.stop()


def test_logging_full_and_to_file(server):
    _request(server._url, "http://changelogs.example/lodash/CHANGELOG.md",
             method="POST", headers={"X-Test": "1"}, body="payload")
    ev = server.events[-1]
    assert ev["event"] == "net_observed"
    assert ev["method"] == "POST"
    assert ev["url"] == "http://changelogs.example/lodash/CHANGELOG.md"
    assert ev["body"] == "payload"
    assert ev["headers"].get("X-Test") == "1"
    # written to the log file as JSONL
    lines = [json.loads(l) for l in Path(server._log).read_text(encoding="utf-8").splitlines()]
    assert lines and lines[-1]["url"].endswith("CHANGELOG.md")
