"""Monitoring for commands run by ``run_command`` (workstream B, B2).

Two sources of observed events (D6):

* **strace** (``observer: "strace"``): each command runs under ``strace -f``
  inside the sandbox; the log is parsed into ``proc_exec``, ``fs_read`` and
  ``fs_write`` events (paths inside the workspace only) and, pending IC-2,
  ``net_connect`` for connections that do not go to the mock proxy.
* **fs_diff** (always): a stat snapshot of the workspace before and after the
  command; differences become ``fs_diff`` events (supporting evidence).

When strace is not available inside the sandbox the observer is ``"none"``
and only ``fs_diff`` is produced; meta.json records this and such runs are
used only for utility pilots (B2).

Event rules (documented for the oracle and the paper appendix):

* Only syscalls that **succeeded** produce fs/proc events. Failed opens and
  failed execs (e.g. ``sh`` searching PATH) are not effects.
* ``fs_read``: a successful open of a *regular file* for reading (``O_RDONLY``
  or ``O_RDWR``). Directory opens are not reported (every ``python3 -c`` lists
  its working directory for imports; see NOTES.md).
* ``fs_write``: open for writing/creating/truncating (``op`` = ``create`` if the
  path did not exist before the command, else ``modify``), ``creat``,
  ``mkdir``/``mknod``/``link``/``symlink`` (``create``), ``unlink``/``rmdir``
  (``delete``), ``rename`` (``rename``, for both the old and the new path),
  ``truncate``/``ftruncate``/``chmod`` family (``modify``).
* Paths: the real path from strace's ``-y`` fd annotation when there is one
  (an opened file's resolved path); otherwise the argument resolved against
  the dirfd annotation / tracked cwd, then symlinks of the *parent* resolved at
  parse time (ops on a link itself act on the link). Paths outside the
  workspace are dropped. Emitted paths are workspace-relative POSIX.
* Duplicates (same event, path, op and exe) within one command are reported
  once, at their first occurrence.
* ``pid``/``ppid`` are the traced process ids (thread ids mapped to their
  process); the command's top shell has ``ppid`` 0.
"""

from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

STRACE_SYSCALLS = "%file,%process,connect,sendto,sendmsg,fchdir,ftruncate,fchmod"
STRACE_ARGS = ["strace", "-f", "-qq", "-v", "-y", "-s", "4096", "-e", "signal=none",
               "-e", f"trace={STRACE_SYSCALLS}"]
# strace < 4.17 names syscall classes without "%".
STRACE_ARGS_LEGACY = [*STRACE_ARGS[:-1], "trace=" + STRACE_SYSCALLS.replace("%", "")]


# --------------------------------------------------------------------------
# Low-level parsing of strace text
# --------------------------------------------------------------------------

_ESC = {"n": "\n", "t": "\t", "r": "\r", "v": "\v", "f": "\f", "a": "\a", "b": "\b",
        "\\": "\\", '"': '"', "'": "'", "?": "?", "e": "\x1b"}


def c_unescape(s: str) -> str:
    """Decode the body of a strace C string literal (no surrounding quotes)."""
    out = bytearray()
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c != "\\":
            out += c.encode("utf-8", "surrogateescape")
            i += 1
            continue
        i += 1
        if i >= n:
            out += b"\\"
            break
        c = s[i]
        if c == "x":
            hx = s[i + 1:i + 3]
            out.append(int(hx, 16))
            i += 1 + len(hx)
        elif c in "01234567":
            j = i
            while j < n and j < i + 3 and s[j] in "01234567":
                j += 1
            out.append(int(s[i:j], 8) & 0xFF)
            i = j
        else:
            out += _ESC.get(c, c).encode()
            i += 1
    return out.decode("utf-8", "surrogateescape")


