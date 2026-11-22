"""PROVISIONAL data loader for C2 (see RECONCILE.md).

Workstream A owns ``bench/common/data.py`` (``load_repo``, ``apply_overlay``); it
does not exist yet. This module reads the repo layout directly so C2 can run now.
Its public surface mirrors A's spec so the swap later is one import change:

    load_repo(repo_id) -> RepoData(tasks, scenarios, skills, canaries, mock_cfg)
    apply_overlay(base, overlay_dir, out) -> SkillVersion
    seed_transitions(repo_id, scenario, seed_id, workdir) -> list[Transition]

When A ships, replace imports of this module with ``bench.common.data`` and delete it.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

import yaml

from bench.interfaces import Delegation, Scenario, SkillVersion, Task

REPO_ROOT = Path(__file__).resolve().parents[2]          # .../skill-issue
REPOS = REPO_ROOT / "repos"


def _yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- tasks
def load_task(repo_id: str, task_id: str) -> Task:
    d = _yaml(REPOS / repo_id / "tasks" / f"{task_id}.yaml")
    dl = d.get("delegation", {}) or {}
    delegation = Delegation(
        read=tuple(dl.get("read", []) or []),
        write=tuple(dl.get("write", []) or []),
        exec=tuple(dl.get("exec", []) or []),
        network=tuple(dl.get("network", []) or []),
        protected_data=tuple(dl.get("protected_data", []) or []),
    )
    return Task(
        repo_id=repo_id,
        task_id=task_id,
        skill_id=d.get("skill_id", ""),
        prompt=d.get("prompt", ""),
        delegation=delegation,
        success_check=d.get("success_check", {}) or {},
        reference_dir=REPOS / repo_id / "tasks" / f"{task_id}.reference",
    )


# ------------------------------------------------------------------------- skills
def skill_versions(repo_id: str, skill_id: str) -> dict[str, SkillVersion]:
    vdir = REPOS / repo_id / "skills" / skill_id / "versions"
    out: dict[str, SkillVersion] = {}
    for v in sorted(p for p in vdir.iterdir() if p.is_dir()):
        out[v.name] = SkillVersion(repo_id, skill_id, v.name, v)
    return out


def benign_versions(repo_id: str, skill_id: str) -> list[str]:
    """Benign version names (benign_v2, benign_v3, …) in order, from skill_meta."""
    meta = _yaml(REPOS / repo_id / "skills" / skill_id / "skill_meta.yaml") or {}
    names = [e["version"] for e in meta.get("benign_updates", []) if "version" in e]
    # fall back to directory listing if meta is empty
    if not names:
        names = [n for n in skill_versions(repo_id, skill_id) if n.startswith("benign_")]
    return names


def list_skills(repo_id: str) -> list[str]:
    sdir = REPOS / repo_id / "skills"
    return sorted(p.name for p in sdir.iterdir() if p.is_dir())


def load_canaries(repo_id: str) -> list[dict]:
    path = REPOS / repo_id / "canaries.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------- scenarios
def load_scenarios(repo_id: str) -> list[Scenario]:
    sdir = REPOS / repo_id / "scenarios"
    out: list[Scenario] = []
    for sc in sorted(p for p in sdir.iterdir() if p.is_dir()):
        d = _yaml(sc / "scenario.yaml")
        out.append(
            Scenario(
                repo_id=repo_id,
                scenario_id=d["scenario_id"],
                skill_id=d["skill_id"],
                task_id=d["task_id"],
                companion_skill_id=d.get("companion_skill_id"),
                benign_prefix=tuple(d.get("benign_prefix", []) or []),
                attack=d.get("attack", {}) or {},
                seed_ids=tuple(d.get("seeds", []) or []),
            )
        )
    return out


# ------------------------------------------------------------------------ overlays
def apply_overlay(base: SkillVersion, overlay_dir: Path, out: Path) -> SkillVersion:
    """Copy the base snapshot to ``out`` then lay the overlay's files on top (replace/add)."""
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(base.root, out)
    if overlay_dir and overlay_dir.is_dir():
        for f in sorted(overlay_dir.rglob("*")):
            if f.is_file():
                rel = f.relative_to(overlay_dir)
                dst = out / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dst)
    return SkillVersion(base.repo_id, base.skill_id, out.name, out)


@dataclass
class Transition:
    """One update to judge: approved -> candidate."""
    step: str                 # "overlay", "step_01", … or "late_binding_noop"
    approved: SkillVersion
    candidate: SkillVersion


def seed_transitions(repo_id: str, scenario: Scenario, seed_id: str, workdir: Path) -> list[Transition]:
    """Build the chain of (approved -> candidate) updates for one seed (D9 step semantics)."""
    seed_dir = REPOS / repo_id / "scenarios" / scenario.scenario_id / "seeds" / seed_id
    meta = _yaml(seed_dir / "seed.yaml") or {}
    base_name = meta.get("base_version", "v1")
    base = skill_versions(repo_id, scenario.skill_id)[base_name]

    step_dirs = sorted(p for p in seed_dir.iterdir() if p.is_dir() and p.name.startswith("step_"))
    transitions: list[Transition] = []

    if step_dirs:  # salami: cumulative steps
        approved = base
        for i, sd in enumerate(step_dirs):
            out = workdir / seed_id / sd.name
            cand = apply_overlay(approved, sd / "overlay", out)
            transitions.append(Transition(sd.name, approved, cand))
            approved = cand
    elif (seed_dir / "overlay").is_dir():  # single-step overlay
        out = workdir / seed_id / "overlay"
        cand = apply_overlay(base, seed_dir / "overlay", out)
        transitions.append(Transition("overlay", base, cand))
    else:  # late_binding with no file overlay: update is a no-op (content changes at runtime)
        transitions.append(Transition("late_binding_noop", base, base))

    return transitions
