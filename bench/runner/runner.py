"""Runs an experiment: expands the grid, shards it, executes episodes, resumes after a kill.

Sharding and multi-process dispatch both work on *groups* (episodes that differ only by policy),
so the agent-run cache is only ever used by one worker at a time. A failed episode writes
``error.json`` and leaves no ``oracle.json``, so the next invocation retries it.

Cost cap (Tinker): ``max_cost_usd`` is the job's hard cap. Each worker process gets an equal share
(B's ``Budget``: no request is sent that could pass it), so the job never spends more than the cap.
A worker whose share is used up stops starting episodes; runs it could not finish stay incomplete
(``error.json`` with ``"incomplete": "budget"``) and the next job reruns them.
"""

from __future__ import annotations

import json
import signal
import time
import traceback
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from bench.runner import components, target
from bench.runner.ids import data_tag
from bench.runner.config import EpisodeKey, ExperimentConfig, expand
from bench.runner.episode import IncompleteRun, run_episode
from bench.runner.ids import short_hash


def parse_shard(text: str | None) -> tuple[int, int]:
    if not text:
        return (0, 1)
    i, _, n = text.partition("/")
    i, n = int(i), int(n)
    if not (n >= 1 and 0 <= i < n):
        raise ValueError(f"--shard must be i/n with 0 <= i < n, got {text!r}")
    return (i, n)


def select_groups(keys: list[EpisodeKey], shard: tuple[int, int]) -> list[list[EpisodeKey]]:
    """Group episodes (all policies of one scenario/seed/model/repeat) and keep this shard's groups."""
    groups: dict[str, list[EpisodeKey]] = defaultdict(list)
    for k in keys:
        groups[k.group_id()].append(k)
    i, n = shard
    return [groups[g] for g in sorted(groups) if int(short_hash(g, n=8), 16) % n == i]


class Deadline:
    """Stops *starting* new groups after ``max_seconds`` or after SIGTERM (Slurm's time-limit warning)."""

    def __init__(self, max_seconds: float | None):
        self.end = time.time() + max_seconds if max_seconds is not None else None
        self.term = False

    def install_sigterm(self) -> None:
        try:
            signal.signal(signal.SIGTERM, lambda *_: setattr(self, "term", True))
        except ValueError:                    # not the main thread
            pass

    def expired(self) -> bool:
        return self.term or (self.end is not None and time.time() >= self.end)


def _run_group(args: tuple) -> list[dict]:
    cfg_dict, keys, runs_dir, dry_run, cost_share = args
    cfg = ExperimentConfig(**cfg_dict)
    comps = components.build(dry_run, cfg.components, harness_options=cfg.harness_options, max_cost_usd=cost_share)
    baseline = target.baseline_for(cfg.baseline_runs)
    out_root = Path(runs_dir)
    results = []
    spent0 = comps.budget.spent if comps.budget is not None else 0.0
    for key in keys:
        if comps.budget_exhausted():
            results.append({"run_id": key.run_id(data_tag()), "status": "not_started", "reason": "cost cap"})
            continue
        try:
            results.append(run_episode(key, comps, out_root, out_root / "_work", budget=cfg.budget,
                                       stop_at_bypass=cfg.stop_at_bypass, baseline=baseline))
        except Exception as e:
            run_id = key.run_id(data_tag())
            d = out_root / run_id
            d.mkdir(parents=True, exist_ok=True)
            (d / "error.json").write_text(json.dumps({"error": f"{type(e).__name__}: {e}",
                                                      "incomplete": e.kind if isinstance(e, IncompleteRun) else None,
                                                      "trace": traceback.format_exc(), "key": key.__dict__}, indent=2))
            results.append({"run_id": run_id, "status": "incomplete" if isinstance(e, IncompleteRun) else "error",
                            "error": str(e)})
    if comps.budget is not None:
        results.append({"status": "_spent", "usd": comps.budget.spent - spent0})   # this group's spend
    return results


def check_prices(cfg: ExperimentConfig) -> None:
    """A cost cap needs a price for every model (models.yaml ``price``), as in B's pilot."""
    from bench.backends import model_config
    missing = [m for m in cfg.models if not (model_config(m) or {}).get("price")]
    if missing:
        raise ValueError(f"--max-cost-usd needs a price in models.yaml for {missing}")


def shard_marker(runs_dir: Path, shard: tuple[int, int]) -> Path:
    return runs_dir / "_shards" / f"{shard[0]}of{shard[1]}.json"


def run_experiment(cfg: ExperimentConfig, runs_root: Path, *, dry_run: bool = False,
                   shard: tuple[int, int] = (0, 1), workers: int = 1, max_seconds: float | None = None,
                   max_cost_usd: float | None = None) -> dict:
    runs_dir = Path(runs_root) / cfg.name
    runs_dir.mkdir(parents=True, exist_ok=True)
    keys = list(expand(cfg))
    groups = select_groups(keys, shard)
    if max_cost_usd and not dry_run:
        check_prices(cfg)
    n_proc = workers if workers > 1 and len(groups) > 1 else 1
    cost_share = (max_cost_usd / n_proc) if (max_cost_usd and not dry_run) else None
    jobs = [(cfg.__dict__, g, str(runs_dir), dry_run, cost_share) for g in groups]
    deadline = Deadline(max_seconds)
    deadline.install_sigterm()
    nested: list[list[dict]] = []
    stopped_early = False
    if workers > 1 and len(jobs) > 1:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            pending = list(jobs)
            futures = []
            while pending or futures:
                while pending and len(futures) < workers and not deadline.expired():
                    futures.append(ex.submit(_run_group, pending.pop(0)))
                if not futures:
                    break
                nested.append(futures.pop(0).result())
            stopped_early = bool(pending)
    else:
        for j in jobs:
            if deadline.expired():
                stopped_early = True
                break
            nested.append(_run_group(j))
    results = [r for part in nested for r in part]
    spent = [r["usd"] for r in results if r["status"] == "_spent"]
    results = [r for r in results if r["status"] != "_spent"]
    counts: dict[str, int] = defaultdict(int)
    for r in results:
        counts[r["status"]] += 1
    summary = {"experiment": cfg.name, "runs_dir": str(runs_dir), "grid_size": len(keys),
               "selected": sum(len(g) for g in groups), "shard": f"{shard[0]}/{shard[1]}",
               "stopped_early": stopped_early, **counts}
    if max_cost_usd and not dry_run:
        summary["cost_cap_usd"] = max_cost_usd
        summary["spent_usd"] = round(sum(spent), 4)
    marker = shard_marker(runs_dir, shard)          # "this shard process finished"; completeness is checked
    marker.parent.mkdir(exist_ok=True)              # against oracle.json files by bench.runner.shards
    marker.write_text(json.dumps({**summary, "finished_at": time.time()}, indent=2))
    return summary