def split_args(s: str) -> list[str]:
    """Split a syscall argument list at top-level commas (quote/bracket aware)."""
    args: list[str] = []
    depth = 0
    cur: list[str] = []
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c == '"':
            j = i + 1
            while j < n and s[j] != '"':
                j += 2 if s[j] == "\\" else 1
            cur.append(s[i:j + 1])
            i = j + 1
            continue
        if c in "([{<":
            depth += 1
        elif c in ")]}>":
            depth -= 1
        if c == "," and depth == 0:
            args.append("".join(cur).strip())
            cur = []
        else:
            cur.append(c)
        i += 1
    tail = "".join(cur).strip()
    if tail or args:
        args.append(tail)
    return args


def parse_string(tok: str) -> str | None:
    """``"abc"`` or ``"abc"...`` -> ``abc``; anything else -> None."""
    tok = tok.strip()
    if not tok.startswith('"'):
        return None
    end = tok.rfind('"')
    if end <= 0:
        return None
    return c_unescape(tok[1:end])


def parse_str_array(tok: str) -> list[str] | None:
    tok = tok.strip()
    if not tok.startswith("["):
        return None
    inner = tok[1:tok.rfind("]")] if "]" in tok else tok[1:]
    out = []
    for a in split_args(inner):
        v = parse_string(a)
        if v is not None:
            out.append(v)
    return out


_ANNOT = re.compile(r"^(-?\d+|AT_FDCWD)<(.*)>$", re.S)


def fd_annotation(tok: str) -> tuple[str, str | None]:
    """``3</a/b>`` -> ("3", "/a/b"); ``AT_FDCWD`` -> ("AT_FDCWD", None)."""
    tok = tok.strip()
    m = _ANNOT.match(tok)
    if m:
        p = m.group(2)
        if p.startswith(("socket:", "pipe:", "anon_inode:", "TCP", "UDP", "UNIX", "/dev/pts")):
            return m.group(1), None
        return m.group(1), c_unescape(p)
    return tok, None


@dataclass
class Syscall:
    pid: int
    name: str
    args: list[str]
    ret: str                    # raw return token: "0", "-1", "3", "?" ...
    ret_path: str | None        # -y annotation on the return value
    errno: str | None
    line_no: int

    @property
    def ok(self) -> bool:
        if self.errno:
            return False
        try:
            return int(self.ret, 0) >= 0
        except ValueError:
            return self.ret == "?" and self.name.startswith("exec")


_HEAD = re.compile(r"^\s*(\d+)\s+(.*)$", re.S)
_RESUMED = re.compile(r"^<\.\.\. (\w+) resumed>\s?(.*)$", re.S)
_RET = re.compile(r"^\s*=\s*(-?\d+|\?|0x[0-9a-fA-F]+)(<.*>)?(?:\s+([A-Z][A-Z0-9_]+)\b.*)?\s*$", re.S)


def _find_close(s: str, start: int) -> int:
    """Index of the ``)`` closing the ``(`` at ``start`` (quote aware), or -1."""
    depth = 0
    i = start
    n = len(s)
    while i < n:
        c = s[i]
        if c == '"':
            i += 1
            while i < n and s[i] != '"':
                i += 2 if s[i] == "\\" else 1
        elif c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def iter_syscalls(lines: Iterable[str]) -> Iterable[Syscall]:
    """Yield complete syscalls, joining ``<unfinished ...>`` / ``resumed`` pairs."""
    pending: dict[int, str] = {}
    for no, raw in enumerate(lines):
        raw = raw.rstrip("\n")
        m = _HEAD.match(raw)
        if not m:
            continue
        pid, body = int(m.group(1)), m.group(2)
        if body.startswith(("+++", "---")):
            continue
        if body.endswith("<unfinished ...>"):
            pending[pid] = body[: -len("<unfinished ...>")].rstrip()
            continue
        r = _RESUMED.match(body)
        if r:
            head = pending.pop(pid, None)
            if head is None:
                continue
            rest = r.group(2)
            sep = "" if head.endswith(("(", " ")) or rest.startswith((")", ",")) else ", "
            body = head + sep + rest
        po = body.find("(")
        if po <= 0:
            continue
        name = body[:po]
        if not re.fullmatch(r"\w+", name):
            continue
        pc = _find_close(body, po)
        if pc < 0:
            continue
        rm = _RET.match(body[pc + 1:])
        if not rm:
            continue
        ret_path = None
        if rm.group(2):
            ret_path = c_unescape(rm.group(2)[1:-1])
        yield Syscall(pid, name, split_args(body[po + 1:pc]), rm.group(1), ret_path,
                      rm.group(3), no)


