"""Builds the pluggable parts of a run (harness, oracle, policy, attacker, success checker).

``--dry-run`` uses the stubs from bench/interfaces.py for the harness, oracle and mock
network. Policies stay real in a dry run because they are deterministic and offline;
``llm_reviewer`` is replaced by a stub that allows everything, since it needs a model.
Outside a dry run, parts are resolved by dotted path ("package.module:Name"), either from
the experiment's ``components:`` block or from DEFAULTS below. The defaults point at
modules other workstreams own and will fail with a clear message until those land.
"""

from __future__ import annotations

import importlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bench.interfaces import (Harness, Oracle, Policy, StubAttacker, StubHarness, StubOracle, StubPolicy)

# Policies whose on_tool_call can block a call (D12). An agent run under one of these cannot be
# shared with a policy that has no runtime checks, because blocked calls change the run.
RUNTIME_POLICIES = frozenset({"deny_by_default_manifest", "delegation_envelope"})

DEFAULTS = {
    "harness": "bench.harness.run:Harness",         # B (not yet merged)
    "oracle": "bench.oracle:Oracle",                # A (on main, data-v1)
    "attacker:static": "bench.attackers.static:StaticAttacker",             # D2
    "attacker:black_box_adaptive": "bench.attackers.adaptive:BlackBoxAttacker",   # D4
    "attacker:policy_aware_adaptive": "bench.attackers.adaptive:PolicyAwareAttacker",  # D4
}


def resolve(dotted: str) -> Any:
    mod, _, name = dotted.partition(":")
    try:
        return getattr(importlib.import_module(mod), name)
    except (ImportError, AttributeError) as e:
        raise RuntimeError(f"cannot load {dotted!r}: {e}. This part belongs to another workstream "
                           f"and may not be merged yet; use --dry-run or set components: in the config.") from e


class SuccessChecker:
    """Returns the task's success result for a run.

    B's harness evaluates ``success_check`` inside the sandbox and writes ``success.json`` (and a
    copy in ``meta.json["success"]``); the runner reads that and never recomputes it (team note,
    2026-11-22). With no harness result (stub harness, or no agent run) success is unknown (None).
    """

    def check(self, task, run_dir: Path) -> dict:
        path = run_dir / "success.json"
        try:
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
            meta_path = run_dir / "meta.json"
            if meta_path.exists():
                success = json.loads(meta_path.read_text(encoding="utf-8")).get("success")
                if isinstance(success, dict):
                    return success
        except (OSError, ValueError) as e:
            return {"success": None, "checked": False, "reason": f"unreadable harness result: {e}"}
        return {"success": None, "checked": False, "reason": "no harness success result"}


@dataclass
class Components:
    harness: Harness
    oracle: Oracle
    success: SuccessChecker
    dry_run: bool
    overrides: dict[str, str]

    def make_policy(self, name: str) -> Policy:
        from bench.policies import get_policy
        if name == "llm_reviewer":
            if self.dry_run:
                p = StubPolicy()
                p.name = "llm_reviewer"
                return p
            return get_policy(name)       # C wires the model client; needs B's backend
        return get_policy(name)

    def make_attacker(self, name: str, seed_id: str | None = None, workdir: Path | None = None, **ctx):
        if name == "stub":
            return StubAttacker()
        target = self.overrides.get(f"attacker:{name}") or DEFAULTS.get(f"attacker:{name}")
        if target is None:
            raise RuntimeError(f"unknown attacker {name!r}")
        cls = resolve(target)
        if name == "static":
            return cls(seed_id=seed_id, workdir=workdir)
        proposer = self.overrides.get("proposer")           # stage 3, supplied by the team (D13)
        if proposer:
            ctx["proposer"] = resolve(proposer)()
        return cls(workdir=workdir, **ctx)


def build(dry_run: bool, overrides: dict[str, str] | None = None) -> Components:
    overrides = dict(overrides or {})
    if dry_run:
        return Components(StubHarness(), StubOracle(), SuccessChecker(), True, overrides)
    harness = resolve(overrides.get("harness", DEFAULTS["harness"]))()
    oracle = resolve(overrides.get("oracle", DEFAULTS["oracle"]))()
    return Components(harness, oracle, SuccessChecker(), False, overrides)
