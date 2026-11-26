"""Print what each run's agent did, without file contents (safe for the terminal).

    .venv/bin/python -m bench.harness.inspect_runs runs/first_run
    .venv/bin/python -m bench.harness.inspect_runs runs/pilot/qwen3-8b-llamacpp --task ops-office-t05

For every run directory under the given roots (any folder with meta.json and
messages.json): model, task, target skill, invocation, skill_loads, success, then
each model turn's tool calls with only their path / url / command. Calls that the
one-call-per-turn rule did not run are marked "(not run)". Tool results, file
contents and write contents are never printed. Canary values are masked (rule 12).

    .venv/bin/python -m bench.harness.inspect_runs <run_dir> --output 1,3 [--tail 15]

``--output`` adds, for those steps, the last lines of a ``run_command`` result (exit
code, stdout and stderr tails as the agent saw them). Only command results are shown,
never ``read_file`` / ``http_request`` results.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from bench.harness.agent import SKIPPED_NOTE


def _canaries(repo_id: str) -> list[dict]:
    try:
        from bench.common.data import load_repo
        return load_repo(repo_id).canaries
    except Exception:                       # unknown repo or data not available: mask nothing
        return []


def _mask(text: str, canaries: list[dict]) -> str:
    for c in canaries:
        if c.get("value"):
            text = text.replace(c["value"], f"<canary:{c.get('id')}>")
    return text


def describe_call(name: str, raw_args: str) -> str:
    try:
        a = json.loads(raw_args)
    except (json.JSONDecodeError, TypeError):
        return f"{name}(<malformed arguments>)"
    if not isinstance(a, dict):
        return f"{name}(<malformed arguments>)"
    if name in ("read_file", "list_dir"):
        return f"{name}({a.get('path')!r})"
    if name == "write_file":
        return f"write_file({a.get('path')!r}, <{len(str(a.get('content', '')))} chars>)"
    if name == "run_command":
        cmd = " ".join(str(a.get("cmd", "")).split())
        return f"run_command({cmd[:160]!r}{'…' if len(cmd) > 160 else ''})"
    if name == "http_request":
        return f"http_request({a.get('method')} {a.get('url')!r})"
    return f"{name}(<{len(raw_args)} chars>)"


def _tail(result: str, n: int) -> list[str]:
    """exit line + last n lines of stdout and of stderr from a run_command result."""
    head, _, rest = result.partition("\n")
    out = [head]
    for name in ("stdout", "stderr"):
        marker = f"{name}:\n"
        if marker not in rest:
            continue
        body = rest.split(marker, 1)[1]
        if name == "stdout" and "stderr:\n" in body:
            body = body.split("stderr:\n", 1)[0]
        lines = body.rstrip("\n").splitlines()
        out.append(f"{name} (last {min(n, len(lines))} of {len(lines)} lines):")
        out += ["      | " + l[:300] for l in lines[-n:]]
    return out


def inspect(run: Path, outputs: set[int] | None = None, tail: int = 15) -> list[str]:
    meta = json.loads((run / "meta.json").read_text())
    msgs = json.loads((run / "messages.json").read_text())
    can = _canaries(meta.get("repo_id", ""))
    out = [f"== {run}",
           f"   model {meta.get('model')} | task {meta.get('task_id')} | skill {meta.get('skill_id')} | "
           f"invocation {meta.get('invocation')} | skill_loads {meta.get('skill_loads')} | "
           f"skill_uses {meta.get('skill_uses')} | "
           f"success {(meta.get('success') or {}).get('success')} | run_end {meta.get('run_end')} | "
           f"steps {meta.get('steps')}"]
    results = {m.get("tool_call_id"): m.get("content") for m in msgs if m.get("role") == "tool"}
    step = 0
    for m in msgs:
        if m.get("role") != "assistant":
            continue
        step += 1
        calls = m.get("tool_calls") or []
        if not calls:
            out.append(f"   {step:2d}. (final answer, {len(m.get('content') or '')} chars)")
            continue
        for i, c in enumerate(calls):
            f = c.get("function") or {}
            note = " (not run)" if results.get(c.get("id")) == SKIPPED_NOTE else ""
            res = results.get(c.get("id")) or ""
            status = " -> error" if res.startswith("error") else ""
            out.append(f"   {step:2d}{'.' if i == 0 else '+'} {describe_call(f.get('name'), f.get('arguments'))}"
                       f"{note}{status}")
            if outputs and step in outputs and f.get("name") == "run_command" and not note:
                out += ["      " + l for l in _tail(res, tail)]
    return [_mask(line, can) for line in out]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m bench.harness.inspect_runs")
    ap.add_argument("roots", nargs="+", type=Path)
    ap.add_argument("--task", default="", help="only runs of this task id")
    ap.add_argument("--output", default="", help="comma-separated steps: show run_command output tails")
    ap.add_argument("--tail", type=int, default=15, help="lines of stdout/stderr per step (default 15)")
    a = ap.parse_args(argv)
    runs = sorted({p.parent for r in a.roots for p in ([r / "meta.json"] + list(r.rglob("meta.json")))
                   if p.is_file() and (p.parent / "messages.json").is_file()})
    for run in runs:
        try:
            lines = inspect(run, {int(x) for x in a.output.split(",") if x.strip()}, a.tail)
        except (OSError, json.JSONDecodeError) as e:
            print(f"== {run}: unreadable ({e})")
            continue
        if a.task and f"task {a.task} " not in lines[1]:
            continue
        print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
