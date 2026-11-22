"""The ``new_permissions_only`` policy: ask only when the manifest grows.

This policy reads the declared ``permissions`` block of the manifest (the four
lists ``fs_read``, ``fs_write``, ``exec``, ``network``). It ignores edits to the
skill's prose and code; it reacts only to the manifest. If the new version's
permissions gain any entry that the approved version did not already allow — a
new path to read or write, a new host to contact, a new command to run — it
returns ``ask``. If the permissions are unchanged or narrower, it allows the
update silently. There are no runtime checks.

The idea is to bother the user only when a skill asks for more capability than
before. Its blind spot is any new capability a version takes *without* declaring
it in the manifest (for example a new fetch written only into the prose).
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