# --------------------------------------------------------------------------
# Socket addresses
# --------------------------------------------------------------------------

_INET = re.compile(r'sa_family=AF_INET\b.*?sin_port=htons\((\d+)\).*?sin_addr=inet_addr\("([^"]+)"\)', re.S)
_INET6 = re.compile(r'sa_family=AF_INET6\b.*?sin6_port=htons\((\d+)\).*?inet_pton\(AF_INET6,\s*"([^"]+)"', re.S)


def parse_sockaddr(text: str) -> tuple[str, str, int] | None:
    m = _INET.search(text)
    if m:
        return "inet", m.group(2), int(m.group(1))
    m = _INET6.search(text)
    if m:
        return "inet6", m.group(2), int(m.group(1))
    return None


# --------------------------------------------------------------------------
# strace log -> D6 events
# --------------------------------------------------------------------------

_WRITE_FLAGS = ("O_WRONLY", "O_RDWR", "O_CREAT", "O_TRUNC", "O_APPEND", "O_TMPFILE")
_CLONES = ("clone", "clone3", "fork", "vfork")


@dataclass
class StraceResult:
    events: list[dict[str, Any]] = field(default_factory=list)       # D6 events (spec fields only)
    connects: list[dict[str, Any]] = field(default_factory=list)     # all non-proxy AF_INET/6 connects
    problems: list[str] = field(default_factory=list)


