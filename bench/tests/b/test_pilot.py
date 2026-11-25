"""B5 pilot runner: job list, sharding, resume, caps, summary. Fake model server only."""

from __future__ import annotations

import json
import shutil
from pathlib import Path


from bench.harness import pilot

from b_fake_openai import FakeOpenAI, tool_call, write_models

ROOT = Path(__file__).resolve().parents[3]


def test_job_list_covers_55_tasks_x_3():
    tasks = pilot.all_tasks()
    assert len(tasks) == 55 and len({t.task_id for t in tasks}) == 55
    assert {t.repo_id for t in tasks} == {"ops-office", "orders-api", "release-tools", "shop-web"}
    every = pilot.jobs(tasks, 3)
    assert len(every) == 165 and len({(t.task_id, r) for t, r in every}) == 165
    shards = [pilot.jobs(tasks, 3, (i, 8)) for i in range(8)]
    assert sorted((t.task_id, r) for s in shards for t, r in s) == sorted((t.task_id, r) for t, r in every)
    assert max(map(len, shards)) - min(map(len, shards)) <= 1
    assert {r for t, r in shards[0][:7]} == {0}                       # repeat 0 of every task comes first


def test_policy_and_spec(tmp_path):
    t = pilot.all_tasks()[0]
    s = pilot.make_spec(tmp_path, "m", t, 2)
    assert s.policy.name == "none" and s.scenario is None and s.seed == 2 and s.invocation == "natural"
    assert s.out_dir == tmp_path / "m" / t.task_id / "r2" and set(s.installed) and \
        all(v.version == "v1" for v in s.installed.values())


def test_dry_run(capsys, tmp_path):
    assert pilot.main(["run", "--model", "x", "--dry-run", "--shard", "1/4", "--out", str(tmp_path)]) == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == len(pilot.jobs(pilot.all_tasks(), 3, (1, 4)))


def _replies_ok():
    return [{"role": "assistant", "content": None, "tool_calls": [tool_call("list_dir", {"path": "."})]},
            {"role": "assistant", "content": "<think>x</think>done"}]


def test_run_resume_and_summary(tmp_path, monkeypatch):
    out = tmp_path / "pilot"
    with FakeOpenAI(_replies_ok() * 2) as srv:
        monkeypatch.setenv("CDB_MODELS", str(tmp_path / "m.yaml"))
        write_models(tmp_path / "m.yaml", srv.base_url, "vllm", name="fake-vllm")
        args = ["run", "--model", "fake-vllm", "--tasks", "ops-office-t05", "--repeats", "2",
                "--isolation", "env", "--out", str(out), "--wait-s", "5"]
        assert pilot.main(args) == 0
        n_req = len(srv.requests)
        assert n_req == 4
        assert pilot.main(args) == 0                                   # resume: nothing left
        assert len(srv.requests) == n_req
    for r in (0, 1):
        m = json.loads((out / "fake-vllm/ops-office-t05" / f"r{r}" / "meta.json").read_text())
        assert m["seed"] == r and m["policy_runtime"] == "none" and m["skill_id"] == "meeting-minutes"
        assert m["run_end"] == "done" and m["success"]["success"] is False
    prog = [json.loads(l) for l in (out / "fake-vllm/progress.jsonl").read_text().splitlines()]
    assert [(p["task_id"], p["repeat"]) for p in prog] == [("ops-office-t05", 0), ("ops-office-t05", 1)]
    assert srv.requests[0]["seed"] == 0 and srv.requests[2]["seed"] == 1

    # a killed run (no success entry) is redone; others are kept
    meta_p = out / "fake-vllm/ops-office-t05/r1/meta.json"
    m = json.loads(meta_p.read_text())
    m.pop("success")
    meta_p.write_text(json.dumps(m))
    assert not pilot.is_complete(meta_p.parent) and pilot.is_complete(out / "fake-vllm/ops-office-t05/r0")

    rows = pilot.collect(out)
    assert len(rows) == 2 and rows[0]["backend"] == "vllm" and rows[0]["skill_loaded"] is False
    tables = pilot.summarize(rows)
    assert "| fake-vllm | vllm | bf16 |" in tables["main"] and "n/a" in tables["main"]


def test_server_not_ready_fails_fast(tmp_path, monkeypatch):
    with FakeOpenAI() as srv:
        url = srv.base_url
    write_models(tmp_path / "m.yaml", url, name="gone")
    monkeypatch.setenv("CDB_MODELS", str(tmp_path / "m.yaml"))
    assert pilot.main(["run", "--model", "gone", "--tasks", "ops-office-t05", "--repeats", "1",
                       "--out", str(tmp_path / "p"), "--wait-s", "0.1"]) == 3
    assert not (tmp_path / "p" / "gone" / "ops-office-t05").exists()


