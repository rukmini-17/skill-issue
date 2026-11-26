"""Runtime tool-call matching for the two policies that check each call.

Checks a single ToolCall's arguments against the allowed paths, commands and hosts
(D2-D4). The matching itself is A's shared implementation in `bench.common.match`;
this module is the thin C-side adapter that maps a `ToolCall` onto it. (Earlier a
provisional matcher lived here; it has been replaced by A's `match.py` now that it has
landed — see RECONCILE.md / NOTES.md. A's matcher adds what the provisional one could
not: real symlink resolution when given a live workspace root, and `command_aliases.yaml`.)

Command matching follows D3 (via `match`): the string is split into separate commands
at control operators outside quotes (`;`, `&&`, `||`, `|`, `&`, newline); command
substitutions (`$(...)`, backticks) are pulled out and checked as their own commands;
output redirections (`>`, `>>`, `&>`, `>|`) are writes and input redirections (`<`) are
reads, checked against the write/read lists. A command is allowed if its argv starts with
some exec entry's argv, token by token; anything that cannot be parsed is not allowed.
"""

from __future__ import annotations

from bench.common import match
from bench.interfaces import ToolCall

# `_split_commands` kept as a name for C's matching tests (now A's quote-aware splitter).
_split_commands = match.split_commands


# --------------------------------------------------------------------------- paths
def path_allowed(path: str, patterns) -> bool:
    """True if `path` (D2-normalised, lexical `.`/`..`) is covered by any of `patterns`."""
    return match.path_allowed(path, patterns)


# -------------------------------------------------------------------- command text
def command_io(cmd: str) -> tuple[list[str], list[str]]:
    """All redirection targets across the command: (write_targets, read_targets).

    Covers the whole chain and every substitution (A's `extract_redirections`); `<` is a
    read, `>`/`>>`/`&>`/`>|`/`N>` are writes.
    """
    writes: list[str] = []
    reads: list[str] = []
    for mode, target in match.extract_redirections(cmd):
        (reads if mode == "read" else writes).append(target)
    return writes, reads


def command_allowed(cmd: str, exec_entries) -> bool:
    """Every command in the chain (and in every substitution) argv-prefix-matches an exec entry (D3)."""
    return match.command_allowed(cmd, exec_entries)


def run_command_allowed(cmd: str, perms: dict[str, list[str]]) -> bool:
    """A run_command is allowed only if every command is in exec AND every redirection
    target is in the write/read grant (D3: redirections are file effects)."""
    if not match.command_allowed(cmd, perms.get("exec", [])):
        return False
    for mode, target in match.extract_redirections(cmd):
        grant = "fs_read" if mode == "read" else "fs_write"
        if not match.path_allowed(target, perms.get(grant, [])):
            return False
    return True


# --------------------------------------------------------------------------- hosts
def host_allowed(url: str, hosts) -> bool:
    return match.host_allowed(url, hosts)


# ----------------------------------------------------------------------- dispatch
def tool_call_allowed(call: ToolCall, perms: dict[str, list[str]]) -> bool:
    """True if this tool call is within the given permission lists (fs_read/fs_write/exec/network)."""
    tool = call.tool
    args = call.args or {}
    if tool in ("read_file", "list_dir"):
        return match.path_allowed(str(args.get("path", "")), perms.get("fs_read", []))
    if tool == "write_file":
        return match.path_allowed(str(args.get("path", "")), perms.get("fs_write", []))
    if tool == "run_command":
        return run_command_allowed(str(args.get("cmd", "")), perms)
    if tool == "http_request":
        return host_allowed(str(args.get("url", "")), perms.get("network", []))
    # Unknown tool: conservative default is to block.
    return False
