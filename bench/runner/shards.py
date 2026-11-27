"""Shard bookkeeping: which shards of an experiment are incomplete, and resubmitting them.

A shard is complete when every run it owns has ``oracle.json`` (the marker file written by the
runner only says the process ended). Usage:

    python -m bench.runner.shards <experiment.yaml> --shards 8                 # list status
    python -m bench.runner.shards <experiment.yaml> --shards 8 --resubmit      # print sbatch command
    python -m bench.runner.shards <experiment.yaml> --shards 8 --resubmit --submit   # really submit

``--submit`` refuses to go over --max-jobs array tasks (default 10, the per-session cap in Part 0).
"""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
from pathlib import Path

from bench.runner.config import ExperimentConfig, expand
from bench.runner.data import REPO_ROOT
from bench.runner.ids import data_tag
from bench.runner.runner import select_groups

SBATCH_FILE = Path(__file__).parent / "slurm" / "run_shard.sbatch"


def shard_status(cfg: ExperimentConfig, runs_root: Path, n_shards: int) -> list[dict]:
    runs_dir = Path(runs_root) / cfg.name
    keys = list(expand(cfg))
    tag = data_tag()
    out = []
    for i in range(n_shards):
        ids = [k.run_id(tag) for g in select_groups(keys, (i, n_shards)) for k in g]
        done = sum((runs_dir / r / "oracle.json").exists() for r in ids)
        failed = sum((runs_dir / r / "error.json").exists() for r in ids)
        out.append({"shard": i, "total": len(ids), "done": done, "failed": failed,
                    "complete": done == len(ids), "marker": (runs_dir / "_shards" / f"{i}of{n_shards}.json").exists()})
    return out


def sbatch_command(cfg_path: Path, shards: list[int], n_shards: int, *, partition: str = "gtx",
                   gres: str | None = None, runs_root: Path | None = None, dry_run: bool = False,
                   workers: int = 1) -> list[str]:
    cmd = ["sbatch", f"--array={','.join(map(str, shards))}", f"--partition={partition}"]
    if gres:
        cmd.append(f"--gres={gres}")
    env = [f"EXPERIMENT={Path(cfg_path).resolve()}", f"NSHARDS={n_shards}", f"WORKERS={workers}",
           f"DRY_RUN={'1' if dry_run else '0'}"]
    if runs_root:
        env.append(f"RUNS_DIR={runs_root}")
    cmd += ["--export=ALL," + ",".join(env), str(SBATCH_FILE)]
    return cmd


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m bench.runner.shards", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("experiment", type=Path)
    ap.add_argument("--shards", type=int, required=True, help="total number of shards n")
    ap.add_argument("--runs-dir", type=Path, default=REPO_ROOT / "runs")
    ap.add_argument("--resubmit", action="store_true", help="build the sbatch command for incomplete shards")
    ap.add_argument("--submit", action="store_true", help="with --resubmit: actually run sbatch")
    ap.add_argument("--partition", default="gtx", help="COOK partition: gtx (4B/8B), t4 (14B), rtx (32B)")
    ap.add_argument("--gres", default=None, help="e.g. gpu:1 (COOK-specific; not assumed)")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--dry-run", action="store_true", help="submit jobs that run the runner with --dry-run")
    ap.add_argument("--max-jobs", type=int, default=10)
    args = ap.parse_args(argv)

    cfg = ExperimentConfig.load(args.experiment)
    status = shard_status(cfg, args.runs_dir, args.shards)
    for s in status:
        flag = "ok" if s["complete"] else ("FAILED" if s["failed"] else "incomplete")
        print(f"shard {s['shard']:>3}/{args.shards}: {s['done']:>5}/{s['total']:<5} done, {s['failed']} failed  [{flag}]")
    todo = [s["shard"] for s in status if not s["complete"] and s["total"]]
    print(f"{len(todo)} shard(s) to resubmit: {todo}")
    if not (args.resubmit and todo):
        return 0
    cmd = sbatch_command(args.experiment, todo, args.shards, partition=args.partition, gres=args.gres,
                         runs_root=args.runs_dir, dry_run=args.dry_run, workers=args.workers)
    print("\n" + " ".join(shlex.quote(c) for c in cmd))
    if not args.submit:
        print("(not submitted; add --submit)")
        return 0
    if len(todo) > args.max_jobs:
        print(f"refusing: {len(todo)} array tasks > --max-jobs {args.max_jobs}; submit in smaller batches or raise it deliberately")
        return 2
    (args.runs_dir / "slurm_logs").mkdir(parents=True, exist_ok=True)
    cmd[0] = os.environ.get("SBATCH", "sbatch")
    return subprocess.run(cmd, cwd=REPO_ROOT).returncode


if __name__ == "__main__":
    raise SystemExit(main())
