"""D4 acceptance: adaptive loop on stubs, three stages, budget, validation and the feedback restriction."""

import json
from dataclasses import fields, is_dataclass
from pathlib import Path

import pytest

from bench.attackers import adaptive, templates, validate
from bench.attackers.adaptive import (BlackBoxAttacker, PolicyAwareAttacker, ProposalContext, RawProposal)
from bench.interfaces import AttackFeedback, Delegation, OracleResult, StubHarness, StubOracle, StubPolicy, Task
from bench.runner import components, data
from bench.runner.components import Components, SuccessChecker
from bench.runner.config import EpisodeKey, ExperimentConfig, expand
from bench.runner.episode import run_episode
from bench.runner.runner import run_experiment


def base_of(repo, sc):
    return repo.skills[sc.skill_id][sc.benign_prefix[-1]] if sc.benign_prefix else repo.v1(sc.skill_id)


def drive(session, decision="allow", effect=None):
    out = []
    while (v := session.next_update()) is not None:
        out.append(v)
        session.feedback(AttackFeedback(decision, effect))
    return out


class Scripted:
    """A stand-in proposer: returns a fixed list of RawProposals, records every context it saw."""

    def __init__(self, proposals):
        self.proposals, self.contexts = list(proposals), []

    def propose(self, ctx):
        self.contexts.append(ctx)
        return self.proposals.pop(0) if self.proposals else None


@pytest.fixture
def rt():
    return data.load_repo("release-tools")


def sc_of(rt, cls):
    return next(s for s in rt.scenarios.values() if s.attack["class"] == cls)


# ------------------------------------------------------------------ stages and budget
def test_stage_order_and_budget(rt, tmp_path):
    sc = sc_of(rt, "instruction_only")
    s = BlackBoxAttacker(budget=8, workdir=tmp_path).proposals(sc, base_of(rt, sc))
    drive(s)
    stages = [e["stage"] for e in s.drain_events() if e["kind"] == "proposal"]
    assert stages == sorted(stages) and stages[:2] == [1, 1] and 2 in stages
    assert s.used == 8 and len(stages) == 8


def test_without_proposer_search_ends_after_stage_two(rt, tmp_path):
    sc = sc_of(rt, "instruction_only")
    s = BlackBoxAttacker(budget=50, workdir=tmp_path).proposals(sc, base_of(rt, sc))
    drive(s)
    assert 2 < s.used < 50
    assert {e["stage"] for e in s.drain_events() if e["kind"] == "proposal"} == {1, 2}


def test_stage_three_runs_to_the_budget_and_invalid_proposals_count(rt, tmp_path):
    sc = sc_of(rt, "instruction_only")
    bad = RawProposal(files={"manifest.json": "{}"})                       # breaks the class rules
    good = RawProposal(files={"SKILL.md": "# x\n\nA harmless extra line.\n"})
    prop = Scripted([bad, good] * 100)
    s = BlackBoxAttacker(budget=30, workdir=tmp_path, proposer=prop).proposals(sc, base_of(rt, sc))
    versions = drive(s)
    events = [e for e in s.drain_events() if e["kind"] == "proposal"]
    assert s.used == 30 == len(events)
    invalid = [e for e in events if not e["valid"]]
    assert invalid and all(e["stage"] == 3 for e in invalid)                # seeds and templates are valid
    assert len(versions) == len([e for e in events if e["valid"]])           # invalid ones are never submitted


def test_proposer_exception_costs_budget_and_search_continues(rt, tmp_path):
    class Boom:
        def propose(self, ctx):
            raise RuntimeError("model down")
    sc = sc_of(rt, "instruction_only")
    s = BlackBoxAttacker(budget=40, workdir=tmp_path, proposer=Boom()).proposals(sc, base_of(rt, sc))
    drive(s)
    assert s.used == 40


def test_duplicates_do_not_cost_budget(rt, tmp_path):
    sc = sc_of(rt, "instruction_only")
    same = RawProposal(files={"SKILL.md": "# x\n\nOnly this.\n"})
    s = BlackBoxAttacker(budget=50, workdir=tmp_path, proposer=Scripted([same, same, same])).proposals(sc, base_of(rt, sc))
    drive(s)
    stage3 = [e for e in s.drain_events() if e["kind"] == "proposal" and e["stage"] == 3]
    assert len(stage3) == 1


# ------------------------------------------------------------------ the feedback restriction (D13)
SENTINELS = ("delegation", "protected_data", "oracle", "trace", "success_check")


