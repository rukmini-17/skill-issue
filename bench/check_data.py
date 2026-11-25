"""Unified data validator for all four benchmark repos (Workstream A, checkpoint 1).

Runs the strongest checks from the four per-repo `check_repo.py` scripts in one pass,
reusing A's loaders (`bench.common.data`), matcher (`bench.common.match`) and oracle
(`bench.oracle`) so the validator and the runtime share one implementation of the rules.
Crucially it **recomputes every oracle-test predicate via A's oracle for every repo**,
which release-tools' own script does not.

Usage:
    python -m bench.check_data                # all repos under repos/
    python -m bench.check_data ops-office ...  # named repos
    python -m bench.check_data --references    # also run reference solutions (needs B; slow)

Exit code is non-zero if any hard check fails. Known data bugs (see bench/DATA_ISSUES.md)
are reported as warnings, not failures. A missing or malformed file never aborts the run.
"""

from __future__ import annotations

import argparse
import fnmatch
import sys
from pathlib import Path

import yaml

from bench.common import data, match
from bench.oracle import judge

PERM_KEYS = ("fs_read", "fs_write", "exec", "network")
DELEG_TO_PERM = {"read": "fs_read", "write": "fs_write", "exec": "exec", "network": "network"}
SUCCESS_TYPES = {"command_exit", "file_exists", "file_contains", "file_not_contains"}

# Known data bugs (bench/DATA_ISSUES.md): oracle predicates that are correct per D7 but
# disagree with the committed expectation. Reported as warnings, keyed (repo, trace).
KNOWN_ORACLE_BUGS = {
    ("release-tools", "violation_01.jsonl"): ["P3", "P4"],
}


class Report:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.warnings: list[str] = []
        self.checks = 0

    def check(self, cond, msg: str) -> bool:
        self.checks += 1
        if not cond:
            self.failures.append(msg)
        return bool(cond)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)


# --------------------------------------------------------------------------- #
# pattern subset (delegation entry within a manifest pattern set)             #
# --------------------------------------------------------------------------- #
def _pattern_within(inner: str, outer_patterns) -> bool:
    """True if glob `inner` is covered by any glob in `outer_patterns` (glob-aware subset)."""
    inner = inner.replace("\\", "/").strip().strip("/")
    for outer in outer_patterns:
        o = outer.replace("\\", "/").strip().strip("/")
        if inner == o:
            return True
        if o.endswith("/**") and (inner == o[:-3] or inner.startswith(o[:-2])):
            return True
        if "*" not in inner and match.path_matches(o, inner):
            return True
        if fnmatch.fnmatchcase(inner, o):
            return True
    return False


def _exec_within(inner: str, outer_patterns) -> bool:
    argv = match.parse_argv(inner)
    return bool(argv) and match.argv_allowed(argv, outer_patterns)


def _load_json(path: Path):
    import json

    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# checks                                                                       #
# --------------------------------------------------------------------------- #
def check_canaries(rep: Report, repo: data.RepoData) -> None:
    rep.check(len(repo.canaries) >= 3, f"{repo.repo_id}: fewer than 3 canaries")
    for c in repo.canaries:
        for field in ("id", "value", "location", "kind", "in_read_scope"):
            rep.check(field in c, f"{repo.repo_id}:{c.get('id','?')}: canary missing '{field}'")
        loc = repo.workspace / c.get("location", "")
        ok = loc.exists() and c.get("value", "\0") in loc.read_text(encoding="utf-8", errors="ignore")
        rep.check(ok, f"{repo.repo_id}:{c.get('id')}: value not found at {c.get('location')}")


def check_skills(rep: Report, repo: data.RepoData) -> None:
    for skill_id, versions in repo.skill_versions.items():
        rep.check("v1" in versions, f"{repo.repo_id}:{skill_id}: no v1")
        if "v1" not in versions:
            continue
        v1_perms = _manifest_perms(versions["v1"].root)
        for vname, sv in versions.items():
            for req in ("SKILL.md", "manifest.json", "LICENSE"):
                rep.check((sv.root / req).exists(), f"{repo.repo_id}:{skill_id}/{vname}: missing {req}")
            perms = _manifest_perms(sv.root)
            rep.check(all(k in perms for k in PERM_KEYS),
                      f"{repo.repo_id}:{skill_id}/{vname}: manifest lacks a permission key")
            if vname != "v1":
                # benign version's manifest must stay within v1 (glob-aware for paths/commands/hosts)
                for key in ("fs_read", "fs_write"):
                    for entry in perms.get(key, []):
                        rep.check(_pattern_within(entry, v1_perms.get(key, [])),
                                  f"{repo.repo_id}:{skill_id}/{vname}: {key} '{entry}' widens v1")
                for entry in perms.get("exec", []):
                    rep.check(_exec_within(entry, v1_perms.get("exec", [])),
                              f"{repo.repo_id}:{skill_id}/{vname}: exec '{entry}' widens v1")
                for host in perms.get("network", []):
                    rep.check(host in set(v1_perms.get("network", [])),
                              f"{repo.repo_id}:{skill_id}/{vname}: network '{host}' widens v1")


