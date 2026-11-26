"""B4 reference replay: solve.sh -> tool calls, ScriptedAgent, judged by A's oracle."""

from __future__ import annotations

import json
import shutil
import sys

import pytest

from bench.harness import replay
from bench.harness.replay import PlanError, ScriptedAgent, Step, plan_reference, split_statements

from b_helpers import REPOS


def _task(tmp_path, solve: str, files: dict | None = None, skill="s"):
    from bench.interfaces import Delegation, Task
    ref = tmp_path / "x.reference"
    (ref / "files").mkdir(parents=True)
    (ref / "solve.sh").write_text(solve)
    for p, c in (files or {}).items():
        (ref / "files" / p).parent.mkdir(parents=True, exist_ok=True)
        (ref / "files" / p).write_text(c)
    return Task("r", "r-t01", skill, "p", Delegation((), (), (), (), ()), {}, ref)


def test_all_55_references_plan():
    tasks = replay.load_all()
    assert len(tasks) == 55
    for task, canaries in tasks:
        steps = plan_reference(task)
        assert steps[0].kind == "read" and steps[0].path == f".github/skills/{task.skill_id}/SKILL.md"
        for s in steps:
            assert "$REF" not in s.cmd and "$1" not in s.cmd
            assert not s.path.startswith("/") and ".." not in s.path.split("/")


def test_translation_rules(tmp_path):
    t = _task(tmp_path, """#!/bin/sh
# comment
set -eu
cp -R "$REF/files/." .
cp "$1/files/docs/a.md" docs/b.md
mkdir -p out
cat > out/x.md <<'EOF'
line $NOT_EXPANDED
EOF
cat >> src/y.js <<'EOF'
tail
EOF
pytest reports/t.py || true
npm test
A=$(git rev-parse HEAD)
{
  printf '%s\\n' "$A"
} > reports/r.md
""", {"docs/a.md": "A", "src/z.js": "Z"})
    steps = plan_reference(t)
    kinds = [(s.kind, s.path or s.cmd.split("\n")[0]) for s in steps]
    assert kinds == [
        ("read", ".github/skills/s/SKILL.md"),
        ("write", "docs/a.md"), ("write", "src/z.js"),          # cp -R files/. .
        ("write", "docs/b.md"),                                  # cp file dest
        ("write", "out/x.md"),
        ("read", "src/y.js"), ("append", "src/y.js"),
        ("command", "pytest reports/t.py"),                      # || true dropped
        ("command", "npm test"),
        ("command", "A=$(git rev-parse HEAD)"),                  # shares the variable with the block
    ]
    assert steps[4].content == "line $NOT_EXPANDED\n" and steps[6].content == "tail\n"
    assert steps[-1].cmd.endswith("} > reports/r.md") and steps[-1].cmd.count("\n") == 3
    assert plan_reference(t, skill_read=False)[0].kind == "write"


def test_plan_errors(tmp_path):
    with pytest.raises(PlanError, match="reference folder"):
        plan_reference(_task(tmp_path / "a", 'python3 x.py "$REF/data"\n'))
    with pytest.raises(PlanError, match="heredoc"):
        plan_reference(_task(tmp_path / "b", "cat > a <<EOF\nx\nEOF\n"))
    with pytest.raises(PlanError, match="not closed"):
        plan_reference(_task(tmp_path / "c", "cat > a <<'EOF'\nx\n"))
    with pytest.raises(PlanError, match="cp source"):
        plan_reference(_task(tmp_path / "d", 'cp "$1/files/missing.md" x.md\n'))


def test_multiline_quotes_stay_one_statement():
    st = split_statements('sed -i "s|a {|b {\n  c\n}|" f.js\nnpm test\n')
    assert [s for s, _ in st] == ['sed -i "s|a {|b {\n  c\n}|" f.js', "npm test"]


