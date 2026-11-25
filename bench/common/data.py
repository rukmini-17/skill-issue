"""Data loaders for the four benchmark repos (Workstream A, A2).

`load_repo(repo_id)` returns everything the runtime needs: tasks, scenarios, skills
(with per-version roots), canaries and the mock host config. `apply_overlay` builds an
attack SkillVersion by layering a seed's overlay files on top of a base version.

All formats were confirmed across ops-office, orders-api, release-tools and shop-web.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from bench.interfaces import Delegation, Scenario, SkillVersion, Task

# repos/ lives at the repository root, two levels up from this file's package.
REPO_ROOT = Path(__file__).resolve().parents[2]
REPOS_DIR = REPO_ROOT / "repos"


def _load_yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _delegation(d: dict) -> Delegation:
    d = d or {}
    return Delegation(
        read=tuple(d.get("read", []) or []),
        write=tuple(d.get("write", []) or []),
        exec=tuple(d.get("exec", []) or []),
        network=tuple(d.get("network", []) or []),
        protected_data=tuple(d.get("protected_data", []) or []),
    )


@dataclass(frozen=True)
class Seed:
    seed_id: str
    scenario_id: str
    repo_id: str
    base_version: str
    cls: str
    description: str
    expected_predicates: tuple[str, ...]
    expected_to_fire_without_policy: bool
    root: Path               # the seed directory
    overlay_dir: Path | None            # single-step overlay, if present
    step_dirs: tuple[Path, ...]         # salami: step_NN/overlay dirs, in order
    mock_override_dir: Path | None      # late_binding mock responses, if present


@dataclass(frozen=True)
class RepoData:
    repo_id: str
    root: Path
    workspace: Path
    tasks: dict[str, Task]
    scenarios: dict[str, Scenario]
    skill_versions: dict[str, dict[str, SkillVersion]]   # skill_id -> version -> SkillVersion
    skill_meta: dict[str, dict]
    canaries: list[dict]
    mock_hosts: dict

    def version(self, skill_id: str, version: str) -> SkillVersion:
        return self.skill_versions[skill_id][version]

    def seeds(self, scenario_id: str) -> dict[str, Seed]:
        return _load_seeds(self.repo_id, scenario_id)


def available_repos() -> list[str]:
    if not REPOS_DIR.is_dir():
        return []
    return sorted(p.name for p in REPOS_DIR.iterdir() if p.is_dir() and (p / "canaries.json").exists())


def _load_tasks(repo_id: str, root: Path) -> dict[str, Task]:
    tasks: dict[str, Task] = {}
    tdir = root / "tasks"
    for f in sorted(tdir.glob("*.yaml")):
        raw = _load_yaml(f)
        tid = raw["task_id"]
        tasks[tid] = Task(
            repo_id=repo_id,
            task_id=tid,
            skill_id=raw["skill_id"],
            prompt=raw["prompt"],
            delegation=_delegation(raw.get("delegation", {})),
            success_check=raw.get("success_check", {}) or {},
            reference_dir=tdir / f"{tid}.reference",
        )
    return tasks


def _load_scenarios(repo_id: str, root: Path) -> dict[str, Scenario]:
    scenarios: dict[str, Scenario] = {}
    for f in sorted(root.glob("scenarios/*/scenario.yaml")):
        raw = _load_yaml(f)
        sid = raw["scenario_id"]
        scenarios[sid] = Scenario(
            repo_id=repo_id,
            scenario_id=sid,
            skill_id=raw["skill_id"],
            task_id=raw["task_id"],
            companion_skill_id=raw.get("companion_skill_id"),
            benign_prefix=tuple(raw.get("benign_prefix", []) or []),
            attack=raw.get("attack", {}) or {},
            seed_ids=tuple(raw.get("seeds", []) or []),
        )
    return scenarios


def _load_skills(repo_id: str, root: Path) -> tuple[dict[str, dict[str, SkillVersion]], dict[str, dict]]:
    versions: dict[str, dict[str, SkillVersion]] = {}
    meta: dict[str, dict] = {}
    sdir = root / "skills"
    if not sdir.is_dir():
        return versions, meta
    for skill_dir in sorted(p for p in sdir.iterdir() if p.is_dir()):
        skill_id = skill_dir.name
        mpath = skill_dir / "skill_meta.yaml"
        meta[skill_id] = _load_yaml(mpath) if mpath.exists() else {}
        vmap: dict[str, SkillVersion] = {}
        vroot = skill_dir / "versions"
        if vroot.is_dir():
            for vdir in sorted(p for p in vroot.iterdir() if p.is_dir()):
                vmap[vdir.name] = SkillVersion(
                    repo_id=repo_id, skill_id=skill_id, version=vdir.name, root=vdir
                )
        versions[skill_id] = vmap
    return versions, meta


@lru_cache(maxsize=None)
def load_repo(repo_id: str) -> RepoData:
    root = REPOS_DIR / repo_id
    if not root.is_dir():
        raise FileNotFoundError(f"repo not found: {root}")
    skill_versions, skill_meta = _load_skills(repo_id, root)
    mock_path = root / "mock_hosts.yaml"
    return RepoData(
        repo_id=repo_id,
        root=root,
        workspace=root / "workspace",
        tasks=_load_tasks(repo_id, root),
        scenarios=_load_scenarios(repo_id, root),
        skill_versions=skill_versions,
        skill_meta=skill_meta,
        canaries=_load_json(root / "canaries.json"),
        mock_hosts=_load_yaml(mock_path) if mock_path.exists() else {},
    )


@lru_cache(maxsize=None)
def _load_seeds(repo_id: str, scenario_id: str) -> dict[str, Seed]:
    root = REPOS_DIR / repo_id / "scenarios" / scenario_id / "seeds"
    seeds: dict[str, Seed] = {}
    if not root.is_dir():
        return seeds
    for sdir in sorted(p for p in root.iterdir() if p.is_dir()):
        ypath = sdir / "seed.yaml"
        if not ypath.exists():
            continue
        raw = _load_yaml(ypath)
        overlay = sdir / "overlay"
        steps = sorted(sdir.glob("step_*"))
        step_overlays = tuple((s / "overlay") for s in steps if (s / "overlay").is_dir())
        mock_override = sdir / "mock_override"
        seeds[sdir.name] = Seed(
            seed_id=raw.get("seed_id", sdir.name),
            scenario_id=scenario_id,
            repo_id=repo_id,
            base_version=raw.get("base_version", "v1"),
            cls=raw.get("class", ""),
            description=raw.get("description", ""),
            expected_predicates=tuple(raw.get("expected_predicates", []) or []),
            expected_to_fire_without_policy=bool(raw.get("expected_to_fire_without_policy", False)),
            root=sdir,
            overlay_dir=overlay if overlay.is_dir() else None,
            step_dirs=step_overlays,
            mock_override_dir=mock_override if mock_override.is_dir() else None,
        )
    return seeds


def apply_overlay(base: SkillVersion, overlay_dir: Path, out: Path, version: str | None = None) -> SkillVersion:
    """Copy `base` to `out`, then lay `overlay_dir` files on top (replace/add). Returns the new version."""
    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(base.root, out)
    if overlay_dir is not None and Path(overlay_dir).is_dir():
        for src in sorted(Path(overlay_dir).rglob("*")):
            if src.is_file():
                rel = src.relative_to(overlay_dir)
                dst = out / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
    return SkillVersion(
        repo_id=base.repo_id,
        skill_id=base.skill_id,
        version=version or f"{base.version}+overlay",
        root=out,
    )
