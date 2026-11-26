"""The `new_permissions_only` policy: ask only when the manifest grows.

Looks only at the manifest's `permissions` (fs_read, fs_write, exec, network) and
ignores edits to prose or code. If the new version adds a permission the approved
one didn't have (a new path, host, or command), we ask. If the permissions are
the same or narrower, it installs silently. No runtime checks.

The point is to bother the user only when the skill asks for more than before. Its
blind spot is anything a version does without declaring it in the manifest, like a
new fetch mentioned only in the prose.
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


class NewPermissionsOnlyPolicy:
    name = "new_permissions_only"

    def on_update(self, approved: SkillVersion, new: SkillVersion, task: Task) -> tuple[Decision, str]:
        old = permissions(load_manifest(approved.root))
        cur = permissions(load_manifest(new.root))
        gains: dict[str, list[str]] = {}
        for key in PERM_KEYS:
            gained = gained_entries(cur[key], old[key])
            if gained:
                gains[key] = gained
        if gains:
            return ("ask", f"manifest gains permissions: {gains}")
        return ("allow", "no new manifest permissions")

    def on_tool_call(self, call: ToolCall, installed: SkillVersion, task: Task) -> Literal["allow", "block"]:
        return "allow"
