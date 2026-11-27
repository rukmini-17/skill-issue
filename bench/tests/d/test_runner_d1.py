"""D1 acceptance: grid, dry run, resume after a kill, sharding, update semantics, agent-run cache."""

import json
from pathlib import Path

import pytest

from bench.interfaces import RunSpec, StubHarness, StubOracle, StubPolicy
from bench.runner import components, data
from bench.runner.components import Components, SuccessChecker
from bench.runner.config import EpisodeKey, ExperimentConfig, expand
from bench.runner.episode import run_episode
from bench.runner.runner import parse_shard, run_experiment, select_groups

REQUIRED = ["decisions.jsonl", "trace.jsonl", "meta.json", "success.json", "oracle.json"]


def cfg(**kw):
    base = dict(name="t", kind="attack", repos=["release-tools"], max_scenarios_per_repo=2,
                policies=["none", "pin_reapprove", "deny_by_default_manifest"], attackers=["stub"])
    base.update(kw)
    return ExperimentConfig(**base)


def test_grid_size_and_determinism():
    c = cfg()
    keys = list(expand(c))
    assert len(keys) == 2 * 3                       # scenarios x policies (stub attacker has no seed dimension)
    assert keys == list(expand(c))
    assert len({k.run_id("x") for k in keys}) == len(keys)


def test_static_attacker_grid_includes_seeds():
    keys = list(expand(cfg(attackers=["static"], policies=["none"])))
    assert len(keys) == 2 * 2                       # 2 scenarios x 2 seeds
    assert all(k.seed_id for k in keys)


def test_adaptive_skips_policy_none():
    keys = list(expand(cfg(attackers=["black_box_adaptive"], policies=["none", "pin_reapprove"])))
    assert {k.policy for k in keys} == {"pin_reapprove"}


def test_unknown_config_key_rejected(tmp_path):
    p = tmp_path / "e.yaml"
    p.write_text("name: x\nbogus: 1\n")
    with pytest.raises(ValueError):
        ExperimentConfig.load(p)


def test_dry_run_end_to_end(tmp_path):
    s = run_experiment(cfg(), tmp_path, dry_run=True)
    assert s["grid_size"] == s["selected"] == 6 and s.get("error", 0) == 0
    runs = [d for d in (tmp_path / "t").iterdir() if not d.name.startswith("_")]
    assert len(runs) == 6
    for d in runs:
        for name in REQUIRED:
            assert (d / name).exists(), (d, name)
        meta = json.loads((d / "meta.json").read_text())
        assert meta["dry_run"] and meta["data_tag"] and meta["run_id"] == d.name


def test_resume_skips_complete_and_reruns_killed(tmp_path):
    run_experiment(cfg(), tmp_path, dry_run=True)
    again = run_experiment(cfg(), tmp_path, dry_run=True)
    assert again["skipped"] == 6 and "ran" not in again
    # simulate a kill: one run lost its oracle.json (written last) and left a stray file
    victim = sorted(d for d in (tmp_path / "t").iterdir() if not d.name.startswith("_"))[0]
    (victim / "oracle.json").unlink()
    (victim / "stray.tmp").write_text("x")
    third = run_experiment(cfg(), tmp_path, dry_run=True)
    assert third["skipped"] == 5 and third.get("ran", 0) + third.get("reused", 0) == 1
    assert (victim / "oracle.json").exists() and not (victim / "stray.tmp").exists()


def test_shards_partition_the_grid():
    keys = list(expand(cfg(max_scenarios_per_repo=None, repos=["all"])))
    seen = []
    for i in range(3):
        for g in select_groups(keys, (i, 3)):
            seen.extend(k.run_id("x") for k in g)
    assert sorted(seen) == sorted(k.run_id("x") for k in keys)       # disjoint and complete


def test_shard_runs_only_its_groups(tmp_path):
    a = run_experiment(cfg(), tmp_path / "a", dry_run=True, shard=(0, 2))
    b = run_experiment(cfg(), tmp_path / "b", dry_run=True, shard=(1, 2))
    assert a["selected"] + b["selected"] == 6
    ids = lambda p: {d.name for d in (p / "t").iterdir() if not d.name.startswith("_")}
    assert not ids(tmp_path / "a") & ids(tmp_path / "b")


def test_parse_shard_validation():
    assert parse_shard(None) == (0, 1) and parse_shard("2/5") == (2, 5)
    for bad in ("5/5", "-1/3", "x"):
        with pytest.raises(ValueError):
            parse_shard(bad)


