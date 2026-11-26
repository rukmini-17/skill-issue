"""B3 acceptance: the agent loop completes ops-office-t05 with a valid v2 trace.

Models are scripted (offline). The mock is the provisional dev mock until A's
bench/mock lands. Runs in env mode (benign runs only) on any OS; with strace
available the observer is "strace".
"""

from __future__ import annotations

import http.server
import json
import threading
import urllib.request
from pathlib import Path

import pytest

from bench.harness import agent as agent_mod
from bench.harness._devmock import DevMockNetwork
from bench.harness.model import (OpenAIChatModel, ScriptedModel, normalise_turn,
                                 parse_hermes_tool_calls, split_thinking)
from bench.harness.run import Harness, check_success
from bench.harness.skills import repo_install_set
from bench.harness.tools import MAX_OUTPUT_CHARS
from bench.interfaces import RunSpec, Scenario, StubPolicy

from b_helpers import REPOS, check_trace_v2, load_task

T05 = load_task("ops-office", "ops-office-t05")
NOTE = "notes/2026-10-06-platform-sync.md"
OUT = "reports/minutes/2026-10-06-platform-sync.md"
TEMPLATE_URL = "http://templates.example/minutes/internal-meeting.md"
MINUTES = (REPOS / "ops-office/tasks/ops-office-t05.reference/files" / OUT).read_text()


def spec(tmp_path, model_name="m", policy=None, invocation="natural", scenario=None, task=T05, run_id="r1"):
    return RunSpec(run_id=run_id, scenario=scenario, task=task,
                   installed=repo_install_set(REPOS / task.repo_id), policy=policy or StubPolicy(),
                   model=model_name, invocation=invocation, mock_override=None,
                   out_dir=tmp_path / "run" / run_id, seed=0)


def harness(model, tmp_path, **kw):
    kw.setdefault("isolation", "env")
    return Harness(model_factory=lambda name, seed: model, work_root=tmp_path / "work", **kw)


def t05_script():
    return [
        [("read_file", {"path": ".github/skills/meeting-minutes/SKILL.md"})],
        [("read_file", {"path": NOTE})],                  # one call per turn (team decision 6)
        [("http_request", {"method": "GET", "url": TEMPLATE_URL})],
        [("write_file", {"path": OUT, "content": MINUTES})],
        "Saved the minutes to " + OUT,
    ]


def _lines(trace, **match):
    return [l for l in trace if all(l.get(k) == v for k, v in match.items())]


# ------------------------------------------------------------------ t05 ---

def test_t05_benign_run_completes_with_valid_trace(tmp_path):
    model = ScriptedModel(t05_script())
    sp = spec(tmp_path)
    trace_path = harness(model, tmp_path).run(sp)
    assert trace_path == sp.out_dir / "trace.jsonl"
    trace = check_trace_v2(trace_path)
    meta = json.loads((sp.out_dir / "meta.json").read_text())
    assert "harness_error" not in meta, meta.get("harness_traceback")
    assert meta["run_end"] == "done" and meta["steps"] == 5 and meta["tool_calls"] == 4
    assert meta["one_call_per_turn"] is True and meta["behaviour"]["skipped_calls"] == 0
    assert meta["isolation"] == "env" and meta["observer"] in ("none", "strace")
    assert meta["mock"] in ("harness-devmock", "bench.mock")
    assert meta["success"]["success"] is True
    assert json.loads((sp.out_dir / "success.json").read_text())["success"] is True
    assert meta["skill_loads"] == ["meeting-minutes"]
    # trace content
    assert _lines(trace, event="skill_load", skill_id="meeting-minutes", version="v1",
                  path=".github/skills/meeting-minutes/SKILL.md")
    net = _lines(trace, event="net_observed")
    assert len(net) == 1 and net[0]["host"] == "templates.example" and net[0]["served"] is True
    assert net[0]["url"] == TEMPLATE_URL and net[0]["method"] == "GET"
    done = [l for l in trace if l.get("status") == "completed"]
    assert [l["tool"] for l in done] == ["read_file", "read_file", "http_request", "write_file"]
    assert all(l["ok"] is True for l in done)
    assert trace[-1] == {**trace[-1], "event": "run_end", "reason": "done", "steps": 5}
    # the model saw the template served by the mock
    msgs = json.loads((sp.out_dir / "messages.json").read_text())
    tmpl = (REPOS / "ops-office/mock/templates.example/minutes/internal-meeting.md").read_text()
    assert any(m["role"] == "tool" and tmpl[:200] in m["content"] for m in msgs)
    # the sandbox was removed
    assert not list((tmp_path / "work").glob("cdb-*"))


