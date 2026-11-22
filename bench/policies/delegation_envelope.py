"""The ``delegation_envelope`` policy: hold every version to the delegation the
user granted at v1, and enforce that delegation at run time.

When the user approved v1 for this task they granted a delegation: the paths the
skill may read and write, the commands it may run, and the hosts it may contact.
This policy treats that delegation as a fixed envelope. At update time it denies a
new version that *gains* a capability the previously approved version did not have
— a new host, path, command, or declared manifest permission — when that gain
falls outside the delegation. Capability growth that stays inside the delegation is
allowed (that is what separates this policy from `capability_diff`, which asks on
any growth at all), and so is v1 itself and any benign reword that adds nothing.

At run time it is a reference monitor against the same delegation: any tool call to
a path, command or host outside the delegation is blocked. Unlike
`deny_by_default_manifest`, the runtime boundary is the user's original grant, not
the skill's own evolving manifest, so a skill cannot widen what it may do by
shipping a wider manifest.
"""

from __future__ import annotations

from typing import Literal

from bench.interfaces import Decision, Delegation, SkillVersion, Task, ToolCall
from bench.policies._capabilities import (
    DELEGATION_KEYS,
    capability_gains,
    gained_entries,
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

        # 1) Manifest entries the new version GAINS (vs approved) that fall outside
        #    the delegation. Gains within the delegation are allowed; so is v1.
        old_perms = permissions(load_manifest(approved.root))
        new_perms = permissions(load_manifest(new.root))
        for perm_key in DELEGATION_KEYS.values():
            gained = gained_entries(new_perms[perm_key], old_perms[perm_key])
            beyond = [g for g in gained if not glob_within(g, env[perm_key])]
            if beyond:
                exceed[f"manifest.{perm_key}"] = sorted(beyond)

        # 2) Extracted capabilities the new version GAINS (vs approved) that fall
        #    outside the delegation. (deps are not an envelope dimension — the
        #    delegation has no dependency field; see RECONCILE.md.)
        gains = capability_gains(new.root, approved.root)
        read_write = env["fs_read"] + env["fs_write"]
        beyond_hosts = [h for h in gains["hosts"] if h not in set(env["network"])]
        if beyond_hosts:
            exceed["hosts"] = sorted(beyond_hosts)
        beyond_paths = [p for p in gains["paths"] if not glob_within(p, read_write)]
        if beyond_paths:
            exceed["paths"] = sorted(beyond_paths)
        beyond_cmds = [c for c in gains["commands"] if not command_allowed(c, env["exec"])]
        if beyond_cmds:
            exceed["commands"] = sorted(beyond_cmds)

        if exceed:
            return ("deny", f"gains capability beyond delegation: {exceed}")
        return ("allow", "no capability gained beyond delegation")

    def on_tool_call(self, call: ToolCall, installed: SkillVersion, task: Task) -> Literal["allow", "block"]:
        env = _envelope(task.delegation)
        return "allow" if tool_call_allowed(call, env) else "block"
