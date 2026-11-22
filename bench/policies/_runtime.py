"""Runtime tool-call matching for the two policies that check each call.

Implements D2 (path globs), D3 (command matching) and D4 (network) against the
arguments of a single ToolCall, provisionally. Like ``_capabilities``, this is a
stand-in for A's ``bench/common/match.py``: it does lexical ``..``/``.``
resolution only (no symlink / real-path resolution, which needs the live
workspace), so when ``common/match.py`` lands, route these three checks through
it. The public seam is ``tool_call_allowed(call, perms)``.
"""

from __future__ import annotations

import posixpath
import shlex
from urllib.parse import urlparse

from bench.interfaces import ToolCall
from bench.policies._capabilities import path_matches

# Shell control operators that separate commands (D3).
_OPERATORS = ("&&", "||", ";", "|", "\n", "&")


def _normalize(path: str) -> str | None:
    """Lexically resolve ``.``/``..`` and make workspace-relative. None if it escapes."""
    norm = posixpath.normpath(path.lstrip("/"))
    if norm == ".." or norm.startswith("../"):
        return None
    return norm


def path_allowed(path: str, patterns) -> bool:
    norm = _normalize(path)
    if norm is None:
        return False  # resolves outside the workspace -> never matches (D2)
    return path_matches(norm, patterns)


def _split_commands(cmd: str) -> list[str]:
    parts = [cmd]
    for op in _OPERATORS:
        parts = [seg for p in parts for seg in p.split(op)]
    return [p.strip() for p in parts if p.strip()]


def command_allowed(cmd: str, exec_entries) -> bool:
    """Every command in the chain must argv-prefix-match some exec entry (D3)."""
    allowed_argvs = []
    for entry in exec_entries:
        try:
            allowed_argvs.append(shlex.split(entry))
        except ValueError:
            continue
    commands = _split_commands(cmd)
    if not commands:
        return False
    for one in commands:
        try:
            argv = shlex.split(one)
        except ValueError:
            return False  # unparseable -> not allowed (D3)
        if not argv:
            return False
        if not any(
            len(argv) >= len(a) and argv[: len(a)] == a
            for a in allowed_argvs
            if a
        ):
            return False
    return True


def host_allowed(url: str, hosts) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in set(hosts)


def tool_call_allowed(call: ToolCall, perms: dict[str, list[str]]) -> bool:
    """True if this tool call is within the given permission lists (fs_read/fs_write/exec/network)."""
    tool = call.tool
    args = call.args or {}
    if tool in ("read_file", "list_dir"):
        return path_allowed(str(args.get("path", "")), perms.get("fs_read", []))
    if tool == "write_file":
        return path_allowed(str(args.get("path", "")), perms.get("fs_write", []))
    if tool == "run_command":
        return command_allowed(str(args.get("cmd", "")), perms.get("exec", []))
    if tool == "http_request":
        return host_allowed(str(args.get("url", "")), perms.get("network", []))
    # Unknown tool: conservative default is to block.
    return False