class StraceParser:
    """Turns one command's strace log into D6 events.

    ``workspace``: real path of the workspace root. ``cwd``: the command's
    working directory. ``existed``: workspace-relative paths that existed
    before the command (to tell ``create`` from ``modify``). ``proxy``:
    ``(addr, port)`` of the mock proxy as seen from inside the sandbox.
    """

    def __init__(self, workspace: Path, cwd: Path, existed: set[str], proxy: tuple[str, int] | None):
        self.ws = os.path.realpath(workspace)
        self.root_cwd = os.path.realpath(cwd)
        self.existed = existed
        self.proxy = proxy

    # -- path helpers ---------------------------------------------------------

    def _rel(self, real: str | None) -> str | None:
        if not real:
            return None
        real = os.path.normpath(real)
        if real == self.ws:
            return "."
        if not real.startswith(self.ws + os.sep):
            return None
        return Path(os.path.relpath(real, self.ws)).as_posix()

    @staticmethod
    def _real_parent(p: str) -> str:
        p = os.path.normpath(p)
        d, b = os.path.split(p)
        return os.path.join(os.path.realpath(d), b) if b else os.path.realpath(p)

    def _resolve(self, pid: int, dirfd_tok: str | None, path: str | None, follow: bool) -> str | None:
        if path is None:
            return None
        if not os.path.isabs(path):
            base = None
            if dirfd_tok is not None:
                fd, ann = fd_annotation(dirfd_tok)
                if ann:
                    base = ann
                elif fd == "AT_FDCWD":
                    base = self._cwd(pid)
            else:
                base = self._cwd(pid)
            if base is None:
                return None
            path = os.path.join(base, path)
        path = os.path.normpath(path)
        return os.path.realpath(path) if follow else self._real_parent(path)

    def _cwd(self, pid: int) -> str:
        p = pid
        seen = set()
        while p not in self.cwd and p in self.parent and p not in seen:
            seen.add(p)
            p = self.parent[p]
        return self.cwd.get(p, self.root_cwd)

    def _exe(self, pid: int) -> str | None:
        p = pid
        seen = set()
        while p not in self.exe and p in self.parent and p not in seen:
            seen.add(p)
            p = self.parent[p]
        return self.exe.get(p)

    # -- main -----------------------------------------------------------------

    def parse(self, lines: Iterable[str]) -> StraceResult:
        calls = list(iter_syscalls(lines))
        self.parent: dict[int, int] = {}
        self.tgid: dict[int, int] = {}
        for c in calls:                                  # pass 1: process tree
            if c.name in _CLONES and c.ok:
                child = int(c.ret, 0)
                if c.name in ("clone", "clone3") and "CLONE_THREAD" in " ".join(c.args):
                    self.tgid[child] = self.tgid.get(c.pid, c.pid)
                else:
                    self.parent[child] = self.tgid.get(c.pid, c.pid)
        root = calls[0].pid if calls else None
        self.cwd: dict[int, str] = {}
        self.exe: dict[int, str] = {}
        res = StraceResult()
        seen: set[tuple] = set()

        def proc(pid: int) -> int:
            return self.tgid.get(pid, pid)

        def emit(ev: dict[str, Any], key: tuple) -> None:
            if key in seen:
                return
            seen.add(key)
            res.events.append(ev)

        def fs(kind: str, pid: int, real: str | None, op: str | None = None) -> None:
            rel = self._rel(real)
            if rel is None:
                return
            exe = self._exe(proc(pid))
            ev: dict[str, Any] = {"event": kind, "path": rel}
            if op:
                ev["op"] = op
            ev["pid"] = proc(pid)
            ev["exe"] = exe
            emit(ev, (kind, rel, op, exe))

        def wop(rel_real: str | None) -> str:
            rel = self._rel(rel_real)
            return "modify" if rel is not None and rel in self.existed else "create"

        for c in calls:
            pid = proc(c.pid)
            a = c.args
            n = c.name
            if n in _CLONES:
                if c.ok:
                    child = int(c.ret, 0)
                    if child not in self.tgid:
                        self.cwd.setdefault(child, self._cwd(pid))
                        if self._exe(pid):
                            self.exe.setdefault(child, self._exe(pid))
                continue
            if not c.ok:
                if n in ("connect", "sendto", "sendmsg"):
                    self._connect(res, c, pid)
                continue
            try:
                if n in ("execve", "execveat"):
                    if n == "execve":
                        path = self._resolve(pid, None, parse_string(a[0]), True)
                        argv = parse_str_array(a[1]) or []
                    else:
                        path = self._resolve(pid, a[0], parse_string(a[1]), True)
                        argv = parse_str_array(a[2]) or []
                    if path:
                        self.exe[pid] = path
                    key = ("proc_exec", pid, tuple(argv))
                    if key not in seen:
                        seen.add(key)
                        res.events.append({"event": "proc_exec", "argv": argv, "pid": pid,
                                           "ppid": 0 if pid == proc(root) else self.parent.get(pid, 0)})
                elif n == "chdir":
                    p = self._resolve(pid, None, parse_string(a[0]), True)
                    if p:
                        self.cwd[pid] = p
                elif n == "fchdir":
                    _, ann = fd_annotation(a[0])
                    if ann:
                        self.cwd[pid] = ann
                elif n in ("open", "openat", "openat2", "creat"):
                    if n == "creat":
                        flags = "O_WRONLY|O_CREAT|O_TRUNC"
                        path_tok, dirfd = a[0], None
                    elif n == "open":
                        path_tok, dirfd, flags = a[0], None, a[1] if len(a) > 1 else ""
                    else:
                        path_tok, dirfd = a[1], a[0]
                        flags = a[2] if len(a) > 2 else ""
                    if "O_DIRECTORY" in flags:
                        continue
                    real = c.ret_path or self._resolve(pid, dirfd, parse_string(path_tok), True)
                    if real and os.path.isdir(real):
                        continue
                    if any(f in flags for f in _WRITE_FLAGS):
                        fs("fs_write", c.pid, real, wop(real))
                        if "O_RDWR" in flags:
                            fs("fs_read", c.pid, real)
                    else:
                        fs("fs_read", c.pid, real)
                elif n in ("unlink", "rmdir"):
                    fs("fs_write", c.pid, self._resolve(pid, None, parse_string(a[0]), False), "delete")
                elif n == "unlinkat":
                    fs("fs_write", c.pid, self._resolve(pid, a[0], parse_string(a[1]), False), "delete")
                elif n == "rename":
                    for t in a[:2]:
                        fs("fs_write", c.pid, self._resolve(pid, None, parse_string(t), False), "rename")
                elif n in ("renameat", "renameat2"):
                    fs("fs_write", c.pid, self._resolve(pid, a[0], parse_string(a[1]), False), "rename")
                    fs("fs_write", c.pid, self._resolve(pid, a[2], parse_string(a[3]), False), "rename")
                elif n in ("mkdir", "mknod"):
                    fs("fs_write", c.pid, self._resolve(pid, None, parse_string(a[0]), False), "create")
                elif n in ("mkdirat", "mknodat"):
                    fs("fs_write", c.pid, self._resolve(pid, a[0], parse_string(a[1]), False), "create")
                elif n in ("link", "symlink"):
                    fs("fs_write", c.pid, self._resolve(pid, None, parse_string(a[1]), False), "create")
                elif n == "linkat":
                    fs("fs_write", c.pid, self._resolve(pid, a[2], parse_string(a[3]), False), "create")
                elif n == "symlinkat":
                    fs("fs_write", c.pid, self._resolve(pid, a[1], parse_string(a[2]), False), "create")
                elif n == "truncate":
                    fs("fs_write", c.pid, self._resolve(pid, None, parse_string(a[0]), True), "modify")
                elif n in ("ftruncate", "fchmod"):
                    _, ann = fd_annotation(a[0])
                    fs("fs_write", c.pid, ann, "modify")
                elif n == "chmod":
                    fs("fs_write", c.pid, self._resolve(pid, None, parse_string(a[0]), True), "modify")
                elif n in ("fchmodat", "fchmodat2"):
                    fs("fs_write", c.pid, self._resolve(pid, a[0], parse_string(a[1]), True), "modify")
                elif n in ("connect", "sendto", "sendmsg"):
                    self._connect(res, c, pid)
            except (IndexError, ValueError) as e:
                res.problems.append(f"strace line {c.line_no + 1}: {n}: {e}")
        return res

    def _connect(self, res: StraceResult, c: Syscall, pid: int) -> None:
        addr = parse_sockaddr(", ".join(c.args))
        if not addr:
            return
        fam, host, port = addr
        if self.proxy and (host, port) == self.proxy:
            return
        if self.proxy and self.proxy[0] in ("127.0.0.1", "localhost") and host in ("::1", "::ffff:127.0.0.1") \
                and port == self.proxy[1]:
            return
        result = "ok" if c.ok else (c.errno or "error")
        if c.errno == "EINPROGRESS":
            result = "EINPROGRESS"
        res.connects.append({"event": "net_connect", "family": fam, "addr": host, "port": port,
                             "pid": pid, "exe": self._exe(pid), "result": result})