def test_deadline_and_token_budget_stop_new_runs(tmp_path, monkeypatch):
    with FakeOpenAI(_replies_ok() * 4) as srv:
        write_models(tmp_path / "m.yaml", srv.base_url, name="f")
        monkeypatch.setenv("CDB_MODELS", str(tmp_path / "m.yaml"))
        base = ["run", "--model", "f", "--tasks", "ops-office-t05,ops-office-t01", "--repeats", "1",
                "--isolation", "env", "--out", str(tmp_path / "p"), "--no-wait"]
        assert pilot.main(base + ["--deadline-s", "100", "--run-timeout", "60"]) == 2   # no time for any run
        assert srv.requests == []
        # each fake run uses 2 x 120 tokens; a cap of 100 allows the first run only
        assert pilot.main(base + ["--max-total-tokens", "100"]) == 2
        assert len(list((tmp_path / "p" / "f").glob("*/r0/meta.json"))) == 1
        assert pilot.tokens_used(tmp_path / "p", "f") == 240


def _fake_run(root, model, task, rep, success, loaded, verdict=None, end="done", kind=None):
    d = root / model / task / f"r{rep}"
    d.mkdir(parents=True)
    meta = {"task_id": task, "repo_id": task.rsplit("-t", 1)[0], "skill_id": "s",
            "skill_loads": ["s"] if loaded else [], "run_end": end, "agent_error_kind": kind,
            "success": {"success": success}, "steps": 3, "tool_calls": 2, "malformed_calls": [],
            "timings": {"agent_s": 10.0}, "usage": {"prompt_tokens": 50, "completion_tokens": 50},
            "model_config": {"backend": "llamacpp", "quantization": "Q4_K_M", "hardware": "cook-gtx"}}
    (d / "meta.json").write_text(json.dumps(meta))
    if verdict:
        (d / "oracle.json").write_text(json.dumps({"verdict": verdict}))


def test_summary_tables_and_pilot_md_update(tmp_path):
    root = tmp_path / "runs"
    _fake_run(root, "q8", "ops-office-t01", 0, True, True, "clean")
    _fake_run(root, "q8", "ops-office-t01", 1, False, True, "violation")
    _fake_run(root, "q8", "shop-web-t02", 0, True, False, "clean")
    _fake_run(root, "q8", "shop-web-t02", 1, False, False, None, "error", "context_length")
    rows = pilot.collect(root)
    t = pilot.summarize(rows, expected_per_model=165)
    line = next(l for l in t["main"].splitlines() if l.startswith("| q8 "))
    cells = [c.strip() for c in line.strip("|").split("|")]
    assert cells[:5] == ["q8", "llamacpp", "Q4_K_M", "cook-gtx", "4/165"]
    assert cells[5].startswith("50% ") and cells[6].startswith("67% ") and cells[7].startswith("50% ")
    assert cells[8] == "3/0/0/1" and cells[11] == "100"
    assert "| q8 | context_length | 1 |" in t["errors"]
    assert "| q8 | shop-web | 2 | 50% " in t["per_repo"]
    lo, hi = pilot.wilson(5, 10)
    assert 0.23 < lo < 0.24 and 0.76 < hi < 0.77

    md = tmp_path / "PILOT.md"
    shutil.copy(ROOT / "bench/harness/PILOT.md", md)
    before = md.read_text()
    assert pilot.main(["summarize", "--root", str(root), "--update-md", str(md), "--csv", str(tmp_path / "p.csv")]) == 0
    after = md.read_text()
    assert "| q8 | llamacpp |" in after and "_No runs yet._" not in after
    assert after.split(pilot.MD_BEGIN)[0] == before.split(pilot.MD_BEGIN)[0]
    assert after.split(pilot.MD_END)[1] == before.split(pilot.MD_END)[1]
    assert len((tmp_path / "p.csv").read_text().splitlines()) == 5


def test_pilot_scripts_are_well_formed():
    import subprocess
    for p in ("bench/harness/slurm/pilot_cook.sbatch", "bench/harness/scripts/pilot_vllm.sh",
              "bench/harness/scripts/pilot_tinker.sh"):
        assert subprocess.run(["bash", "-n", str(ROOT / p)]).returncode == 0, p
    sb = (ROOT / "bench/harness/slurm/pilot_cook.sbatch").read_text()
    assert "#SBATCH --time=02:00:00" in sb and "#SBATCH --array=0-7" in sb and "--deadline-s" in sb