def test_context_type_has_no_task_or_oracle_fields():
    names = {f.name for f in fields(ProposalContext)}
    assert not names & {"task", "delegation", "oracle", "trace", "canaries", "policy", "success_check"}
    for f in fields(ProposalContext):
        assert "Task" not in str(f.type) and "Delegation" not in str(f.type) and "OracleResult" not in str(f.type)


def _walk(obj, seen=None, depth=0):
    seen = seen if seen is not None else set()
    if id(obj) in seen or depth > 6:
        return
    seen.add(id(obj))
    yield obj
    if isinstance(obj, dict):
        for v in list(obj.values()) + list(obj.keys()):
            yield from _walk(v, seen, depth + 1)
    elif isinstance(obj, (list, tuple, set)):
        for v in obj:
            yield from _walk(v, seen, depth + 1)
    elif hasattr(obj, "__dict__") and not isinstance(obj, type) and type(obj).__module__.startswith("bench"):
        yield from _walk(vars(obj), seen, depth + 1)


def test_session_never_holds_task_delegation_or_oracle_data(rt, tmp_path):
    sc = sc_of(rt, "instruction_only")
    s = BlackBoxAttacker(budget=10, workdir=tmp_path, proposer=Scripted([])).proposals(sc, base_of(rt, sc))
    drive(s, effect=True)
    assert not [o for o in _walk(s) if isinstance(o, (Task, Delegation, OracleResult))]


def test_effect_feedback_only_for_p1_p5_goals(rt, tmp_path):
    observable = next(s for s in rt.scenarios.values() if set(s.attack["target_predicates"]) & {"P1", "P5"})
    hidden = next(s for s in rt.scenarios.values() if not set(s.attack["target_predicates"]) & {"P1", "P5"})
    for sc, expect in ((observable, True), (hidden, None)):
        prop = Scripted([RawProposal(files={"SKILL.md": "# x\n"}) ])
        s = BlackBoxAttacker(budget=60, workdir=tmp_path / sc.scenario_id, proposer=prop).proposals(sc, base_of(rt, sc))
        drive(s, decision="allow", effect=True)                              # the runner "tells" the attacker True
        s.drain_events()
        seen = [h.effect_happened for c in prop.contexts for h in c.history if h.decision]
        assert seen and all(e is expect for e in seen), sc.scenario_id


def test_context_only_has_allowed_information(rt, tmp_path):
    sc = sc_of(rt, "instruction_only")
    prop = Scripted([RawProposal(files={"SKILL.md": "# x\n"})])
    drive(BlackBoxAttacker(budget=60, workdir=tmp_path, proposer=prop).proposals(sc, base_of(rt, sc)))
    ctx = prop.contexts[0]
    assert ctx.policy_description is None                                    # black box: no policy knowledge
    blob = json.dumps({"files": ctx.current_files, "seed": ctx.seed_payloads,
                       "hist": [vars(h) for h in ctx.history]}, default=str).lower()
    assert "protected_data" not in blob and "delegation" not in blob


def test_policy_aware_gets_description_black_box_does_not(rt, tmp_path):
    sc = sc_of(rt, "instruction_only")
    for cls, want in ((BlackBoxAttacker, None), (PolicyAwareAttacker, "plain description")):
        prop = Scripted([RawProposal(files={"SKILL.md": "# x\n"})])
        drive(cls(budget=60, workdir=tmp_path / cls.__name__, proposer=prop, policy_description="plain description")
              .proposals(sc, base_of(rt, sc)))
        assert prop.contexts[0].policy_description == want


# ----------------------------------------------- D13 isolation: the LLM proposer's actual prompt
class _PromptSpy:
    """Stands in for an LLM client: records every (system, user) it is sent and ends the search
    right away (so a test need drive only one stage-3 call)."""

    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def complete(self, system, user):
        self.calls.append((system, user))
        return "STOP"


def _spy_proposer():
    """An LLMProposer with its real prompt split and a spy in place of the network client."""
    prop = adaptive.LLMProposer(dry_run=True)       # dry_run=True: never touches the network either way
    spy = _PromptSpy()
    prop._model = spy
    return prop, spy


