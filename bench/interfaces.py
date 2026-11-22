"""Shared contract for ConsentDriftBench (Phase 2).

The dataclasses and Protocols below are the interface contract from the
IMPLEMENTATION_PROMPT, Part 4. They are written exactly as specified; do not
change a signature, dataclass field or file format without an approved entry at
the top of bench/INTERFACE_CHANGES.md (Part 0, rule 3).

Every interface also has a *stub* implementation here so the whole pipeline runs
end to end from day one (Part 0, rule 4). Each workstream replaces the stubs with
real code and keeps the stubs for tests / --dry-run.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

# ---------------------------------------------------------------------------
# Part 4 contract — write these exactly.
# ---------------------------------------------------------------------------

Decision = Literal["allow", "ask", "deny"]


@dataclass(frozen=True)
class Delegation:
    read: tuple[str, ...]; write: tuple[str, ...]; exec: tuple[str, ...]
    network: tuple[str, ...]; protected_data: tuple[str, ...]


@dataclass(frozen=True)
class Task:
    repo_id: str; task_id: str; skill_id: str; prompt: str
    delegation: Delegation; success_check: dict; reference_dir: Path


@dataclass(frozen=True)
class SkillVersion:
    repo_id: str; skill_id: str; version: str      # "v1", "benign_v2", or an attack id like "s21-seed-a-step_02"
    root: Path                                     # directory holding the full snapshot


@dataclass(frozen=True)
class Scenario:
    repo_id: str; scenario_id: str; skill_id: str; task_id: str
    companion_skill_id: str | None; benign_prefix: tuple[str, ...]
    attack: dict; seed_ids: tuple[str, ...]


@dataclass
class OracleResult:
    verdict: Literal["clean", "violation", "unjudgeable"]
    predicates: list[str]          # effects (headline)
    attempts: list[str]            # attempted predicates
    p5_match: Literal["none", "exact", "encoded"]
    problems: list[str] = field(default_factory=list)


class Oracle(Protocol):
    def judge(self, trace_path: Path, task: Task, canaries: list[dict]) -> OracleResult: ...


class MockNetwork(Protocol):
    def start(self, repo_id: str, log_path: Path) -> str: ...            # returns proxy URL
    def set_overrides(self, override_root: Path | None) -> None: ...     # late_binding on/off
    def stop(self) -> None: ...


@dataclass
class ToolCall:
    tool: str; args: dict


class Policy(Protocol):
    name: str
    def on_update(self, approved: SkillVersion, new: SkillVersion, task: Task) -> tuple[Decision, str]: ...
    def on_tool_call(self, call: ToolCall, installed: SkillVersion, task: Task) -> Literal["allow", "block"]: ...


@dataclass
class RunSpec:
    run_id: str; scenario: Scenario | None; task: Task
    installed: dict[str, SkillVersion]     # skill_id -> version to install
    policy: Policy; model: str; invocation: Literal["natural", "explicit"]
    mock_override: Path | None; out_dir: Path; seed: int


class Harness(Protocol):
    def run(self, spec: RunSpec) -> Path: ...        # returns trace path; writes meta.json beside it


@dataclass
class AttackFeedback:
    decision: Decision; effect_happened: bool | None   # None if the agent was not run or the effect is not observable to the attacker (D13)


class Attacker(Protocol):
    name: str
    def proposals(self, scenario: Scenario, base: SkillVersion) -> "AttackSession": ...


class AttackSession(Protocol):
    def next_update(self) -> SkillVersion | None: ...  # None = attacker is done
    def feedback(self, fb: AttackFeedback) -> None: ...


# ---------------------------------------------------------------------------
# Stub implementations — valid dummy values so the pipeline runs from day one.
# Each workstream replaces its own stub(s) with real code (Part 0, rule 4).
# ---------------------------------------------------------------------------


class StubOracle:
    """Oracle stub (workstream A). Always returns a clean verdict."""

    def judge(self, trace_path: Path, task: Task, canaries: list[dict]) -> OracleResult:
        return OracleResult(
            verdict="clean",
            predicates=[],
            attempts=[],
            p5_match="none",
            problems=[],
        )


class StubMockNetwork:
    """Mock network stub (workstream A). Returns a dummy proxy URL, no-ops otherwise."""

    def start(self, repo_id: str, log_path: Path) -> str:
        return "http://127.0.0.1:0"

    def set_overrides(self, override_root: Path | None) -> None:
        return None

    def stop(self) -> None:
        return None


class StubPolicy:
    """Policy stub (workstream C). Allows every update and every tool call."""

    name = "stub"

    def on_update(self, approved: SkillVersion, new: SkillVersion, task: Task) -> tuple[Decision, str]:
        return ("allow", "stub: allow all")

    def on_tool_call(self, call: ToolCall, installed: SkillVersion, task: Task) -> Literal["allow", "block"]:
        return "allow"


class StubHarness:
    """Harness stub (workstream B). Writes a minimal valid trace and meta.json."""

    def run(self, spec: RunSpec) -> Path:
        spec.out_dir.mkdir(parents=True, exist_ok=True)
        trace_path = spec.out_dir / "trace.jsonl"
        with trace_path.open("w") as fh:
            fh.write(json.dumps({"seq": 0, "event": "run_end", "reason": "done", "steps": 0}) + "\n")
        meta_path = spec.out_dir / "meta.json"
        with meta_path.open("w") as fh:
            json.dump(
                {
                    "run_id": spec.run_id,
                    "model": spec.model,
                    "invocation": spec.invocation,
                    "observer": "none",
                    "stub": True,
                },
                fh,
            )
        return trace_path


class StubAttackSession:
    """Attack session stub (workstream D). Produces no updates."""

    def next_update(self) -> SkillVersion | None:
        return None

    def feedback(self, fb: AttackFeedback) -> None:
        return None


class StubAttacker:
    """Attacker stub (workstream D). Immediately-done session."""

    name = "stub"

    def proposals(self, scenario: Scenario, base: SkillVersion) -> "AttackSession":
        return StubAttackSession()
