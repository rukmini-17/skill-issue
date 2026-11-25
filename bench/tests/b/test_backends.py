"""B5: backends behind one OpenAI-compatible interface, against a fake server (no model).

Covers the tool-call round trip through the agent loop, Qwen3 <think> stripping,
the <tool_call> text fallback (native mode) and prompt mode (Tinker), error
classification and retries, config loading, server commands and health checks.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bench.backends import (BACKENDS, BackendError, ConfigError, LlamaCppModel, TinkerModel, VLLMModel,
                            expand, load_models, make_model, model_config)
from bench.backends import hermes
from bench.backends.__main__ import main as backends_cli
from bench.harness.model import OpenAIChatModel
from bench.harness.run import Harness
from bench.harness.skills import repo_install_set
from bench.harness.tools import TOOL_SCHEMAS
from bench.interfaces import RunSpec, StubPolicy

from b_fake_openai import Err, FakeOpenAI, Raw, tool_call, write_models
from b_helpers import REPOS, check_trace_v2, load_task

ROOT = Path(__file__).resolve().parents[3]
T05 = load_task("ops-office", "ops-office-t05")
SKILL = ".github/skills/meeting-minutes/SKILL.md"
NOTE = "notes/2026-10-06-platform-sync.md"
OUT = "reports/minutes/2026-10-06-platform-sync.md"
TEMPLATE_URL = "http://templates.example/minutes/internal-meeting.md"
MINUTES = (REPOS / "ops-office/tasks/ops-office-t05.reference/files" / OUT).read_text()
USER = [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]


def model(tmp_path, srv, backend="vllm", **extra):
    p = tmp_path / "models.yaml"
    return make_model(write_models(p, srv.base_url, backend, **extra), path=p)


def run_t05(tmp_path, srv, backend="vllm", **extra):
    p = tmp_path / "models.yaml"
    name = write_models(p, srv.base_url, backend, **extra)
    h = Harness(model_factory=lambda n, seed: make_model(n, path=p, seed=seed), isolation="env",
                work_root=tmp_path / "work")
    spec = RunSpec(run_id="r1", scenario=None, task=T05, installed=repo_install_set(REPOS / "ops-office"),
                   policy=StubPolicy(), model=name, invocation="natural", mock_override=None,
                   out_dir=tmp_path / "run", seed=1)
    trace = h.run(spec)
    return check_trace_v2(trace), json.loads((tmp_path / "run" / "meta.json").read_text())


# ------------------------------------------------------- tool-call round trip ---

def t05_native_replies():
    return [
        {"role": "assistant", "content": None, "tool_calls": [tool_call("read_file", {"path": SKILL}, "c1")]},
        {"role": "assistant", "content": "<think>read the note and template</think>", "tool_calls": [
            tool_call("read_file", {"path": NOTE}, "c2"),
            tool_call("http_request", {"method": "GET", "url": TEMPLATE_URL}, "c3")]},
        {"role": "assistant", "content": None, "tool_calls": [
            tool_call("write_file", {"path": OUT, "content": MINUTES}, "c4")]},
        {"role": "assistant", "content": "<think>all written</think>Saved the minutes to " + OUT},
    ]


def test_tool_call_round_trip_through_agent_loop(tmp_path):
    with FakeOpenAI(t05_native_replies()) as srv:
        trace, meta = run_t05(tmp_path, srv)
    assert meta["run_end"] == "done" and meta["steps"] == 4 and meta["tool_calls"] == 4
    assert meta["success"]["success"] is True and not meta["malformed_calls"]
    assert meta["model_config"]["backend"] == "vllm"
    assert meta["model_config"]["server_info"]["max_model_len"] == 32768
    assert meta["usage"] == {"prompt_tokens": 400, "completion_tokens": 80}
    assert [(l["tool"], l["status"]) for l in trace if "tool" in l and l["status"] != "requested"] == [
        ("read_file", "completed"), ("read_file", "completed"), ("http_request", "completed"),
        ("write_file", "completed")]
    reqs = srv.requests
    assert len(reqs) == 4
    first = reqs[0]
    assert first["model"] == "m" and first["temperature"] == 0.2 and first["seed"] == 1
    assert first["tool_choice"] == "auto" and {t["function"]["name"] for t in first["tools"]} == {
        "read_file", "write_file", "list_dir", "run_command", "http_request"}
    # the second request carries the assistant's call and the tool result under the same id
    m2 = reqs[1]["messages"]
    assert m2[2]["role"] == "assistant" and m2[2]["tool_calls"][0]["id"] == "c1"
    assert m2[3]["role"] == "tool" and m2[3]["tool_call_id"] == "c1" and "meeting" in m2[3]["content"].lower()
    # two calls in one turn -> two tool messages, in order
    m3 = reqs[2]["messages"]
    assert [m.get("tool_call_id") for m in m3[-2:]] == ["c2", "c3"]


def test_think_blocks_are_stripped_and_kept_out_of_history(tmp_path):
    with FakeOpenAI(t05_native_replies()) as srv:
        _, meta = run_t05(tmp_path, srv)
    assert meta["final_text"] == "Saved the minutes to " + OUT
    sent = json.dumps(srv.requests[2]["messages"])
    assert "<think>" not in sent and "read the note and template" not in sent
    msgs = json.loads((tmp_path / "run" / "messages.json").read_text())
    assert msgs[-1] == {"role": "assistant", "content": "Saved the minutes to " + OUT}


def test_think_variants(tmp_path):
    with FakeOpenAI([
        {"role": "assistant", "content": "plan only</think>Answer"},              # opening tag in template
        {"role": "assistant", "content": "Answer", "reasoning_content": "server-parsed"},
        {"role": "assistant", "content": "<think>\n\n</think>\n\nAnswer"},        # thinking off
    ]) as srv:
        m = model(tmp_path, srv, backend="llamacpp")
        t1, t2, t3 = (m.chat(USER, TOOL_SCHEMAS) for _ in range(3))
    assert (t1.content, t1.reasoning) == ("Answer", "plan only")
    assert (t2.content, t2.reasoning) == ("Answer", "server-parsed")
    assert (t3.content, t3.reasoning) == ("Answer", "")


# ---------------------------------------------- Qwen <tool_call> text fallback ---

def test_hermes_fallback_in_native_mode(tmp_path):
    with FakeOpenAI([
        {"role": "assistant", "content": '<think>x</think>Let me look.\n<tool_call>\n{"name": "list_dir", '
                                         '"arguments": {"path": "."}}\n</tool_call>\n<tool_call>{"name": '
                                         '"read_file", "arguments": {"path": "a.md"}}</tool_call>'},
        {"role": "assistant", "content": "<tool_call>{not json}</tool_call>"},
    ]) as srv:
        m = model(tmp_path, srv)
        t = m.chat(USER, TOOL_SCHEMAS)
        bad = m.chat(USER, TOOL_SCHEMAS)
    assert t.parsed_from_content and t.content == "Let me look." and t.reasoning == "x"
    assert [(c.name, json.loads(c.arguments)) for c in t.tool_calls] == [("list_dir", {"path": "."}),
                                                                        ("read_file", {"path": "a.md"})]
    assert bad.tool_calls[0].name == "" and bad.tool_calls[0].arguments == "{not json}"


def test_no_hermes_parse_without_tools_or_for_other_families(tmp_path):
    txt = '<tool_call>{"name": "list_dir", "arguments": {}}</tool_call>'
    with FakeOpenAI([{"role": "assistant", "content": txt}] * 2) as srv:
        assert model(tmp_path, srv).complete(USER) == txt           # reviewer/attacker: text kept
        assert not model(tmp_path, srv, family="llama").chat(USER, TOOL_SCHEMAS).tool_calls


def test_malformed_text_call_goes_back_to_model(tmp_path):
    replies = [{"role": "assistant", "content": "<tool_call>{oops</tool_call>"},
               {"role": "assistant", "content": "giving up"}]
    with FakeOpenAI(replies) as srv:
        _, meta = run_t05(tmp_path, srv)
    assert meta["run_end"] == "done" and meta["tool_calls"] == 0
    assert meta["malformed_calls"][0]["parsed_from_content"] is True
    tool_msg = srv.requests[1]["messages"][-1]
    assert tool_msg["role"] == "tool" and tool_msg["content"].startswith("error: malformed tool call")


def test_prompt_mode_round_trip_tinker_style(tmp_path):
    def reply(req):
        n = sum(1 for m in req["messages"] if m["role"] == "assistant")
        return [
            {"role": "assistant", "content": '<tool_call>\n{"name": "read_file", "arguments": {"path": "'
                                             + SKILL + '"}}\n</tool_call>'},
            {"role": "assistant", "content": "<think>ok</think>"
                                             f'<tool_call>{{"name": "read_file", "arguments": {{"path": "{NOTE}"}}}}'
                                             "</tool_call>"
                                             f'<tool_call>{{"name": "http_request", "arguments": {{"method": "GET", '
                                             f'"url": "{TEMPLATE_URL}"}}}}</tool_call>'},
            {"role": "assistant", "content": "<tool_call>" + json.dumps(
                {"name": "write_file", "arguments": {"path": OUT, "content": MINUTES}}) + "</tool_call>"},
            {"role": "assistant", "content": "Done."},
        ][n]
    with FakeOpenAI([reply] * 4) as srv:
        _, meta = run_t05(tmp_path, srv, backend="openai-compatible", tool_mode="prompt")
    assert meta["run_end"] == "done" and meta["tool_calls"] == 4 and meta["success"]["success"] is True
    assert meta["model_config"]["tool_mode"] == "prompt"
    for req in srv.requests:
        assert "tools" not in req and "tool_choice" not in req
        assert {m["role"] for m in req["messages"]} <= {"system", "user", "assistant"}
        assert "<tools>" in req["messages"][0]["content"] and '"name": "run_command"' in req["messages"][0]["content"]
    last = srv.requests[3]["messages"]
    # the earlier parallel calls are rendered as <tool_call> text, both results in one user turn
    assert last[-4]["role"] == "assistant" and last[-4]["content"].count("<tool_call>") == 2
    assert "<think>" not in last[-4]["content"]
    assert last[-3]["role"] == "user" and last[-3]["content"].count("<tool_response>") == 2
    assert last[-1]["role"] == "user" and last[-1]["content"].count("<tool_response>") == 1


def test_hermes_prompt_conversion_unit():
    msgs = [{"role": "system", "content": "S"}, {"role": "user", "content": "U"},
            {"role": "assistant", "content": "", "tool_calls": [tool_call("list_dir", {"path": "."}, "a"),
                                                                tool_call("read_file", "{bad", "b")]},
            {"role": "tool", "tool_call_id": "a", "content": "x.md"},
            {"role": "tool", "tool_call_id": "b", "content": "error: malformed"},
            {"role": "user", "content": "next"}]
    out = hermes.to_prompt_messages(msgs, TOOL_SCHEMAS)
    assert [m["role"] for m in out] == ["system", "user", "assistant", "user", "user"]
    assert out[0]["content"].startswith("S\n\n# Tools") and out[0]["content"].count('{"type": "function"') == 5
    assert '{"name": "list_dir", "arguments": {"path": "."}}' in out[2]["content"]
    assert '"arguments": "{bad"' in out[2]["content"]
    assert out[3]["content"] == "<tool_response>\nx.md\n</tool_response>\n<tool_response>\nerror: malformed\n</tool_response>"
    assert all(set(m) == {"role", "content"} for m in out)
    assert hermes.to_prompt_messages([{"role": "user", "content": "U"}], TOOL_SCHEMAS)[0]["role"] == "system"


# ------------------------------------------------------------- error handling ---

def test_server_error_is_retried_then_succeeds(tmp_path):
    with FakeOpenAI([Err(500, "boom"), Err(503, "busy"), {"role": "assistant", "content": "ok"}]) as srv:
        m = model(tmp_path, srv)
        assert m.chat(USER, TOOL_SCHEMAS).content == "ok"
    assert len(srv.requests) == 3 and [r["kind"] for r in m.retry_log] == ["server", "server"]


def test_persistent_server_error_raises_after_retries(tmp_path):
    with FakeOpenAI([Err(500)] * 5) as srv:
        m = model(tmp_path, srv)
        with pytest.raises(BackendError) as ei:
            m.chat(USER, TOOL_SCHEMAS)
    assert ei.value.kind == "server" and ei.value.status == 500 and len(srv.requests) == 3   # 1 + retries=2


def test_rate_limit_is_retried(tmp_path):
    with FakeOpenAI([Err(429, "slow down"), {"role": "assistant", "content": "ok"}]) as srv:
        assert model(tmp_path, srv).chat(USER).content == "ok"
    assert len(srv.requests) == 2


@pytest.mark.parametrize("status,message,kind", [
    (400, "This model's maximum context length is 32768 tokens. However, you requested 40000 tokens",
     "context_length"),
    (400, "the request exceeds the available context size", "context_length"),
    (400, "unknown field", "bad_request"),
    (401, "bad key", "auth"),
    (404, "model not found", "not_found"),
])
def test_client_errors_are_not_retried(tmp_path, status, message, kind):
    with FakeOpenAI([Err(status, message)] * 3) as srv:
        with pytest.raises(BackendError) as ei:
            model(tmp_path, srv).chat(USER, TOOL_SCHEMAS)
    assert ei.value.kind == kind and len(srv.requests) == 1


def test_bad_responses(tmp_path):
    with FakeOpenAI([Raw("not json"), Raw(json.dumps({"id": "x", "choices": []}))]) as srv:
        m = model(tmp_path, srv, retries=0)
        for _ in range(2):
            with pytest.raises(BackendError) as ei:
                m.chat(USER, TOOL_SCHEMAS)
            assert ei.value.kind == "bad_response"


def test_connection_refused(tmp_path):
    with FakeOpenAI() as srv:
        url = srv.base_url
    p = tmp_path / "m.yaml"
    m = make_model(write_models(p, url, retries=1), path=p)
    with pytest.raises(BackendError) as ei:
        m.chat(USER, TOOL_SCHEMAS)
    assert ei.value.kind == "connection" and len(m.retry_log) == 1
    assert m.ready() is False and m.wait_ready(timeout=0.2, interval=0.05) is False
    assert "error" in m.describe()["server_info"]          # metadata failure does not raise


def test_backend_error_ends_run_with_error_kind(tmp_path):
    replies = [{"role": "assistant", "content": None, "tool_calls": [tool_call("list_dir", {"path": "."})]},
               Err(400, "maximum context length exceeded")]
    with FakeOpenAI(replies) as srv:
        trace, meta = run_t05(tmp_path, srv)
    assert meta["run_end"] == "error" and meta["agent_error_kind"] == "context_length"
    assert "harness_error" not in meta and trace[-1]["event"] == "run_end" and trace[-1]["reason"] == "error"
    assert meta["success"]["success"] is False          # success check still runs


def test_truncated_turns_counted(tmp_path):
    replies = [{"role": "assistant", "content": "<think>long", "_finish": "length"},]
    with FakeOpenAI(replies) as srv:
        _, meta = run_t05(tmp_path, srv)
    assert meta["truncated_turns"] == 1 and meta["run_end"] == "done"


# --------------------------------------------------------- backends and config ---

def test_backend_specific_request_fields(tmp_path):
    with FakeOpenAI([{"role": "assistant", "content": "a"}] * 3) as srv:
        model(tmp_path, srv, backend="vllm", thinking=False, top_p=0.8).chat(USER)
        model(tmp_path, srv, backend="llamacpp").chat(USER)
        model(tmp_path, srv, backend="vllm", extra_body={"top_k": 20}).chat(USER)
    v, l, x = srv.requests
    assert v["chat_template_kwargs"] == {"enable_thinking": False} and v["top_p"] == 0.8 and "tools" not in v
    assert l["cache_prompt"] is True and "chat_template_kwargs" not in l
    assert x["top_k"] == 20 and "chat_template_kwargs" not in x


def test_overrides_for_reviewer_and_attacker(tmp_path):
    with FakeOpenAI([{"role": "assistant", "content": "<think>t</think>allow: fine"}]) as srv:
        m = model(tmp_path, srv)
        r = make_model("fake", path=tmp_path / "models.yaml", temperature=0.0)
        assert r.complete(USER) == "allow: fine"
    assert srv.requests[0]["temperature"] == 0.0 and m.temperature == 0.2


def test_describe_records_backend_quant_and_server_info(tmp_path):
    with FakeOpenAI() as srv:
        d = model(tmp_path, srv, backend="llamacpp", model_file="/nfs/opt/models/x.gguf", quantization="Q4_K_M",
                  hardware="cook-gtx").describe()
    assert d["backend"] == "llamacpp" and d["quantization"] == "Q4_K_M" and d["hardware"] == "cook-gtx"
    assert d["model_file"] == "/nfs/opt/models/x.gguf" and d["server_info"]["n_ctx"] == 32768
    assert d["decoding"]["temperature"] == 0.2 and d["tool_mode"] == "native"


def test_health_waits_for_model_load(tmp_path):
    with FakeOpenAI(health=[503, 503]) as srv:
        m = model(tmp_path, srv, backend="llamacpp")
        assert m.health_url() == f"http://127.0.0.1:{srv.port}/health"
        assert m.wait_ready(timeout=5, interval=0.01) is True
    assert srv.gets.count("/health") == 3


def test_server_commands():
    v = VLLMModel("v", "http://127.0.0.1:8123/v1", "Qwen/Qwen3-8B", server={"ctx_size": 16384})
    cmd = v.server_command()
    assert cmd[:3] == ["vllm", "serve", "Qwen/Qwen3-8B"] and cmd[cmd.index("--port") + 1] == "8123"
    assert cmd[cmd.index("--tool-call-parser") + 1] == "hermes" and "--enable-auto-tool-choice" in cmd
    assert cmd[cmd.index("--reasoning-parser") + 1] == "qwen3" and cmd[cmd.index("--max-model-len") + 1] == "16384"
    assert cmd[cmd.index("--host") + 1] == "127.0.0.1"
    l = LlamaCppModel("l", "http://127.0.0.1:8124/v1", "qwen3-8b", model_file="/m/Qwen3-8B-Q4_K_M.gguf",
                      server={"binary": "/opt/llama-server", "extra_args": ["--no-mmap"]})
    cmd = l.server_command()
    assert cmd[0] == "/opt/llama-server" and cmd[cmd.index("-m") + 1] == "/m/Qwen3-8B-Q4_K_M.gguf"
    assert "--jinja" in cmd and cmd[cmd.index("--port") + 1] == "8124" and cmd[cmd.index("-np") + 1] == "1"
    assert cmd[cmd.index("--host") + 1] == "127.0.0.1" and cmd[-1] == "--no-mmap"
    with pytest.raises(ValueError):
        LlamaCppModel("l", "http://x/v1", "m").server_command()
    with pytest.raises(NotImplementedError):
        TinkerModel("t", model="tinker://a/b").server_command()


def test_tinker_backend(tmp_path):
    p = tmp_path / "m.yaml"
    write_models(p, "https://tinker.example/v1", "tinker", model="${CDB_T}", api_key_env="TK")
    with pytest.raises(ConfigError, match="CDB_T"):
        make_model("fake", path=p, env={"TK": "k"})
    with pytest.raises(ConfigError, match="TK"):
        make_model("fake", path=p, env={"CDB_T": "tinker://x/sampler_weights/1"})
    with pytest.raises(ValueError, match="tinker://"):
        make_model("fake", path=p, env={"CDB_T": "Qwen/Qwen3-8B", "TK": "k"})
    m = make_model("fake", path=p, env={"CDB_T": "tinker://x/sampler_weights/1", "TK": "k"})
    assert m.tool_mode == "prompt" and m.ready() is True
    assert "server_info" not in m.describe()                     # no API call for metadata


def test_config_validation_and_expansion(tmp_path):
    assert expand("http://h:${P:-8080}/v1", {}) == "http://h:8080/v1"
    assert expand("http://h:${P:-8080}/v1", {"P": "9"}) == "http://h:9/v1"
    assert expand({"a": ["${X}"]}, {"X": "y"}) == {"a": ["y"]}
    p = tmp_path / "m.yaml"
    write_models(p, "http://x/v1", temprature=0.3)
    with pytest.raises(ConfigError, match="temprature"):
        make_model("fake", path=p)
    write_models(p, "http://x/v1", "nope")
    with pytest.raises(ConfigError, match="backend"):
        make_model("fake", path=p)
    with pytest.raises(ConfigError, match="known"):
        make_model("other", path=p)
    with pytest.raises(ConfigError, match="does not exist"):
        load_models(tmp_path / "missing.yaml")
    write_models(p, "http://x/v1", tool_mode="xml")
    with pytest.raises(ValueError, match="tool_mode"):
        make_model("fake", path=p)


def test_cdb_models_env_and_run_seed(tmp_path, monkeypatch):
    from bench.harness.run import default_model_factory
    p = tmp_path / "m.yaml"
    write_models(p, "http://127.0.0.1:1/v1")
    monkeypatch.setenv("CDB_MODELS", str(p))
    assert default_model_factory("fake", 2).seed == 2
    write_models(p, "http://127.0.0.1:1/v1", seed=11)
    assert default_model_factory("fake", 2).seed == 11
    assert OpenAIChatModel.__name__ == "OpenAICompatModel"


def test_shipped_models_yaml(monkeypatch):
    monkeypatch.delenv("CDB_MODELS", raising=False)
    cfg = load_models()
    env = {"CDB_TINKER_QWEN3_8B": "tinker://x/s/1", "CDB_TINKER_QWEN3_32B": "tinker://y/s/1", "TINKER_API_KEY": "k"}
    for name in cfg:
        m = make_model(name, env=env)
        assert m.temperature == 0.2 and m.family == "qwen3" and m.quantization and m.hardware
        assert type(m) is BACKENDS[cfg[name]["backend"]]
        if m.backend in ("vllm", "llamacpp"):
            assert m.server_command()
    cands = {(c["backend"], n.split("-")[1]) for n, c in cfg.items() if c.get("candidate")}
    assert cands == {(b, s) for b in ("vllm", "llamacpp") for s in ("4b", "8b", "14b", "32b")}
    parts = {n: c["partition"] for n, c in cfg.items() if c["backend"] == "llamacpp"}
    assert parts == {"qwen3-4b-llamacpp": "gtx", "qwen3-8b-llamacpp": "gtx", "qwen3-14b-llamacpp": "t4",
                     "qwen3-32b-llamacpp": "rtx"}
    assert model_config("qwen3-8b-llamacpp", env={"CDB_PORT": "20001"})["base_url"] == "http://127.0.0.1:20001/v1"
    assert make_model("qwen3-8b-llamacpp", env={"CDB_PORT": "20001"}).port == 20001
    text = (ROOT / "bench/configs/models.yaml").read_text().lower()
    assert "api_key:" not in text                                # keys only via api_key_env


def test_backends_cli(capsys, monkeypatch):
    monkeypatch.delenv("CDB_MODELS", raising=False)
    monkeypatch.setenv("CDB_PORT", "20002")
    assert backends_cli(["get", "qwen3-14b-llamacpp", "partition"]) == 0
    assert capsys.readouterr().out.strip() == "t4"
    assert backends_cli(["get", "qwen3-8b-llamacpp", "port"]) == 0
    assert capsys.readouterr().out.strip() == "20002"
    assert backends_cli(["serve-cmd", "qwen3-8b-llamacpp"]) == 0
    out = capsys.readouterr().out
    assert "--jinja" in out and "--port 20002" in out and "Qwen3-8B-Q4_K_M.gguf" in out
    assert backends_cli(["list"]) == 0 and "qwen3-32b-vllm" in capsys.readouterr().out
