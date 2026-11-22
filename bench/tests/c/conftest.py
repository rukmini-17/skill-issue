"""Helpers for the C policy tests: build hand-made skill-version snapshots on disk."""

from __future__ import annotations

import json
from pathlib import Path

from bench.interfaces import Delegation, SkillVersion, Task

DEFAULT_PERMS = {
    "fs_read": [".github/skills/demo/**", "data/orders.csv"],
    "fs_write": ["reports/**"],
    "exec": [],
    "network": ["contracts.example"],
}


def make_version(
    tmp_path: Path,
    name: str,
    *,
    permissions: dict | None = None,
    skill_md: str = "# Demo skill\n\nReads data/orders.csv and writes reports/out.md.\n",
    extra_files: dict[str, str] | None = None,
    deps: dict | None = None,
) -> SkillVersion:
    """Write a version snapshot (manifest.json + SKILL.md + LICENSE + extras) and return a SkillVersion."""
    root = tmp_path / name
    root.mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": "demo",
        "version": name,
        "permissions": permissions if permissions is not None else DEFAULT_PERMS,
        "dependencies": deps if deps is not None else {"npm": [], "pip": []},
    }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2))
    (root / "SKILL.md").write_text(skill_md)
    (root / "LICENSE").write_text("MIT\n")
    for rel, content in (extra_files or {}).items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return SkillVersion("demo-repo", "demo", name, root)


def make_task(
    *,
    read=(".github/skills/demo/**", "data/orders.csv"),
    write=("reports/**",),
    exec_=(),
    network=("contracts.example",),
) -> Task:
    deleg = Delegation(read=tuple(read), write=tuple(write), exec=tuple(exec_),
                       network=tuple(network), protected_data=())
    return Task("demo-repo", "t1", "demo", "do the task", deleg, {}, Path("."))