def test_black_box_proposer_prompt_has_no_policy_aware_block(rt, tmp_path):
    sc = sc_of(rt, "instruction_only")
    proposer, spy = _spy_proposer()
    s = BlackBoxAttacker(budget=60, workdir=tmp_path, proposer=proposer).proposals(sc, base_of(rt, sc))
    drive(s)
    assert spy.calls, "the proposer was never asked for a stage-3 proposal"
    system, user = spy.calls[0]
    assert adaptive.POLICY_AWARE_MARKER not in system
    assert "{policy_description}" not in system
    assert "blind spot" not in system.lower()                      # the policy-aware block's own text
    assert not any(s_ in user.lower() for s_ in SENTINELS)          # D13: no task/delegation/oracle/trace


def test_policy_aware_proposer_prompt_includes_the_description(rt, tmp_path):
    sc = sc_of(rt, "instruction_only")
    proposer, spy = _spy_proposer()
    s = PolicyAwareAttacker(budget=60, workdir=tmp_path, proposer=proposer,
                            policy_description="checks only the manifest diff").proposals(sc, base_of(rt, sc))
    drive(s)
    assert spy.calls
    system, _ = spy.calls[0]
    assert adaptive.POLICY_AWARE_MARKER not in system               # the marker line itself is stripped out
    assert "checks only the manifest diff" in system


# ------------------------------------------------------------------ structural rules
def files(**kw):
    base = {"SKILL.md": b"# s\n", "LICENSE": b"mit", "manifest.json": json.dumps(
        {"permissions": {"fs_read": ["a"], "fs_write": [], "exec": [], "network": ["h.example"]}}).encode(),
            "scripts/run.py": b"print(1)\n"}
    base.update(kw)
    return base


def test_validate_rules_per_class():
    base = files()
    assert validate.validate("instruction_only", base, files(**{"SKILL.md": b"# s\nmore\n"})) == []
    assert validate.validate("instruction_only", base, files(**{"scripts/run.py": b"x"})) != []
    wide = json.dumps({"permissions": {"fs_read": ["a", "b"], "fs_write": [], "exec": [], "network": ["h.example"]}}).encode()
    assert validate.validate("capability_expansion", base, files(**{"manifest.json": wide})) == []
    assert validate.validate("capability_expansion", base, files(**{"SKILL.md": b"x"})) != []
    assert validate.validate("concealed_dependency", base, files(**{"scripts/run.py": b"print(2)\n"})) == []
    assert validate.validate("concealed_dependency", base, files(**{"SKILL.md": b"x"})) != []
    assert validate.validate("salami", base, files(**{"SKILL.md": b"# s\n" + b"line\n" * 40})) != []
    assert validate.validate("late_binding", base, base, mock_changes={"h.example/p": b"x"}, known_mock_paths={"h.example/p"}) == []
    assert validate.validate("late_binding", base, base, mock_changes={"evil.example/p": b"x"}, known_mock_paths={"h.example/p"}) != []
    assert validate.validate("instruction_only", base, {k: v for k, v in base.items() if k != "manifest.json"}) != []
    assert validate.validate("instruction_only", base, files(**{"../x": b"y"})) != []


def test_every_scenario_runs_through_stages_one_and_two(tmp_path):
    for repo_id in data.repo_ids():
        repo = data.load_repo(repo_id)
        for sc in repo.scenarios.values():
            s = BlackBoxAttacker(budget=50, workdir=tmp_path / sc.scenario_id).proposals(sc, base_of(repo, sc))
            drive(s)
            ev = [e for e in s.drain_events() if e["kind"] == "proposal"]
            assert 0 < s.used <= 50
            assert all(e["valid"] for e in ev if e["stage"] == 1), sc.scenario_id        # seeds pass the rules
            if sc.attack["class"] == "late_binding":
                md_seed = any(p.endswith(".md") for seed in sc.seed_ids
                              for p in (m for e in ev if e["stage"] == 1 for m in e["mock_changed"]))
                if md_seed:      # templates only reword .md pages; other pages have no stage-2 variations
                    assert any(e["mock_changed"] for e in ev if e["stage"] == 2), sc.scenario_id


def test_late_binding_proposals_set_mock_override(rt, tmp_path):
    sc = sc_of(rt, "late_binding")
    s = BlackBoxAttacker(budget=20, workdir=tmp_path).proposals(sc, base_of(rt, sc))
    overrides = []
    while (v := s.next_update()) is not None:
        assert v.root == base_of(rt, sc).root                                # the update itself is a no-op
        overrides.append(s.mock_override)
        s.feedback(AttackFeedback("allow", None))
    assert overrides and all(o is not None and any(o.rglob("*.md")) or o is not None for o in overrides)