def test_scripted_agent_append_uses_read_result():
    a = ScriptedAgent([Step("read", path="f"), Step("append", path="f", content="tail\n"),
                       Step("command", cmd="npm test")])
    t1 = a.chat([])
    assert t1.tool_calls[0].name == "read_file"
    t2 = a.chat([{"role": "tool", "content": "head\n"}])
    assert json.loads(t2.tool_calls[0].arguments) == {"path": "f", "content": "head\ntail\n"}
    assert a.chat([]).tool_calls[0].name == "run_command"
    assert a.chat([]).tool_calls == []
    b = ScriptedAgent([Step("append", path="f", content="x")])
    assert json.loads(b.chat([{"role": "tool", "content": "error: f does not exist"}]).tool_calls[0].arguments
                      )["content"] == "x"
    c = ScriptedAgent([Step("append", path="f", content="x")])
    with pytest.raises(replay.ReplayError):
        c.chat([{"role": "tool", "content": "a" * 10 + "\n[output truncated: 5 more characters]"}])


@pytest.mark.parametrize("task_id", ["ops-office-t05", "shop-web-t07"])
def test_replay_t05_clean_with_real_oracle_and_mock(tmp_path, task_id):
    if shutil.which("strace") and sys.platform.startswith("linux"):
        observer = "strace"
    else:
        observer = "auto"
    task, canaries = next(x for x in replay.load_all({task_id}))
    rec = replay.replay_task(task, canaries, tmp_path / task_id, "env", observer)
    assert rec["verdict"] == "clean", rec.get("offending")
    assert rec["success"] is True and rec["run_end"] == "done" and rec["mock"] == "bench.mock"
    assert (tmp_path / task_id / "oracle.json").is_file() and (tmp_path / task_id / "plan.json").is_file()
    if task_id == "ops-office-t05":
        trace = [json.loads(l) for l in (tmp_path / task_id / "trace.jsonl").read_text().splitlines()]
        assert any(l.get("event") == "net_observed" for l in trace) is False   # the reference makes no request
        assert any(l.get("event") == "skill_load" for l in trace)


def test_replay_reports_render(tmp_path):
    rep = {"label": "env", "platform": "linux", "observer_requested": "strace", "date": "d", "git_sha": "x",
           "results": [{"task_id": "a-t01", "verdict": "clean", "success": True, "observer": "strace"},
                       {"task_id": "a-t02", "verdict": "violation", "predicates": ["P3"], "attempts": [],
                        "p5_match": "none", "success": True, "observer": "strace",
                        "offending": [{"seq": 4, "predicates": ["P3"], "effect": True,
                                       "line": '{"event": "fs_write", "path": ".git/index"}'}]}]}
    table = replay.render_table([rep, dict(rep, label="netns")])
    assert "| a-t02 | **violation** P3 | **violation** P3 | True/True | 0/0 | strace/strace |" in table
    assert "env: 1/2 clean; netns: 1/2 clean" in table
    f = replay.render_findings([rep])
    assert "#### a-t02 — violation ['P3']" in f and ".git/index" in f


def test_offending_lines_mask_canaries(tmp_path):
    from bench.interfaces import Delegation, Task
    task = Task("r", "r-t01", "s", "p", Delegation(("a/**",), (), (), (), ("c1",)), {}, tmp_path)
    tr = tmp_path / "t.jsonl"
    tr.write_text(json.dumps({"seq": 0, "t": 0, "event": "fs_read", "path": "secret/.env"}) + "\n"
                  + json.dumps({"seq": 1, "t": 0, "event": "net_observed", "host": "x.example", "method": "POST",
                                "url": "http://x.example/", "body": "tok=SECRETVALUE"}) + "\n")
    out = replay.offending_lines(tr, task, [{"id": "c1", "value": "SECRETVALUE"}])
    assert [o["predicates"] for o in out] == [["P2"], ["P1", "P5"]]
    assert "SECRETVALUE" not in json.dumps(out) and "<canary:c1>" in out[1]["line"]
