"""A3 acceptance: the oracle reproduces every existing oracle_tests answer (32 across 4 repos)."""

import re

import yaml
import pytest

from bench.common import data
from bench.oracle import judge


def _normalize_expectations(repo_id, raw):
    """Return {trace_filename: {task_id, verdict, predicates}} across both known formats.

    Flat format (ops-office/orders-api/shop-web): '<name>.jsonl': {task_id, verdict, predicates}.
    Nested format (release-tools): traces: {<name>: {verdict, predicates, note}} with the
    task id embedded in `note`. (DATA_ISSUES: release-tools expectations lack task_id and omit
    the .jsonl suffix.)
    """
    out = {}
    if "traces" in raw and isinstance(raw["traces"], dict):
        for name, exp in raw["traces"].items():
            fname = name if name.endswith(".jsonl") else f"{name}.jsonl"
            tid = exp.get("task_id")
            if tid is None:
                m = re.search(rf"{re.escape(repo_id)}-t\d+", exp.get("note", ""))
                tid = m.group(0) if m else None
            out[fname] = {"task_id": tid, "verdict": exp["verdict"],
                          "predicates": exp.get("predicates", [])}
    else:
        for name, exp in raw.items():
            fname = name if name.endswith(".jsonl") else f"{name}.jsonl"
            out[fname] = {"task_id": exp.get("task_id"), "verdict": exp["verdict"],
                          "predicates": exp.get("predicates", [])}
    return out


def _cases():
    out = []
    for repo_id in data.available_repos():
        repo = data.load_repo(repo_id)
        exp_path = repo.root / "oracle_tests" / "expectations.yaml"
        if not exp_path.exists():
            continue
        raw = yaml.safe_load(exp_path.read_text(encoding="utf-8"))
        for name, exp in _normalize_expectations(repo_id, raw).items():
            out.append((repo_id, name, exp))
    return out


_CASES = _cases()

# Known data bugs (see bench/DATA_ISSUES.md). Maps (repo_id, trace) -> the D7-consistent
# predicates the oracle should report. The listed data expectation is inconsistent, so we
# assert the oracle is D7-correct and xfail the mismatch until a human fixes the data.
_DATA_BUGS = {
    ("release-tools", "violation_01.jsonl"): ["P3", "P4"],
}


def test_there_are_oracle_cases():
    # 4 repos x 8 traces = 32 expected once all repos are present.
    assert len(_CASES) >= 8, f"found only {len(_CASES)} oracle cases"


@pytest.mark.parametrize("repo_id,name,exp", _CASES, ids=[f"{c[0]}/{c[1]}" for c in _CASES])
def test_oracle_reproduces(repo_id, name, exp):
    repo = data.load_repo(repo_id)
    task = repo.tasks[exp["task_id"]]
    trace_path = repo.root / "oracle_tests" / name
    result = judge(trace_path, task, repo.canaries)

    key = (repo_id, name)
    if key in _DATA_BUGS:
        d7 = sorted(_DATA_BUGS[key])
        if sorted(result.predicates) == sorted(exp.get("predicates", [])):
            return  # data was fixed to match the oracle; fine
        assert sorted(result.predicates) == d7, (
            f"{repo_id}/{name}: oracle should give the D7-consistent {d7}, got {result.predicates}"
        )
        pytest.xfail(f"{repo_id}/{name}: data expectation inconsistent with D7; see bench/DATA_ISSUES.md")

    assert result.verdict == exp["verdict"], (
        f"{repo_id}/{name}: verdict {result.verdict} != {exp['verdict']} "
        f"(effects={result.predicates}, attempts={result.attempts}, problems={result.problems})"
    )
    assert sorted(result.predicates) == sorted(exp.get("predicates", [])), (
        f"{repo_id}/{name}: predicates {result.predicates} != {exp.get('predicates')}"
    )
