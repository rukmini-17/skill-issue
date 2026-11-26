"""Decision 9 (max_tokens 8192 + one truncation nudge), the final workspace delta, re-scoring
with format-tolerant checks, and the manual-audit sample."""

import csv
import json
import tarfile

import pytest
import yaml
from b_helpers import REPOS, load_task

from bench.harness import agent as agent_mod
from bench.harness import pilot, rescore
from bench.harness.model import AssistantTurn, ScriptedModel
from bench.harness.run import Harness, text_matches
from bench.harness.skills import repo_install_set
from bench.interfaces import RunSpec, StubPolicy

ROOT = REPOS.parent
T01 = load_task("ops-office", "ops-office-t01")
REPORT = "reports/expenses-by-category.md"
CUT = AssistantTurn("", [], reasoning="x" * 50, finish_reason="length", usage={"completion_tokens": 4096})


class MaxTokModel(ScriptedModel):
    max_tokens = 4096

    def describe(self) -> dict:
        d = super().describe()
        d["decoding"] = {"max_tokens": self.max_tokens}
        return d


def run(tmp_path, script, task=T01, run_id="r", **kw):
    model = MaxTokModel(script)
    sp = RunSpec(run_id=run_id, scenario=None, task=task, installed=repo_install_set(REPOS / task.repo_id),
                 policy=StubPolicy(), model="m", invocation="natural", mock_override=None,
                 out_dir=tmp_path / "runs" / "m" / task.task_id / run_id, seed=0)
    Harness(model_factory=lambda n, s: model, work_root=tmp_path / "work", isolation="env", **kw).run(sp)
    return model, json.loads((sp.out_dir / "meta.json").read_text()), sp.out_dir


def test_d9_nudges_once_after_a_truncated_turn(tmp_path):
    model, meta, _ = run(tmp_path, [CUT, [("list_dir", {"path": "."})], "done"])
    assert meta["setup"] == "d9" and meta["truncation_nudge"] is True and meta["nudges"] == 1
    assert meta["run_end"] == "done" and meta["steps"] == 3 and meta["truncated_turns"] == 1
    assert meta["model_config"]["decoding"]["max_tokens"] == 8192
    assert {"role": "user", "content": agent_mod.TRUNCATION_NUDGE} in model.calls[1]


def test_d9_second_truncated_turn_ends_the_run(tmp_path):
    _, meta, _ = run(tmp_path, [CUT, CUT, "never reached"])
    assert meta["run_end"] == "truncated" and meta["steps"] == 2 and meta["nudges"] == 1


def test_pre_d9_keeps_the_early_pilot_behaviour(tmp_path):
    _, meta, _ = run(tmp_path, [CUT, "never reached"], setup="pre-d9")
    assert meta["run_end"] == "done" and meta["steps"] == 1 and meta["nudges"] == 0
    assert meta["setup"] == "pre-d9" and meta["model_config"]["decoding"]["max_tokens"] == 4096
    with pytest.raises(ValueError):
        Harness(setup="d10")


def test_truncated_turn_with_a_tool_call_is_not_nudged(tmp_path):
    cut_call = AssistantTurn("", CUT.tool_calls, finish_reason="length")
    from bench.harness.model import ToolCallRequest
    cut_call.tool_calls = [ToolCallRequest("c1", "list_dir", json.dumps({"path": "."}))]
    _, meta, _ = run(tmp_path, [cut_call, "done"])
    assert meta["nudges"] == 0 and meta["run_end"] == "done" and meta["truncated_turns"] == 1


def test_final_delta_and_rescore_from_delta_and_from_trace(tmp_path):
    body = "| Category | Total CAD |\n| Travel | 1,121.75 |\n"
    _, meta, out = run(tmp_path, [[("write_file", {"path": REPORT, "content": body})],
                                  [("run_command", {"cmd": "rm finance/ledger.csv"})], "done"])
    assert meta["success"]["success"] is False                      # current check: exact 1121.75
    info = json.loads((out / "final_delta.json").read_text())
    assert REPORT in info["created"] and "finance/ledger.csv" in info["deleted"]
    with tarfile.open(out / "final_delta.tar.gz") as tar:
        assert REPORT in tar.getnames()
    assert meta["final_delta"]["saved"] >= 1
    checks = rescore.load_checks(ROOT / "bench/harness/proposed_checks.yaml")
    rows = rescore.rescore([tmp_path / "runs"], checks)
    assert [(r["old"], r["new"], r["source"]) for r in rows] == [(False, True, "delta")]
    for f in ("final_delta.json", "final_delta.tar.gz"):              # an early-pilot run: trace only
        (out / f).unlink()
    rows = rescore.rescore([tmp_path / "runs"], checks)
    assert [(r["old"], r["new"], r["source"]) for r in rows] == [(False, True, "write_file")]
    text = rescore.render(rows, flips=True)
    assert "F->T 1" in text and "1121.75" not in text and "F->T  " in text


def test_rescore_marks_command_written_files_unknown(tmp_path):
    _, _, out = run(tmp_path, [[("write_file", {"path": REPORT, "content": "1121.75"})],
                               [("run_command", {"cmd": f"echo more >> {REPORT}"})], "done"], save_delta=False)
    content, source = rescore.final_text(out, "ops-office", REPORT)
    assert content is rescore.UNKNOWN and source == "changed by a command"
    content, source = rescore.final_text(out, "ops-office", "finance/expenses.xlsx")
    assert source == "initial"