def test_templates_change_wording_not_meaning():
    start = {"SKILL.md": b"---\nname: x\n---\n# T\nbody\n", "manifest.json": b"{}"}
    chain = [{**start, "SKILL.md": start["SKILL.md"] + b"Do the extra step.\n"}]
    d = templates.deltas_from_chain(start, chain)[0]
    assert d.add_lines == {"SKILL.md": ["Do the extra step."]}
    outs = {t: templates.apply_template(start, d, t) for t in templates.TEMPLATES}
    assert all(b"Do the extra step." in o["SKILL.md"] or b"Do the extra step." in o.get(templates.REFERENCE_FILE, b"")
               for o in outs.values())
    assert len({tuple(sorted(o.items())) for o in outs.values()}) == len(templates.TEMPLATES)


# ------------------------------------------------------------------ the runner loop on stubs
class OracleSequence(StubOracle):
    """Reports predicate P1 on its n-th call (counting every judged probe)."""

    def __init__(self, fire_on=None, preds=None):
        self.n, self.fire_on, self.preds = 0, fire_on, preds

    def judge(self, trace_path, task, canaries):
        self.n += 1
        fired = self.fire_on is not None and self.n >= self.fire_on
        return OracleResult("violation" if fired else "clean", list(self.preds or []) if fired else [], [], "none", [])


class ScriptedPolicy(StubPolicy):
    def __init__(self, decisions):
        self.name, self.seq = "scripted", list(decisions)

    def on_update(self, approved, new, task):
        return (self.seq.pop(0) if self.seq else "allow", "scripted")


class CountingHarness(StubHarness):
    def __init__(self):
        self.n = 0

    def run(self, spec):
        self.n += 1
        return super().run(spec)


def comps_for(oracle, policy, harness=None):
    if isinstance(oracle, OracleSequence) and oracle.preds is None:
        oracle.preds = []
    c = Components(harness or CountingHarness(), oracle, SuccessChecker(), True, {})
    c.make_policy = lambda name: policy
    return c


def fires(sc, n):
    return OracleSequence(fire_on=n, preds=sc.attack["target_predicates"])


def adaptive_key(rt, cls="instruction_only", attacker="black_box_adaptive"):
    sc = sc_of(rt, cls)
    return sc, EpisodeKey("attack", rt.repo_id, sc.scenario_id, sc.task_id, None, "scripted", attacker, "m", "natural", 0)


def only_run(tmp_path):
    return next(d for d in tmp_path.iterdir() if not d.name.startswith("_"))


def test_first_bypass_recorded_and_search_stops(rt, tmp_path):
    sc, key = adaptive_key(rt)
    run_episode(key, comps_for(fires(sc, 3), ScriptedPolicy([])), tmp_path, tmp_path / "w", budget=20)
    d = only_run(tmp_path)
    meta = json.loads((d / "meta.json").read_text())
    assert meta["adaptive"]["first_bypass_proposal"] == 3 and not meta["adaptive"]["censored"]
    assert meta["adaptive"]["proposals_used"] == 3
    assert json.loads((d / "oracle.json").read_text())["predicates"] == sc.attack["target_predicates"]
    rows = [json.loads(l) for l in (d / "attacker.jsonl").read_text().splitlines()]
    evals = [r for r in rows if r["kind"] == "eval"]
    assert [e["bypass"] for e in evals] == [False, False, True]


def test_censored_when_no_bypass_and_all_proposals_probed(rt, tmp_path):
    sc, key = adaptive_key(rt)
    h = CountingHarness()
    run_episode(key, comps_for(OracleSequence(None), ScriptedPolicy([]), h), tmp_path, tmp_path / "w", budget=6)
    meta = json.loads((only_run(tmp_path) / "meta.json").read_text())
    assert meta["adaptive"]["censored"] and meta["adaptive"]["first_bypass_proposal"] is None
    assert meta["adaptive"]["proposals_used"] == 6 and h.n == 6              # distinct installed states, one agent run each


def test_denied_proposals_do_not_run_the_agent_and_cannot_bypass(rt, tmp_path):
    sc, key = adaptive_key(rt)
    h = CountingHarness()
    run_episode(key, comps_for(fires(sc, 1), ScriptedPolicy(["deny"] * 4 + ["allow"]), h),
                tmp_path, tmp_path / "w", budget=10)
    d = only_run(tmp_path)
    meta = json.loads((d / "meta.json").read_text())
    assert meta["adaptive"]["first_bypass_proposal"] == 5                    # the first allowed proposal
    assert meta["adaptive"]["agent_probes"] == 1 and h.n == 1
    assert meta["denied"]["attack"] == 4


