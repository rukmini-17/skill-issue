"""B2 acceptance on a real machine: strace monitoring inside the sandbox.

Runs in every isolation mode available on the machine where strace works
inside the sandbox (Linux). On macOS only the observer-"none" tests run.
Never contacts a real host: the only non-proxy address used is 192.0.2.1
(TEST-NET-1, RFC 5737, not routable).
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from bench.harness.monitor import CommandMonitor
from bench.harness.sandbox import docker_available, make_sandbox, netns_available
from bench.harness.skills import repo_install_set
from bench.harness.trace import EVENT_FIELDS, MockLogTailer, TraceWriter

from b_helpers import REPOS, url as _url

MODES = ["env"] + (["netns"] if netns_available() else []) + (["docker"] if docker_available() else [])


def _strace_in(mode: str) -> bool:
    if mode == "env" and subprocess.run(["sh", "-c", "command -v strace"], capture_output=True).returncode:
        return False
    return True       # netns/docker: decided by the monitor's probe below


@pytest.fixture(params=MODES)
def mon(request, tmp_path, proxy):
    mode = request.param
    if not _strace_in(mode):
        pytest.skip("strace not installed")
    root = REPOS / "orders-api"
    sb = make_sandbox(root, _url(proxy), isolation=mode, work_root=tmp_path)
    sb.build(repo_install_set(root))
    m = CommandMonitor(sb, observer="auto")
    if m.observer != "strace":
        sb.close()
        pytest.skip(f"strace unusable in {mode} sandbox: {m.probe_error}")
    yield m
    sb.close()


def _of(evs, kind):
    return [e for e in evs if e["event"] == kind]


def _check_parent_link(execs, e):
    """ppid is 0 exactly for the traced root; otherwise it is another traced process.

    Whether ``sh -c 'prog'`` forks or execs ``prog`` in place depends on the
    platform's shell (Ubuntu's dash forks, COOK's AlmaLinux bash execs in place),
    so tests must not assume either.
    """
    root = execs[0]["pid"]
    if e["pid"] == root:
        assert e["ppid"] == 0
    else:
        assert e["ppid"] not in (0, e["pid"])
        assert e["ppid"] in {x["pid"] for x in execs}


def test_script_reading_env_produces_fs_read(mon):
    ws = mon.sb.workspace
    (ws / "reports/peek.py").write_text("print(open('.env').read()[:3])\n")
    r = mon.run("python3 reports/peek.py")
    assert r.result.exit == 0, r.result.stderr
    reads = _of(r.events, "fs_read")
    env = [e for e in reads if e["path"] == ".env"]
    assert env, reads
    assert "python" in os.path.basename(env[0]["exe"] or "")
    assert any(e["path"] == "reports/peek.py" for e in reads)
    execs = _of(r.events, "proc_exec")
    py = [e for e in execs if e["argv"][:2] == ["python3", "reports/peek.py"]]
    assert py
    _check_parent_link(execs, py[0])
    assert env[0]["pid"] == py[0]["pid"]                     # the read is attributed to python


def test_writes_deletes_renames(mon):
    r = mon.run("echo a > reports/n.txt && mkdir reports/d && mv reports/n.txt reports/d/m.txt "
                "&& rm config/*.yaml 2>/dev/null; chmod 600 requirements.txt")
    ops = {(e["path"], e["op"]) for e in _of(r.events, "fs_write")}
    assert ("reports/n.txt", "create") in ops
    assert ("reports/d", "create") in ops
    assert ("reports/n.txt", "rename") in ops and ("reports/d/m.txt", "rename") in ops
    assert ("requirements.txt", "modify") in ops
    assert any(op == "delete" and p.startswith("config/") for p, op in ops)
    diff = {(e["path"], e["change"]) for e in _of(r.events, "fs_diff")}
    assert ("reports/d/m.txt", "created") in diff
    assert ("requirements.txt", "modified") in diff


def test_child_runs_workspace_script(mon):
    ws = mon.sb.workspace
    (ws / "reports/hop.sh").write_text("#!/bin/sh\ncat .env > /dev/null\n")
    os.chmod(ws / "reports/hop.sh", 0o755)
    r = mon.run("sh -c ./reports/hop.sh")
    execs = _of(r.events, "proc_exec")
    hop = [e for e in execs if e["argv"] == ["./reports/hop.sh"]]
    assert hop
    _check_parent_link(execs, hop[0])
    cat = [e for e in execs if e["argv"][:2] == ["cat", ".env"]]
    assert cat
    _check_parent_link(execs, cat[0])
    reads = [e for e in _of(r.events, "fs_read") if e["path"] == ".env"]
    assert reads and reads[0]["exe"].endswith("/cat") and reads[0]["pid"] == cat[0]["pid"]


def test_exec_in_place_is_the_root(mon):
    """``exec`` replaces the traced shell on every platform: same pid, ppid 0, effects attributed."""
    ws = mon.sb.workspace
    (ws / "reports/peek.py").write_text("print(open('.env').read()[:3])\n")
    r = mon.run("exec python3 reports/peek.py")
    assert r.result.exit == 0, r.result.stderr
    execs = _of(r.events, "proc_exec")
    assert execs[0]["argv"][0] == "/bin/sh"
    py = [e for e in execs if e["argv"][:2] == ["python3", "reports/peek.py"]]
    assert py and py[0]["pid"] == execs[0]["pid"] and py[0]["ppid"] == 0
    env = [e for e in _of(r.events, "fs_read") if e["path"] == ".env"]
    assert env and env[0]["pid"] == py[0]["pid"]
    assert "python" in os.path.basename(env[0]["exe"])


def test_forked_child_links_to_parent(mon):
    """A script that launches a child (the concealed_dependency path): the child's
    proc_exec has ppid == the parent python's pid and the child's read is its own."""
    ws = mon.sb.workspace
    (ws / "reports/child.py").write_text("open('.env').read()\n")
    (ws / "reports/parent.py").write_text(
        "import subprocess, sys\n"
        "subprocess.run([sys.executable, 'reports/child.py'], check=True)\n")
    r = mon.run("python3 reports/parent.py")
    assert r.result.exit == 0, r.result.stderr
    execs = _of(r.events, "proc_exec")
    parent = [e for e in execs if e["argv"][1:2] == ["reports/parent.py"]]
    child = [e for e in execs if e["argv"][1:2] == ["reports/child.py"]]
    assert parent and child
    assert child[0]["pid"] != parent[0]["pid"]
    assert child[0]["ppid"] == parent[0]["pid"]
    env = [e for e in _of(r.events, "fs_read") if e["path"] == ".env"]
    assert env and env[0]["pid"] == child[0]["pid"]


def test_symlink_escape_and_outside_paths_not_reported(mon):
    r = mon.run("ln -s /etc/hostname reports/h && cat reports/h /etc/passwd > /dev/null")
    reads = [e["path"] for e in _of(r.events, "fs_read")]
    assert "reports/h" not in reads and not any(p.startswith("/") or ".." in p for p in reads)
    assert ("reports/h", "create") in {(e["path"], e["op"]) for e in _of(r.events, "fs_write")}


def test_connects_outside_proxy_are_recorded(mon, proxy):
    py = ("import socket, urllib.request as u\n"
          "print(u.urlopen('http://templates.example/x', timeout=10).read())\n"
          "s = socket.socket(); s.settimeout(2)\n"
          "try: s.connect(('192.0.2.1', 80))\n"
          "except OSError as e: print('blocked', e)\n")
    (mon.sb.workspace / "reports/c.py").write_text(py)
    r = mon.run("python3 reports/c.py")
    assert r.result.exit == 0, r.result.stderr
    assert any(s["host"] == "templates.example" for s in proxy.seen)
    dests = [(c["addr"], c["port"]) for c in r.connects]
    assert ("192.0.2.1", 80) in dests
    assert mon.sb.proxy_inside() not in dests                 # the proxy itself is not reported
    if mon.sb.isolation != "env":
        assert all(c["result"] != "ok" for c in r.connects)
    assert not _of(r.events, "net_connect")                    # pending IC-2
    assert all("exe" not in e for e in _of(r.events, "proc_exec"))
    mon.ic2 = True
    r = mon.run("python3 reports/c.py")
    assert _of(r.events, "net_connect")
    py = [e for e in _of(r.events, "proc_exec") if e["argv"][:1] == ["python3"]]
    assert py and os.path.isabs(py[0]["exe"]) and os.path.basename(py[0]["exe"]).startswith("python")


def test_full_trace_lines_follow_d6(mon, tmp_path, proxy):
    log = tmp_path / "mock.jsonl"
    log.write_text(json.dumps({"event": "net_observed", "host": "templates.example", "method": "GET",
                               "url": "http://templates.example/x", "headers": {}, "body": "",
                               "served": True}) + "\n")
    tail = MockLogTailer(log)
    trace = tmp_path / "trace.jsonl"
    with TraceWriter(trace) as tw:
        args = {"cmd": "cat .env > /dev/null; echo ok > reports/t.txt"}
        tw.tool("run_command", args, "requested")
        r = mon.run(args["cmd"])
        tw.events(r.events)
        tw.events(tail.drain())
        tw.tool("run_command", args, "completed", exit=r.result.exit, out_bytes=len(r.result.stdout))
        tw.event("run_end", reason="done", steps=1)
    lines = [json.loads(l) for l in trace.read_text().splitlines()]
    assert [l["seq"] for l in lines] == list(range(len(lines)))
    kinds = {l.get("event") for l in lines}
    assert {"proc_exec", "fs_read", "fs_write", "fs_diff", "net_observed", "run_end"} <= kinds
    for l in lines:
        if "event" in l:
            assert set(l) == {"seq", "t", "event", *EVENT_FIELDS[l["event"]]}


@pytest.mark.parametrize("mode", MODES)
def test_observer_none_still_diffs(mode, tmp_path):
    root = REPOS / "orders-api"
    with make_sandbox(root, "http://127.0.0.1:9", isolation=mode, work_root=tmp_path) as sb:
        sb.build(repo_install_set(root))
        m = CommandMonitor(sb, observer="none")
        assert m.observer == "none"
        r = m.run("cat .env > /dev/null; echo x > reports/q.txt")
        assert r.result.exit == 0
        assert [e["event"] for e in r.events] == ["fs_diff"]
        assert r.events[0]["path"] == "reports/q.txt"


def test_observer_strace_required_raises_when_missing(tmp_path):
    if subprocess.run(["sh", "-c", "command -v strace"], capture_output=True).returncode == 0:
        pytest.skip("strace present")
    root = REPOS / "orders-api"
    with make_sandbox(root, "http://127.0.0.1:9", isolation="env", work_root=tmp_path) as sb:
        sb.build(repo_install_set(root))
        with pytest.raises(RuntimeError):
            CommandMonitor(sb, observer="strace")
        assert CommandMonitor(sb, observer="auto").observer == "none"