# --------------------------------------------------------------------------
# fs_diff snapshots
# --------------------------------------------------------------------------

Snapshot = dict[str, tuple]


def snapshot(workspace: Path) -> Snapshot:
    """``rel path -> (kind, size, mtime_ns, mode, link target)`` for files and symlinks.

    Directories are walked but not listed themselves; symlinks are not followed.
    """
    out: Snapshot = {}
    ws = str(workspace)
    stack = [ws]
    while stack:
        d = stack.pop()
        try:
            it = os.scandir(d)
        except OSError:
            continue
        with it:
            for e in it:
                try:
                    st = e.stat(follow_symlinks=False)
                except OSError:
                    continue
                rel = Path(os.path.relpath(e.path, ws)).as_posix()
                if stat.S_ISDIR(st.st_mode):
                    stack.append(e.path)
                elif stat.S_ISLNK(st.st_mode):
                    try:
                        tgt = os.readlink(e.path)
                    except OSError:
                        tgt = None
                    out[rel] = ("l", 0, 0, 0, tgt)
                else:
                    out[rel] = ("f", st.st_size, st.st_mtime_ns, stat.S_IMODE(st.st_mode), None)
    return out


def diff_snapshots(before: Snapshot, after: Snapshot) -> list[dict[str, Any]]:
    evs = []
    for p in sorted(set(before) | set(after)):
        b, a = before.get(p), after.get(p)
        if b is None:
            change = "created"
        elif a is None:
            change = "deleted"
        elif a != b:
            change = "modified"
        else:
            continue
        evs.append({"event": "fs_diff", "path": p, "change": change})
    return evs


