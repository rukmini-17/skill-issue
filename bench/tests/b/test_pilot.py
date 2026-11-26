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


def _fake_run(root, model, task, rep, success, loaded, verdict=None, end="done", kind=None, used=None):
    d = root / model / task / f"r{rep}"
    d.mkdir(parents=True)
    meta = {"task_id": task, "repo_id": task.rsplit("-t", 1)[0], "skill_id": "s",
            "skill_loads": ["s"] if loaded else [], "skill_uses": ["s"] if (loaded if used is None else used) else [],
            "run_end": end, "agent_error_kind": kind,
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
    assert cells[8].startswith("50% ")                                  # skill-use rate
    assert cells[9] == "3/0/0/1" and cells[12] == "100"
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
              "bench/harness/scripts/pilot_tinker.sh", "bench/harness/slurm/cook_env.sh",
              "bench/harness/slurm/first_run_t05.sbatch", "bench/harness/scripts/cook_probe.sh",
              "bench/harness/scripts/cook_submit.sh", "bench/harness/slurm/skill_check.sbatch"):
        assert subprocess.run(["bash", "-n", str(ROOT / p)]).returncode == 0, p
    sb = (ROOT / "bench/harness/slurm/pilot_cook.sbatch").read_text()
    assert "#SBATCH --time=02:00:00" in sb and "#SBATCH --array=0-7" in sb and "--deadline-s" in sb
    assert ". bench/harness/slurm/cook_env.sh" in sb
    env = (ROOT / "bench/harness/slurm/cook_env.sh").read_text()
    assert "llm-r580-llamacpp/2026.10" in env and "llm-r615-llamacpp/2026.11 python/3.13.15" in env
    assert ". /etc/profile" in env and "module purge" in env and "CUDA_VISIBLE_DEVICES:?" in env
    assert "srun --ntasks=1 --gres=gpu:1" in env and "OMP_NUM_THREADS" in env and ".venv-r615" not in env
    sub = (ROOT / "bench/harness/scripts/cook_submit.sh").read_text()
    assert "gtx) MEM=16G" in sub and "t4) MEM=24G" in sub and "rtx) MEM=40G" in sub
    for f in ("pilot_cook.sbatch", "first_run_t05.sbatch"):
        t = (ROOT / "bench/harness/slurm" / f).read_text()
        assert "cdb_start_server" in t and 'cdb_log_buffers "$SLOG"' in t, f
    fr = (ROOT / "bench/harness/slurm/first_run_t05.sbatch").read_text()
    assert "#SBATCH --partition=gtx" in fr and "#SBATCH --time=00:30:00" in fr and "#SBATCH --gres=gpu:1" in fr
    assert "--isolation netns --observer strace" in fr and "--judge" in fr
    assert "--mem=\"$MEM\"" in (ROOT / "bench/harness/scripts/cook_submit.sh").read_text()


def test_behaviour_table_counts_multi_call_and_blind_writes(tmp_path):
    root = tmp_path / "runs"
    beh = [{"multi_call_turns": 1, "blind_write_turns": 1, "turns_with_reasoning": 0},
           {"multi_call_turns": 2, "blind_write_turns": 0, "turns_with_reasoning": 3},
           {"multi_call_turns": 0, "blind_write_turns": 0, "turns_with_reasoning": 2}]
    for i, b in enumerate(beh):
        _fake_run(root, "q8", "ops-office-t05", i, i == 2, i > 0, "clean")
        p = root / "q8/ops-office-t05" / f"r{i}" / "meta.json"
        p.write_text(json.dumps({**json.loads(p.read_text()), "behaviour": b}))
    _fake_run(root, "q8", "ops-office-t05", 3, True, True, "clean")        # old run: no behaviour
    t = pilot.summarize(pilot.collect(root))
    line = next(l for l in t["behaviour"].splitlines() if l.startswith("| q8 "))
    cells = [c.strip() for c in line.strip("|").split("|")]
    assert cells[1] == "3" and cells[2].startswith("67% ") and cells[3].startswith("33% ")
    assert cells[4] == "1.00" and cells[5].startswith("67% ")
    assert "#### Behaviour" in pilot.render(t)


