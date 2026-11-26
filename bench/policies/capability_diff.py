"""The `capability_diff` policy: ask when the skill's real capabilities grow.

Rather than trust the manifest, this reads every file in the version and pulls out
what it would actually do:
 - hosts, from URLs;
 - paths, from literal path strings;
 - shell commands, from bash/sh code blocks;
 - dependencies, from requirements files and Python imports.
If that set grows against the approved version, we ask; otherwise allow. No
runtime checks.

It catches growth that `new_permissions_only` misses, since it looks at the
content and not just the manifest. The tradeoff is that it's sensitive to wording:
a path or command newly mentioned in an example counts as growth, so a benign
rewrite can trip it.
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
