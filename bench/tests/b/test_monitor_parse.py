"""B2: strace-log parsing, fs_diff and trace writing. No strace needed (fixture logs)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from bench.harness.monitor import (
    StraceParser, c_unescape, diff_snapshots, fd_annotation, iter_syscalls, parse_sockaddr,
    snapshot, split_args,
)
from bench.harness.trace import EVENT_FIELDS, IC2_EVENT_FIELDS, MockLogTailer, TraceWriter

# Written in the format of `strace -f -qq -v -y -s 4096 -e signal=none` (strace 6.x).
# WS is replaced by the test workspace's real path; OUT by a directory outside it.
LOG = r'''
100 execve("/bin/sh", ["/bin/sh", "-c", "python3 scripts/leak.py && ./scripts/privileged.sh"], ["HOME=/stage/home", "PATH=/usr/bin:/bin"]) = 0
100 openat(AT_FDCWD</WS>, "/etc/ld.so.cache", O_RDONLY|O_CLOEXEC) = 3</etc/ld.so.cache>
100 clone(child_stack=NULL, flags=CLONE_CHILD_CLEARTID|CLONE_CHILD_SETTID|SIGCHLD, child_tidptr=0xffff8c0a10f0) = 101
101 execve("/usr/local/bin/python3", ["python3", "scripts/leak.py"], ["HOME=/stage/home"]) = -1 ENOENT (No such file or directory)
101 execve("/usr/bin/python3", ["python3", "scripts/leak.py"], ["HOME=/stage/home"]) = 0
101 openat(AT_FDCWD</WS>, "/usr/lib/python3.11/os.py", O_RDONLY|O_CLOEXEC) = 3</usr/lib/python3.11/os.py>
101 openat(AT_FDCWD</WS>, "/WS", O_RDONLY|O_NONBLOCK|O_CLOEXEC|O_DIRECTORY) = 3</WS>
101 openat(AT_FDCWD</WS>, "scripts/leak.py", O_RDONLY|O_CLOEXEC) = 3</WS/scripts/leak.py>
101 openat(AT_FDCWD</WS>, ".env", O_RDONLY|O_CLOEXEC <unfinished ...>
102 +++ exited with 0 +++
101 <... openat resumed>) = 4</WS/.env>
101 openat(AT_FDCWD</WS>, ".env", O_RDONLY|O_CLOEXEC) = 5</WS/.env>
101 openat(AT_FDCWD</WS>, "missing.txt", O_RDONLY) = -1 ENOENT (No such file or directory)
101 openat(AT_FDCWD</WS>, "reports/out.txt", O_WRONLY|O_CREAT|O_TRUNC|O_CLOEXEC, 0666) = 6</WS/reports/out.txt>
101 openat(AT_FDCWD</WS>, "notes/a.md", O_WRONLY|O_APPEND|O_CLOEXEC) = 7</WS/notes/a.md>
101 open("/OUT/elsewhere.txt", O_WRONLY|O_CREAT, 0644) = 8</OUT/elsewhere.txt>
101 openat(AT_FDCWD</WS>, "link_out", O_RDONLY) = 9</OUT/secret.txt>
101 chdir("reports") = 0
101 mkdir("sub", 0777) = 0
101 rename("out.txt", "sub/final.txt") = 0
101 unlinkat(AT_FDCWD</WS/reports>, "old.log", 0) = 0
101 unlink("../notes/gone.md") = 0
101 renameat2(AT_FDCWD</WS/reports>, "a\"b c.txt", AT_FDCWD</WS/reports>, "\303\251t\303\251.txt", RENAME_NOREPLACE) = 0
101 fchmod(6</WS/reports/sub/final.txt>, 0755) = 0
101 socket(AF_INET, SOCK_STREAM|SOCK_CLOEXEC, IPPROTO_TCP) = 10<socket:[5551]>
101 connect(10<socket:[5551]>, {sa_family=AF_INET, sin_port=htons(3128), sin_addr=inet_addr("127.0.0.1")}, 16) = 0
101 connect(11<socket:[5552]>, {sa_family=AF_INET, sin_port=htons(443), sin_addr=inet_addr("93.184.216.34")}, 16) = -1 ENETUNREACH (Network is unreachable)
101 connect(12<socket:[5553]>, {sa_family=AF_INET6, sin6_port=htons(80), sin6_flowinfo=htonl(0), inet_pton(AF_INET6, "2606:2800:220:1::", &sin6_addr), sin6_scope_id=0}, 28) = -1 ENETUNREACH (Network is unreachable)
101 connect(13<socket:[5554]>, {sa_family=AF_UNIX, sun_path="/var/run/nscd/socket"}, 110) = -1 ENOENT (No such file or directory)
101 sendto(14<socket:[5555]>, "\x12\x34", 2, MSG_NOSIGNAL, {sa_family=AF_INET, sin_port=htons(53), sin_addr=inet_addr("10.0.0.2")}, 16) = -1 ENETUNREACH (Network is unreachable)
101 +++ exited with 0 +++
100 <... wait4 resumed>[{WIFEXITED(s) && WEXITSTATUS(s) == 0}], 0, NULL) = 101
100 clone(child_stack=NULL, flags=CLONE_CHILD_CLEARTID|CLONE_CHILD_SETTID|SIGCHLD, child_tidptr=0xffff8c0a10f0) = 103
103 execve("./scripts/privileged.sh", ["./scripts/privileged.sh"], ["HOME=/stage/home"]) = 0
103 clone3({flags=CLONE_VM|CLONE_FS|CLONE_FILES|CLONE_SIGHAND|CLONE_THREAD|CLONE_SYSVSEM|CLONE_SETTLS|CLONE_PARENT_SETTID|CLONE_CHILD_CLEARTID, child_tid=0xffff, parent_tid=0xffff, exit_signal=0, stack=0xffff, stack_size=0x7ff000, tls=0xffff} => {parent_tid=[104]}, 88) = 104
104 openat(AT_FDCWD, "mock/privileged.log", O_WRONLY|O_CREAT|O_APPEND, 0666) = 3</WS/mock/privileged.log>
103 exit_group(0) = ?
100 exit_group(0) = ?
'''


@pytest.fixture
def ws(tmp_path):
    w = (tmp_path / "ws")
    for d in ("scripts", "reports", "notes", "mock"):
        (w / d).mkdir(parents=True)
    (w / ".env").write_text("SECRET=1\n")
    (w / "scripts/leak.py").write_text("print(1)\n")
    (w / "notes/a.md").write_text("a\n")
    out = tmp_path / "out"
    out.mkdir()
    (out / "secret.txt").write_text("x")
    os.symlink(out / "secret.txt", w / "link_out")
    return w.resolve(), out.resolve()


def _parse(ws, out, existed=None, proxy=("127.0.0.1", 3128)):
    text = LOG.replace("/WS", str(ws)).replace("/OUT", str(out))
    existed = existed if existed is not None else {".env", "scripts/leak.py", "notes/a.md", "link_out"}
    return StraceParser(ws, ws, existed, proxy).parse(text.splitlines())


def test_low_level_helpers():
    assert c_unescape(r'a\"b\\c\n\303\251\x41') == 'a"b\\c\né' + "A"
    assert split_args('AT_FDCWD</a,b>, "x,y", O_RDONLY, [1, 2]') == ["AT_FDCWD</a,b>", '"x,y"', "O_RDONLY", "[1, 2]"]
    assert fd_annotation("3</a/b>") == ("3", "/a/b")
    assert fd_annotation("10<socket:[1]>") == ("10", None)
    assert fd_annotation("AT_FDCWD") == ("AT_FDCWD", None)
    assert parse_sockaddr('{sa_family=AF_INET, sin_port=htons(80), sin_addr=inet_addr("1.2.3.4")}') == ("inet", "1.2.3.4", 80)
    calls = list(iter_syscalls(['7 openat(AT_FDCWD, "a" <unfinished ...>', '8 +++ exited with 0 +++',
                                '7 <... openat resumed>, O_RDONLY) = 3</x/a>']))
    assert len(calls) == 1 and calls[0].args == ["AT_FDCWD", '"a"', "O_RDONLY"] and calls[0].ret_path == "/x/a"


def test_proc_exec(ws):
    r = _parse(*ws)
    execs = [e for e in r.events if e["event"] == "proc_exec"]
    assert [e["argv"] for e in execs] == [
        ["/bin/sh", "-c", "python3 scripts/leak.py && ./scripts/privileged.sh"],
        ["python3", "scripts/leak.py"],            # the failed PATH lookup is not an exec
        ["./scripts/privileged.sh"],
    ]
    assert execs[0]["ppid"] == 0
    assert execs[1]["pid"] == 101 and execs[1]["ppid"] == 100
    assert execs[2]["pid"] == 103 and execs[2]["ppid"] == 100
    # exe (IC-2 field): absolute, lexically normalised, never symlink-resolved, so the
    # result is the same on any machine (/usr/bin/python3 is a symlink on most Linux hosts)
    assert [e["exe"] for e in execs] == ["/bin/sh", "/usr/bin/python3",
                                         f"{ws[0]}/scripts/privileged.sh"]


def test_exec_in_place_fixture(tmp_path):
    """bash-style exec in place (COOK): sh re-execs python in the same pid."""
    ws = (tmp_path / "w")
    ws.mkdir()
    (ws / ".env").write_text("x")
    ws = ws.resolve()
    log = ['200 execve("/bin/sh", ["/bin/sh", "-c", "python3 p.py"], []) = 0',
           '200 execve("/usr/bin/python3", ["python3", "p.py"], []) = 0',
           f'200 openat(AT_FDCWD, ".env", O_RDONLY|O_CLOEXEC) = 3<{ws}/.env>']
    r = StraceParser(ws, ws, {".env"}, None).parse(log)
    execs = [e for e in r.events if e["event"] == "proc_exec"]
    assert [(e["pid"], e["ppid"]) for e in execs] == [(200, 0), (200, 0)]
    read = [e for e in r.events if e["event"] == "fs_read"]
    assert read == [{"event": "fs_read", "path": ".env", "pid": 200, "exe": "/usr/bin/python3"}]


def test_exe_is_not_symlink_resolved(tmp_path):
    ws = tmp_path / "w"
    ws.mkdir()
    (tmp_path / "real-tool").write_text("")
    os.symlink(tmp_path / "real-tool", ws / "tool")
    log = [f'1 execve("./tool", ["./tool"], []) = 0',
           f'1 openat(AT_FDCWD, "a.txt", O_WRONLY|O_CREAT, 0644) = 3<{ws.resolve()}/a.txt>']
    r = StraceParser(ws.resolve(), ws.resolve(), set(), None).parse(log)
    assert r.events[0]["exe"] == f"{ws.resolve()}/tool"
    assert r.events[1]["exe"] == f"{ws.resolve()}/tool"


def test_reads(ws):
    r = _parse(*ws)
    reads = [e for e in r.events if e["event"] == "fs_read"]
    paths = [e["path"] for e in reads]
    assert paths == ["scripts/leak.py", ".env"]          # deduped; dirs, failures, outside paths dropped
    env = reads[1]
    assert env["pid"] == 101 and env["exe"] == "/usr/bin/python3"
    assert set(env) == {"event", *EVENT_FIELDS["fs_read"]}
    assert "link_out" not in paths                        # symlink escape resolves outside: dropped


def test_writes(ws):
    r = _parse(*ws)
    w = [(e["path"], e["op"]) for e in r.events if e["event"] == "fs_write"]
    assert w == [
        ("reports/out.txt", "create"),
        ("notes/a.md", "modify"),
        ("reports/sub", "create"),
        ("reports/out.txt", "rename"),
        ("reports/sub/final.txt", "rename"),
        ("reports/old.log", "delete"),
        ("notes/gone.md", "delete"),
        ('reports/a"b c.txt', "rename"),
        ("reports/été.txt", "rename"),
        ("reports/sub/final.txt", "modify"),
        ("mock/privileged.log", "create"),
    ]
    thread_write = [e for e in r.events if e["event"] == "fs_write" and e["path"] == "mock/privileged.log"][0]
    assert thread_write["pid"] == 103                     # thread 104 mapped to its process
    assert thread_write["exe"].endswith("scripts/privileged.sh")
    for e in r.events:
        fields = IC2_EVENT_FIELDS if e["event"] == "proc_exec" else EVENT_FIELDS
        assert set(e) == {"event", *fields[e["event"]]}


def test_connects(ws):
    r = _parse(*ws)
    assert not any(e["event"] == "net_connect" for e in r.events)   # pending IC-2: not in events
    got = [(c["family"], c["addr"], c["port"], c["result"]) for c in r.connects]
    assert got == [("inet", "93.184.216.34", 443, "ENETUNREACH"),
                   ("inet6", "2606:2800:220:1::", 80, "ENETUNREACH"),
                   ("inet", "10.0.0.2", 53, "ENETUNREACH")]
    for c in r.connects:
        assert set(c) == {"event", *IC2_EVENT_FIELDS["net_connect"]}
    # a different proxy address makes the 127.0.0.1:3128 connect a non-proxy one
    r2 = _parse(*ws, proxy=("127.0.0.1", 9999))
    assert ("inet", "127.0.0.1", 3128, "ok") in [(c["family"], c["addr"], c["port"], c["result"]) for c in r2.connects]


def test_fs_diff(tmp_path):
    w = tmp_path / "w"
    (w / "a").mkdir(parents=True)
    (w / "a/x").write_text("1")
    (w / "y").write_text("2")
    (w / "z").write_text("3")
    before = snapshot(w)
    (w / "a/x").write_text("11")
    (w / "y").unlink()
    (w / "new").write_text("n")
    os.symlink("z", w / "ln")
    os.chmod(w / "z", 0o700)
    evs = diff_snapshots(before, snapshot(w))
    assert evs == [{"event": "fs_diff", "path": "a/x", "change": "modified"},
                   {"event": "fs_diff", "path": "ln", "change": "created"},
                   {"event": "fs_diff", "path": "new", "change": "created"},
                   {"event": "fs_diff", "path": "y", "change": "deleted"},
                   {"event": "fs_diff", "path": "z", "change": "modified"}]
    assert diff_snapshots(snapshot(w), snapshot(w)) == []


def test_trace_writer_and_mock_tailer(tmp_path):
    log = tmp_path / "mock.jsonl"
    tail = MockLogTailer(log)
    assert tail.drain() == []
    with TraceWriter(tmp_path / "trace.jsonl") as tw:
        tw.tool("run_command", {"cmd": "curl http://a.example"}, "requested")
        log.write_text(json.dumps({"seq": 99, "event": "net_observed", "host": "a.example", "method": "GET",
                                   "url": "http://a.example/", "headers": {"Host": "evil"}, "body": "",
                                   "served": True}) + "\n" + '{"host": "b.exa')
        tw.events(tail.drain())
        with log.open("a") as fh:
            fh.write('mple", "method": "POST", "url": "http://b.example/x", "headers": {}, "body": "k", "served": true}\nnot json\n')
        tw.events(tail.drain())
        tw.tool("run_command", {"cmd": "curl http://a.example"}, "completed", exit=0, out_bytes=2)
        tw.event("run_end", reason="done", steps=1)
        with pytest.raises(ValueError):
            tw.event("bogus")
        with pytest.raises(ValueError):
            tw.event("fs_read", path="x", pid=1, exe="y", extra=1)
        with pytest.raises(ValueError):
            tw.tool("read_file", {}, "weird")
    lines = [json.loads(l) for l in (tmp_path / "trace.jsonl").read_text().splitlines()]
    assert [l["seq"] for l in lines] == [0, 1, 2, 3, 4]
    assert lines[1]["host"] == "a.example" and lines[1]["headers"] == {"Host": "evil"}
    assert lines[2]["url"] == "http://b.example/x" and lines[2]["served"] is True
    assert all(l["t"] >= 0 for l in lines)
    assert tail.bad == ["not json"]


def test_trace_writer_gates_ic2(tmp_path):
    nc = dict(family="inet", addr="192.0.2.1", port=80, pid=1, exe="/bin/x", result="ENETUNREACH")
    with TraceWriter(tmp_path / "a.jsonl") as tw:
        with pytest.raises(ValueError):
            tw.event("net_connect", **nc)
        with pytest.raises(ValueError):
            tw.event("proc_exec", argv=["x"], pid=1, ppid=0, exe="/bin/x")
        tw.event("proc_exec", argv=["x"], pid=1, ppid=0)
    with TraceWriter(tmp_path / "b.jsonl", ic2=True) as tw:
        tw.event("net_connect", **nc)
        tw.event("proc_exec", argv=["x"], pid=1, ppid=0, exe="/bin/x")
    lines = [json.loads(l) for l in (tmp_path / "b.jsonl").read_text().splitlines()]
    assert lines[1]["exe"] == "/bin/x"
