"""The ``pin_reapprove`` policy: re-ask whenever the skill's files change at all.

The user pinned the exact version they approved. Any later version whose file
contents differ in any way — even a one-word edit to the documentation — is
treated as something the user must look at again, so the update returns ``ask``.
A version byte-for-byte identical to the approved one is allowed. There are no
runtime checks: once a version is installed, its tool calls are not inspected.

This is the strictest content-pinning defense. It never misses a real change, but
it also asks on every benign edit, so its benign false-positive rate is high.
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