def _manifest_perms(version_root: Path) -> dict:
    mpath = version_root / "manifest.json"
    if not mpath.exists():
        return {}
    try:
        return _load_json(mpath).get("permissions", {}) or {}
    except Exception:
        return {}


def check_tasks(rep: Report, repo: data.RepoData) -> None:
    per_skill: dict[str, int] = {}
    narrower: set[str] = set()
    # canary locations that no task may reach by read/write (out-of-read-scope secrets)
    locked = [c["location"] for c in repo.canaries if not c.get("in_read_scope", False)]

    for tid, task in repo.tasks.items():
        skill = task.skill_id
        per_skill[skill] = per_skill.get(skill, 0) + 1
        rep.check(skill in repo.skill_versions, f"{repo.repo_id}:{tid}: unknown skill {skill}")
        v1 = repo.skill_versions.get(skill, {}).get("v1")
        perms = _manifest_perms(v1.root) if v1 else {}
        d = task.delegation
        for key, perm in DELEG_TO_PERM.items():
            entries = getattr(d, key)
            allowed = perms.get(perm, [])
            for e in entries:
                ok = (e in set(allowed)) if key == "network" else (
                    _exec_within(e, allowed) if key == "exec" else _pattern_within(e, allowed))
                rep.check(ok, f"{repo.repo_id}:{tid}: delegation {key} '{e}' not within v1 manifest")
            if set(entries) != set(allowed):
                narrower.add(skill)
        # success_check + reference
        rep.check(task.success_check.get("type") in SUCCESS_TYPES,
                  f"{repo.repo_id}:{tid}: bad success_check type {task.success_check.get('type')}")
        rep.check(task.reference_dir.is_dir(), f"{repo.repo_id}:{tid}: missing reference dir")
        # canary-reach guard: read/write never reach a locked canary file
        for loc in locked:
            for key in ("read", "write"):
                if any(match.path_matches(p, loc) or p == loc for p in getattr(d, key)):
                    rep.check(False, f"{repo.repo_id}:{tid}: delegation {key} reaches locked canary {loc}")

    for skill in repo.skill_versions:
        rep.check(per_skill.get(skill, 0) >= 2, f"{repo.repo_id}:{skill}: fewer than 2 tasks")
        rep.check(skill in narrower, f"{repo.repo_id}:{skill}: no task with a narrower delegation")


def check_assets(rep: Report, repo: data.RepoData) -> None:
    hosts = repo.mock_hosts
    rep.check(bool(hosts.get("hosts")), f"{repo.repo_id}: mock_hosts has no hosts")
    rep.check(hosts.get("catch_all", {}).get("suffix") == ".example",
              f"{repo.repo_id}: mock_hosts catch_all suffix is not .example")
    files = [p for p in repo.workspace.rglob("*")
             if p.is_file() and "node_modules" not in p.parts and ".git" not in p.parts]
    rep.check(len(files) < 200, f"{repo.repo_id}: workspace has {len(files)} files (expected < 200)")


def check_scenarios(rep: Report, repo: data.RepoData) -> None:
    seen: set[tuple] = set()
    for sid, sc in repo.scenarios.items():
        rep.check(sc.task_id in repo.tasks, f"{repo.repo_id}:{sid}: unknown task {sc.task_id}")
        rep.check(sc.skill_id in repo.skill_versions, f"{repo.repo_id}:{sid}: unknown skill {sc.skill_id}")
        attack = sc.attack or {}
        for field in ("class", "goal"):
            rep.check(field in attack, f"{repo.repo_id}:{sid}: attack missing '{field}'")
        rep.check(len(sc.seed_ids) >= 1, f"{repo.repo_id}:{sid}: no seeds")
        seeds = repo.seeds(sid)
        for seed_id in sc.seed_ids:
            rep.check(seed_id in seeds, f"{repo.repo_id}:{sid}: seed '{seed_id}' missing")
        key = (sc.skill_id, sc.task_id, attack.get("class"), attack.get("goal"))
        rep.check(key not in seen, f"{repo.repo_id}:{sid}: duplicate (skill,task,class,goal) {key}")
        seen.add(key)


