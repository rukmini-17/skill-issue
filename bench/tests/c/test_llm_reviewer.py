"""Tests for llm_reviewer: response parsing and content-hash caching (C4 acceptance)."""

from __future__ import annotations

from bench.policies import get_policy
from bench.policies.llm_reviewer import parse_decision
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
