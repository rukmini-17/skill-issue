"""The static attacker (D13): replays one seed exactly, with no feedback.

A seed is one of three shapes (BUILD_PROMPT 2.7 / data layout):

* ``overlay/``            one update: ``base_version`` snapshot with the overlay laid on top
* ``step_NN/overlay/``    salami: a chain of cumulative updates; step N is step N-1 plus its overlay
* ``mock_override/``      late_binding: the mock host serves different content; the update itself is
                          the overlay if it has real files, otherwise a no-op (the base version again)

The chain is what the attacker *publishes*, so it does not depend on what the policy installed: a
denied step is still the base of the next one. The session exposes ``mock_override`` (a path or
None) for the runner to pass to the harness. ``.keep`` files only hold empty directories in git
and are not part of an update.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import yaml

from bench.interfaces import Scenario, SkillVersion
from bench.runner import data


def _short_name(scenario: Scenario, seed_id: str) -> str:
    """'release-tools-s21-seed-a' -> 's21-seed-a' (the attack-id style used by SkillVersion.version)."""
    return seed_id.removeprefix(f"{scenario.repo_id}-")


def _real_files(overlay: Path) -> list[Path]:
    return [f for f in sorted(overlay.rglob("*")) if f.is_file() and f.name != ".keep"] if overlay.is_dir() else []


def _lay_overlay(base: SkillVersion, overlay: Path, out: Path, name: str) -> SkillVersion:
    """Like data.apply_overlay, but ignores .keep placeholders."""
    v = data.apply_overlay(base, None, out, name)
    for f in _real_files(overlay):
        dst = out / f.relative_to(overlay)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(f.read_bytes())
    return v


class StaticSession:
    def __init__(self, versions: list[SkillVersion], mock_override: Path | None, seed_meta: dict):
        self._versions = list(versions)
        self._i = 0
        self.mock_override = mock_override
        self.seed_meta = seed_meta           # seed.yaml, for logging only (never shown to a model)
        self.feedback_log: list = []

    def next_update(self) -> SkillVersion | None:
        if self._i >= len(self._versions):
            return None
        v = self._versions[self._i]
        self._i += 1
        return v

    def feedback(self, fb) -> None:          # static: no feedback is used
        self.feedback_log.append(fb)


class StaticAttacker:
    name = "static"

    def __init__(self, seed_id: str, workdir: Path | None = None):
        self.seed_id = seed_id
        self.workdir = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="static_attacker_"))

    def proposals(self, scenario: Scenario, base: SkillVersion) -> StaticSession:
        if self.seed_id not in scenario.seed_ids:
            raise ValueError(f"{self.seed_id} is not a seed of {scenario.scenario_id}")
        repo = data.load_repo(scenario.repo_id)
        sdir = data.seed_dir(repo, scenario, self.seed_id)
        meta = yaml.safe_load((sdir / "seed.yaml").read_text(encoding="utf-8")) or {}
        start = repo.skills[scenario.skill_id][meta.get("base_version", "v1")]
        short = _short_name(scenario, self.seed_id)
        out_root = self.workdir / self.seed_id
        mock = sdir / "mock_override"
        mock_override = mock if mock.is_dir() else None

        steps = sorted(p for p in sdir.iterdir() if p.is_dir() and p.name.startswith("step_"))
        versions: list[SkillVersion] = []
        if steps:                                     # salami: each step builds on the previous published one
            cur = start
            for sd in steps:
                cur = _lay_overlay(cur, sd / "overlay", out_root / sd.name, f"{short}-{sd.name}")
                versions.append(cur)
        elif _real_files(sdir / "overlay"):
            versions.append(_lay_overlay(start, sdir / "overlay", out_root / "overlay", short))
        else:                                         # late_binding with nothing to change in the skill files
            versions.append(start)                   # same snapshot as the base: a no-op update
        return StaticSession(versions, mock_override, meta)