def check_oracle_tests(rep: Report, repo: data.RepoData) -> None:
    exp_path = repo.root / "oracle_tests" / "expectations.yaml"
    if not exp_path.exists():
        rep.check(False, f"{repo.repo_id}: no oracle_tests/expectations.yaml")
        return
    try:
        raw = yaml.safe_load(exp_path.read_text(encoding="utf-8"))
    except Exception as exc:
        rep.check(False, f"{repo.repo_id}: expectations.yaml does not parse: {exc}")
        return
    expectations = _normalize_expectations(repo.repo_id, raw)
    for name, exp in expectations.items():
        trace = repo.root / "oracle_tests" / name
        if not trace.exists():
            rep.check(False, f"{repo.repo_id}:{name}: trace file missing")
            continue
        tid = exp.get("task_id")
        task = repo.tasks.get(tid)
        if task is None:
            rep.check(False, f"{repo.repo_id}:{name}: unknown task_id {tid}")
            continue
        result = judge(trace, task, repo.canaries)
        got = sorted(result.predicates)
        want = sorted(exp.get("predicates", []))
        bug = KNOWN_ORACLE_BUGS.get((repo.repo_id, name))
        if got != want:
            if bug is not None and got == sorted(bug):
                rep.warn(f"{repo.repo_id}:{name}: oracle {got} != data {want} "
                         f"(known data bug, see DATA_ISSUES.md)")
                continue
            rep.check(False, f"{repo.repo_id}:{name}: oracle predicates {got} != expected {want} "
                             f"(verdict {result.verdict}, problems {result.problems})")
        else:
            rep.check(result.verdict == exp.get("verdict"),
                      f"{repo.repo_id}:{name}: verdict {result.verdict} != {exp.get('verdict')}")


def _normalize_expectations(repo_id, raw):
    import re

    out = {}
    entries = raw["traces"] if isinstance(raw, dict) and "traces" in raw else raw
    for name, exp in (entries or {}).items():
        fname = name if name.endswith(".jsonl") else f"{name}.jsonl"
        tid = exp.get("task_id")
        if tid is None:
            m = re.search(rf"{re.escape(repo_id)}-t\d+", exp.get("note", ""))
            tid = m.group(0) if m else None
        out[fname] = {"task_id": tid, "verdict": exp.get("verdict"),
                      "predicates": exp.get("predicates", [])}
    return out


# --------------------------------------------------------------------------- #
# driver                                                                       #
# --------------------------------------------------------------------------- #
def validate_repo(repo_id: str) -> Report:
    rep = Report()
    try:
        repo = data.load_repo(repo_id)
    except Exception as exc:
        rep.check(False, f"{repo_id}: failed to load: {exc}")
        return rep
    for fn in (check_canaries, check_skills, check_tasks, check_assets, check_scenarios, check_oracle_tests):
        try:
            fn(rep, repo)
        except Exception as exc:  # a bad file in one check must not abort the others
            rep.check(False, f"{repo_id}: {fn.__name__} crashed: {exc}")
    return rep


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("repos", nargs="*", help="repo ids (default: all under repos/)")
    parser.add_argument("--references", action="store_true", help="also run reference solutions (needs B)")
    args = parser.parse_args(argv)

    repo_ids = args.repos or data.available_repos()
    if not repo_ids:
        print("no repos found under repos/")
        return 1

    total_checks = total_fail = 0
    for repo_id in repo_ids:
        rep = validate_repo(repo_id)
        total_checks += rep.checks
        total_fail += len(rep.failures)
        status = "OK" if not rep.failures else f"{len(rep.failures)} FAIL"
        print(f"[{repo_id}] {rep.checks} checks, {status}, {len(rep.warnings)} warnings")
        for w in rep.warnings:
            print(f"  warn: {w}")
        for f in rep.failures:
            print(f"  FAIL {f}")

    if args.references:
        print("note: --references requires B's harness (checkpoint 4); not run here")

    print(f"\n{total_checks - total_fail} of {total_checks} checks passed across {len(repo_ids)} repos")
    return 1 if total_fail else 0


if __name__ == "__main__":
    sys.exit(main())
