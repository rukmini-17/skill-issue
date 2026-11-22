"""The ``none`` policy: no update review and no runtime checks.

This is the no-defense baseline. Every skill update is installed silently and
every tool call the agent makes is allowed. It measures what an attacker achieves
when nothing stands between an approved skill and its future versions.
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
