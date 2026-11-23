"""One episode (D9): approve v1, process updates through the policy, run the agent, judge.

Updates follow D9: each update is judged against the last *installed* version; ``allow`` and
``ask`` install it (an ask is recorded and weighted later, D10); ``deny`` does not install it and
the next update is still offered. For late_binding the mock override is switched on after the last
update. The agent runs once on the final installed state, and agent runs are cached across
policies that end in the same state (see ``agent_cache_key``).

Output files (Part 4): decisions.jsonl, trace.jsonl, meta.json, success.json, oracle.json.
``oracle.json`` is written last; its presence marks the run directory complete.
"""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import asdict
from pathlib import Path

from bench.interfaces import AttackFeedback, OracleResult, RunSpec, SkillVersion
from bench.runner import data
from bench.runner.components import RUNTIME_POLICIES, Components
from bench.runner.config import EpisodeKey
from bench.runner.ids import data_tag, git_sha, short_hash, tree_hash


def agent_cache_key(task_id: str, model: str, invocation: str, repeat: int,
                    installed: dict[str, SkillVersion], mock_override: Path | None, policy) -> str:
    """Two runs share an agent run only if everything the agent can see or be blocked by matches.

    Policies with run-time checks are keyed by name: their blocked calls change the run, so they
    never share with another policy (a deviation from the letter of D9; see NOTES.md).
    """
    runtime = policy.name if (policy.name in RUNTIME_POLICIES or getattr(policy, "has_runtime_checks", False)) else "-"
    skills = sorted((sid, tree_hash(v.root)) for sid, v in installed.items())
    return short_hash(task_id, model, invocation, repeat, skills, tree_hash(mock_override), runtime, n=20)


def _write_json(path: Path, obj) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str), encoding="utf-8")
    tmp.replace(path)


class _Decisions:
    def __init__(self, path: Path):
        self.path = path
        self.rows: list[dict] = []
        path.touch()                       # exists even when there are no updates

    def add(self, row: dict) -> None:
        row = {"i": len(self.rows), **row}
        self.rows.append(row)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, sort_keys=True) + "\n")


def run_episode(key: EpisodeKey, comps: Components, runs_dir: Path, workdir: Path) -> dict:
    tag = data_tag()
    run_id = key.run_id(tag)
    out_dir = runs_dir / run_id
    if (out_dir / "oracle.json").exists():
        return {"run_id": run_id, "status": "skipped"}
    if out_dir.exists():                      # partial leftovers from a killed run
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    t0 = time.time()

    repo = data.load_repo(key.repo_id)
    task = repo.tasks[key.task_id]
    scenario = repo.scenarios[key.scenario_id] if key.scenario_id else None
    policy = comps.make_policy(key.policy)
    decisions = _Decisions(out_dir / "decisions.jsonl")

    approved = repo.v1(task.skill_id)             # v1 is approved at the start (D9)
    asks = 0
    denied = {"benign_prefix": 0, "attack": 0, "benign": 0}
    mock_override: Path | None = None
    attacker_name = key.attacker

    def offer(phase: str, new: SkillVersion) -> str:
        nonlocal approved, asks
        if new.root == approved.root:        # a no-op update (late_binding): nothing to review
            decisions.add({"phase": phase, "from_version": approved.version, "to_version": new.version,
                           "decision": "allow", "reason": "no-op update", "installed": False, "noop": True})
            return "allow"
        decision, reason = policy.on_update(approved, new, task)
        installed = decision in ("allow", "ask")
        decisions.add({"phase": phase, "policy": policy.name, "from_version": approved.version,
                       "to_version": new.version, "decision": decision, "reason": reason, "installed": installed})
        if decision == "ask":
            asks += 1
        if decision == "deny":
            denied[phase] += 1
        if installed:
            approved = new
        return decision

    if key.kind == "attack":
        for name in scenario.benign_prefix:
            offer("benign_prefix", repo.skills[task.skill_id][name])
        attacker = comps.make_attacker(key.attacker, key.seed_id, workdir / run_id)
        session = attacker.proposals(scenario, approved)
        while (new := session.next_update()) is not None:
            d = offer("attack", new)
            session.feedback(AttackFeedback(decision=d, effect_happened=None))
        mock_override = getattr(session, "mock_override", None)   # late_binding: on after the last update
    elif key.kind == "benign_updates":
        for name in repo.benign[task.skill_id]:
            offer("benign", repo.skills[task.skill_id][name])

    installed = repo.install_set({task.skill_id: approved})
    spec = RunSpec(run_id=run_id, scenario=scenario, task=task, installed=installed, policy=policy,
                   model=key.model, invocation=key.invocation, mock_override=mock_override,
                   out_dir=out_dir, seed=key.repeat)

    # ---- agent run, with cross-policy caching
    cache_dir = runs_dir / "_agent_cache" / agent_cache_key(
        task.task_id, key.model, key.invocation, key.repeat, installed, mock_override, policy)
    reused_from = None
    if (cache_dir / "trace.jsonl").exists():
        for f in cache_dir.iterdir():
            (shutil.copytree if f.is_dir() else shutil.copy2)(f, out_dir / f.name)
        trace_path = out_dir / "trace.jsonl"
        reused_from = cache_dir.name
    else:
        trace_path = comps.harness.run(spec)
        tmp = cache_dir.with_name(cache_dir.name + f".tmp{run_id}")
        cache_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(out_dir, tmp, ignore=shutil.ignore_patterns("decisions.jsonl"))
        try:
            tmp.replace(cache_dir)
        except OSError:                              # another worker won the race; keep theirs
            shutil.rmtree(tmp, ignore_errors=True)

    # ---- meta, success, oracle (oracle last)
    meta_path = out_dir / "meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    meta.update({
        "run_id": run_id, "kind": key.kind, "repo_id": key.repo_id, "scenario_id": key.scenario_id,
        "task_id": key.task_id, "seed_id": key.seed_id, "policy": key.policy, "attacker": attacker_name,
        "model": key.model, "invocation": key.invocation, "repeat": key.repeat,
        "data_tag": tag, "git_sha": git_sha(), "dry_run": comps.dry_run,
        "installed": {sid: v.version for sid, v in installed.items()},
        "asks": asks, "denied": denied, "n_updates": len(decisions.rows),
        "mock_override": str(mock_override) if mock_override else None,
        "agent_run_reused_from": reused_from, "runner_seconds": round(time.time() - t0, 3),
    })
    _write_json(meta_path, meta)
    _write_json(out_dir / "success.json", comps.success.check(task, out_dir))
    try:
        result = comps.oracle.judge(trace_path, task, repo.canaries)
    except Exception as e:                           # a bad trace must never crash the sweep
        result = OracleResult("unjudgeable", [], [], "none", [f"oracle error: {type(e).__name__}: {e}"])
    _write_json(out_dir / "oracle.json", asdict(result))
    shutil.rmtree(workdir / run_id, ignore_errors=True)       # materialised attack versions
    return {"run_id": run_id, "status": "reused" if reused_from else "ran", "verdict": result.verdict}