# --------------------------------------------------------------------------
# Monitored command execution
# --------------------------------------------------------------------------

@dataclass
class MonitoredResult:
    result: Any                                   # sandbox.CommandResult
    events: list[dict[str, Any]]                  # D6 events to write, in order
    connects: list[dict[str, Any]]                # non-proxy connects (IC-2), always collected
    problems: list[str]


class CommandMonitor:
    """Runs commands in a built sandbox with strace + fs_diff.

    ``observer``: ``"auto"`` (strace if it works inside the sandbox, else
    none), ``"strace"`` (raise if unavailable) or ``"none"``.
    ``emit_net_connect``: also put ``net_connect`` events in ``events``
    (pending IC-2; keep False until approved).
    """

    def __init__(self, sandbox, observer: str = "auto", emit_net_connect: bool = False):
        self.sb = sandbox
        self.emit_net_connect = emit_net_connect
        self.strace_args: list[str] = STRACE_ARGS
        if observer not in ("auto", "strace", "none"):
            raise ValueError(f"observer {observer!r}")
        if observer != "none":
            ok, why = self.probe()
            if not ok and observer == "strace":
                raise RuntimeError(f"strace unavailable in sandbox ({self.sb.isolation}): {why}")
            observer = "strace" if ok else "none"
            self.probe_error = None if ok else why
        else:
            self.probe_error = None
        self.observer = observer

    def probe(self) -> tuple[bool, str]:
        """Try strace inside the sandbox; pick the first argument set that works."""
        why = ""
        for args in (STRACE_ARGS, STRACE_ARGS_LEGACY):
            out = self.sb.new_run_file(".probe.strace")
            r = self.sb.run("cat /dev/null", prefix=[*args, "-o", str(out)], timeout=30)
            if r.exit != 0:
                why = (r.stderr or r.stdout).strip()[:500] or f"exit {r.exit}"
                continue
            try:
                text = out.read_text(errors="replace")
            except OSError as e:
                why = str(e)
                continue
            if "execve(" not in text:
                why = "strace log has no execve line"
                continue
            self.strace_args = args
            return True, ""
        return False, why

    def run(self, cmd: str, timeout: float | None = None) -> MonitoredResult:
        ws = self.sb.workspace
        before = snapshot(ws)
        problems: list[str] = []
        events: list[dict[str, Any]] = []
        connects: list[dict[str, Any]] = []
        if self.observer == "strace":
            log = self.sb.new_run_file(".strace")
            r = self.sb.run(cmd, timeout=timeout, prefix=[*self.strace_args, "-o", str(log)])
            try:
                with log.open(errors="replace") as fh:
                    parsed = StraceParser(ws, ws, set(before), self.sb.proxy_inside()).parse(fh)
                events += parsed.events
                connects = parsed.connects
                problems += parsed.problems
                if self.emit_net_connect:
                    events += connects
            except OSError as e:
                problems.append(f"strace log unreadable: {e}")
        else:
            r = self.sb.run(cmd, timeout=timeout)
        events += diff_snapshots(before, snapshot(ws))
        return MonitoredResult(r, events, connects, problems)
