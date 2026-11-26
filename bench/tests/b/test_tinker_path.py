"""Tinker pilot path: prices and per-run cost, the job's hard USD cap, key redaction, the
Tinker entries, and the CPU-only COOK job. Fake model server only; no Tinker call."""

from __future__ import annotations

import json
import py_compile
import re
from pathlib import Path

import pytest

from bench.backends import BackendError, load_models, make_model
from bench.backends.base import Budget, cost_usd
from bench.harness import pilot

from b_fake_openai import FakeOpenAI, tool_call, write_models

ROOT = Path(__file__).resolve().parents[3]
PRICE = {"prefill": 10.0, "cached_prefill": 2.0, "sample": 10.0}      # USD per million (test only)


def test_cost_counts_prefill_cached_and_sampled_tokens():
    p = {"prefill": 0.54, "cached_prefill": 0.108, "sample": 1.335}
    assert cost_usd({"prompt_tokens": 1_000_000, "completion_tokens": 0}, p) == pytest.approx(0.54)
    assert cost_usd({"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000,
                     "cached_prompt_tokens": 500_000}, p) == pytest.approx(0.27 + 0.054 + 1.335)
    assert cost_usd({"prompt_tokens": 10, "completion_tokens": 10}, None) is None


def test_budget_refuses_a_call_that_could_pass_the_cap():
    b = Budget(1.0)
    b.reserve(0.6)
    b.add(0.5)
    with pytest.raises(BackendError) as e:
        b.reserve(0.6)
    assert e.value.kind == "budget" and b.refused == 1 and b.spent == pytest.approx(0.5)


def _replies():
    return [{"role": "assistant", "content": None, "tool_calls": [tool_call("list_dir", {"path": "."})]},
            {"role": "assistant", "content": "done"}]


def test_pilot_cost_cap_is_hard_and_runs_it_stops_are_rerun(tmp_path, monkeypatch, capsys):
    out = tmp_path / "p"
    with FakeOpenAI(_replies() * 2) as srv:
        write_models(tmp_path / "m.yaml", srv.base_url, name="f", price=PRICE)
        monkeypatch.setenv("CDB_MODELS", str(tmp_path / "m.yaml"))
        base = ["run", "--model", "f", "--tasks", "ops-office-t05", "--repeats", "1",
                "--isolation", "env", "--out", str(out), "--no-wait"]
        # worst case of the first call (8192 sampled tokens at $10/M = $0.08 + prompt) > $0.05
        assert pilot.main(base + ["--max-cost-usd", "0.05"]) == 2
        assert srv.requests == []                                 # nothing was sent
        d = out / "f+d9/ops-office-t05/r0"
        meta = json.loads((d / "meta.json").read_text())
        assert meta["run_end"] == "error" and meta["agent_error_kind"] == "budget"
        assert not pilot.is_complete(d)                           # rerun by the next job
        assert pilot.main(base + ["--max-cost-usd", "1"]) == 0
        meta = json.loads((d / "meta.json").read_text())
        # fake usage: 2 calls x (100 prompt + 20 sampled) at $10/M
        assert meta["cost_usd"] == pytest.approx(2 * 120 * 10 / 1e6)
        assert meta["model_config"]["price"] == PRICE
        prog = [json.loads(l) for l in (out / "f+d9/progress.jsonl").read_text().splitlines()]
        assert prog[-1]["job_spent_usd"] == pytest.approx(0.0024, abs=1e-4)
        assert pilot.main(base[:1] + ["--max-cost-usd", "1"] + base[1:]) == 0   # nothing left
    capsys.readouterr()
    pilot.main(["report", "--root", str(out), "--timing"])
    assert "cost: $0.0024 over 1 runs" in capsys.readouterr().out


def test_cost_cap_needs_a_price(tmp_path, monkeypatch):
    with FakeOpenAI(_replies()) as srv:
        write_models(tmp_path / "m.yaml", srv.base_url, name="f")
        monkeypatch.setenv("CDB_MODELS", str(tmp_path / "m.yaml"))
        assert pilot.main(["run", "--model", "f", "--tasks", "ops-office-t05", "--repeats", "1",
                           "--out", str(tmp_path / "p"), "--no-wait", "--max-cost-usd", "5"]) == 3


def test_api_key_is_redacted_from_backend_errors(tmp_path):
    key = "tk-SECRET-0123456789"
    with FakeOpenAI([]) as srv:                               # no replies queued: the server errors
        write_models(tmp_path / "m.yaml", srv.base_url, name="f", retries=0, api_key_env="FAKE_KEY")
        m = make_model("f", path=tmp_path / "m.yaml", env={"FAKE_KEY": key})
        err = m._redact(BackendError("auth", f"HTTP 401: bad key {key}", 401))
        assert key not in str(err) and "<redacted>" in str(err) and err.kind == "auth" and err.status == 401
        assert key not in json.dumps(m.describe())


def test_tinker_entries():
    cfg = load_models()
    want = {"qwen3-8b-tinker": ("Qwen/Qwen3-8B", 32768, 0.60),
            "qwen3.6-35b-a3b-tinker": ("Qwen/Qwen3.6-35B-A3B", 65536, 1.335),
            "qwen3.8-27b-tinker": ("Qwen/Qwen3.8-27B", 65536, 5.595)}
    for name, (mid, ctx, sample) in want.items():
        c = cfg[name]
        assert c["backend"] == "tinker" and c["model"] == mid and c["tool_mode"] == "native", name
        assert c["server"]["ctx_size"] == ctx and c["price"]["sample"] == sample and c["price"]["prefill"] > 0
        m = make_model(name, env={"TINKER_API_KEY": "x"})
        assert m.tool_mode == "native" and m.describe()["price"] == c["price"]
    py_compile.compile(str(ROOT / "bench/harness/scripts/tinker_smoke.py"), doraise=True)
    smoke = (ROOT / "bench/harness/scripts/tinker_smoke.py").read_text()
    assert "--model" in smoke and "build_request" in smoke and "print(key" not in smoke


def test_cpu_only_tinker_job_handles_the_key_safely():
    sb = (ROOT / "bench/harness/slurm/tinker_pilot.sbatch").read_text()
    assert "--gres" not in sb and "export CDB_GPUS=0" in sb and "set +x" in sb
    assert '. "$KEYF"' in sb and "$HOME/.tinker_key" in sb and '[ "$MODE" = 600 ]' in sb
    assert "--isolation netns --observer strace" in sb and '--max-cost-usd "${MAX_COST_USD:-5}"' in sb
    assert "grep -rlF -f -" in sb                         # the key never goes on a command line
    assert not re.search(r"echo[^\n]*\$\{?TINKER_API_KEY\}?[^:#]", sb.replace("${#TINKER_API_KEY}", ""))
    assert "import openai, httpx" in sb and "check_env --isolation netns" in sb
    sub = (ROOT / "bench/harness/scripts/cook_submit.sh").read_text()
    branch = sub[sub.index('if [ "$JOB" = tinker-pilot ]'):sub.index("exit $?")]
    assert "--gres" not in branch and "unset TINKER_API_KEY" in branch and "CDB_GPUS=0" in branch
    env = (ROOT / "bench/harness/slurm/cook_env.sh").read_text()
    assert 'if [ "$CDB_GPUS" = 0 ]; then' in env and "module load python/3.13.15" in env
