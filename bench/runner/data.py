"""Data access for the runner.

A owns ``bench/common/data.py`` (``load_repo``, ``apply_overlay``). Until it lands this
module reads the repo layout directly, with similar names, so the swap is one import.

Everything here is read-only on ``repos/``; overlays are applied into a scratch directory.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from bench.interfaces import Delegation, Scenario, SkillVersion, Task

REPO_ROOT = Path(__file__).resolve().parents[2]
REPOS = REPO_ROOT / "repos"


def _yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def repo_ids() -> list[str]:
    return sorted(p.name for p in REPOS.iterdir() if (p / "scenarios").is_dir())


def _task(repo_id: str, path: Path) -> Task:
    d = _yaml(path)
    dl = d.get("delegation") or {}
    delegation = Delegation(
        read=tuple(dl.get("read") or ()), write=tuple(dl.get("write") or ()),
        exec=tuple(dl.get("exec") or ()), network=tuple(dl.get("network") or ()),
        protected_data=tuple(dl.get("protected_data") or ()),
    )
    return Task(repo_id=repo_id, task_id=d["task_id"], skill_id=d["skill_id"], prompt=d.get("prompt", ""),
                delegation=delegation, success_check=d.get("success_check") or {},
                reference_dir=path.with_suffix(".reference"))


def _scenario(repo_id: str, path: Path) -> Scenario:
    d = _yaml(path)
    return Scenario(repo_id=repo_id, scenario_id=d["scenario_id"], skill_id=d["skill_id"], task_id=d["task_id"],
                    companion_skill_id=d.get("companion_skill_id"),
                    benign_prefix=tuple(d.get("benign_prefix") or ()),
                    attack=d.get("attack") or {}, seed_ids=tuple(d.get("seeds") or ()))


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


_CACHE: dict[str, Repo] = {}


def load_repo(repo_id: str) -> Repo:
    if repo_id in _CACHE:
        return _CACHE[repo_id]
    root = REPOS / repo_id
    if not root.is_dir():
        raise FileNotFoundError(f"unknown repo {repo_id!r} (looked in {REPOS})")
    tasks = {p.stem: _task(repo_id, p) for p in sorted((root / "tasks").glob("*.yaml"))}
    scenarios = {p.parent.name: _scenario(repo_id, p) for p in sorted((root / "scenarios").glob("*/scenario.yaml"))}
    skills: dict[str, dict[str, SkillVersion]] = {}
    benign: dict[str, list[str]] = {}
    for sdir in sorted(p for p in (root / "skills").iterdir() if p.is_dir()):
        vroot = sdir / "versions"
        skills[sdir.name] = {v.name: SkillVersion(repo_id, sdir.name, v.name, v)
                             for v in sorted(vroot.iterdir()) if v.is_dir()}
        meta = _yaml(sdir / "skill_meta.yaml") if (sdir / "skill_meta.yaml").exists() else {}
        names = [e["version"] for e in (meta.get("benign_updates") or []) if "version" in e]
        benign[sdir.name] = names or sorted(n for n in skills[sdir.name] if n.startswith("benign_"))
    canary_path = root / "canaries.json"
    canaries = json.loads(canary_path.read_text(encoding="utf-8")) if canary_path.exists() else []
    repo = Repo(repo_id, root, tasks, scenarios, skills, benign, canaries)
    _CACHE[repo_id] = repo
    return repo


def apply_overlay(base: SkillVersion, overlay_dir: Path | None, out: Path, name: str | None = None) -> SkillVersion:
    """Copy ``base`` to ``out`` and lay the overlay's files on top (replace or add)."""
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(base.root, out)
    if overlay_dir is not None and overlay_dir.is_dir():
        for f in sorted(overlay_dir.rglob("*")):
            if f.is_file():
                dst = out / f.relative_to(overlay_dir)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dst)
    return SkillVersion(base.repo_id, base.skill_id, name or out.name, out)


def seed_dir(repo: Repo, scenario: Scenario, seed_id: str) -> Path:
    return repo.root / "scenarios" / scenario.scenario_id / "seeds" / seed_id