def test_text_matches_format_options():
    n = {"text": "1121.75", "normalize": ["numbers"]}
    assert text_matches("Travel: $1,121.75", n) and text_matches("1121.750 CAD", n)
    assert not text_matches("11121.75", n) and not text_matches("1121.7", n)
    assert text_matches("total 96", {"text": "96.00", "normalize": ["numbers"]})
    assert not text_matches("total 196.00", {"text": "96.00", "normalize": ["numbers"]})
    assert text_matches("## Action items", {"text": "Action Items", "normalize": ["case"]})
    assert not text_matches("## Action items", {"text": "Action Items"})
    assert text_matches("id-token:   write", {"text": "id-token: write", "normalize": ["whitespace"]})
    assert text_matches("May 2026 was dropped", {"any_of": ["202605", "May 2026"], "normalize": ["case"]})
    assert text_matches("latest()", {"contains": "latest()"})
    with pytest.raises(ValueError):
        text_matches("x", {"text": "x", "normalize": ["fuzzy"]})


def test_proposed_checks_match_the_data_and_pass_the_references():
    data = yaml.safe_load((ROOT / "bench/harness/proposed_checks.yaml").read_text())["tasks"]
    assert len(data) == 21
    for tid, e in data.items():
        task = load_task(tid.rsplit("-t", 1)[0], tid)
        cur, new = task.success_check, e["success_check"]
        assert new["type"] == cur["type"] and new["path"] == cur["path"], tid
        assert {k: v for k, v in cur.items() if k in ("text", "contains")} == e["was"], tid
        assert e["prompt"].replace("...", "").split()[0] in " ".join(task.prompt.split()), tid
        ref = REPOS / task.repo_id / "tasks" / f"{tid}.reference" / "files" / cur["path"]
        if ref.is_file():                                   # the reference still passes
            assert text_matches(ref.read_text(), cur) and text_matches(ref.read_text(), new), tid


def _fake(root, row, task, rep, success, end="done"):
    d = root / row / task / f"r{rep}"
    d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps({
        "task_id": task, "repo_id": task.rsplit("-t", 1)[0], "skill_id": "s", "run_end": end,
        "success": {"type": "file_contains", "success": success}, "steps": 2, "timings": {"agent_s": 1.0}}))


def test_audit_sample_spreads_over_repos_and_skips_errors(tmp_path):
    root = tmp_path / "p"
    for i, task in enumerate(["ops-office-t01", "ops-office-t02", "orders-api-t01", "shop-web-t05"]):
        for rep in range(3):
            _fake(root, "q14+explicit-v2+d9", task, rep, success=(rep == 0))
    _fake(root, "q14+explicit-v2+d9", "release-tools-t03", 0, False, end="error")
    out = tmp_path / "audit.csv"
    assert pilot.main(["audit-sample", "--root", str(root), "--fail", "4", "--pass", "3", "--out", str(out)]) == 0
    rows = list(csv.DictReader(out.open()))
    assert len(rows) == 7 and list(rows[0]) == pilot.AUDIT_COLUMNS
    failed = [r for r in rows if r["check_success"] != "True"]
    assert len(failed) == 4 and {r["task_id"].rsplit("-t", 1)[0] for r in failed} == \
        {"ops-office", "orders-api", "shop-web"}
    assert "release-tools-t03" not in {r["task_id"] for r in rows}
    again = tmp_path / "again.csv"
    pilot.main(["audit-sample", "--root", str(root), "--fail", "4", "--pass", "3", "--out", str(again)])
    assert again.read_text() == out.read_text()                       # same seed, same sample


def test_jobs_take_setup_and_run_timeout():
    sb = (ROOT / "bench/harness/slurm/pilot_cook.sbatch").read_text()
    assert '--setup "${SETUP:-d9}" --run-timeout "${RUN_TIMEOUT:-1800}" --repeats "${REPEATS:-3}"' in sb
    assert "--array=0-9%6" in sb and "SHARDS=10" in sb
    assert '--setup "${SETUP:-d9}"' in (ROOT / "bench/harness/slurm/skill_check.sbatch").read_text()
    assert '--setup "${SETUP:-d9}"' in (ROOT / "bench/harness/slurm/first_run_t05.sbatch").read_text()


def test_gtx4_entry_and_gpu_count_plumbing():
    from bench.backends import make_model, model_config
    c = model_config("qwen3-32b-llamacpp-gtx4")
    rtx = model_config("qwen3-32b-llamacpp")
    assert (c["partition"], c["gpus"], c["mem"], c["hardware"]) == ("gtx", 4, "32G", "cook-gtx-1080ti-x4")
    assert c["model_file"] == rtx["model_file"] and c["server"]["ctx_size"] == 16384
    cmd = " ".join(make_model("qwen3-32b-llamacpp-gtx4").server_command())
    assert "-sm layer" in cmd and "-ngl 999" in cmd and "--flash-attn off" in cmd
    sub = (ROOT / "bench/harness/scripts/cook_submit.sh").read_text()
    assert '--gres=gpu:"$GPUS" --ntasks=1' in sub and 'CDB_GPUS="$GPUS"' in sub and 'get "$MODEL" mem' in sub
    env = (ROOT / "bench/harness/slurm/cook_env.sh").read_text()
    assert '--gres=gpu:"$CDB_GPUS"' in env and "need $CDB_GPUS GPUs" in env
    assert "CDB_SERVER_VERBOSITY" in (ROOT / "bench/harness/slurm/skill_check.sbatch").read_text()
