"""The ``capability_diff`` policy: ask when the skill's *actual* capabilities grow.

Instead of trusting the manifest, this policy reads every file in the version
(prose, scripts, references) and extracts the capabilities they imply:
 - hosts, from any URL that appears;
 - workspace paths, from literal path strings;
 - shell commands, from bash/sh code blocks;
 - dependencies, from requirements files and Python imports.
It compares that set against the approved version. If the new version gains any
host, path, command or dependency, it returns ``ask``; otherwise it allows the
update. There are no runtime checks.

This catches capability growth that `new_permissions_only` misses, because it
looks at what the content would actually do rather than what the manifest
declares. Its cost is sensitivity to wording: a newly mentioned path or command
in an example block counts as a gain, so benign rewrites can trip it.
"""

from __future__ import annotations

from typing import Literal

from bench.interfaces import Decision, SkillVersion, Task, ToolCall
from bench.policies._capabilities import capability_gains


class CapabilityDiffPolicy:
    name = "capability_diff"

    def on_update(self, approved: SkillVersion, new: SkillVersion, task: Task) -> tuple[Decision, str]:
        gains = capability_gains(new.root, approved.root)
        nonempty = {kind: vals for kind, vals in gains.items() if vals}
        if nonempty:
            return ("ask", f"capabilities gained vs approved: {nonempty}")
        return ("allow", "no capabilities gained")

    def on_tool_call(self, call: ToolCall, installed: SkillVersion, task: Task) -> Literal["allow", "block"]:
        return "allow"
