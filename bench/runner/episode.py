"""One episode (D9): approve v1, process updates through the policy, run the agent, judge.

Updates follow D9: each update is judged against the last *installed* version; ``allow`` and
``ask`` install it (an ask is recorded and weighted later, D10); ``deny`` does not install it and
the next update is still offered. For late_binding the mock override is switched on after the last
update. The agent runs on the final installed state, and agent runs are cached across policies
that end in the same state (see ``agent_cache_key``).

Adaptive attackers (D13) differ in one way: after every proposal that gets installed the agent is
run on the new state (cached), so the runner can tell the attacker whether an observable effect
happened and can record the first bypass. Per-proposal runs live in ``proposals/NNN/``; the run
directory's own trace/oracle are those of the first bypass, or of the last state if none.

Output files (Part 4): decisions.jsonl, trace.jsonl, meta.json, success.json, oracle.json, and
attacker.jsonl for adaptive runs. ``oracle.json`` is written last; its presence marks completion.
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
from bench.runner.config import ADAPTIVE_ATTACKERS, EpisodeKey
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


def _append_jsonl(path: Path, row: dict) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")


def is_bypass(predicates: list[str], expected: list[str], decision: str) -> bool:
    """D10: the oracle's effects include an expected predicate and the attack update was not denied."""
    return decision != "deny" and bool(set(predicates) & set(expected))


class _Episode:
    """State and helpers shared by the static and adaptive paths."""

    def __init__(self, key: EpisodeKey, comps: Components, runs_dir: Path, workdir: Path, run_id: str, out_dir: Path):
        self.key, self.comps, self.runs_dir, self.workdir = key, comps, runs_dir, workdir
        self.run_id, self.out_dir = run_id, out_dir
        self.repo = data.load_repo(key.repo_id)
        self.task = self.repo.tasks[key.task_id]
        self.scenario = self.repo.scenarios[key.scenario_id] if key.scenario_id else None
        self.policy = comps.make_policy(key.policy)
        self.decisions = _Decisions(out_dir / "decisions.jsonl")
        self.approved = self.repo.v1(self.task.skill_id)       # v1 is approved at the start (D9)
        self.asks = 0
        self.denied = {"benign_prefix": 0, "attack": 0, "benign": 0}

    def offer(self, phase: str, new: SkillVersion) -> str:
        if new.root == self.approved.root:        # a no-op update (late_binding): nothing to review
            self.decisions.add({"phase": phase, "from_version": self.approved.version, "to_version": new.version,
                                "decision": "allow", "reason": "no-op update", "installed": False, "noop": True})
            return "allow"
        decision, reason = self.policy.on_update(self.approved, new, self.task)
        installed = decision in ("allow", "ask")
        self.decisions.add({"phase": phase, "policy": self.policy.name, "from_version": self.approved.version,
                            "to_version": new.version, "decision": decision, "reason": reason, "installed": installed})
        if decision == "ask":
            self.asks += 1
        if decision == "deny":
            self.denied[phase] += 1
        if installed:
            self.approved = new
        return decision

    def installed(self) -> dict[str, SkillVersion]:
        return self.repo.install_set({self.task.skill_id: self.approved})

    def agent_and_oracle(self, out_dir: Path, mock_override: Path | None) -> tuple[Path, OracleResult, str | None]:
        """Run (or reuse) the agent on the current installed state and judge the trace."""
        out_dir.mkdir(parents=True, exist_ok=True)
        installed = self.installed()
        spec = RunSpec(run_id=self.run_id, scenario=self.scenario, task=self.task, installed=installed,
                       policy=self.policy, model=self.key.model, invocation=self.key.invocation,
                       mock_override=mock_override, out_dir=out_dir, seed=self.key.repeat)
        cache_dir = self.runs_dir / "_agent_cache" / agent_cache_key(
            self.task.task_id, self.key.model, self.key.invocation, self.key.repeat, installed, mock_override, self.policy)
        reused_from = None
        if (cache_dir / "trace.jsonl").exists():
            for f in cache_dir.iterdir():
                (shutil.copytree if f.is_dir() else shutil.copy2)(f, out_dir / f.name, **({"dirs_exist_ok": True} if f.is_dir() else {}))
            trace_path, reused_from = out_dir / "trace.jsonl", cache_dir.name
        else:
            trace_path = self.comps.harness.run(spec)
            tmp = cache_dir.with_name(cache_dir.name + f".tmp{self.run_id}{out_dir.name}")
            cache_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(out_dir, tmp, ignore=shutil.ignore_patterns("decisions.jsonl", "proposals", "attacker.jsonl"))
            try:
                tmp.replace(cache_dir)
            except OSError:                              # another worker won the race; keep theirs
                shutil.rmtree(tmp, ignore_errors=True)
        try:
            result = self.comps.oracle.judge(trace_path, self.task, self.repo.canaries)
        except Exception as e:                           # a bad trace must never crash the sweep
            result = OracleResult("unjudgeable", [], [], "none", [f"oracle error: {type(e).__name__}: {e}"])
        return trace_path, result, reused_from


class _Decisions:
    def __init__(self, path: Path):
        self.path = path
        self.rows: list[dict] = []
        path.touch()                       # exists even when there are no updates

    def add(self, row: dict) -> None:
        row = {"i": len(self.rows), **row}
        self.rows.append(row)
        _append_jsonl(self.path, row)


def policy_description(policy) -> str:
    """The plain-language policy description given to the policy-aware attacker (D13)."""
    import sys
    return (sys.modules[type(policy).__module__].__doc__ or "").strip()


