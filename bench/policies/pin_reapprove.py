"""The `pin_reapprove` policy: ask again whenever any file changes.

The user approved one exact version. If a later version differs at all, even a
one-word doc edit, we ask them to look again (`ask`). A version that is identical
to the approved one is allowed. No runtime checks.

It's the strictest content check. It never misses a real change, but it also asks
on every harmless edit, so it flags a lot of benign updates.
"""

from __future__ import annotations

from typing import Literal

from bench.interfaces import Decision, SkillVersion, Task, ToolCall
from bench.policies._capabilities import file_hashes


class PinReapprovePolicy:
    name = "pin_reapprove"

    def on_update(self, approved: SkillVersion, new: SkillVersion, task: Task) -> tuple[Decision, str]:
        old = file_hashes(approved.root)
        cur = file_hashes(new.root)
        if old == cur:
            return ("allow", "identical to approved version")
        changed = sorted(
            p for p in (set(old) | set(cur)) if old.get(p) != cur.get(p)
        )
        return ("ask", f"files differ from approved version: {changed}")

    def on_tool_call(self, call: ToolCall, installed: SkillVersion, task: Task) -> Literal["allow", "block"]:
        return "allow"