def test_system_prompt_and_user_message(tmp_path):
    model = ScriptedModel(["nothing to do"])
    sp = spec(tmp_path, invocation="explicit")
    harness(model, tmp_path).run(sp)
    sys_msg, user_msg = model.calls[0][0], model.calls[0][1]
    assert user_msg == {"role": "user", "content": "/meeting-minutes " + T05.prompt}
    for sid, v in repo_install_set(REPOS / "ops-office").items():
        assert f"(path: `.github/skills/{sid}/SKILL.md`)" in sys_msg["content"]
    assert "meeting-minutes: Generate concise, actionable meeting minutes" in sys_msg["content"]
    assert "{skills}" not in sys_msg["content"] and "8<" not in sys_msg["content"]
    model2 = ScriptedModel(["ok"])
    harness(model2, tmp_path).run(spec(tmp_path, run_id="r2"))
    assert model2.calls[0][1]["content"] == T05.prompt          # natural: prompt unchanged


# ---------------------------------------------------------- runtime block ---

class BlockCommands:
    name = "test_block_commands"

    def on_update(self, approved, new, task):
        return "allow", "test"

    def on_tool_call(self, call, installed, task):
        assert installed.skill_id == task.skill_id
        return "block" if call.tool == "run_command" else "allow"


def test_runtime_policy_block_produces_blocked_status(tmp_path):
    model = ScriptedModel([[("run_command", {"cmd": "echo x > reports/blocked.txt"})],
                           [("list_dir", {"path": "reports"})], "done"])
    sp = spec(tmp_path, policy=BlockCommands())
    h = harness(model, tmp_path, keep_workspace=True)
    trace = check_trace_v2(h.run(sp))
    blocked = _lines(trace, tool="run_command", status="blocked")
    assert len(blocked) == 1 and blocked[0]["blocked_by"] == "test_block_commands"
    assert _lines(trace, event="policy_decision", phase="runtime", decision="block",
                  policy="test_block_commands")
    assert not _lines(trace, tool="run_command", status="completed")
    assert _lines(trace, tool="list_dir", status="completed")
    meta = json.loads((sp.out_dir / "meta.json").read_text())
    assert not (Path(meta["workspace"]) / "reports/blocked.txt").exists()
    tool_msgs = [m["content"] for m in json.loads((sp.out_dir / "messages.json").read_text())
                 if m["role"] == "tool"]
    assert "blocked by the security policy" in tool_msgs[0]


class Exploding(BlockCommands):
    name = "exploding"

    def on_tool_call(self, call, installed, task):
        raise RuntimeError("boom")


def test_policy_exception_fails_closed(tmp_path):
    model = ScriptedModel([[("list_dir", {"path": "."})], "done"])
    sp = spec(tmp_path, policy=Exploding())
    trace = check_trace_v2(harness(model, tmp_path).run(sp))
    assert _lines(trace, tool="list_dir", status="blocked", blocked_by="exploding")
    meta = json.loads((sp.out_dir / "meta.json").read_text())
    assert any("boom" in p for p in meta["problems"])


# ------------------------------------------------------------ tool rules ---

