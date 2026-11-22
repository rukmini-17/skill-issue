"""Runtime tool-call matching for the two policies that check each call.

Checks a single ToolCall's arguments against the allowed paths, commands and hosts
(D2-D4). Like _capabilities, this is a stand-in for A's `bench/common/match.py`:
it resolves `..`/`.` lexically but not symlinks (that needs the live workspace), so
route these checks through match.py once it lands. The seam is
tool_call_allowed(call, perms).

Command matching follows D3: the string is split into separate commands at control
operators outside quotes (`;`, `&&`, `||`, `|`, `&`, newline); command
substitutions (`$(...)`, backticks) are pulled out and checked as their own
commands; output redirections (`>`, `>>`, `&>`, `>|`) are writes and input
redirections (`<`) are reads, checked against the write/read lists. A command is
allowed if its argv starts with some exec entry's argv, token by token; anything
that cannot be parsed is not allowed.
"""

from __future__ import annotations

import posixpath
import shlex
from urllib.parse import urlparse

from bench.interfaces import ToolCall
from bench.policies._capabilities import path_matches

# Control operators that separate commands (D3), longest first for the two-char ones.
_SPLIT_TWO = ("&&", "||")
_SPLIT_ONE = (";", "|", "&", "\n")
# Redirection operators, longest first. `&>`/`>|` are kept intact so the `&`/`|`
# inside them is not mistaken for a control operator.
_REDIR_OPS = (">>", "&>", ">|", ">", "<")


# --------------------------------------------------------------------------- paths
def _normalize(path: str) -> str | None:
    """Lexically resolve ``.``/``..`` and keep workspace-relative. None if rejected.

    Absolute paths are rejected outright (D2): an absolute path in a tool call never
    matches. A path that resolves above the workspace root is rejected too. Symlinks
    are not resolved here (no live workspace) — that is the oracle's job.
    """
    if path.startswith("/"):
        return None  # absolute paths are rejected (D2)
    norm = posixpath.normpath(path)
    if norm == ".." or norm.startswith("../"):
        return None
    return norm


def path_allowed(path: str, patterns) -> bool:
    norm = _normalize(path)
    if norm is None:
        return False
    return path_matches(norm, patterns)


# -------------------------------------------------------------------- command text
def _shlex(s: str):
    try:
        return shlex.split(s)
    except ValueError:
        return None


def _match_redir(s: str, i: int) -> str | None:
    for op in _REDIR_OPS:
        if s[i:i + len(op)] == op:
            return op
    return None


def _split_commands(cmd: str) -> list[str]:
    """Split a command string into separate commands at control operators (quote-aware).

    Operators inside single/double quotes do not split (``echo "a;b"`` is one
    command). Redirection operators are kept inside the current command so the
    ``&`` of ``&>`` and the ``|`` of ``>|`` are not read as control operators.
    """
    parts: list[str] = []
    buf = ""
    i, n = 0, len(cmd)
    quote: str | None = None
    while i < n:
        c = cmd[i]
        if quote:
            buf += c
            if c == quote:
                quote = None
            i += 1
            continue
        if c in ("'", '"'):
            quote = c
            buf += c
            i += 1
            continue
        if c == "\\" and i + 1 < n:
            buf += cmd[i:i + 2]
            i += 2
            continue
        red = _match_redir(cmd, i)
        if red:
            buf += cmd[i:i + len(red)]
            i += len(red)
            continue
        if cmd[i:i + 2] in _SPLIT_TWO:
            parts.append(buf)
            buf = ""
            i += 2
            continue
        if c in _SPLIT_ONE:
            parts.append(buf)
            buf = ""
            i += 1
            continue
        buf += c
        i += 1
    parts.append(buf)
    return [p.strip() for p in parts if p.strip()]


def _extract_substitutions(cmd: str) -> list[str]:
    """Bodies of command substitutions (``$(...)`` with nesting, and backticks).

    Single quotes suppress substitution; double quotes do not (bash semantics).
    """
    subs: list[str] = []
    i, n = 0, len(cmd)
    in_single = False
    while i < n:
        c = cmd[i]
        if in_single:
            if c == "'":
                in_single = False
            i += 1
            continue
        if c == "'":
            in_single = True
            i += 1
            continue
        if c == "$" and i + 1 < n and cmd[i + 1] == "(":
            depth, j = 1, i + 2
            start = j
            while j < n and depth:
                if cmd[j] == "(":
                    depth += 1
                elif cmd[j] == ")":
                    depth -= 1
                j += 1
            subs.append(cmd[start:j - 1])
            i = j
            continue
        if c == "`":
            j = cmd.find("`", i + 1)
            if j == -1:
                break
            subs.append(cmd[i + 1:j])
            i = j + 1
            continue
        i += 1
    return subs


