"""Skill installation helpers (workstream B, D1/D8).

Skills install at ``.github/skills/<skill_id>/`` in the workspace (D1). Every
skill of the scenario's repo is installed: the target at its current version,
the companion and all others at ``v1`` (D8). Building the ``installed`` map for
a run is the runner's job (D9); :func:`repo_install_set` is the D8 default the
runner and tests can start from.
"""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path

import yaml

from bench.interfaces import SkillVersion

SKILLS_DIR = ".github/skills"


@dataclass(frozen=True)
class InstalledSkill:
    skill_id: str
    version: str
    path: str                     # workspace-relative install dir, e.g. ".github/skills/meeting-minutes"
    source: str                   # snapshot root the files were copied from
    files: dict[str, str]         # install-relative POSIX path -> sha256 of the copied file

    def to_json(self) -> dict:
        return {"skill_id": self.skill_id, "version": self.version, "path": self.path,
                "source": self.source, "files": dict(self.files)}


def install_path(skill_id: str) -> str:
    return f"{SKILLS_DIR}/{skill_id}"


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def tree_hashes(root: Path) -> dict[str, str]:
    """sha256 of every regular file under ``root`` (symlinks are not followed)."""
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if p.is_file() and not p.is_symlink():
            out[p.relative_to(root).as_posix()] = _sha256(p)
    return out


def install_skills(workspace: Path, installed: dict[str, SkillVersion]) -> list[InstalledSkill]:
    """Copy each snapshot to ``<workspace>/.github/skills/<skill_id>/``.

    An existing directory of the same name is replaced. Raises ``ValueError``
    for a snapshot without ``SKILL.md`` or a skill id that is not one path
    segment.
    """
    result: list[InstalledSkill] = []
    base = workspace / SKILLS_DIR
    base.mkdir(parents=True, exist_ok=True)
    for skill_id in sorted(installed):
        sv = installed[skill_id]
        if sv.skill_id != skill_id:
            raise ValueError(f"installed[{skill_id!r}] holds skill {sv.skill_id!r}")
        if not skill_id or "/" in skill_id or skill_id in (".", ".."):
            raise ValueError(f"bad skill id {skill_id!r}")
        root = Path(sv.root)
        if not (root / "SKILL.md").is_file():
            raise ValueError(f"{root} has no SKILL.md")
        dest = base / skill_id
        if dest.exists() or dest.is_symlink():
            if dest.is_dir() and not dest.is_symlink():
                shutil.rmtree(dest)
            else:
                dest.unlink()
        shutil.copytree(root, dest, symlinks=True)
        result.append(InstalledSkill(skill_id, sv.version, install_path(skill_id), str(root),
                                     tree_hashes(dest)))
    return result


def repo_install_set(repo_root: Path, overrides: dict[str, SkillVersion] | None = None) -> dict[str, SkillVersion]:
    """D8 default: every skill in ``<repo_root>/skills`` at ``v1``, then ``overrides``."""
    repo_root = Path(repo_root)
    repo_id = repo_root.name
    out: dict[str, SkillVersion] = {}
    for d in sorted((repo_root / "skills").iterdir()):
        v1 = d / "versions" / "v1"
        if d.is_dir() and v1.is_dir():
            out[d.name] = SkillVersion(repo_id, d.name, "v1", v1)
    out.update(overrides or {})
    return out


def skill_frontmatter(skill_md: Path) -> dict:
    """``name``/``description`` etc. from a SKILL.md YAML frontmatter ({} if none)."""
    text = Path(skill_md).read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    parts = text.split("\n---", 1)
    if len(parts) < 2:
        return {}
    try:
        data = yaml.safe_load(parts[0][3:])
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}
