"""D2 acceptance: the static attacker reproduces every seed's installs byte for byte."""

import hashlib
import json
from pathlib import Path

import pytest
import yaml

from bench.attackers.static import StaticAttacker
from bench.runner import data
from bench.runner.config import ExperimentConfig
from bench.runner.runner import run_experiment

ALL = [(r, s, seed) for r in data.repo_ids() for s in sorted(data.load_repo(r).scenarios.values(), key=lambda x: x.scenario_id)
       for seed in s.seed_ids]


def tree(root: Path) -> dict[str, str]:
    return {f.relative_to(root).as_posix(): hashlib.sha256(f.read_bytes()).hexdigest()
            for f in sorted(root.rglob("*")) if f.is_file()}


def expected_chain(repo, sc, seed_id):
    """Independent reconstruction straight from the files on disk (no code shared with the attacker)."""
    sdir = repo.root / "scenarios" / sc.scenario_id / "seeds" / seed_id
    meta = yaml.safe_load((sdir / "seed.yaml").read_text())
    cur = tree(repo.skills[sc.skill_id][meta["base_version"]].root)
    layers = [sdir / f"{d.name}/overlay" for d in sorted(sdir.glob("step_*"))] or [sdir / "overlay"]
    chain = []
    for layer in layers:
        files = [f for f in sorted(layer.rglob("*")) if f.is_file() and f.name != ".keep"] if layer.exists() else []
        cur = dict(cur)
        for f in files:
            cur[f.relative_to(layer).as_posix()] = hashlib.sha256(f.read_bytes()).hexdigest()
        chain.append(cur)
    return chain


def test_there_are_200_seeds():
    assert len(ALL) == 200


@pytest.mark.parametrize("repo_id", data.repo_ids())
def test_byte_for_byte_all_seeds(repo_id, tmp_path):
    repo = data.load_repo(repo_id)
    for sc in repo.scenarios.values():
        for seed_id in sc.seed_ids:
            session = StaticAttacker(seed_id, tmp_path / sc.scenario_id).proposals(sc, repo.v1(sc.skill_id))
            got = []
            while (v := session.next_update()) is not None:
                got.append(tree(v.root))
            want = expected_chain(repo, sc, seed_id)
            assert got == want, seed_id
            sdir = repo.root / "scenarios" / sc.scenario_id / "seeds" / seed_id
            assert (session.mock_override is not None) == (sdir / "mock_override").is_dir(), seed_id


def test_salami_steps_are_cumulative_and_named(tmp_path):
    repo = data.load_repo("release-tools")
    sc = repo.scenarios["release-tools-s20"]
    s = StaticAttacker("release-tools-s20-seed-a", tmp_path).proposals(sc, repo.v1(sc.skill_id))
    vs = []
    while (v := s.next_update()) is not None:
        vs.append(v)
    assert [v.version for v in vs] == ["s20-seed-a-step_01", "s20-seed-a-step_02", "s20-seed-a-step_03"]
    assert all(v.skill_id == sc.skill_id and v.repo_id == "release-tools" for v in vs)
    assert s.next_update() is None


def test_late_binding_keep_only_overlay_is_a_noop(tmp_path):
    repo = data.load_repo("release-tools")
    sc = repo.scenarios["release-tools-s16"]
    s = StaticAttacker("release-tools-s16-seed-a", tmp_path).proposals(sc, repo.v1(sc.skill_id))
    v = s.next_update()
    assert v.root == repo.v1(sc.skill_id).root                       # nothing changed in the skill files
    assert s.mock_override and (s.mock_override / "spec.example").is_dir()


def test_late_binding_without_overlay_dir_is_a_noop(tmp_path):
    repo = data.load_repo("orders-api")
    sc = repo.scenarios["orders-api-s05"]
    s = StaticAttacker(sc.seed_ids[0], tmp_path).proposals(sc, repo.v1(sc.skill_id))
    assert s.next_update().root == repo.skills[sc.skill_id][yaml.safe_load(
        (repo.root / "scenarios/orders-api-s05/seeds" / sc.seed_ids[0] / "seed.yaml").read_text())["base_version"]].root


def test_foreign_seed_rejected(tmp_path):
    repo = data.load_repo("release-tools")
    sc = repo.scenarios["release-tools-s20"]
    with pytest.raises(ValueError):
        StaticAttacker("release-tools-s01-seed-a", tmp_path).proposals(sc, repo.v1(sc.skill_id))


def test_repos_untouched_by_replay(tmp_path):
    repo = data.load_repo("release-tools")
    before = tree(repo.root / "scenarios")
    for sc in list(repo.scenarios.values())[:5]:
        for seed in sc.seed_ids:
            StaticAttacker(seed, tmp_path).proposals(sc, repo.v1(sc.skill_id))
    assert tree(repo.root / "scenarios") == before


def test_full_static_grid_dry_run(tmp_path):
    cfg = ExperimentConfig(name="grid", kind="attack", repos=["all"], attackers=["static"],
                           policies=["none", "pin_reapprove", "new_permissions_only", "capability_diff",
                                     "deny_by_default_manifest", "delegation_envelope"])
    s = run_experiment(cfg, tmp_path, dry_run=True, workers=4)
    assert s["grid_size"] == 200 * 6 and s.get("error", 0) == 0
    runs = [d for d in (tmp_path / "grid").iterdir() if not d.name.startswith("_")]
    assert len(runs) == 1200 and all((d / "oracle.json").exists() for d in runs)
    # every salami seed produced 3-4 attack decisions; single-step seeds produced one (or a no-op)
    rows = {}
    for d in runs:
        m = json.loads((d / "meta.json").read_text())
        n = len([l for l in (d / "decisions.jsonl").read_text().splitlines() if '"phase": "attack"' in l])
        rows.setdefault((m["scenario_id"], m["seed_id"]), set()).add(n)
    assert all(len(v) == 1 for v in rows.values())
    assert {n for v in rows.values() for n in v} == {1, 3, 4}
    assert not (tmp_path / "grid" / "_work").exists() or not any((tmp_path / "grid" / "_work").iterdir())