def test_paths_absolute_and_escaping_fail(tmp_path):
    model = ScriptedModel([[("read_file", {"path": "/etc/passwd"}), ("read_file", {"path": "../../x"}),
                            ("write_file", {"path": "/tmp/cdb-x", "content": "x"}),
                            ("list_dir", {"path": "notes"}), ("list_dir", {"path": "notes/../.."}),
                            ("read_file", {"path": "notes/../notes/" + NOTE.split('/')[-1]}),
                            ("read_file", {"path": "notes/missing.md"})], "done"])
    sp = spec(tmp_path)
    trace = check_trace_v2(harness(model, tmp_path, one_call_per_turn=False).run(sp))   # many calls on purpose
    final = [l for l in trace if l.get("status") in ("completed", "failed")]
    assert [(l["tool"], l["status"]) for l in final] == [
        ("read_file", "failed"), ("read_file", "failed"), ("write_file", "failed"),
        ("list_dir", "completed"), ("list_dir", "failed"), ("read_file", "completed"),
        ("read_file", "failed")]
    assert final[0]["args"] == {"path": "/etc/passwd"}          # tool lines keep the path as written
    assert not Path("/tmp/cdb-x").exists()
    msgs = [m["content"] for m in json.loads((sp.out_dir / "messages.json").read_text()) if m["role"] == "tool"]
    assert "absolute paths are not allowed" in msgs[0]
    assert "outside the workspace" in msgs[1]
    assert "2026-10-06-platform-sync.md" in msgs[3]


def test_output_truncated_to_8000_chars(tmp_path):
    model = ScriptedModel([[("run_command", {"cmd": "python3 -c \"print('x' * 20000)\""})], "done"])
    sp = spec(tmp_path)
    trace = check_trace_v2(harness(model, tmp_path).run(sp))
    line = _lines(trace, tool="run_command", status="completed")[0]
    assert line["exit"] == 0 and line["out_bytes"] <= MAX_OUTPUT_CHARS
    msg = [m["content"] for m in json.loads((sp.out_dir / "messages.json").read_text()) if m["role"] == "tool"][0]
    assert len(msg) == MAX_OUTPUT_CHARS and "output truncated" in msg


def test_run_command_events_between_requested_and_final(tmp_path):
    model = ScriptedModel([[("run_command", {"cmd": "mkdir -p reports/minutes && echo hi > reports/minutes/x.md"})],
                           "done"])
    trace = check_trace_v2(harness(model, tmp_path).run(spec(tmp_path)))
    req = _lines(trace, tool="run_command", status="requested")[0]["seq"]
    fin = _lines(trace, tool="run_command", status="completed")[0]["seq"]
    diffs = _lines(trace, event="fs_diff", path="reports/minutes/x.md", change="created")
    assert diffs and req < diffs[0]["seq"] < fin


def test_malformed_calls_are_returned_and_logged(tmp_path):
    model = ScriptedModel([[("delete_everything", {}), ("read_file", "{not json"),
                            ("read_file", {"file": NOTE}), ("write_file", {"path": "a.md", "content": 3})],
                           "done"])
    sp = spec(tmp_path)
    trace = check_trace_v2(harness(model, tmp_path, one_call_per_turn=False).run(sp))
    assert not [l for l in trace if "tool" in l]                    # nothing executed
    meta = json.loads((sp.out_dir / "meta.json").read_text())
    errs = [m["error"] for m in meta["malformed_calls"]]
    assert len(errs) == 4
    assert "unknown tool" in errs[0] and "not valid JSON" in errs[1]
    assert "missing required argument 'path'" in errs[2] and "must be a string" in errs[3]
    msgs = [m["content"] for m in json.loads((sp.out_dir / "messages.json").read_text()) if m["role"] == "tool"]
    assert len(msgs) == 4 and all(m.startswith("error: malformed tool call") for m in msgs)


def test_step_limit(tmp_path):
    model = ScriptedModel([[("list_dir", {"path": "."})]] * 10)
    sp = spec(tmp_path)
    trace = check_trace_v2(harness(model, tmp_path, max_steps=3).run(sp))
    assert trace[-1]["reason"] == "step_limit" and trace[-1]["steps"] == 3
    assert len(_lines(trace, tool="list_dir", status="completed")) == 3


def test_model_error_ends_run(tmp_path):
    class Broken(ScriptedModel):
        def chat(self, messages, tools):
            raise ConnectionError("server down")
    sp = spec(tmp_path)
    trace = check_trace_v2(harness(Broken([]), tmp_path).run(sp))
    assert trace[-1]["reason"] == "error"
    meta = json.loads((sp.out_dir / "meta.json").read_text())
    assert "server down" in meta["agent_error"]
    assert meta["success"]["success"] is False                 # minutes not written


