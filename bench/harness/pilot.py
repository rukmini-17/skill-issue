"""Utility pilot (workstream B, B5): every task x repeats on v1, policy ``none``, per model.

    # what would run (no model needed)
    python -m bench.harness.pilot run --model qwen3-8b-llamacpp --dry-run
    # one shard of the pilot (Slurm array task 2 of 8), stop starting runs after 100 min
    python -m bench.harness.pilot run --model qwen3-8b-llamacpp --shard 2/8 --deadline-s 6000
    # tables for PILOT.md
    python -m bench.harness.pilot summarize --update-md bench/harness/PILOT.md

Runs go to ``runs/pilot/<model>/<task_id>/r<k>/`` (the harness's usual files,
see ``bench.harness.run``). Repeat ``k`` uses seed ``k``. Invocation is
``natural``. A run directory whose meta.json has a ``success`` entry and no
``harness_error`` is complete and is skipped, so a killed or timed-out job is
resumed by submitting it again. Agent errors (server down, context overflow)
are complete runs, not retried, unless ``--retry-agent-errors``.

Clean rate needs A's oracle. ``summarize`` reads ``oracle.json`` from each run
directory; until A's oracle lands (or ``judge`` has been run) it reports n/a.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import csv
import io
import json
import math
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import yaml

from bench.harness.run import REPO_ROOT, REPOS, Harness
from bench.harness.skills import repo_install_set
from bench.interfaces import Delegation, RunSpec, StubPolicy, Task

PILOT_ROOT = REPO_ROOT / "runs" / "pilot"
REPEATS = 3
MD_BEGIN = "<!-- pilot:tables:begin -->"
MD_END = "<!-- pilot:tables:end -->"


# ------------------------------------------------------------------ tasks ---

def load_task(path: Path) -> Task:
    d = yaml.safe_load(path.read_text())
    dl = d["delegation"]
    repo_id = path.parent.parent.name
    return Task(repo_id, d["task_id"], d["skill_id"], d["prompt"],
                Delegation(*(tuple(dl.get(k) or ()) for k in ("read", "write", "exec", "network",
                                                               "protected_data"))),
                d["success_check"], path.with_suffix(".reference"))


def all_tasks(repos: Path = REPOS) -> list[Task]:
    return [load_task(p) for p in sorted(repos.glob("*/tasks/*.yaml"))]


def jobs(tasks: list[Task], repeats: int, shard: tuple[int, int] = (0, 1)) -> list[tuple[Task, int]]:
    """Deterministic (task, repeat) list; shard i of n takes every n-th job, so shards stay balanced."""
    i, n = shard
    every = [(t, r) for r in range(repeats) for t in tasks]       # repeat-major: early stops still cover all tasks
    return [j for k, j in enumerate(every) if k % n == i]


INVOCATIONS = ("natural", "explicit")


def row_label(model: str, invocation: str = "natural") -> str:
    """Directory / table row for one pilot row. Natural (the default) keeps the bare model
    name; explicit invocation (the prompt starts with ``/<skill_id>``) is its own row."""
    return model if invocation == "natural" else f"{model}+{invocation}"


def run_dir(root: Path, model: str, task: Task, rep: int) -> Path:
    return root / model / task.task_id / f"r{rep}"     # model = row_label(...)


def read_meta(d: Path) -> dict | None:
    try:
        return json.loads((d / "meta.json").read_text())
    except (OSError, json.JSONDecodeError):
        return None


def is_complete(d: Path, retry_agent_errors: bool = False) -> bool:
    m = read_meta(d)
    if not m or m.get("harness_error") or "success" not in m:
        return False
    return not (retry_agent_errors and m.get("run_end") == "error")


def none_policy() -> StubPolicy:
    p = StubPolicy()
    p.name = "none"
    return p


def make_spec(root: Path, model: str, task: Task, rep: int, invocation: str = "natural") -> RunSpec:
    label = row_label(model, invocation)
    return RunSpec(run_id=f"pilot-{label}-{task.task_id}-r{rep}", scenario=None, task=task,
                   installed=repo_install_set(REPOS / task.repo_id), policy=none_policy(), model=model,
                   invocation=invocation, mock_override=None, out_dir=run_dir(root, label, task, rep), seed=rep)


def tokens_used(root: Path, model: str) -> int:
    total = 0
    for p in (root / model).glob("*/r*/meta.json"):
        try:
            u = json.loads(p.read_text()).get("usage") or {}
        except (OSError, json.JSONDecodeError):
            continue
        total += int(u.get("prompt_tokens", 0)) + int(u.get("completion_tokens", 0))
    return total


# -------------------------------------------------------------------- run ---

def cmd_run(a) -> int:
    t_start = time.monotonic()
    label = row_label(a.model, a.invocation)
    tasks = all_tasks()
    if a.tasks:
        want = set(a.tasks.split(","))
        tasks = [t for t in tasks if t.task_id in want or t.repo_id in want]
    shard = tuple(int(x) for x in a.shard.split("/"))
    todo = jobs(tasks, a.repeats, (shard[0], shard[1]))
    pending = [(t, r) for t, r in todo if not is_complete(run_dir(a.out, label, t, r), a.retry_agent_errors)]
    print(f"pilot {label}: shard {a.shard}, {len(todo)} runs in shard, {len(pending)} to do", file=sys.stderr)
    if a.dry_run:
        for t, r in pending:
            print(f"{t.task_id} r{r} -> {run_dir(a.out, label, t, r)}")
        return 0
    if not pending:
        return 0

    from bench.backends import make_model
    m = make_model(a.model)
    if not a.no_wait and not m.wait_ready(a.wait_s):
        print(f"pilot: model server for {a.model} not ready at {m.health_url()}", file=sys.stderr)
        return 3

    harness = Harness(isolation=a.isolation, run_timeout=a.run_timeout)
    progress = a.out / label / "progress.jsonl"
    progress.parent.mkdir(parents=True, exist_ok=True)
    stop_reason = None

    def can_start() -> str | None:
        if a.deadline_s and time.monotonic() - t_start > a.deadline_s - a.run_timeout - 120:
            return "deadline"
        if a.max_total_tokens and tokens_used(a.out, label) >= a.max_total_tokens:
            return "token_budget"
        return None

    def one(t: Task, r: int) -> dict:
        t0 = time.monotonic()
        spec = make_spec(a.out, a.model, t, r, a.invocation)
        harness.run(spec)
        meta = read_meta(spec.out_dir) or {}
        rec = {"task_id": t.task_id, "repeat": r, "invocation": a.invocation, "shard": a.shard, "seconds": round(time.monotonic() - t0, 1),
               "run_end": meta.get("run_end"), "success": (meta.get("success") or {}).get("success"),
               "agent_error_kind": meta.get("agent_error_kind"), "harness_error": meta.get("harness_error"),
               "time": time.strftime("%Y-%m-%dT%H:%M:%S")}
        with progress.open("a") as fh:
            fh.write(json.dumps(rec) + "\n")
        print(json.dumps(rec), file=sys.stderr)       # no tool output, no canaries
        return rec

    queue = list(pending)
    with cf.ThreadPoolExecutor(max_workers=a.workers) as pool:
        running: set[cf.Future] = set()
        while queue or running:
            while queue and len(running) < a.workers:
                stop_reason = can_start()
                if stop_reason:
                    queue.clear()
                    break
                running.add(pool.submit(one, *queue.pop(0)))
            if not running:
                break
            done, running = cf.wait(running, return_when=cf.FIRST_COMPLETED)
            for f in done:
                f.result()
    left = sum(not is_complete(run_dir(a.out, label, t, r), a.retry_agent_errors) for t, r in todo)
    print(f"pilot {label}: shard {a.shard} finished; {left} runs left"
          + (f" (stopped: {stop_reason})" if stop_reason else ""), file=sys.stderr)
    return 0 if left == 0 else 2


# -------------------------------------------------------------- summarize ---

def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (math.nan, math.nan)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def collect(root: Path) -> list[dict]:
    rows = []
    for meta_p in sorted(root.glob("*/*/r*/meta.json")):
        try:
            m = json.loads(meta_p.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        d = meta_p.parent
        oracle = None
        if (d / "oracle.json").is_file():
            try:
                oracle = json.loads((d / "oracle.json").read_text()).get("verdict")
            except (OSError, json.JSONDecodeError):
                oracle = "unreadable"
        mc = m.get("model_config") or {}
        rows.append({
            "model": meta_p.parents[2].name, "backend": mc.get("backend"), "quantization": mc.get("quantization"),
            "hardware": mc.get("hardware"), "repo_id": m.get("repo_id"), "task_id": m.get("task_id"),
            "invocation": m.get("invocation"), "skill_id": m.get("skill_id"),
            "repeat": int(d.name[1:]), "complete": "success" in m and not m.get("harness_error"),
            "success": (m.get("success") or {}).get("success"), "oracle": oracle,
            "skill_loaded": (m.get("skill_id") in (m.get("skill_loads") or [])) if m.get("skill_id") else None,
            "run_end": m.get("run_end") or ("harness_error" if m.get("harness_error") else None),
            "error_kind": m.get("agent_error_kind"), "steps": m.get("steps") or 0,
            "tool_calls": m.get("tool_calls") or 0, "malformed": len(m.get("malformed_calls") or []),
            "truncated_turns": m.get("truncated_turns") or 0, "observer": m.get("observer"),
            "isolation": m.get("isolation"), "agent_s": (m.get("timings") or {}).get("agent_s"),
            "tokens": sum((m.get("usage") or {}).get(k, 0) for k in ("prompt_tokens", "completion_tokens")),
            # behaviour (None for runs recorded before meta.json had "behaviour")
            "multi_call_turns": (m.get("behaviour") or {}).get("multi_call_turns"),
            "blind_write_turns": (m.get("behaviour") or {}).get("blind_write_turns"),
            "turns_with_reasoning": (m.get("behaviour") or {}).get("turns_with_reasoning"),
        })
    return rows


def _rate(rows: list[dict], key: str, good=True) -> tuple[str, int, int]:
    judged = [r for r in rows if r[key] is not None]
    k = sum(r[key] == good for r in judged)
    if not judged:
        return "n/a", 0, 0
    lo, hi = wilson(k, len(judged))
    return f"{k / len(judged):.0%} [{lo:.0%}, {hi:.0%}]", k, len(judged)


def summarize(rows: list[dict], expected_per_model: int | None = None) -> dict[str, str]:
    by_model: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_model[r["model"]].append(r)
    head = ("| model | backend | quant | hardware | runs | task success | clean rate | skill-load rate "
            "| run_end done/step/timeout/error | malformed calls/run | median agent s | tokens/run |\n"
            "|---|---|---|---|---|---|---|---|---|---|---|---|")
    lines = [head]
    for model, rs in sorted(by_model.items()):
        done = [r for r in rs if r["complete"]]
        ends = Counter(r["run_end"] for r in done)
        secs = [r["agent_s"] for r in done if r["agent_s"] is not None]
        oracle_rows = [dict(r, oracle_clean=(None if r["oracle"] is None else r["oracle"] == "clean")) for r in done]
        n_runs = f"{len(done)}" + (f"/{expected_per_model}" if expected_per_model else "")
        lines.append("| " + " | ".join([
            model, str(rs[0]["backend"]), str(rs[0]["quantization"]), str(rs[0]["hardware"]), n_runs,
            _rate(done, "success")[0], _rate(oracle_rows, "oracle_clean")[0], _rate(done, "skill_loaded")[0],
            "/".join(str(ends.get(k, 0)) for k in ("done", "step_limit", "timeout", "error")),
            f"{statistics.mean(r['malformed'] for r in done):.2f}" if done else "-",
            f"{statistics.median(secs):.0f}" if secs else "-",
            f"{statistics.mean(r['tokens'] for r in done):.0f}" if done else "-",
        ]) + " |")
    per_repo = ["| model | repo | runs | task success | clean rate | skill-load rate |", "|---|---|---|---|---|---|"]
    for model, rs in sorted(by_model.items()):
        for repo in sorted({r["repo_id"] for r in rs}):
            sub = [r for r in rs if r["repo_id"] == repo and r["complete"]]
            orows = [dict(r, oracle_clean=(None if r["oracle"] is None else r["oracle"] == "clean")) for r in sub]
            per_repo.append(f"| {model} | {repo} | {len(sub)} | {_rate(sub, 'success')[0]} | "
                            f"{_rate(orows, 'oracle_clean')[0]} | {_rate(sub, 'skill_loaded')[0]} |")
    beh = ["| model | runs | runs with a multi-call turn | runs that wrote before reading "
           "| multi-call turns/run | runs with thinking | skill-load rate |", "|---|---|---|---|---|---|---|"]
    for model, rs in sorted(by_model.items()):
        sub = [r for r in rs if r["complete"] and r["multi_call_turns"] is not None]
        flags = [dict(r, multi=r["multi_call_turns"] > 0, blind=r["blind_write_turns"] > 0,
                      thinks=r["turns_with_reasoning"] > 0) for r in sub]
        beh.append(f"| {model} | {len(sub)} | {_rate(flags, 'multi')[0]} | {_rate(flags, 'blind')[0]} | "
                   + (f"{statistics.mean(r['multi_call_turns'] for r in sub):.2f}" if sub else "-")
                   + f" | {_rate(flags, 'thinks')[0]} | {_rate(sub, 'skill_loaded')[0]} |")
    labels = sorted(by_model)
    per_task = ["| task | skill | " + " | ".join(f"{m}: skill loads / success" for m in labels) + " |",
                "|---|---|" + "---|" * len(labels)]
    never = []
    for tid in sorted({r["task_id"] for r in rows if r["task_id"]}):
        cells, skill, total_loads, total = [], "", 0, 0
        for m in labels:
            sub = [r for r in by_model[m] if r["task_id"] == tid and r["complete"]]
            skill = skill or next((r["skill_id"] for r in sub if r["skill_id"]), "")
            loads = sum(bool(r["skill_loaded"]) for r in sub)
            ok = sum(r["success"] is True for r in sub)
            total_loads, total = total_loads + loads, total + len(sub)
            cells.append(f"{loads}/{len(sub)} / {ok}/{len(sub)}" if sub else "-")
        if total and not total_loads:
            never.append(tid)
        per_task.append(f"| {tid} | {skill} | " + " | ".join(cells) + " |")
    per_task.append("")
    per_task.append(f"Tasks whose skill was never loaded in any completed run ({len(never)}): "
                    + (", ".join(never) if never else "none"))
    errs = ["| model | error kind | runs |", "|---|---|---|"]
    for model, rs in sorted(by_model.items()):
        for kind, n in sorted(Counter(r["error_kind"] or r["run_end"] for r in rs
                                      if r["run_end"] in ("error", "harness_error")).items()):
            errs.append(f"| {model} | {kind} | {n} |")
    return {"main": "\n".join(lines), "per_repo": "\n".join(per_repo), "behaviour": "\n".join(beh),
            "per_task": "\n".join(per_task),
            "errors": "\n".join(errs)}


def render(tables: dict[str, str]) -> str:
    return (f"_Generated by `python -m bench.harness.pilot summarize` on {time.strftime('%Y-%m-%d %H:%M')}. "
            "Rates are over completed runs, with 95% Wilson intervals; runs are not independent "
            "(3 repeats per task), so the intervals are optimistic._\n\n"
            f"#### Per model\n\n{tables['main']}\n\n#### Per model and repo\n\n{tables['per_repo']}\n\n"
            "#### Behaviour\n\n'Wrote before reading': a turn with `write_file` alongside a read, "
            "list, request or command whose result the model had not seen yet.\n\n"
            f"{tables['behaviour']}\n\n#### Skill loads per task\n\nEach cell: runs that read the task's "
            "SKILL.md / runs that passed the success check, over completed runs. A `+explicit` row "
            "used explicit invocation.\n\n"
            f"{tables['per_task']}\n\n#### Errors\n\n{tables['errors']}\n")


def cmd_summarize(a) -> int:
    rows = collect(a.root)
    if a.csv:
        a.csv.parent.mkdir(parents=True, exist_ok=True)
        buf = io.StringIO()
        if rows:
            w = csv.DictWriter(buf, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        a.csv.write_text(buf.getvalue())
    expected = len(all_tasks()) * a.repeats
    text = render(summarize(rows, expected))
    if a.update_md:
        md = a.update_md.read_text()
        if MD_BEGIN not in md or MD_END not in md:
            print(f"{a.update_md}: markers {MD_BEGIN} / {MD_END} not found", file=sys.stderr)
            return 1
        head, _, rest = md.partition(MD_BEGIN)
        _, _, tail = rest.partition(MD_END)
        a.update_md.write_text(f"{head}{MD_BEGIN}\n{text}{MD_END}{tail}")
    else:
        print(text)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m bench.harness.pilot")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--model", required=True)
    r.add_argument("--repeats", type=int, default=REPEATS)
    r.add_argument("--invocation", choices=INVOCATIONS, default="natural",
                   help="natural (default): the task prompt as written; explicit: prompt starts with "
                        "/<skill_id> and runs go to <model>+explicit/")
    r.add_argument("--tasks", default="", help="comma-separated task ids or repo ids (default: all 55)")
    r.add_argument("--shard", default="0/1", help="i/n")
    r.add_argument("--workers", type=int, default=1, help="parallel runs (vLLM batches; llama.cpp: keep 1)")
    r.add_argument("--isolation", default="auto")
    r.add_argument("--run-timeout", type=float, default=1800.0)
    r.add_argument("--deadline-s", type=float, default=0.0,
                   help="stop starting runs when fewer than run-timeout+120 s remain (0 = no deadline)")
    r.add_argument("--max-total-tokens", type=int, default=0,
                   help="stop starting runs once this model's runs used this many tokens (Tinker credit)")
    r.add_argument("--wait-s", type=float, default=900.0, help="wait this long for the model server")
    r.add_argument("--no-wait", action="store_true")
    r.add_argument("--retry-agent-errors", action="store_true")
    r.add_argument("--dry-run", action="store_true")
    r.add_argument("--out", type=Path, default=PILOT_ROOT)
    s = sub.add_parser("summarize")
    s.add_argument("--root", type=Path, default=PILOT_ROOT)
    s.add_argument("--repeats", type=int, default=REPEATS)
    s.add_argument("--csv", type=Path, default=None)
    s.add_argument("--update-md", type=Path, default=None)
    a = ap.parse_args(argv)
    if a.cmd == "run":
        if a.shard.count("/") != 1:
            ap.error("--shard must be i/n")
        return cmd_run(a)
    return cmd_summarize(a)


if __name__ == "__main__":
    sys.exit(main())
