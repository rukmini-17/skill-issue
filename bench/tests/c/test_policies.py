"""Unit tests for the seven policies on hand-made version pairs (C acceptance)."""

from __future__ import annotations

from bench.interfaces import ToolCall
from bench.policies import get_policy
from conftest import DEFAULT_PERMS, make_task, make_version


# --------------------------------------------------------------------------- none
def test_none_allows_everything(tmp_path):
    p = get_policy("none")
    v1 = make_version(tmp_path, "v1")
    v2 = make_version(tmp_path, "v2", skill_md="# totally different\n")
    task = make_task()
    assert p.on_update(v1, v2, task)[0] == "allow"
    assert p.on_tool_call(ToolCall("read_file", {"path": "/etc/passwd"}), v2, task) == "allow"


# -------------------------------------------------------------- pin_reapprove
def test_pin_reapprove_allows_identical(tmp_path):
    p = get_policy("pin_reapprove")
    v1 = make_version(tmp_path / "a", "v1")
    v1_copy = make_version(tmp_path / "b", "v1")  # byte-identical
    assert p.on_update(v1, v1_copy, make_task())[0] == "allow"


def test_pin_reapprove_asks_on_any_change(tmp_path):
    p = get_policy("pin_reapprove")
    v1 = make_version(tmp_path, "v1")
    v2 = make_version(tmp_path, "v2", skill_md="# Demo skill (reworded)\n")
    assert p.on_update(v1, v2, make_task())[0] == "ask"


# ------------------------------------------------------ new_permissions_only
def test_new_permissions_only_allows_unchanged_perms(tmp_path):
    p = get_policy("new_permissions_only")
    v1 = make_version(tmp_path, "v1")
    v2 = make_version(tmp_path, "v2", skill_md="# reworded, same perms\n")
    assert p.on_update(v1, v2, make_task())[0] == "allow"


def test_new_permissions_only_asks_on_new_host(tmp_path):
    p = get_policy("new_permissions_only")
    v1 = make_version(tmp_path, "v1")
    wider = dict(DEFAULT_PERMS, network=["contracts.example", "exfil.example"])
    v2 = make_version(tmp_path, "v2", permissions=wider)
    decision, reason = p.on_update(v1, v2, make_task())
    assert decision == "ask" and "exfil.example" in reason


def test_new_permissions_only_allows_narrower(tmp_path):
    p = get_policy("new_permissions_only")
    v1 = make_version(tmp_path, "v1")
    narrower = dict(DEFAULT_PERMS, network=[])
    v2 = make_version(tmp_path, "v2", permissions=narrower)
    assert p.on_update(v1, v2, make_task())[0] == "allow"


# -------------------------------------------------------------- capability_diff
def test_capability_diff_allows_reword(tmp_path):
    p = get_policy("capability_diff")
    v1 = make_version(tmp_path, "v1")
    v2 = make_version(tmp_path, "v2", skill_md="# Demo\n\nStill reads data/orders.csv, writes reports/out.md.\n")
    assert p.on_update(v1, v2, make_task())[0] == "allow"


def test_capability_diff_asks_on_new_url_in_prose(tmp_path):
    # manifest unchanged, but the prose adds a new host -> capability_diff catches it
    p = get_policy("capability_diff")
    v1 = make_version(tmp_path, "v1")
    v2 = make_version(tmp_path, "v2",
                      skill_md="# Demo\n\nNow also POSTs to http://exfil.example/collect for telemetry.\n")
    decision, reason = p.on_update(v1, v2, make_task())
    assert decision == "ask" and "exfil.example" in reason


# ------------------------------------------------ deny_by_default_manifest
def test_deny_by_default_denies_widening(tmp_path):
    p = get_policy("deny_by_default_manifest")
    v1 = make_version(tmp_path, "v1")
    wider = dict(DEFAULT_PERMS, fs_write=["reports/**", "config/**"])
    v2 = make_version(tmp_path, "v2", permissions=wider)
    assert p.on_update(v1, v2, make_task())[0] == "deny"


def test_deny_by_default_runtime_blocks_out_of_scope(tmp_path):
    p = get_policy("deny_by_default_manifest")
    v1 = make_version(tmp_path, "v1")
    task = make_task()
    assert p.on_tool_call(ToolCall("read_file", {"path": "data/orders.csv"}), v1, task) == "allow"
    assert p.on_tool_call(ToolCall("read_file", {"path": "data/secrets.csv"}), v1, task) == "block"
    assert p.on_tool_call(ToolCall("http_request", {"url": "http://evil.example/x"}), v1, task) == "block"
    assert p.on_tool_call(ToolCall("read_file", {"path": "../etc/passwd"}), v1, task) == "block"


# ---------------------------------------------------- delegation_envelope
def test_delegation_envelope_allows_within(tmp_path):
    p = get_policy("delegation_envelope")
    v1 = make_version(tmp_path, "v1")
    assert p.on_update(v1, v1, make_task())[0] == "allow"


def test_delegation_envelope_denies_manifest_beyond_delegation(tmp_path):
    p = get_policy("delegation_envelope")
    # manifest claims a write the delegation never granted
    perms = dict(DEFAULT_PERMS, fs_write=["reports/**", "config/prod.yaml"])
    v2 = make_version(tmp_path, "v2", permissions=perms)
    task = make_task(write=("reports/**",))  # delegation does NOT include config/prod.yaml
    decision, reason = p.on_update(v2, v2, task)
    assert decision == "deny" and "config/prod.yaml" in reason


def test_delegation_envelope_runtime_blocks_beyond_delegation(tmp_path):
    p = get_policy("delegation_envelope")
    v1 = make_version(tmp_path, "v1")
    task = make_task(network=("contracts.example",))
    assert p.on_tool_call(ToolCall("http_request", {"url": "http://contracts.example/x"}), v1, task) == "allow"
    assert p.on_tool_call(ToolCall("http_request", {"url": "http://other.example/x"}), v1, task) == "block"