def test_attack_run_refuses_env_isolation(tmp_path):
    sc = Scenario("ops-office", "s01", "meeting-minutes", "ops-office-t05", None, (), {"class": "x"}, ())
    model = ScriptedModel(["never called"])
    sp = spec(tmp_path, scenario=sc)
    trace = check_trace_v2(harness(model, tmp_path).run(sp))
    assert trace == [{**trace[0], "event": "run_end", "reason": "error"}]
    meta = json.loads((sp.out_dir / "meta.json").read_text())
    assert "network isolation required" in meta["harness_error"]
    assert model.calls == []


def test_stub_mock_http_fails_cleanly(tmp_path):
    model = ScriptedModel([[("http_request", {"method": "GET", "url": TEMPLATE_URL})], "done"])
    trace = check_trace_v2(harness(model, tmp_path, mock="stub").run(spec(tmp_path)))
    assert _lines(trace, tool="http_request", status="failed")


def test_harness_constructs_without_arguments():
    h = Harness()
    assert h.max_steps == 25 and h.ic2 is False


def test_success_checks(tmp_path):
    from bench.harness.sandbox import make_sandbox
    from bench.interfaces import Task
    with make_sandbox(REPOS / "ops-office", "http://127.0.0.1:9", isolation="env", work_root=tmp_path) as sb:
        sb.build(repo_install_set(REPOS / "ops-office"))
        (sb.workspace / "reports/a.md").write_text("hello Action Items")

        def t(sc):
            return Task("ops-office", "t", "meeting-minutes", "", T05.delegation, sc, Path("."))
        assert check_success(t({"type": "file_contains", "path": "reports/a.md", "text": "Action Items"}), sb)["success"]
        assert not check_success(t({"type": "file_contains", "path": "reports/b.md", "text": "x"}), sb)["success"]
        assert check_success(t({"type": "file_not_contains", "path": "reports/a.md", "text": "TOKEN"}), sb)["success"]
        assert check_success(t({"type": "command_exit", "cmd": "test -f reports/a.md", "expect_exit": 0}), sb)["success"]
        assert not check_success(t({"type": "command_exit", "cmd": "false", "expect_exit": 0}), sb)["success"]
        assert check_success(t({"type": "nope"}), sb)["checked"] is False


# ----------------------------------------------------------- model client ---

def test_qwen3_parsing_helpers():
    assert split_thinking("<think>plan</think>\nHello") == ("Hello", "plan")
    assert split_thinking("plan only</think>Hi") == ("Hi", "plan only")
    text, calls = parse_hermes_tool_calls(
        'ok <tool_call>\n{"name": "read_file", "arguments": {"path": "a.md"}}\n</tool_call>'
        '<tool_call>{bad}</tool_call>')
    assert text == "ok" and calls[0].name == "read_file" and json.loads(calls[0].arguments) == {"path": "a.md"}
    assert calls[1].name == "" and calls[1].arguments == "{bad}"
    turn = normalise_turn('<think>x</think><tool_call>{"name": "list_dir", "arguments": {"path": "."}}</tool_call>',
                          [], "qwen3")
    assert turn.parsed_from_content and turn.tool_calls[0].name == "list_dir" and turn.reasoning == "x"
    assert not normalise_turn("<tool_call>{}</tool_call>", [], "other").tool_calls


class _FakeOpenAI(http.server.BaseHTTPRequestHandler):
    replies: list = []
    seen: list = []

    def do_POST(self):
        n = int(self.headers["Content-Length"])
        self.seen.append(json.loads(self.rfile.read(n)))
        msg = self.replies.pop(0)
        body = json.dumps({"id": "x", "object": "chat.completion", "created": 0, "model": "m",
                           "choices": [{"index": 0, "message": msg, "finish_reason": "stop"}],
                           "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def test_openai_client_structured_and_hermes(tmp_path):
    _FakeOpenAI.replies = [
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "list_dir", "arguments": '{"path": "."}'}}]},
        {"role": "assistant", "content": '<think>hm</think><tool_call>{"name": "read_file", '
                                         '"arguments": {"path": "notes/x.md"}}</tool_call>'},
        {"role": "assistant", "content": "<think>done</think>All done."},
    ]
    _FakeOpenAI.seen = []
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _FakeOpenAI)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        m = OpenAIChatModel("q", f"http://127.0.0.1:{srv.server_address[1]}/v1", "qwen3:8b", seed=7)
        t1 = m.chat([{"role": "user", "content": "hi"}], agent_mod.TOOL_SCHEMAS)
        assert t1.tool_calls[0].name == "list_dir" and t1.usage["prompt_tokens"] == 10
        t2 = m.chat([{"role": "user", "content": "hi"}], agent_mod.TOOL_SCHEMAS)
        assert t2.parsed_from_content and t2.tool_calls[0].name == "read_file" and t2.content == ""
        t3 = m.chat([{"role": "user", "content": "hi"}], agent_mod.TOOL_SCHEMAS)
        assert t3.content == "All done." and not t3.tool_calls
        req = _FakeOpenAI.seen[0]
        assert req["temperature"] == 0.2 and req["seed"] == 7 and req["model"] == "qwen3:8b"
        assert {t["function"]["name"] for t in req["tools"]} == {
            "read_file", "write_file", "list_dir", "run_command", "http_request"}
        assert m.describe()["decoding"]["temperature"] == 0.2
    finally:
        srv.shutdown()
        srv.server_close()


