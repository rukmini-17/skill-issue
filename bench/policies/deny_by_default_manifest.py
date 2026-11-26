"""The `deny_by_default_manifest` policy: refuse any manifest that grows, and
enforce the installed manifest at run time.

At update time it reads the manifest's `permissions`. If the new version adds any
permission the approved one didn't have, the update is denied outright: it isn't
installed and the user isn't asked. Same or narrower permissions are allowed.

At run time it also acts as a guard. Every tool call is checked against the
installed version's manifest, and anything the manifest doesn't permit (a read,
write, command, or host) is blocked. The manifest is a hard boundary in both
phases.
"""

from __future__ import annotations

from typing import Literal

from bench.interfaces import Decision, SkillVersion, Task, ToolCall
from bench.policies._capabilities import (
    PERM_KEYS,
    gained_entries,
    load_manifest,
    permissions,
)
from bench.policies._runtime import tool_call_allowed


class DenyByDefaultManifestPolicy:
    name = "deny_by_default_manifest"

    def on_update(self, approved: SkillVersion, new: SkillVersion, task: Task) -> tuple[Decision, str]:
        old = permissions(load_manifest(approved.root))
        cur = permissions(load_manifest(new.root))
        gains: dict[str, list[str]] = {}
        for key in PERM_KEYS:
            gained = gained_entries(cur[key], old[key])
            if gained:
                gains[key] = gained
        if gains:
            return ("deny", f"manifest widens: {gains}")
        return ("allow", "manifest does not widen")

    def on_tool_call(self, call: ToolCall, installed: SkillVersion, task: Task) -> Literal["allow", "block"]:
        perms = permissions(load_manifest(installed.root))
        return "allow" if tool_call_allowed(call, perms) else "block"
