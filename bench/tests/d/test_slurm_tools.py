"""D3: deadline exit, shard markers, incomplete-shard listing and resubmission (with a fake sbatch)."""

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import yaml

from bench.runner import shards
from bench.runner.config import ExperimentConfig
from bench.runner.runner import run_experiment

ROOT = Path(__file__).resolve().parents[3]


def cfg(**kw):
    base = dict(name="sl", kind="attack", repos=["all"], max_scenarios_per_repo=2,
                policies=["none", "pin_reapprove"], attackers=["stub"])
    base.update(kw)
    return ExperimentConfig(**base)


def test_max_seconds_stops_cleanly_and_next_run_finishes(tmp_path):
    s = run_experiment(cfg(), tmp_path, dry_run=True, max_seconds=0)
    assert s["stopped_early"] and s["selected"] == 16 and "ran" not in s
    marker = json.loads((tmp_path / "sl" / "_shards" / "0of1.json").read_text())
    assert marker["stopped_early"]
    s2 = run_experiment(cfg(), tmp_path, dry_run=True)
    assert not s2["stopped_early"] and s2.get("ran", 0) + s2.get("reused", 0) == 16


def test_deadline_between_groups(tmp_path):
    # a 0.2 s budget over many groups finishes some groups and leaves the rest for a rerun
    c = cfg(max_scenarios_per_repo=None)
    s = run_experiment(c, tmp_path, dry_run=True, max_seconds=0.05)
    done = sum(1 for d in (tmp_path / "sl").iterdir() if (d / "oracle.json").exists())
    total = s["selected"]
    assert s["stopped_early"] and 0 < done < total
    s2 = run_experiment(c, tmp_path, dry_run=True)
    assert s2["skipped"] >= done


def test_shard_status_and_incomplete_listing(tmp_path):
    c = cfg()
    run_experiment(c, tmp_path, dry_run=True, shard=(0, 3))
    run_experiment(c, tmp_path, dry_run=True, shard=(1, 3), max_seconds=0)     # nothing done
    st = shards.shard_status(c, tmp_path, 3)
    assert [s["complete"] for s in st] == [True, False, False]
    assert sum(s["total"] for s in st) == 16
    assert st[1]["marker"] and not st[2]["marker"]


def test_sbatch_command_shape():
    cmd = shards.sbatch_command(Path("e.yaml"), [1, 4], 8, partition="t4", gres="gpu:1", runs_root=Path("runs"))
    assert cmd[0] == "sbatch" and "--array=1,4" in cmd and "--partition=t4" in cmd and "--gres=gpu:1" in cmd
    exp = [c for c in cmd if c.startswith("--export=")][0]
    assert "NSHARDS=8" in exp and "EXPERIMENT=" in exp and "DRY_RUN=0" in exp
    assert cmd[-1].endswith("run_shard.sbatch") and Path(cmd[-1]).exists()


def _fake_sbatch(tmp_path):
    log = tmp_path / "sbatch.log"
    f = tmp_path / "fake_sbatch"
    f.write_text(f"#!/bin/sh\necho \"$@\" >> {log}\necho 'Submitted batch job 4242'\n")
    f.chmod(f.stat().st_mode | stat.S_IEXEC)
    return f, log


def run_cli(args, env=None):
    e = dict(os.environ, **(env or {}))
    return subprocess.run([sys.executable, "-m", "bench.runner.shards", *args], cwd=ROOT, env=e,
                          capture_output=True, text=True)


def test_resubmit_cli_submits_only_incomplete_shards(tmp_path):
    ypath = tmp_path / "e.yaml"
    ypath.write_text(yaml.safe_dump({"name": "sl", "kind": "attack", "repos": ["all"], "max_scenarios_per_repo": 2,
                                     "policies": ["none"], "attackers": ["stub"]}))
    c = ExperimentConfig.load(ypath)
    run_experiment(c, tmp_path / "runs", dry_run=True, shard=(0, 4))
    fake, log = _fake_sbatch(tmp_path)
    r = run_cli([str(ypath), "--shards", "4", "--runs-dir", str(tmp_path / "runs"), "--resubmit", "--submit"],
                env={"SBATCH": str(fake)})
    assert r.returncode == 0, r.stderr
    sub = log.read_text()
    assert "--array=" in sub and "--array=0" not in sub.split()[0]       # shard 0 is complete, not resubmitted
    assert "NSHARDS=4" in sub
    # without --submit nothing runs
    log.unlink()
    r = run_cli([str(ypath), "--shards", "4", "--runs-dir", str(tmp_path / "runs"), "--resubmit"], env={"SBATCH": str(fake)})
    assert "not submitted" in r.stdout and not log.exists()


def test_resubmit_refuses_over_job_cap(tmp_path):
    ypath = tmp_path / "e.yaml"
    ypath.write_text(yaml.safe_dump({"name": "sl", "kind": "attack", "repos": ["all"], "policies": ["none"], "attackers": ["stub"]}))
    fake, log = _fake_sbatch(tmp_path)
    r = run_cli([str(ypath), "--shards", "40", "--runs-dir", str(tmp_path / "runs"), "--resubmit", "--submit"],
                env={"SBATCH": str(fake)})
    assert r.returncode == 2 and not log.exists() and "refusing" in r.stdout


def test_all_complete_resubmits_nothing(tmp_path):
    ypath = tmp_path / "e.yaml"
    ypath.write_text(yaml.safe_dump({"name": "sl", "kind": "attack", "repos": ["release-tools"],
                                     "max_scenarios_per_repo": 1, "policies": ["none"], "attackers": ["stub"]}))
    run_experiment(ExperimentConfig.load(ypath), tmp_path / "runs", dry_run=True)
    fake, log = _fake_sbatch(tmp_path)
    r = run_cli([str(ypath), "--shards", "1", "--runs-dir", str(tmp_path / "runs"), "--resubmit", "--submit"],
                env={"SBATCH": str(fake)})
    assert "0 shard(s)" in r.stdout and not log.exists()


def test_sbatch_script_has_required_directives_and_valid_bash():
    text = (ROOT / "bench/runner/slurm/run_shard.sbatch").read_text()
    for needle in ("#SBATCH --time=02:00:00", "#SBATCH --partition=gtx", "SLURM_ARRAY_TASK_ID", "--max-seconds"):
        assert needle in text
    assert subprocess.run(["bash", "-n", str(ROOT / "bench/runner/slurm/run_shard.sbatch")]).returncode == 0
    assert subprocess.run(["bash", "-n", str(ROOT / "bench/runner/slurm/resubmit.sh")]).returncode == 0


def test_sbatch_script_runs_locally_as_one_shard(tmp_path):
    """Run the template the way Slurm would, minus Slurm: proves the variables and CLI line up."""
    env = dict(os.environ, EXPERIMENT=str(ROOT / "bench/configs/experiments/slurm_tiny.yaml"), NSHARDS="1",
               DRY_RUN="1", RUNS_DIR=str(tmp_path / "runs"), SLURM_ARRAY_TASK_ID="0", SLURM_SUBMIT_DIR=str(ROOT),
               VENV=str(ROOT / ".venv"), PATH=os.environ["PATH"])
    r = subprocess.run(["bash", str(ROOT / "bench/runner/slurm/run_shard.sbatch")], env=env, cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    done = list((tmp_path / "runs" / "slurm_tiny").glob("*/oracle.json"))
    assert len(done) == 3