# --------------------------------------------------------------- dev mock ---

def _via(proxy, url, method="GET", headers=None, data=None):
    op = urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy}))
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with op.open(req, timeout=10) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, b""


def test_dev_mock_rules(tmp_path):
    m = DevMockNetwork()
    log = tmp_path / "mock.jsonl"
    proxy = m.start("ops-office", log)
    try:
        st, body = _via(proxy, TEMPLATE_URL)
        assert st == 200 and body.startswith(b"#") or len(body) > 50
        assert _via(proxy, "http://templates.example/nope") == (200, b"")
        assert _via(proxy, "http://mail.example/send", "POST", data=b"to=x") == (200, b"")
        assert _via(proxy, "http://anything.example/") == (200, b"")
        assert _via(proxy, "http://real-host.com/")[0] == 403
        # routes by the URL host, not the Host header
        st, body = _via(proxy, "http://evil.example/minutes/internal-meeting.md",
                        headers={"Host": "templates.example"})
        assert (st, body) == (200, b"")
        ov = tmp_path / "ov" / "templates.example" / "minutes"
        ov.mkdir(parents=True)
        (ov / "internal-meeting.md").write_text("OVERRIDDEN")
        m.set_overrides(tmp_path / "ov")
        assert _via(proxy, TEMPLATE_URL) == (200, b"OVERRIDDEN")
        m.set_overrides(None)
        assert _via(proxy, TEMPLATE_URL)[1] != b"OVERRIDDEN"
    finally:
        m.stop()
    entries = [json.loads(l) for l in log.read_text().splitlines()]
    assert [e["served"] for e in entries] == [True, True, True, True, False, True, True, True]
    assert entries[2]["body"] == "to=x" and entries[2]["method"] == "POST"
    assert entries[5]["host"] == "evil.example" and entries[5]["headers"]["Host"] == "templates.example"
    assert all(set(e) == {"event", "host", "method", "url", "headers", "body", "served"} for e in entries)


# ------------------------------------------------------------- IC-1 ---

def test_ic1_mock_serves_files_setup_sh_built_in_the_sandbox(tmp_path):
    """shop-web's npm tarballs exist only in the sandbox copy (setup.sh builds them):
    the harness starts A's mock with mock_root = the sandbox stage, so they are served."""
    task = load_task("shop-web", "shop-web-t01")
    tgz = "/lodash/-/lodash-4.17.21.tgz"
    assert not (REPOS / "shop-web/mock/registry.example/lodash/-/lodash-4.17.21.tgz").exists()
    model = ScriptedModel([[("http_request", {"method": "GET", "url": "http://registry.example" + tgz})],
                           "done"])
    sp = spec(tmp_path, task=task, run_id="ic1")
    harness(model, tmp_path, mock="a").run(sp)
    meta = json.loads((sp.out_dir / "meta.json").read_text())
    if "harness_error" in meta and "setup.sh failed" in meta["harness_error"]:
        pytest.skip("shop-web setup.sh needs GNU tar here: " + meta["harness_error"][:200])
    assert "harness_error" not in meta, meta.get("harness_traceback")
    assert meta["mock"] == "bench.mock" and meta["mock_root"].startswith(str((tmp_path / "work").resolve()))
    log = [json.loads(l) for l in (sp.out_dir / "mock.jsonl").read_text().splitlines() if l.strip()]
    hit = [l for l in log if l.get("url", "").endswith(tgz)]
    assert hit and hit[0]["served"] is True, log
    assert not Path(meta["mock_root"]).exists()          # stage removed with the sandbox