def test_workers_match_serial(tmp_path):
    run_experiment(cfg(), tmp_path / "s", dry_run=True)
    run_experiment(cfg(), tmp_path / "p", dry_run=True, workers=2)
    ids = lambda p: {d.name for d in (p / "t").iterdir() if not d.name.startswith("_")}
    assert ids(tmp_path / "s") == ids(tmp_path / "p")


def test_agent_cache_shared_except_runtime_policies(tmp_path):
    s = run_experiment(cfg(max_scenarios_per_repo=1), tmp_path, dry_run=True)
    # none + pin_reapprove share one agent run; deny_by_default_manifest has run-time checks
    assert s["ran"] == 2 and s["reused"] == 1
    reused = [json.loads((d / "meta.json").read_text()) for d in (tmp_path / "t").iterdir()
              if not d.name.startswith("_")]
    assert sum(1 for m in reused if m["agent_run_reused_from"]) == 1


# ---- update semantics (D9) with a scripted policy and attacker --------------------------------

class ScriptedPolicy(StubPolicy):
    def __init__(self, decisions):
        self.name, self.seq, self.calls = "scripted", list(decisions), []

    def on_update(self, approved, new, task):
        self.calls.append((approved.version, new.version))
        return (self.seq.pop(0), "scripted")


class ScriptedSession:
    mock_override = Path("/nonexistent-override")

    def __init__(self, versions):
        self.versions, self.fb = list(versions), []

    def next_update(self):
        return self.versions.pop(0) if self.versions else None

    def feedback(self, fb):
        self.fb.append(fb)


class RecordingHarness(StubHarness):
    def __init__(self):
        self.specs = []

    def run(self, spec: RunSpec):
        self.specs.append(spec)
        return super().run(spec)


def _comps(policy, session, harness=None):
    comps = Components(harness or RecordingHarness(), StubOracle(), SuccessChecker(), True, {})
    comps.make_policy = lambda name: policy
    attacker = type("A", (), {"name": "scripted", "proposals": lambda self, sc, base: session})()
    comps.make_attacker = lambda name, seed_id=None, workdir=None, **kw: attacker
    return comps


def test_deny_is_not_installed_and_next_update_is_judged_against_last_installed(tmp_path, repo):
    sc = repo.scenarios["release-tools-s20"]
    vs = repo.skills[sc.skill_id]
    policy = ScriptedPolicy(["ask", "deny", "allow"])
    session = ScriptedSession([vs["benign_v2"], vs["benign_v3"], vs["benign_v4"]])
    h = RecordingHarness()
    key = EpisodeKey("attack", repo.repo_id, sc.scenario_id, sc.task_id, None, "scripted", "scripted", "m", "natural", 0)
    run_episode(key, _comps(policy, session, h), tmp_path, tmp_path / "w")
    assert policy.calls == [("v1", "benign_v2"), ("benign_v2", "benign_v3"), ("benign_v2", "benign_v4")]
    assert h.specs[0].installed[sc.skill_id].version == "benign_v4"        # last allowed one is installed
    assert h.specs[0].mock_override == Path("/nonexistent-override")       # passed through to the harness
    run_dir = next(d for d in tmp_path.iterdir() if not d.name.startswith("_"))
    meta = json.loads((run_dir / "meta.json").read_text())
    assert meta["asks"] == 1 and meta["denied"]["attack"] == 1
    rows = [json.loads(l) for l in (run_dir / "decisions.jsonl").read_text().splitlines()]
    assert [r["installed"] for r in rows] == [True, False, True]
    assert [f.decision for f in session.fb] == ["ask", "deny", "allow"]
    assert all(f.effect_happened is None for f in session.fb)


def test_companion_and_other_skills_installed_at_v1(tmp_path, repo):
    sc = repo.scenarios["release-tools-s20"]
    h = RecordingHarness()
    key = EpisodeKey("attack", repo.repo_id, sc.scenario_id, sc.task_id, None, "none", "stub", "m", "natural", 0)
    comps = components.build(True)
    comps.harness = h
    run_episode(key, comps, tmp_path, tmp_path / "w")
    inst = h.specs[0].installed
    assert set(inst) == set(repo.skills) and all(v.version == "v1" for v in inst.values())


def test_benign_updates_kind_runs_each_benign_version(tmp_path, repo):
    task = repo.tasks["release-tools-t01"]
    policy = ScriptedPolicy(["allow", "ask", "deny"] + ["allow"] * 5)
    h = RecordingHarness()
    comps = _comps(policy, None, h)
    key = EpisodeKey("benign_updates", repo.repo_id, None, task.task_id, None, "scripted", None, "m", "natural", 0)
    run_episode(key, comps, tmp_path, tmp_path / "w")
    assert [c[1] for c in policy.calls] == repo.benign[task.skill_id]


