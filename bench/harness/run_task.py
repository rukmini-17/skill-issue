"""Run one task once with a real model, benign (v1 skills, policy none). For checkpoint 3 and pilots.

    .venv/bin/python -m bench.harness.run_task ops-office-t05 --model qwen3-8b-ollama
    .venv/bin/python -m bench.harness.run_task ops-office-t05 --model qwen3-8b-llamacpp \
        --isolation netns --observer strace --judge          # first real COOK run

``--judge`` also judges the trace with A's oracle (bench.oracle) and prints
trace validity (A's trace_schema.json, via the oracle's problems list), the
verdict and predicates; it writes ``oracle.json`` next to the trace.

Models come from bench/configs/models.yaml (or $CDB_MODELS).

Writes runs/dev/<task>-<model>-<n>/ (trace.jsonl, meta.json, messages.json,
success.json, mock.jsonl) and prints a summary. The summary never prints tool
outputs, so canary values do not reach the terminal (Part 0, rule 12).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import yaml

from bench.harness.run import REPO_ROOT, REPOS, Harness
from bench.harness.skills import repo_install_set
from bench.interfaces import Delegation, RunSpec, StubPolicy, Task


def load_task(task_id: str) -> Task:
    repo_id = task_id.rsplit("-t", 1)[0]
    p = REPOS / repo_id / "tasks" / f"{task_id}.yaml"
    d = yaml.safe_load(p.read_text())
    dl = d["delegation"]
    return Task(repo_id, d["task_id"], d["skill_id"], d["prompt"],
                Delegation(*(tuple(dl.get(k) or ()) for k in ("read", "write", "exec", "network",
                                                               "protected_data"))),
                d["success_check"], p.with_suffix(".reference"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("task_id")
    ap.add_argument("--model", required=True, help="name in the models file ($CDB_MODELS)")
    ap.add_argument("--invocation", default="natural", choices=["natural", "explicit"])
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--isolation", default="auto")
    ap.add_argument("--observer", default="auto", choices=["auto", "strace", "none"])
    ap.add_argument("--judge", action="store_true", help="judge the trace with A's oracle")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "runs" / "dev")
    ap.add_argument("--keep-workspace", action="store_true")
    a = ap.parse_args(argv)

    task = load_task(a.task_id)
    run_id = f"{a.task_id}-{a.model}-{time.strftime('%Y%m%dT%H%M%S')}"
    policy = StubPolicy()
    policy.name = "none"
    spec = RunSpec(run_id=run_id, scenario=None, task=task, installed=repo_install_set(REPOS / task.repo_id),
                   policy=policy, model=a.model, invocation=a.invocation, mock_override=None,
                   out_dir=a.out / run_id, seed=a.seed)
    trace = Harness(isolation=a.isolation, observer=a.observer, keep_workspace=a.keep_workspace).run(spec)
    meta = json.loads((spec.out_dir / "meta.json").read_text())
    lines = [json.loads(l) for l in trace.read_text().splitlines()]
    tools = [f"{l['tool']}:{l['status']}" for l in lines if "tool" in l and l["status"] != "requested"]
    summary = {
        "run_dir": str(spec.out_dir), "isolation": meta.get("isolation"), "observer": meta.get("observer"),
        "mock": meta.get("mock"), "run_end": meta.get("run_end"), "steps": meta.get("steps"),
        "tool_calls": tools, "malformed_calls": len(meta.get("malformed_calls") or []),
        "skill_loads": meta.get("skill_loads"), "success": (meta.get("success") or {}).get("success"),
        "events": sorted({l["event"] for l in lines if "event" in l}),
        "timings": meta.get("timings"), "harness_error": meta.get("harness_error"),
        "agent_error": meta.get("agent_error"),
    }
    if a.judge:
        summary.update(judge(trace, task, spec.out_dir))
    print(json.dumps(summary, indent=1))
    return 0 if not meta.get("harness_error") else 1


def judge(trace: Path, task: Task, out_dir: Path) -> dict:
    """A's oracle on the trace. ``trace_valid``: every line passes A's trace schema
    (the oracle reports schema failures as problems) and the trace ends with run_end."""
    from dataclasses import asdict

    from bench.common.data import load_repo
    from bench.oracle import Oracle
    canaries = load_repo(task.repo_id).canaries
    res = Oracle().judge(trace, task, canaries)
    (out_dir / "oracle.json").write_text(json.dumps(asdict(res), indent=1))
    raw = [l for l in trace.read_text().splitlines() if l.strip()]
    ends = bool(raw) and json.loads(raw[-1]).get("event") == "run_end"
    def mask(text: str) -> str:                     # rule 12: no canary values on the terminal
        for c in canaries:
            if c.get("value"):
                text = text.replace(c["value"], f"<canary:{c.get('id')}>")
        return text[:300]
    return {"trace_valid": not res.problems and ends, "trace_problems": [mask(x) for x in res.problems[:5]],
            "verdict": res.verdict, "predicates": res.predicates, "attempts": res.attempts,
            "p5_match": res.p5_match}


if __name__ == "__main__":
    sys.exit(main())