def test_explicit_invocation_is_its_own_row(tmp_path, capsys):
    t = next(x for x in pilot.all_tasks() if x.task_id == "ops-office-t05")
    s = pilot.make_spec(tmp_path, "q8", t, 1, "explicit")
    assert s.invocation == "explicit" and s.out_dir == tmp_path / "q8+explicit-v2" / "ops-office-t05" / "r1"
    assert pilot.make_spec(tmp_path, "q8", t, 1).out_dir == tmp_path / "q8" / "ops-office-t05" / "r1"
    from bench.harness.agent import user_prompt
    assert user_prompt(t.prompt, t.skill_id, s.invocation) == (
        "Use the meeting-minutes skill (.github/skills/meeting-minutes/SKILL.md) for this task.\n\n" + t.prompt)
    assert user_prompt(t.prompt, t.skill_id, "natural") == t.prompt
    assert pilot.main(["run", "--model", "q8", "--invocation", "explicit", "--tasks", "ops-office-t05",
                       "--repeats", "1", "--out", str(tmp_path), "--dry-run"]) == 0
    assert "q8+explicit-v2/ops-office-t05/r0" in capsys.readouterr().out


def test_skill_loads_per_task_table(tmp_path):
    root = tmp_path / "runs"
    _fake_run(root, "q8", "ops-office-t01", 0, True, True)
    _fake_run(root, "q8", "ops-office-t01", 1, False, False, used=True)    # listed the folder, no SKILL.md
    _fake_run(root, "q8", "shop-web-t02", 0, False, False)
    _fake_run(root, "q8+explicit", "shop-web-t02", 0, True, True)
    t = pilot.summarize(pilot.collect(root))["per_task"]
    assert "| q8: loaded / used / success | q8+explicit: loaded / used / success |" in t.splitlines()[0]
    assert "| ops-office-t01 | s | 1/2 / 2/2 / 1/2 | - |" in t
    assert "| shop-web-t02 | s | 0/1 / 0/1 / 0/1 | 1/1 / 1/1 / 1/1 |" in t
    assert "never loaded in any completed run (0): none" in t
    _fake_run(root, "q8", "shop-web-t03", 0, False, False)
    assert "(1): shop-web-t03" in pilot.summarize(pilot.collect(root))["per_task"]
    assert "#### Skill loads per task" in pilot.render(pilot.summarize(pilot.collect(root)))


def test_report_lines_and_skill_check_job(tmp_path, capsys):
    root = tmp_path / "sc"
    _fake_run(root, "q14+explicit-v2", "ops-office-t05", 0, True, True)
    _fake_run(root, "q14+explicit-v2", "ops-office-t01", 0, True, False, used=True)
    _fake_run(root, "q14+explicit-v2", "shop-web-t05", 0, False, False)
    assert pilot.main(["report", "--root", str(root), "--tasks", "ops-office-t01,ops-office-t05"]) == 0
    out = capsys.readouterr().out
    assert "| q14+explicit-v2 | ops-office-t01 r0 | s | None | False | True | True | done | 3 | 10 |" in out
    assert "| q14+explicit-v2 | ops-office-t05 r0 | s | None | True | True | True |" in out
    assert "shop-web-t05" not in out and "2 completed runs: skill_load 1, skill_used 2, success 2" in out
    _fake_run(root, "q32+explicit-v2", "ops-office-t01", 0, False, True)
    other = tmp_path / "nat"
    _fake_run(other, "q14", "ops-office-t01", 0, False, False)
    assert pilot.main(["report", "--root", str(root), "--root", str(other), "--model", "q14", "--timing"]) == 0
    out = capsys.readouterr().out
    assert "q32" not in out and "| q14 | ops-office-t01 r0 |" in out and "4 completed runs" in out
    assert "| done | 3 | 10 | - | 50 | 50 | 17 | 3 | None |" in out      # no model_s in the fake meta
    assert "| q14+explicit-v2 | 3 | 3.0 | 10 | - | 50 | 17 | 3 | done 3 |" in out
    assert pilot.main(["report", "--root", str(root), "--root", str(other), "--model", "q14",
                       "--timing", "--common-tasks"]) == 0
    out = capsys.readouterr().out
    assert "2 completed runs" in out and "ops-office-t05" not in out
    assert "| q14 | 1 |" in out and "| q14+explicit-v2 | 1 |" in out
    sb = (ROOT / "bench/harness/slurm/skill_check.sbatch").read_text()
    assert "#SBATCH --time=02:00:00" in sb and 'INVOCATION="${INVOCATION:-explicit}"' in sb
    assert "ops-office-t05,ops-office-t01,orders-api-t01,shop-web-t05,release-tools-t03" in sb
    assert "--repeats 1" in sb and "--run-timeout" in sb and "--deadline-s" in sb and "pilot report" in sb
    assert '--model "$MODEL" --timing' in sb
    assert "skill-check)" in (ROOT / "bench/harness/scripts/cook_submit.sh").read_text()
    assert '--invocation "${INVOCATION:-natural}"' in (ROOT / "bench/harness/slurm/first_run_t05.sbatch").read_text()