def test_task_completion_kind_has_no_updates(tmp_path, repo):
    task = repo.tasks["release-tools-t01"]
    policy = ScriptedPolicy([])
    key = EpisodeKey("task_completion", repo.repo_id, None, task.task_id, None, "scripted", None, "m", "natural", 0)
    run_episode(key, _comps(policy, None), tmp_path, tmp_path / "w")
    assert policy.calls == []


def test_noop_update_not_reviewed(tmp_path, repo):
    sc = repo.scenarios["release-tools-s16"]
    policy = ScriptedPolicy(["deny"])                                      # would deny if consulted
    session = ScriptedSession([repo.v1(sc.skill_id)])
    key = EpisodeKey("attack", repo.repo_id, sc.scenario_id, sc.task_id, None, "scripted", "scripted", "m", "natural", 0)
    run_episode(key, _comps(policy, session), tmp_path, tmp_path / "w")
    assert policy.calls == []


def test_harness_crash_leaves_run_incomplete_and_retryable(tmp_path):
    class Boom(StubHarness):
        def run(self, spec):
            raise RuntimeError("model server down")

    comps_ok = components.build(True)
    orig = components.build
    try:
        components.build = lambda dry, ov=None, **_kw: Components(Boom(), StubOracle(), SuccessChecker(), True, {})
        s = run_experiment(cfg(max_scenarios_per_repo=1, policies=["none"]), tmp_path, dry_run=True)
        assert s["error"] == 1
        d = next(d for d in (tmp_path / "t").iterdir() if not d.name.startswith("_"))
        assert (d / "error.json").exists() and not (d / "oracle.json").exists()
    finally:
        components.build = orig
    s2 = run_experiment(cfg(max_scenarios_per_repo=1, policies=["none"]), tmp_path, dry_run=True)
    assert s2["ran"] == 1 and (d / "oracle.json").exists()


def test_oracle_exception_becomes_unjudgeable(tmp_path):
    class BadOracle(StubOracle):
        def judge(self, *a):
            raise ValueError("boom")

    orig = components.build
    try:
        components.build = lambda dry, ov=None, **_kw: Components(StubHarness(), BadOracle(), SuccessChecker(), True, {})
        run_experiment(cfg(max_scenarios_per_repo=1, policies=["none"]), tmp_path, dry_run=True)
    finally:
        components.build = orig
    d = next(d for d in (tmp_path / "t").iterdir() if not d.name.startswith("_"))
    assert json.loads((d / "oracle.json").read_text())["verdict"] == "unjudgeable"


# ---- success result comes from the harness (B writes success.json; runner must not overwrite) ----

class SuccessHarness(StubHarness):
    """Writes success.json and meta.json["success"] like B's harness."""

    def __init__(self):
        self.calls = 0

    def run(self, spec: RunSpec):
        self.calls += 1
        trace = super().run(spec)
        result = {"success": True, "checked": True, "type": "file_contains"}
        (spec.out_dir / "success.json").write_text(json.dumps(result))
        meta_path = spec.out_dir / "meta.json"
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        meta["success"] = result
        meta_path.write_text(json.dumps(meta))
        return trace


def test_harness_success_result_kept_including_cache_reuse(tmp_path):
    h = SuccessHarness()
    orig = components.build
    try:
        components.build = lambda dry, ov=None, **_kw: Components(h, StubOracle(), SuccessChecker(), True, {})
        s = run_experiment(cfg(max_scenarios_per_repo=1, policies=["none", "pin_reapprove"]), tmp_path, dry_run=True)
    finally:
        components.build = orig
    assert h.calls == 1 and s["reused"] == 1                # second policy reuses the cached agent run
    for d in (d for d in (tmp_path / "t").iterdir() if not d.name.startswith("_")):
        assert json.loads((d / "success.json").read_text())["success"] is True
        assert json.loads((d / "meta.json").read_text())["success"]["success"] is True


def test_success_checker_falls_back_to_meta_then_unknown(tmp_path):
    (tmp_path / "meta.json").write_text(json.dumps({"success": {"success": False, "checked": True}}))
    assert SuccessChecker().check(None, tmp_path)["success"] is False
    (tmp_path / "meta.json").unlink()
    assert SuccessChecker().check(None, tmp_path)["success"] is None