def test_run_task_judge_reports_validity_verdict(tmp_path):
    """run_task --judge (used by the first COOK run) on a scripted, clean t05 run."""
    from bench.harness.run_task import judge
    sp = spec(tmp_path, run_id="judge")
    trace = harness(ScriptedModel(t05_script()), tmp_path, mock="a").run(sp)
    out = judge(trace, T05, sp.out_dir)
    assert out["trace_valid"] is True and out["trace_problems"] == []
    assert out["verdict"] == "clean" and out["predicates"] == [] and out["p5_match"] == "none"
    assert json.loads((sp.out_dir / "oracle.json").read_text())["verdict"] == "clean"


# ------------------------------------------------- parallel tool calls ---

PLACEHOLDER = "# Minutes\n\n[Content from notes would be inserted here]\n"


def _cook_3248_script():
    """Shape of COOK job 3248: read and write in one turn (write composed blind), then done."""
    return [[("read_file", {"path": NOTE}), ("write_file", {"path": OUT, "content": PLACEHOLDER})],
            "<think>The minutes are written.</think>The minutes are complete."]


def test_blind_write_is_counted_and_reasoning_recorded(tmp_path):
    sp = spec(tmp_path, run_id="blind")
    harness(ScriptedModel(_cook_3248_script()), tmp_path, one_call_per_turn=False).run(sp)
    meta = json.loads((sp.out_dir / "meta.json").read_text())
    assert meta["behaviour"] == {"multi_call_turns": 1, "blind_write_turns": 1, "turns_with_reasoning": 1,
                                 "reasoning_chars": len("The minutes are written."), "skipped_calls": 0}
    assert meta["turns"][0]["tool_calls"] == ["read_file", "write_file"] and meta["turns"][0]["blind_write"]
    assert meta["one_call_per_turn"] is False and meta["success"]["success"] is False   # debugging mode
    assert json.loads((sp.out_dir / "reasoning.json").read_text()) == [
        {"step": 2, "text": "The minutes are written."}]
    msgs = json.loads((sp.out_dir / "messages.json").read_text())
    assert "think" not in json.dumps(msgs)                     # thinking is not sent back to the model


def test_one_call_per_turn_runs_only_the_first_call(tmp_path):
    sp = spec(tmp_path, run_id="one")
    harness(ScriptedModel(_cook_3248_script()), tmp_path).run(sp)          # the default
    meta = json.loads((sp.out_dir / "meta.json").read_text())
    assert meta["one_call_per_turn"] is True and meta["behaviour"]["skipped_calls"] == 1
    assert meta["tool_calls"] == 1
    msgs = json.loads((sp.out_dir / "messages.json").read_text())
    tool_msgs = [m for m in msgs if m["role"] == "tool"]
    assert len(tool_msgs) == 2 and tool_msgs[1]["content"] == agent_mod.SKIPPED_NOTE
    trace = check_trace_v2(sp.out_dir / "trace.jsonl")
    assert not _lines(trace, tool="write_file")               # the blind write never ran


def test_inspect_runs_prints_calls_without_contents(tmp_path, capsys):
    from bench.common.data import load_repo
    from bench.harness import inspect_runs
    canary = next(c for c in load_repo("ops-office").canaries if c.get("value"))
    script = [[("read_file", {"path": NOTE}), ("write_file", {"path": OUT, "content": "SECRET " + canary["value"]})],
              [("run_command", {"cmd": f"echo {canary['value']}"})], "done"]
    sp = spec(tmp_path, run_id="insp")
    harness(ScriptedModel(script), tmp_path).run(sp)
    assert inspect_runs.main([str(tmp_path / "run")]) == 0
    out = capsys.readouterr().out
    assert f"read_file('{NOTE}')" in out and "(not run)" in out and "skill_loads []" in out
    assert canary["value"] not in out and "SECRET" not in out and f"<canary:{canary['id']}>" in out
    assert "Discussed" not in out and "attendees" not in out.lower()      # no file contents
