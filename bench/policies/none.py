"""The `none` policy: no update review, no runtime checks.

The baseline with no defense. Every update installs silently and every tool call
is allowed. It shows what an attacker gets when nothing stands in the way.
"""

from __future__ import annotations

from typing import Literal

from bench.interfaces import Decision, SkillVersion, Task, ToolCall


class NonePolicy:
    name = "none"

    def on_update(self, approved: SkillVersion, new: SkillVersion, task: Task) -> tuple[Decision, str]:
        return ("allow", "no review")

    def on_tool_call(self, call: ToolCall, installed: SkillVersion, task: Task) -> Literal["allow", "block"]:
        return "allow"
