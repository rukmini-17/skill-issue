"""Re-score saved runs with changed file-text success checks, without re-running the agent.

    .venv/bin/python -m bench.harness.rescore --root runs/pilot --checks bench/harness/proposed_checks.yaml
    .venv/bin/python -m bench.harness.rescore --root runs/pilot --model qwen3-8b-llamacpp --flips

For every run of a task that ``--checks`` covers, the checked file's final text is rebuilt:

1. from ``final_delta.tar.gz`` / ``final_delta.json`` when the run has them (runs from
   commit 11aad7f+1 on): a file in the delta is its saved content, a deleted file is missing,
   any other file is the task's initial workspace copy;
2. otherwise from ``trace.jsonl``: the last completed ``write_file`` to that path, unless a
   later command wrote, created or deleted it (``fs_write`` / ``fs_diff``), in which case the
   content is unknown. A file the run never touched is the initial copy.

"Initial copy" means ``repos/<repo>/workspace/<path>``; ``setup.sh`` may change some files, so
those verdicts are marked ``initial``. Only ``file_contains`` / ``file_not_contains`` checks
can be re-scored this way; a ``command_exit`` check needs the workspace (rebuild + delta) and
is reported as not re-scorable. Prints a per-task table (old vs new success, flips, unknown)
and, with ``--flips``, every run whose verdict changes. Nothing is printed from file contents.
"""

from __future__ import annotations

import argparse
import io
import json
import posixpath
import sys
import tarfile
from collections import defaultdict
from pathlib import Path

import yaml

from bench.harness.run import REPOS, text_matches

UNKNOWN = object()       # content changed by a command: cannot tell
MISSING = None


def _norm(path: str) -> str:
    return posixpath.normpath(str(path).lstrip("/")).removeprefix("./")


def _initial(repo_id: str, rel: str):
    p = REPOS / repo_id / "workspace" / rel
    return (p.read_text(encoding="utf-8", errors="replace"), "initial") if p.is_file() else (MISSING, "initial")


def final_text(run: Path, repo_id: str, rel: str):
    """(content | None | UNKNOWN, source) for workspace path ``rel`` at the end of the run."""
    rel = _norm(rel)
    info_p, tar_p = run / "final_delta.json", run / "final_delta.tar.gz"
    if info_p.is_file() and tar_p.is_file():
        info = json.loads(info_p.read_text())
        if rel in info.get("deleted", []):
            return MISSING, "delta"
        if any(s.get("path") == rel for s in info.get("skipped", [])):
            return UNKNOWN, "delta (file over the size cap)"
        with tarfile.open(tar_p, "r:gz") as tar:
            try:
                fh = tar.extractfile(rel)
            except KeyError:
                fh = None
            if fh is not None:
                return io.TextIOWrapper(fh, encoding="utf-8", errors="replace").read(), "delta"
        return _initial(repo_id, rel)
    trace = run / "trace.jsonl"
    if not trace.is_file():
        return UNKNOWN, "no trace"
    state, source = None, None
    for line in trace.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if e.get("tool") == "write_file" and e.get("status") == "completed":
            a = e.get("args") or {}
            if _norm(a.get("path", "")) == rel:
                state, source = str(a.get("content", "")), "write_file"
        elif e.get("event") in ("fs_write", "fs_diff") and _norm(e.get("path", "")) == rel:
            if e.get("event") == "fs_diff" and e.get("change") == "deleted":
                state, source = MISSING, "deleted by a command"
            else:
                state, source = UNKNOWN, "changed by a command"
    if source is None:
        return _initial(repo_id, rel)
    return state, source


def judge(sc: dict, content) -> bool | None:
    kind = sc.get("type")
    if kind not in ("file_contains", "file_not_contains") or content is UNKNOWN:
        return None
    if content is MISSING:
        return kind == "file_not_contains"
    has = text_matches(content, sc)
    return has if kind == "file_contains" else not has


def load_checks(path: Path) -> dict[str, dict]:
    data = yaml.safe_load(path.read_text()) or {}
    return {tid: (v.get("success_check") if isinstance(v, dict) and "success_check" in v else v)
            for tid, v in (data.get("tasks") or data).items()}


def rescore(roots: list[Path], checks: dict[str, dict], model: str = "") -> list[dict]:
    rows = []
    for root in roots:
        for meta_p in sorted(root.glob("*/*/r*/meta.json")):
            label = meta_p.parents[2].name
            if model and not (label == model or label.startswith(model + "+")):
                continue
            try:
                m = json.loads(meta_p.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            tid = m.get("task_id")
            if tid not in checks or "success" not in m or m.get("harness_error"):
                continue
            sc = checks[tid]
            old = (m.get("success") or {}).get("success")
            if sc.get("type") not in ("file_contains", "file_not_contains"):
                rows.append({"row": label, "task_id": tid, "run": str(meta_p.parent), "old": old,
                             "new": None, "source": "command check: needs the workspace"})
                continue
            content, source = final_text(meta_p.parent, m.get("repo_id", ""), sc["path"])
            rows.append({"row": label, "task_id": tid, "run": str(meta_p.parent), "old": old,
                         "new": judge(sc, content), "source": source})
    return rows


def render(rows: list[dict], flips: bool = False) -> str:
    by = defaultdict(list)
    for r in rows:
        by[(r["row"], r["task_id"])].append(r)
    out = ["| row | task | runs | old success | new success | F->T | T->F | unknown | initial copy |",
           "|---|---|---|---|---|---|---|---|---|"]
    tot = defaultdict(int)
    for (row, tid), rs in sorted(by.items()):
        c = {"runs": len(rs), "old": sum(r["old"] is True for r in rs),
             "new": sum(r["new"] is True for r in rs),
             "ft": sum(r["old"] is not True and r["new"] is True for r in rs),
             "tf": sum(r["old"] is True and r["new"] is False for r in rs),
             "unk": sum(r["new"] is None for r in rs),
             "init": sum(r["source"] == "initial" for r in rs)}
        for k, v in c.items():
            tot[k] += v
        out.append(f"| {row} | {tid} | {c['runs']} | {c['old']} | {c['new']} | {c['ft']} | {c['tf']} | "
                   f"{c['unk']} | {c['init']} |")
    out.append(f"\n{tot['runs']} runs: success {tot['old']} -> {tot['new']} (re-scorable runs only count "
               f"in 'new'); F->T {tot['ft']}, T->F {tot['tf']}, not re-scorable {tot['unk']}")
    if flips:
        out.append("")
        for r in rows:
            if r["new"] is not None and r["new"] != (r["old"] is True):
                out.append(f"{'F->T' if r['new'] else 'T->F'}  {r['run']}  ({r['source']})")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m bench.harness.rescore")
    ap.add_argument("--root", type=Path, action="append", required=True, help="pilot root; repeatable")
    ap.add_argument("--checks", type=Path, default=Path(__file__).with_name("proposed_checks.yaml"))
    ap.add_argument("--model", default="", help="only this model's rows")
    ap.add_argument("--flips", action="store_true", help="list every run whose verdict changes")
    a = ap.parse_args(argv)
    print(render(rescore(a.root, load_checks(a.checks), a.model), a.flips))
    return 0


if __name__ == "__main__":
    sys.exit(main())
