"""Data loading for C2/C3, on top of A's `bench.common.data` (load_repo, apply_overlay).

A owns the repo loaders; this module is the thin C-side view the policy reports were
written against (granular `load_task` / `skill_versions` / `load_scenarios` lookups and
the `seed_transitions` update-chain builder C2 needs). It now delegates to
`bench.common.data`; earlier it read the repo layout directly (see RECONCILE.md).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from bench.common import data as _data
from bench.interfaces import Scenario, SkillVersion, Task

REPO_ROOT = _data.REPO_ROOT          # .../skill-issue
REPOS = _data.REPOS_DIR              # .../skill-issue/repos

# apply_overlay is A's (copy base + lay overlay files on top); re-exported unchanged.
apply_overlay = _data.apply_overlay


# --------------------------------------------------------------------------- tasks
def load_task(repo_id: str, task_id: str) -> Task:
    return _data.load_repo(repo_id).tasks[task_id]


# ------------------------------------------------------------------------- skills
def skill_versions(repo_id: str, skill_id: str) -> dict[str, SkillVersion]:
    return dict(_data.load_repo(repo_id).skill_versions[skill_id])


def benign_versions(repo_id: str, skill_id: str) -> list[str]:
    """Benign version names (benign_v2, benign_v3, …) in order, from skill_meta."""
    meta = _data.load_repo(repo_id).skill_meta.get(skill_id, {}) or {}
    names = [e["version"] for e in meta.get("benign_updates", []) if "version" in e]
    # fall back to directory listing if meta is empty
    if not names:
        names = [n for n in skill_versions(repo_id, skill_id) if n.startswith("benign_")]
    return names


def list_skills(repo_id: str) -> list[str]:
    return sorted(_data.load_repo(repo_id).skill_versions)


def load_canaries(repo_id: str) -> list[dict]:
    return _data.load_repo(repo_id).canaries


# ---------------------------------------------------------------------- scenarios
def load_scenarios(repo_id: str) -> list[Scenario]:
    return list(_data.load_repo(repo_id).scenarios.values())


# ------------------------------------------------------------------------ overlays
@dataclass
class Transition:
    """One update to judge: approved -> candidate."""
    step: str                 # "overlay", "step_01", … or "late_binding_noop"
    approved: SkillVersion
    candidate: SkillVersion


def seed_transitions(repo_id: str, scenario: Scenario, seed_id: str, workdir: Path) -> list[Transition]:
    """Build the chain of (approved -> candidate) updates for one seed (D9 step semantics)."""
    repo = _data.load_repo(repo_id)
    seed = repo.seeds(scenario.scenario_id)[seed_id]
    base = repo.skill_versions[scenario.skill_id][seed.base_version]
    transitions: list[Transition] = []

    if seed.step_dirs:  # salami: cumulative steps (each step_dir is .../step_NN/overlay)
        approved = base
        for overlay in seed.step_dirs:
            step_name = overlay.parent.name          # "step_01", …
            out = workdir / seed_id / step_name
            cand = apply_overlay(approved, overlay, out, version=step_name)
            transitions.append(Transition(step_name, approved, cand))
            approved = cand
    elif seed.overlay_dir is not None:  # single-step overlay
        out = workdir / seed_id / "overlay"
        cand = apply_overlay(base, seed.overlay_dir, out, version="overlay")
        transitions.append(Transition("overlay", base, cand))
    else:  # late_binding with no file overlay: update is a no-op (content changes at runtime)
        transitions.append(Transition("late_binding_noop", base, base))

    return transitions
