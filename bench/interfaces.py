"""Shared contract for ConsentDriftBench (Part 4 of the implementation prompt).

This is a JOINT file. The signatures below are copied from Part 4 verbatim and must
not be changed without a proposal at the top of bench/INTERFACE_CHANGES.md and human
approval. Every Protocol has a stub implementation so the whole pipeline runs end to
end on stubs from day one (M0); real implementations live in each workstream's package
and are swapped in, while these stubs stay for tests and --dry-run.

Seeded by Workstream A per Part 4; see bench/INTERFACE_CHANGES.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

Decision = Literal["allow", "ask", "deny"]


# --------------------------------------------------------------------------- #
# Data models                                                                 #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Delegation:
    read: tuple[str, ...]
    write: tuple[str, ...]
    exec: tuple[str, ...]
    network: tuple[str, ...]
    protected_data: tuple[str, ...]


@dataclass(frozen=True)
class Task:
    repo_id: str
    task_id: str
    skill_id: str
    prompt: str
    delegation: Delegation
    success_check: dict
    reference_dir: Path


@dataclass(frozen=True)
class SkillVersion:
    repo_id: str
    skill_id: str
    version: str          # "v1", "benign_v2", or an attack id like "s21-seed-a-step_02"
    root: Path            # directory holding the full snapshot


@dataclass(frozen=True)
class Scenario:
    repo_id: str
    scenario_id: str
    skill_id: str
    task_id: str
    companion_skill_id: str | None
    benign_prefix: tuple[str, ...]
    attack: dict
    seed_ids: tuple[str, ...]


@dataclass
class OracleResult:
    verdict: Literal["clean", "violation", "unjudgeable"]
    predicates: list[str]          # effects (headline)
    attempts: list[str]            # attempted predicates
    p5_match: Literal["none", "exact", "encoded"]
    problems: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Protocols                                                                    #
# --------------------------------------------------------------------------- #
class Oracle(Protocol):
    def judge(self, trace_path: Path, task: Task, canaries: list[dict]) -> OracleResult: ...


class MockNetwork(Protocol):
    # IC-1 (approved): optional mock_root serves files built by setup.sh in the run's
    # sandbox, falling back to repos/<repo_id>/ when not given.
    def start(self, repo_id: str, log_path: Path, mock_root: Path | None = None) -> str: ...  # proxy URL
    def set_overrides(self, override_root: Path | None) -> None: ...     # late_binding on/off
    def stop(self) -> None: ...


@dataclass
class ToolCall:
    tool: str
    args: dict


class Policy(Protocol):
    name: str

    def on_update(self, approved: SkillVersion, new: SkillVersion, task: Task) -> tuple[Decision, str]: ...
    def on_tool_call(self, call: ToolCall, installed: SkillVersion, task: Task) -> Literal["allow", "block"]: ...


@dataclass
class RunSpec:
    run_id: str
    scenario: Scenario | None
    task: Task
    installed: dict[str, SkillVersion]     # skill_id -> version to install
    policy: Policy
    model: str
    invocation: Literal["natural", "explicit"]
    mock_override: Path | None
    out_dir: Path
    seed: int


class Harness(Protocol):
    def run(self, spec: RunSpec) -> Path: ...        # returns trace path; writes meta.json beside it


@dataclass
class AttackFeedback:
    decision: Decision
    effect_happened: bool | None   # None if the agent was not run


class Attacker(Protocol):
    name: str

    def proposals(self, scenario: Scenario, base: SkillVersion) -> "AttackSession": ...


class AttackSession(Protocol):
    def next_update(self) -> SkillVersion | None: ...  # None = attacker is done
    def feedback(self, fb: AttackFeedback) -> None: ...


# --------------------------------------------------------------------------- #
# Stub implementations (keep for tests and --dry-run)                         #
# --------------------------------------------------------------------------- #
class StubOracle:
    """Always returns a clean verdict. Replaced by bench.oracle.Oracle."""

    def judge(self, trace_path: Path, task: Task, canaries: list[dict]) -> OracleResult:
        return OracleResult(verdict="clean", predicates=[], attempts=[], p5_match="none")


class StubMockNetwork:
    def start(self, repo_id: str, log_path: Path, mock_root: Path | None = None) -> str:
        return "http://127.0.0.1:0"

    def set_overrides(self, override_root: Path | None) -> None:
        return None

    def stop(self) -> None:
        return None


class StubPolicy:
    name = "none"

    def on_update(self, approved: SkillVersion, new: SkillVersion, task: Task) -> tuple[Decision, str]:
        return ("allow", "stub: allow all")

    def on_tool_call(self, call: ToolCall, installed: SkillVersion, task: Task) -> Literal["allow", "block"]:
        return "allow"


class StubHarness:
    """Writes a minimal valid trace and meta.json so the pipeline runs on stubs."""

    def run(self, spec: RunSpec) -> Path:
        import json

        spec.out_dir.mkdir(parents=True, exist_ok=True)
        trace_path = spec.out_dir / "trace.jsonl"
        trace_path.write_text(
            json.dumps({"seq": 1, "event": "run_end", "reason": "done", "steps": 0}) + "\n",
            encoding="utf-8",
        )
        (spec.out_dir / "meta.json").write_text(
            json.dumps({"run_id": spec.run_id, "model": spec.model, "observer": "none"}),
            encoding="utf-8",
        )
        return trace_path


class StubAttackSession:
    def __init__(self, base: SkillVersion) -> None:
        self._base = base
        self._done = False

    def next_update(self) -> SkillVersion | None:
        if self._done:
            return None
        self._done = True
        return self._base

    def feedback(self, fb: AttackFeedback) -> None:
        return None


class StubAttacker:
    name = "static"

    def proposals(self, scenario: Scenario, base: SkillVersion) -> "AttackSession":
        return StubAttackSession(base)