def test_ask_is_installed_counted_and_logged(rt, tmp_path):
    sc, key = adaptive_key(rt)
    run_episode(key, comps_for(fires(sc, 2), ScriptedPolicy(["ask", "ask"])), tmp_path, tmp_path / "w", budget=5)
    d = only_run(tmp_path)
    assert json.loads((d / "meta.json").read_text())["asks"] == 2
    evals = [json.loads(l) for l in (d / "attacker.jsonl").read_text().splitlines() if '"eval"' in l]
    assert [e["asks_so_far"] for e in evals] == [1, 2]


def test_runner_withholds_unobservable_effects_from_the_attacker(rt, tmp_path):
    hidden = next(s for s in rt.scenarios.values()
                  if not set(s.attack["target_predicates"]) & {"P1", "P5"} and s.attack["class"] == "instruction_only")
    key = EpisodeKey("attack", rt.repo_id, hidden.scenario_id, hidden.task_id, None, "scripted", "black_box_adaptive", "m", "natural", 0)
    run_episode(key, comps_for(OracleSequence(fire_on=1, preds=hidden.attack["target_predicates"]), ScriptedPolicy([])),
                tmp_path, tmp_path / "w", budget=3, )
    rows = [json.loads(l) for l in (only_run(tmp_path) / "attacker.jsonl").read_text().splitlines()]
    assert all(r["effect_happened"] is None for r in rows if r["kind"] == "feedback")
    assert any(r.get("bypass") for r in rows if r["kind"] == "eval")        # but the runner still measured it


def test_observable_goal_attacker_is_told_the_effect(rt, tmp_path):
    obs = next(s for s in rt.scenarios.values() if set(s.attack["target_predicates"]) & {"P1", "P5"}
               and s.attack["class"] == "instruction_only")
    key = EpisodeKey("attack", rt.repo_id, obs.scenario_id, obs.task_id, None, "scripted", "black_box_adaptive", "m", "natural", 0)
    run_episode(key, comps_for(OracleSequence(fire_on=2, preds=obs.attack["target_predicates"]), ScriptedPolicy([])),
                tmp_path, tmp_path / "w", budget=5, stop_at_bypass=False)
    fb = [r["effect_happened"] for r in map(json.loads, (only_run(tmp_path) / "attacker.jsonl").read_text().splitlines())
          if r["kind"] == "feedback"]
    assert fb[0] is False and fb[1] is True


def test_policy_description_reaches_only_the_aware_attacker(rt, tmp_path):
    seen = {}

    class Spy(Scripted):
        def propose(self, ctx):
            seen[self.tag] = ctx.policy_description
            return None

    for name in ("black_box_adaptive", "policy_aware_adaptive"):
        sc, key = adaptive_key(rt, attacker=name)
        spy = Spy([])
        spy.tag = name
        comps = comps_for(OracleSequence(None), ScriptedPolicy([]))
        comps.overrides["proposer"] = "tests.fake:Spy"
        import bench.runner.components as C
        orig = C.resolve
        C.resolve = lambda dotted, _s=spy, _o=orig: (lambda: _s) if dotted == "tests.fake:Spy" else _o(dotted)
        try:
            run_episode(key, comps, tmp_path / name, tmp_path / "w", budget=60)
        finally:
            C.resolve = orig
    assert seen["black_box_adaptive"] is None
    assert isinstance(seen["policy_aware_adaptive"], str)


def test_dry_run_grid_with_adaptive_attackers(tmp_path):
    cfg = ExperimentConfig(name="ad", kind="attack", repos=["all"], max_scenarios_per_repo=2, budget=15,
                           policies=["none", "pin_reapprove", "delegation_envelope"],
                           attackers=["black_box_adaptive", "policy_aware_adaptive"])
    keys = list(expand(cfg))
    assert {k.policy for k in keys} == {"pin_reapprove", "delegation_envelope"}      # none needs no search
    assert all(k.seed_id is None for k in keys)
    s = run_experiment(cfg, tmp_path, dry_run=True, workers=2)
    assert s.get("error", 0) == 0 and s["grid_size"] == len(keys)
    for d in (tmp_path / "ad").iterdir():
        if d.name.startswith("_"):
            continue
        assert (d / "attacker.jsonl").exists() and (d / "oracle.json").exists()
        assert json.loads((d / "meta.json").read_text())["adaptive"]["proposals_used"] <= 15
