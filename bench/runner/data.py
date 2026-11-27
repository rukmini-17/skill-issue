"""Data access for the runner and attackers.

Thin view over A's ``bench/common/data.py`` (``load_repo``, ``apply_overlay``), keeping the
names D's code already uses (``Repo.skills``, ``Repo.benign``, ``v1``, ``install_set``).

Everything here is read-only on ``repos/``; overlays are applied into a scratch directory.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from bench.common import data as common
from bench.interfaces import Scenario, SkillVersion, Task

REPO_ROOT = common.REPO_ROOT
REPOS = common.REPOS_DIR


def repo_ids() -> list[str]:
    return common.available_repos()


@dataclass
class Repo:
    repo_id: str
    root: Path
    tasks: dict[str, Task]
    scenarios: dict[str, Scenario]
    skills: dict[str, dict[str, SkillVersion]]       # skill_id -> version name -> SkillVersion
    benign: dict[str, list[str]]                      # skill_id -> benign version names, in order
    canaries: list[dict] = field(default_factory=list)

    def v1(self, skill_id: str) -> SkillVersion:
        return self.skills[skill_id]["v1"]

    def install_set(self, overrides: dict[str, SkillVersion] | None = None) -> dict[str, SkillVersion]:
        """D8: every skill of the repo at v1, then the overrides (target skill's current version)."""
        out = {sid: vs["v1"] for sid, vs in self.skills.items()}
        out.update(overrides or {})
        return out


def _benign_order(meta: dict, versions: dict[str, SkillVersion]) -> list[str]:
    names = [e["version"] for e in (meta.get("benign_updates") or []) if "version" in e]
    return names or sorted(n for n in versions if n.startswith("benign_"))


@lru_cache(maxsize=None)
def load_repo(repo_id: str) -> Repo:
    rd = common.load_repo(repo_id)
    benign = {sid: _benign_order(rd.skill_meta.get(sid) or {}, vs) for sid, vs in rd.skill_versions.items()}
    return Repo(rd.repo_id, rd.root, rd.tasks, rd.scenarios, rd.skill_versions, benign, rd.canaries)


def apply_overlay(base: SkillVersion, overlay_dir: Path | None, out: Path, name: str | None = None) -> SkillVersion:
    """Copy ``base`` to ``out`` and lay the overlay's files on top (replace or add)."""
    return common.apply_overlay(base, overlay_dir, out, version=name or Path(out).name)


def seed_dir(repo: Repo, scenario: Scenario, seed_id: str) -> Path:
    return repo.root / "scenarios" / scenario.scenario_id / "seeds" / seed_id
