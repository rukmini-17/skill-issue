"""C3 — runtime policies vs oracle_tests.

Asserts the positive property (runtime policies block directly tool-actionable
violations) and pins the two characterized gaps so they stay documented:
 - P5 content leak to an ALLOWED host is not blockable by host/path/command checks;
 - `list_dir <dir>` under a `<dir>/**` grant is over-blocked by strict D2.
"""

from __future__ import annotations

import pytest

from bench.policies import get_policy
from bench.policies._dataload import REPOS, load_canaries, load_task, skill_versions
from bench.policies.runtime_report import (
    build_report,
    load_tool_calls,
    tool_predicate,
)

REPO_IDS = ("orders-api", "ops-office", "shop-web", "release-tools")


def _has_oracle_tests(repo_id: str) -> bool:
    return (REPOS / repo_id / "oracle_tests" / "expectations.yaml").exists()


@pytest.mark.parametrize("repo_id", [r for r in REPO_IDS if _has_oracle_tests(r)])
def test_runtime_blocks_directly_actionable_violations(repo_id):
    """delegation_envelope must block any P1–P4 produced by a *direct agent tool call*."""
    import yaml
    from bench.policies.runtime_report import normalize_expectations

    exp = normalize_expectations(
        yaml.safe_load((REPOS / repo_id / "oracle_tests" / "expectations.yaml").read_text())
    )
    pol = get_policy("delegation_envelope")
    for fname, e in exp.items():
        if e["verdict"] != "violation" or not e["task_id"]:
            continue
        task = load_task(repo_id, e["task_id"])
        installed = skill_versions(repo_id, task.skill_id).get("v1")
        calls = load_tool_calls(REPOS / repo_id / "oracle_tests" / fname)
        oracle_preds = set(e["predicates"])
        for c in calls:
            p = tool_predicate(c, task.delegation)
            # a tool call that itself produces a flagged P1–P4 must be blocked
            if p and p in oracle_preds:
                assert pol.on_tool_call(c, installed, task) == "block", (
                    f"{repo_id}/{fname}: {c.tool}{c.args} produces {p} but was not blocked"
                )


def test_gap_p5_to_allowed_host_not_blocked():
    """Characterization: a canary leaked to an ALLOWED host is not blocked (host/path/cmd only)."""
    repo, fname, tid = "ops-office", "violation_02.jsonl", "ops-office-t05"
    task = load_task(repo, tid)
    installed = skill_versions(repo, task.skill_id).get("v1")
    calls = load_tool_calls(REPOS / repo / "oracle_tests" / fname)
    for name in ("deny_by_default_manifest", "delegation_envelope"):
        pol = get_policy(name)
        assert all(pol.on_tool_call(c, installed, task) == "allow" for c in calls), (
            f"{name} unexpectedly blocked something in the P5-allowed-host trace"
        )


def test_report_builds_for_all_repos():
    rows = build_report([r for r in REPO_IDS if _has_oracle_tests(r)])
    assert rows and all(r["policy"] in ("deny_by_default_manifest", "delegation_envelope") for r in rows)
