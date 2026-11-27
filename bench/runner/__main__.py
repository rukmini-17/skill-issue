"""CLI: python -m bench.runner <experiment.yaml> [--dry-run] [--shard i/n] [--workers N]"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from bench.runner.config import ExperimentConfig
from bench.runner.data import REPO_ROOT
from bench.runner.runner import parse_shard, run_experiment


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m bench.runner", description=__doc__)
    ap.add_argument("experiment", type=Path, help="experiment config (bench/configs/experiments/*.yaml)")
    ap.add_argument("--dry-run", action="store_true", help="stub harness, oracle and mock network; no model, no sandbox")
    ap.add_argument("--shard", help="i/n: run only shard i of n (0-based)")
    ap.add_argument("--workers", type=int, default=1, help="local worker processes (A100 mode)")
    ap.add_argument("--max-seconds", type=float, default=None,
                    help="stop starting new work after this many seconds and exit 0 (Slurm: leave margin under the limit)")
    ap.add_argument("--runs-dir", type=Path, default=REPO_ROOT / "runs", help="output root (default: runs/)")
    ap.add_argument("--max-cost-usd", type=float, default=None,
                    help="hard USD cap for this job (Tinker), split evenly over --workers; needs model prices in models.yaml")
    args = ap.parse_args(argv)
    cfg = ExperimentConfig.load(args.experiment)
    summary = run_experiment(cfg, args.runs_dir, dry_run=args.dry_run, shard=parse_shard(args.shard), workers=args.workers,
                             max_seconds=args.max_seconds, max_cost_usd=args.max_cost_usd)
    print(json.dumps(summary, indent=2))
    if summary.get("error"):
        return 1
    return 2 if summary.get("incomplete") or summary.get("not_started") else 0   # 2 = runs left; resubmit


if __name__ == "__main__":
    raise SystemExit(main())
