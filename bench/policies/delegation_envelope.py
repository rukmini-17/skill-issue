"""The ``delegation_envelope`` policy: hold every version to the delegation the
user granted at v1, and enforce that delegation at run time.

When the user approved v1 for this task they granted a delegation: the paths the
skill may read and write, the commands it may run, and the hosts it may contact.
This policy treats that delegation as a fixed envelope. At update time it denies
any new version whose manifest permissions *or* whose extracted capabilities
(hosts, paths, commands) fall outside the delegation — regardless of what earlier
versions were allowed. A version that stays within the delegation is allowed.

At run time it is a reference monitor against the same delegation: any tool call
to a path, command or host outside the delegation is blocked. Unlike
`deny_by_default_manifest`, the boundary is the user's original grant, not the
skill's own evolving manifest, so a skill cannot widen what it may do by shipping
a wider manifest.
"""

from __future__ import annotations

from typing import Literal

from bench.interfaces import Decision, Delegation, SkillVersion, Task, ToolCall
from bench.policies._capabilities import (
    DELEGATION_KEYS,
    capabilities,
    glob_within,
    load_manifest,
    permissions,
)
from bench.policies._runtime import command_allowed, tool_call_allowed


def _envelope(delegation: Delegation) -> dict[str, list[str]]:
    """Delegation expressed as the four permission lists (fs_read/fs_write/exec/network)."""
    return {
        "fs_read": list(delegation.read),
        "fs_write": list(delegation.write),
        "exec": list(delegation.exec),
        "network": list(delegation.network),
    }


class DelegationEnvelopePolicy:
    name = "delegation_envelope"

    def on_update(self, approved: SkillVersion, new: SkillVersion, task: Task) -> tuple[Decision, str]:
        env = _envelope(task.delegation)
        exceed: dict[str, list[str]] = {}

        # 1) Manifest permissions must stay within the delegation.
        perms = permissions(load_manifest(new.root))
        for deleg_field, perm_key in DELEGATION_KEYS.items():
            over = [p for p in perms[perm_key] if not glob_within(p, env[perm_key])]
            if over:
                exceed[f"manifest.{perm_key}"] = sorted(over)

        # 2) Extracted capabilities must stay within the delegation.
        caps = capabilities(new.root)
        read_write = env["fs_read"] + env["fs_write"]
        over_hosts = sorted(h for h in caps["hosts"] if h not in set(env["network"]))
        if over_hosts:
            exceed["hosts"] = over_hosts
        over_paths = sorted(p for p in caps["paths"] if not glob_within(p, read_write))
        if over_paths:
            exceed["paths"] = over_paths
        over_cmds = sorted(c for c in caps["commands"] if not command_allowed(c, env["exec"]))
        if over_cmds:
            exceed["commands"] = over_cmds

        if exceed:
            return ("deny", f"exceeds delegation envelope: {exceed}")
        return ("allow", "within delegation envelope")

    def on_tool_call(self, call: ToolCall, installed: SkillVersion, task: Task) -> Literal["allow", "block"]:
        env = _envelope(task.delegation)
        return "allow" if tool_call_allowed(call, env) else "block"
