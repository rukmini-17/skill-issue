"""Tests for llm_reviewer: response parsing and content-hash caching (C4 acceptance)."""

from __future__ import annotations

import bench.policies.llm_reviewer as llm_reviewer
from bench.policies import get_policy
from bench.policies.llm_reviewer import DEFAULT_MODEL, parse_decision
from conftest import make_task, make_version


def test_parse_decision_well_formed():
    assert parse_decision("decision: deny\nreason: adds a new host") == ("deny", "adds a new host")
    assert parse_decision("decision: allow\nreason: reword only")[0] == "allow"
    assert parse_decision("DECISION: Ask\nREASON: new write path")[0] == "ask"


def test_parse_decision_unparseable_fails_to_ask():
    assert parse_decision("I think it's fine")[0] == "ask"


def test_llm_reviewer_caches_by_content_hash(tmp_path):
    calls = {"n": 0}

    def fake_complete(prompt: str) -> str:
        calls["n"] += 1
        return "decision: ask\nreason: new telemetry host"

    cache = tmp_path / "cache"
    p = get_policy("llm_reviewer", complete=fake_complete, model="fake", cache_dir=cache)

    v1 = make_version(tmp_path, "v1")
    v2 = make_version(tmp_path, "v2", skill_md="# Demo\n\nPOSTs to http://exfil.example/x now.\n")
    task = make_task()

    first = p.on_update(v1, v2, task)
    assert first == ("ask", "new telemetry host")
    assert calls["n"] == 1

    # Second identical review: served from cache, model not called again.
    second = p.on_update(v1, v2, task)
    assert second == first
    assert calls["n"] == 1

    # A fresh policy instance pointed at the same cache dir still hits the cache.
    p2 = get_policy("llm_reviewer", complete=fake_complete, model="fake", cache_dir=cache)
    assert p2.on_update(v1, v2, task) == first
    assert calls["n"] == 1


def test_default_model_and_env_override(monkeypatch):
    """No explicit model -> pilot default; $CDB_REVIEWER_MODEL overrides it (C4)."""
    monkeypatch.delenv("CDB_REVIEWER_MODEL", raising=False)
    assert get_policy("llm_reviewer").model == DEFAULT_MODEL
    monkeypatch.setenv("CDB_REVIEWER_MODEL", "qwen3-32b-llamacpp")
    assert get_policy("llm_reviewer").model == "qwen3-32b-llamacpp"
    assert get_policy("llm_reviewer", model="qwen3-8b-vllm").model == "qwen3-8b-vllm"


def test_backend_wired_when_no_complete_injected(tmp_path, monkeypatch):
    """With no complete=, the reviewer builds B's backend via make_model and calls
    .complete with the prompt as one user message, temperature 0 (C4 wiring)."""
    seen = {}

    class FakeClient:
        def complete(self, messages):
            seen["messages"] = messages
            return "decision: deny\nreason: adds a new exfil host"

    def fake_make_model(name, **kw):
        seen["name"] = name
        seen["kw"] = kw
        return FakeClient()

    # make_model is imported lazily inside _backend_complete, so patch it at source.
    monkeypatch.setattr("bench.backends.make_model", fake_make_model, raising=False)

    p = get_policy("llm_reviewer", model="qwen3-32b-vllm", cache_dir=tmp_path / "c")
    v1 = make_version(tmp_path, "v1")
    v2 = make_version(tmp_path, "v2", skill_md="# Demo\n\nPOSTs to http://exfil.example/x now.\n")

    assert p.on_update(v1, v2, make_task()) == ("deny", "adds a new exfil host")
    assert seen["name"] == "qwen3-32b-vllm"
    assert seen["kw"].get("temperature") == 0.0
    assert seen["messages"] == [{"role": "user", "content": p._prompt_template.format(
        approved_manifest=(v1.root / "manifest.json").read_text(),
        new_manifest=(v2.root / "manifest.json").read_text(),
        diff=llm_reviewer._unified_diff(v1.root, v2.root),
    )}]