def _strip_substitutions(cmd: str) -> str:
    """The command with any ``$(...)``/backtick spans blanked out (for argv parsing)."""
    out = ""
    i, n = 0, len(cmd)
    in_single = False
    while i < n:
        c = cmd[i]
        if in_single:
            out += c
            if c == "'":
                in_single = False
            i += 1
            continue
        if c == "'":
            in_single = True
            out += c
            i += 1
            continue
        if c == "$" and i + 1 < n and cmd[i + 1] == "(":
            depth, j = 1, i + 2
            while j < n and depth:
                if cmd[j] == "(":
                    depth += 1
                elif cmd[j] == ")":
                    depth -= 1
                j += 1
            out += " "
            i = j
            continue
        if c == "`":
            j = cmd.find("`", i + 1)
            if j == -1:
                out += c
                i += 1
                continue
            out += " "
            i = j + 1
            continue
        out += c
        i += 1
    return out


def _read_token(s: str, i: int) -> tuple[str, int]:
    """Read one (possibly quoted) token starting at ``i``; return its unquoted value."""
    n = len(s)
    while i < n and s[i] in " \t":
        i += 1
    buf = ""
    quote: str | None = None
    while i < n:
        c = s[i]
        if quote:
            if c == quote:
                quote = None
            else:
                buf += c
            i += 1
            continue
        if c in ("'", '"'):
            quote = c
            i += 1
            continue
        if c in " \t\n;|&<>":
            break
        if c == "\\" and i + 1 < n:
            buf += s[i + 1]
            i += 2
            continue
        buf += c
        i += 1
    return buf, i


def _split_io(segment: str) -> tuple[str, list[str], list[str]]:
    """Pull redirections out of one command: return (clean_command, writes, reads)."""
    clean = ""
    writes: list[str] = []
    reads: list[str] = []
    i, n = 0, len(segment)
    quote: str | None = None
    while i < n:
        c = segment[i]
        if quote:
            clean += c
            if c == quote:
                quote = None
            i += 1
            continue
        if c in ("'", '"'):
            quote = c
            clean += c
            i += 1
            continue
        if c == "\\" and i + 1 < n:
            clean += segment[i:i + 2]
            i += 2
            continue
        op = _match_redir(segment, i)
        if op:
            i += len(op)
            tok, i = _read_token(segment, i)
            if tok:
                (reads if op == "<" else writes).append(tok)
            continue
        clean += c
        i += 1
    return clean, writes, reads


def _leaf_commands(cmd: str) -> list[str]:
    """Every individual command to judge: top-level commands plus substitutions (recursive).

    Each leaf has its redirections and substitution spans removed, so what is left is
    just the argv to prefix-match against the exec grant.
    """
    leaves: list[str] = []
    for seg in _split_commands(cmd):
        subs = _extract_substitutions(seg)
        clean, _w, _r = _split_io(_strip_substitutions(seg))
        if clean.strip():
            leaves.append(clean.strip())
        for s in subs:
            leaves.extend(_leaf_commands(s))
    return leaves


def command_io(cmd: str) -> tuple[list[str], list[str]]:
    """All redirection targets across the command: (write_targets, read_targets), incl. substitutions."""
    writes: list[str] = []
    reads: list[str] = []
    for seg in _split_commands(cmd):
        subs = _extract_substitutions(seg)
        _clean, w, r = _split_io(_strip_substitutions(seg))
        writes += w
        reads += r
        for s in subs:
            sw, sr = command_io(s)
            writes += sw
            reads += sr
    return writes, reads


def command_allowed(cmd: str, exec_entries) -> bool:
    """Every command in the chain (and in every substitution) argv-prefix-matches an exec entry (D3)."""
    allowed_argvs = [a for a in (_shlex(e) for e in exec_entries) if a]
    leaves = _leaf_commands(cmd)
    if not leaves:
        return False
    for leaf in leaves:
        argv = _shlex(leaf)
        if not argv:
            return False  # unparseable or empty -> not allowed (D3)
        if not any(len(argv) >= len(a) and argv[:len(a)] == a for a in allowed_argvs):
            return False
    return True


def run_command_allowed(cmd: str, perms: dict[str, list[str]]) -> bool:
    """A run_command is allowed only if every command is in exec AND every redirection
    target is in the write/read grant (D3: redirections are file effects)."""
    if not command_allowed(cmd, perms.get("exec", [])):
        return False
    writes, reads = command_io(cmd)
    if any(not path_allowed(w, perms.get("fs_write", [])) for w in writes):
        return False
    if any(not path_allowed(r, perms.get("fs_read", [])) for r in reads):
        return False
    return True


# --------------------------------------------------------------------------- hosts
def host_allowed(url: str, hosts) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in set(hosts)


# ----------------------------------------------------------------------- dispatch
def tool_call_allowed(call: ToolCall, perms: dict[str, list[str]]) -> bool:
    """True if this tool call is within the given permission lists (fs_read/fs_write/exec/network)."""
    tool = call.tool
    args = call.args or {}
    if tool in ("read_file", "list_dir"):
        return path_allowed(str(args.get("path", "")), perms.get("fs_read", []))
    if tool == "write_file":
        return path_allowed(str(args.get("path", "")), perms.get("fs_write", []))
    if tool == "run_command":
        return run_command_allowed(str(args.get("cmd", "")), perms)
    if tool == "http_request":
        return host_allowed(str(args.get("url", "")), perms.get("network", []))
    # Unknown tool: conservative default is to block.
    return False