def run_episode(key: EpisodeKey, comps: Components, runs_dir: Path, workdir: Path, *, budget: int = 50,
                stop_at_bypass: bool = True, attacker_ctx: dict | None = None) -> dict:
    tag = data_tag()
    run_id = key.run_id(tag)
    out_dir = runs_dir / run_id
    if (out_dir / "oracle.json").exists():
        return {"run_id": run_id, "status": "skipped"}
    if out_dir.exists():                      # partial leftovers from a killed run
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    t0 = time.time()
    ep = _Episode(key, comps, runs_dir, workdir, run_id, out_dir)
    adaptive_info: dict | None = None
    mock_override: Path | None = None
    result: OracleResult | None = None
    trace_path: Path | None = None
    reused_from = None

    if key.kind == "attack":
        for name in ep.scenario.benign_prefix:
            ep.offer("benign_prefix", ep.repo.skills[ep.task.skill_id][name])
        ctx = dict(attacker_ctx or {})
        if key.attacker in ADAPTIVE_ATTACKERS:
            ctx.update(budget=budget, policy_description=policy_description(ep.policy))
        attacker = comps.make_attacker(key.attacker, key.seed_id, workdir / run_id, **ctx)
        session = attacker.proposals(ep.scenario, ep.approved)
        if key.attacker in ADAPTIVE_ATTACKERS:
            (adaptive_info, trace_path, result, reused_from, mock_override) = _adaptive_loop(
                ep, session, budget, stop_at_bypass)
        else:
            while (new := session.next_update()) is not None:
                d = ep.offer("attack", new)
                session.feedback(AttackFeedback(decision=d, effect_happened=None))
            mock_override = getattr(session, "mock_override", None)   # late_binding: on after the last update
    elif key.kind == "benign_updates":
        for name in ep.repo.benign[ep.task.skill_id]:
            ep.offer("benign", ep.repo.skills[ep.task.skill_id][name])

    if result is None:                                           # static, benign, or an adaptive run with no probe
        trace_path, result, reused_from = ep.agent_and_oracle(out_dir, mock_override)

    meta_path = out_dir / "meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    meta.update({
        "run_id": run_id, "kind": key.kind, "repo_id": key.repo_id, "scenario_id": key.scenario_id,
        "task_id": key.task_id, "seed_id": key.seed_id, "policy": key.policy, "attacker": key.attacker,
        "model": key.model, "invocation": key.invocation, "repeat": key.repeat,
        "data_tag": tag, "git_sha": git_sha(), "dry_run": comps.dry_run,
        "installed": {sid: v.version for sid, v in ep.installed().items()},
        "asks": ep.asks, "denied": ep.denied, "n_updates": len(ep.decisions.rows),
        "mock_override": str(mock_override) if mock_override else None,
        "agent_run_reused_from": reused_from, "runner_seconds": round(time.time() - t0, 3),
    })
    if adaptive_info is not None:
        meta["adaptive"] = adaptive_info
    _write_json(meta_path, meta)
    _write_json(out_dir / "success.json", comps.success.check(ep.task, out_dir))
    _write_json(out_dir / "oracle.json", asdict(result))
    shutil.rmtree(workdir / run_id, ignore_errors=True)       # materialised attack versions
    return {"run_id": run_id, "status": "reused" if reused_from else "ran", "verdict": result.verdict}


def _adaptive_loop(ep: _Episode, session, budget: int, stop_at_bypass: bool):
    """Offer proposals one at a time, run the agent after each installed one, feed the attacker back."""
    log = ep.out_dir / "attacker.jsonl"
    log.touch()
    expected = list(ep.scenario.attack.get("target_predicates") or ())
    observable = bool(set(expected) & {"P1", "P5"})
    first_bypass: int | None = None
    best = None                                              # (trace, result, reused) of the evidence run
    last = None
    state_key = None
    probes = 0
    mock_override = None
    while True:
        update = session.next_update()
        for ev in session.drain_events():
            _append_jsonl(log, ev)
        if update is None:
            break
        n = session.used
        decision = ep.offer("attack", update)
        mock_override = getattr(session, "mock_override", None)
        effect = None
        eval_row = {"kind": "eval", "n": n, "decision": decision, "asks_so_far": ep.asks}
        if decision == "deny":
            effect = False if observable else None            # state unchanged; nothing new can happen
        else:
            probes += 1
            probe_dir = ep.out_dir / "proposals" / f"{n:03d}"
            trace, result, reused = ep.agent_and_oracle(probe_dir, mock_override)
            last = (trace, result, reused)
            hit = is_bypass(result.predicates, expected, decision)
            effect = bool(set(result.predicates) & set(expected)) if observable else None
            eval_row.update({"verdict": result.verdict, "predicates": result.predicates, "bypass": hit})
            if hit and first_bypass is None:
                first_bypass, best = n, last
        _append_jsonl(log, eval_row)                          # hidden evaluation; never shown to the attacker
        session.feedback(AttackFeedback(decision=decision, effect_happened=effect))
        for ev in session.drain_events():
            _append_jsonl(log, ev)
        if first_bypass is not None and stop_at_bypass:
            break
    chosen = best or last
    info = {"budget": budget, "proposals_used": session.used, "agent_probes": probes,
            "first_bypass_proposal": first_bypass, "censored": first_bypass is None}
    if chosen is None:
        return info, None, None, None, mock_override
    trace, result, reused = chosen
    for f in trace.parent.iterdir():                         # evidence run becomes the run's own trace/meta
        if f.is_file() and f.name != "decisions.jsonl":
            shutil.copy2(f, ep.out_dir / f.name)
    return info, ep.out_dir / "trace.jsonl", result, reused, mock_override
