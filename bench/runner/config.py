"""Experiment config (bench/configs/experiments/*.yaml) and grid expansion.

One *episode* = one scenario x one seed x one policy x one attacker x one model x one
invocation x one repeat (D9). Benign experiments replace scenario/seed/attacker with a task.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

import yaml

from bench.runner import data
from bench.runner.ids import short_hash

KINDS = ("attack", "benign_updates", "task_completion")
# Attackers that replay a fixed seed (one run per seed). Adaptive attackers search from the
# scenario, so seed is not a grid dimension for them.
SEEDED_ATTACKERS = ("static",)
ADAPTIVE_ATTACKERS = ("black_box_adaptive", "policy_aware_adaptive")
# Attackers that need no search against a given policy: `none` has nothing to evade (D13).
NO_SEARCH_POLICIES = ("none",)


@dataclass(frozen=True)
class EpisodeKey:
    kind: str
    repo_id: str
    scenario_id: str | None
    task_id: str
    seed_id: str | None
    policy: str
    attacker: str | None
    model: str
    invocation: str
    repeat: int

    def group_id(self) -> str:
        """Episodes that may share an agent run (same everything except policy) form a group.

        Groups are the unit of sharding and of multi-process dispatch, so the agent-run cache
        is only ever touched by one worker at a time for a given group.
        """
        return short_hash(self.kind, self.repo_id, self.scenario_id, self.task_id, self.seed_id,
                          self.attacker, self.model, self.invocation, self.repeat)

    def run_id(self, tag: str) -> str:
        return short_hash(self.kind, self.scenario_id or self.task_id, self.seed_id, self.policy,
                          self.attacker, self.model, self.invocation, self.repeat, tag)


@dataclass
class ExperimentConfig:
    name: str
    kind: str = "attack"
    repos: list[str] = field(default_factory=lambda: ["all"])
    scenarios: list[str] | str = "all"        # attack: scenario ids, or "all"
    tasks: list[str] | str = "all"            # benign kinds: task ids, or "all"
    max_scenarios_per_repo: int | None = None  # pilot-size cap; applied after sorting by id
    policies: list[str] = field(default_factory=lambda: ["none"])
    attackers: list[str] = field(default_factory=lambda: ["stub"])
    models: list[str] = field(default_factory=lambda: ["qwen3-8b"])
    invocations: list[str] = field(default_factory=lambda: ["natural"])
    repeats: int = 1
    budget: int = 25                           # adaptive proposals per scenario per policy (team decision 2026-11-26; was 50)
    stop_at_bypass: bool = True                # adaptive: the runner ends a search at its first bypass (queries-to-first-bypass, D10)
    # Benign runs (runner output or B's pilot rows) whose goal-on-target hits are subtracted before
    # a proposal counts as a bypass ("beyond what the task's benign runs already do"). Empty = raw hits.
    baseline_runs: list[str] = field(default_factory=list)
    harness_options: dict = field(default_factory=dict)   # B's Harness(...) kwargs: isolation, observer, run_timeout, setup
    components: dict[str, str] = field(default_factory=dict)  # optional dotted-path overrides ("proposer": "pkg.mod:Class")

    @classmethod
    def load(cls, path: Path) -> "ExperimentConfig":
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        unknown = set(raw) - set(cls.__dataclass_fields__)
        if unknown:
            raise ValueError(f"{path}: unknown experiment keys {sorted(unknown)}")
        cfg = cls(**raw)
        cfg.validate()
        return cfg

    def validate(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"kind must be one of {KINDS}, got {self.kind!r}")
        for key in ("policies", "models", "invocations"):
            if not getattr(self, key):
                raise ValueError(f"{key} must not be empty")
        for inv in self.invocations:
            if inv not in ("natural", "explicit"):
                raise ValueError(f"invocation must be natural or explicit, got {inv!r}")
        if self.kind == "attack" and not self.attackers:
            raise ValueError("attack experiments need at least one attacker")
        if self.repeats < 1:
            raise ValueError("repeats must be >= 1")
        if self.budget < 1:
            raise ValueError("budget must be >= 1")
        bad = set(self.harness_options) - {"isolation", "observer", "run_timeout", "setup", "max_steps", "mock"}
        if bad:
            raise ValueError(f"unknown harness_options {sorted(bad)}")


def _repos(cfg: ExperimentConfig) -> list[str]:
    return data.repo_ids() if cfg.repos == ["all"] or cfg.repos == "all" else list(cfg.repos)


def expand(cfg: ExperimentConfig) -> Iterator[EpisodeKey]:
    """Yield every episode of the experiment in a deterministic order."""
    for repo_id in _repos(cfg):
        repo = data.load_repo(repo_id)
        if cfg.kind == "attack":
            ids = sorted(repo.scenarios) if cfg.scenarios == "all" else [s for s in cfg.scenarios if s in repo.scenarios]
            if cfg.max_scenarios_per_repo is not None:
                ids = ids[: cfg.max_scenarios_per_repo]
            for sid in ids:
                sc = repo.scenarios[sid]
                for attacker in cfg.attackers:
                    seeds: list[str | None] = list(sc.seed_ids) if attacker in SEEDED_ATTACKERS else [None]
                    for seed_id in seeds:
                        for policy in cfg.policies:
                            if attacker not in SEEDED_ATTACKERS and attacker != "stub" and policy in NO_SEARCH_POLICIES:
                                continue
                            for model in cfg.models:
                                for inv in cfg.invocations:
                                    for rep in range(cfg.repeats):
                                        yield EpisodeKey("attack", repo_id, sid, sc.task_id, seed_id,
                                                         policy, attacker, model, inv, rep)
        else:
            ids = sorted(repo.tasks) if cfg.tasks == "all" else [t for t in cfg.tasks if t in repo.tasks]
            for tid in ids:
                for policy in cfg.policies:
                    for model in cfg.models:
                        for inv in cfg.invocations:
                            for rep in range(cfg.repeats):
                                yield EpisodeKey(cfg.kind, repo_id, None, tid, None, policy, None, model, inv, rep)
