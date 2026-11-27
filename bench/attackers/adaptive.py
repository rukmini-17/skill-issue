"""Adaptive attackers (D13): black_box_adaptive and policy_aware_adaptive.

The search shares one proposal budget across three stages:

  1. the handcrafted seeds, replayed exactly (bench/attackers/static.py);
  2. template-based variations of those seeds (bench/attackers/templates.py);
  3. free rewriting by a *proposer* the team supplies (an LLM wrapper conditioned on feedback).

Stage 3 is a plug-in point: ``Proposer.propose(ctx)`` gets a ``ProposalContext`` and returns file
contents. This module does not contain the proposer or its prompt text. Without a proposer the
search ends after stage 2.

Every proposal is validated against the class's structural rules (validate.py) before it is
submitted; invalid proposals count against the budget. Seeds are validated too but submitted even
if a rule flags them (the team wrote them); the flag is logged.

What the attacker may learn (D13): the policy decision after each proposal, and whether its target
effect happened *only* for goals whose effect it can observe itself: traffic reaching a host it
controls (goals with P1 or P5). For other goals ``effect_happened`` is None whatever the runner
passes. It never sees the delegation, the task, oracle output, traces or policy code. The
policy-aware variant also gets a plain-language description of the policy (the module docstring).
Nothing here imports the oracle, ``Task`` or ``Delegation``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import yaml

from bench.attackers import llm, templates, validate
from bench.attackers.static import StaticAttacker
from bench.interfaces import AttackFeedback, Scenario, SkillVersion
from bench.runner import data

OBSERVABLE_PREDICATES = {"P1", "P5"}      # traffic reaching an attacker-controlled host
HISTORY_IN_CONTEXT = 10


# ----------------------------------------------------------------------------- stage 3 plug-in
@dataclass(frozen=True)
class HistoryItem:
    n: int
    stage: int
    origin: str
    changed_paths: tuple[str, ...]
    valid: bool
    problems: tuple[str, ...]
    decision: str | None            # allow / ask / deny; None if the proposal was never submitted
    effect_happened: bool | None    # None unless the effect is observable to the attacker


@dataclass(frozen=True)
class ProposalContext:
    """Everything a stage-3 proposer may use. Deliberately has no field for task, delegation or traces."""
    attack_class: str
    style: str | None
    goal: str                                  # e.g. "leak_secret"; the team's prompt turns it into words
    budget: int
    used: int
    current_files: dict[str, str]              # the version the attacker believes is installed
    seed_payloads: dict[str, list[str]]        # lines the handcrafted seeds add, by file (its own prior work)
    mock_pages: dict[str, str]                 # late_binding: pages of allowed hosts, "host/path" -> text
    history: tuple[HistoryItem, ...]
    policy_description: str | None             # policy-aware attacker only


@dataclass
class RawProposal:
    files: dict[str, str] = field(default_factory=dict)        # changed skill files, full contents
    mock_files: dict[str, str] = field(default_factory=dict)   # "host/path" -> full page (late_binding)


class Proposer(Protocol):
    def propose(self, ctx: ProposalContext) -> RawProposal | None: ...   # None = nothing more to try


# ----------------------------------------------------------------------------- stage 3: the team's LLM proposer
PROMPT_PATH = Path(__file__).parent / "prompts" / "proposer.md"
POLICY_AWARE_MARKER = "INJECTED ONLY FOR policy_aware_adaptive"
POLICY_DESCRIPTION_TOKEN = "{policy_description}"
_FILE_BLOCK_RE = re.compile(r'<file\s+path="([^"]*)">\n?(.*?)</file>', re.S)
_MOCK_BLOCK_RE = re.compile(r'<mock_page\s+path="([^"]*)">\n?(.*?)</mock_page>', re.S)


def _split_prompt(text: str) -> tuple[str, str]:
    """Base system prompt, and the block to append for the policy-aware attacker only.

    The split point is the line containing ``POLICY_AWARE_MARKER``; that line itself is dropped
    from both halves. A file with no marker line has no policy-aware block (empty string).
    """
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if POLICY_AWARE_MARKER in line:
            return "\n".join(lines[:i]).strip(), "\n".join(lines[i + 1:]).strip()
    return text.strip(), ""


def _apply_policy_description(aware_block: str, policy_description: str) -> str:
    """Insert the actual per-run policy description into the policy-aware block.

    If the block has a literal ``{policy_description}`` token, substitute it there (lets the
    prompt place it mid-paragraph). Otherwise append it at the end, so a prompt that only writes
    general policy-family guidance (no token) still gets the concrete text D13 says the
    policy-aware attacker is entitled to, instead of it being silently dropped.
    """
    if POLICY_DESCRIPTION_TOKEN in aware_block:
        return aware_block.replace(POLICY_DESCRIPTION_TOKEN, policy_description)
    return f"{aware_block}\n\nPolicy description:\n{policy_description}"


def _parse_blocks(reply: str) -> RawProposal:
    """Parse the team's wire format: one or more ``<file path="...">...</file>`` blocks (every
    class except late_binding) and/or ``<mock_page path="host/route">...</mock_page>`` blocks
    (late_binding only). A leading newline right after the opening tag is dropped; everything else
    between the tags is kept verbatim as that file's full new content."""
    files = {p: c[1:] if c.startswith("\n") else c for p, c in _FILE_BLOCK_RE.findall(reply)}
    mock_files = {p: c[1:] if c.startswith("\n") else c for p, c in _MOCK_BLOCK_RE.findall(reply)}
    if not files and not mock_files:
        raise ValueError("reply has no <file> or <mock_page> blocks")
    return RawProposal(files=files, mock_files=mock_files)


def _render_user_prompt(ctx: ProposalContext) -> str:
    payload = {
        "attack_class": ctx.attack_class, "style": ctx.style, "goal": ctx.goal,
        "budget": ctx.budget, "used": ctx.used, "current_files": ctx.current_files,
        "seed_payloads": ctx.seed_payloads, "mock_pages": ctx.mock_pages,
        "history": [{"n": h.n, "stage": h.stage, "origin": h.origin, "changed_paths": list(h.changed_paths),
                     "valid": h.valid, "problems": list(h.problems), "decision": h.decision,
                     "effect_happened": h.effect_happened} for h in ctx.history],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


class LLMProposer:
    """Stage-3 proposer (D13): the team's attacker prompt plus bench/attackers/llm.py.

    One instance is shared by whichever attacker class wraps it (``Components.make_attacker``
    resolves ``components: {proposer: ...}`` to a single no-argument constructor call), so
    black-box vs. policy-aware is decided per call from ``ctx.policy_description`` — ``None`` for
    ``black_box_adaptive``, a string for ``policy_aware_adaptive`` (D13) — rather than at
    construction. The policy-aware block of the prompt (everything after the
    ``POLICY_AWARE_MARKER`` line) is appended only when that field is not None, with the actual
    text inserted via ``_apply_policy_description``; it is never built into, or sent in, the
    black-box system prompt.

    A reply is expected to be one or more ``<file path="...">...</file>`` / ``<mock_page
    path="...">...</mock_page>`` blocks (the team's wire format; see ``_parse_blocks``) and nothing
    else. There is no "stop" signal in that format — the search is bounded purely by budget, as
    D13 specifies. A reply with no parseable blocks raises, which the caller
    (``AdaptiveSession._from_proposer``) already treats as a failed proposal that still costs the
    budget ("a failing proposer costs budget") rather than ending the search.
    """

    def __init__(self, prompt_path: Path | str | None = None, model_cfg: dict | None = None,
                 dry_run: bool | None = None):
        self._base_prompt, self._policy_aware_block = _split_prompt(
            Path(prompt_path or PROMPT_PATH).read_text(encoding="utf-8"))
        settings = llm.ModelSettings.from_dict(model_cfg)
        # No key for this model in the environment -> NullModel, never a real network call. This is
        # the normal case for a dry run or a test; a real sweep sources the Tinker key file first.
        is_dry = dry_run if dry_run is not None else not os.environ.get(settings.api_key_env)
        self._model = llm.NullModel() if is_dry else llm.ChatClient(settings)

    def propose(self, ctx: ProposalContext) -> RawProposal | None:
        system = self._base_prompt
        if ctx.policy_description is not None and self._policy_aware_block:
            system = f"{system}\n\n{_apply_policy_description(self._policy_aware_block, ctx.policy_description)}"
        reply = self._model.complete(system, _render_user_prompt(ctx))
        return _parse_blocks(reply)


# ----------------------------------------------------------------------------- helpers
def read_files(root: Path) -> dict[str, bytes]:
    return {f.relative_to(root).as_posix(): f.read_bytes() for f in sorted(root.rglob("*")) if f.is_file()}


def _digest(files: dict[str, bytes], mock: dict[str, bytes]) -> str:
    h = hashlib.sha256()
    for tag, m in (("f", files), ("m", mock)):
        for k in sorted(m):
            h.update(f"{tag}\0{k}\0".encode())
            h.update(m[k])
    return h.hexdigest()


def mock_routes(repo: data.Repo) -> dict[str, bytes]:
    """'host/path' -> page bytes for every route of every allowed host of the repo."""
    cfg = yaml.safe_load((repo.root / "mock_hosts.yaml").read_text(encoding="utf-8")) or {}
    out: dict[str, bytes] = {}
    for h in cfg.get("hosts", []):
        if str(h.get("role", "")).startswith("allowed"):
            for path, f in (h.get("routes") or {}).items():
                p = repo.root / f
                if p.is_file():
                    out[f"{h['name']}{path}"] = p.read_bytes()
    return out


@dataclass
class _Item:
    stage: int
    origin: str
    files: dict[str, bytes]
    mock: dict[str, bytes]
    version: SkillVersion | None = None          # stage 1 comes prebuilt
    mock_dir: Path | None = None
    problems: list[str] = field(default_factory=list)


# ----------------------------------------------------------------------------- session
class AdaptiveSession:
    def __init__(self, scenario: Scenario, base: SkillVersion, *, budget: int, workdir: Path,
                 proposer: Proposer | None, policy_description: str | None):
        self.scenario, self.base = scenario, base
        repo = data.load_repo(scenario.repo_id)
        # Keep only what the attacker legitimately has: its own skill's snapshots and the mock hosts'
        # public pages. Never the Repo object itself (it holds tasks, delegations and canaries).
        self._versions = dict(repo.skills[scenario.skill_id])
        self.cls = scenario.attack["class"]
        self.goal = scenario.attack.get("goal", "")
        self.style = scenario.attack.get("style")
        self.observable = bool(set(scenario.attack.get("target_predicates") or ()) & OBSERVABLE_PREDICATES)
        self.budget, self.proposer, self.policy_description = budget, proposer, policy_description
        self.workdir = Path(workdir) / "adaptive"
        self.clean = read_files(base.root)             # what the attacker started from
        self.installed = dict(self.clean)              # what it believes is installed (allow/ask)
        self.routes = mock_routes(repo)
        self.mock_override: Path | None = None
        self.used = 0                                  # valid + invalid proposals (the budget)
        self.history: list[HistoryItem] = []
        self.events: list[dict] = []
        self._pending: tuple[_Item, int] | None = None
        self._seen: set[str] = set()
        self._published = self.clean                   # last published files (salami step base)
        self._queue = self._stage_items()
        self._stage3_done = proposer is None

    # -- the attacker protocol --------------------------------------------------------------
    def next_update(self) -> SkillVersion | None:
        while self.used < self.budget:
            item = next(self._queue, None)
            if item is None:
                item = self._from_proposer()
                if item is None:
                    return None
            problems = list(item.problems)
            if item.stage != 1:
                problems += validate.validate(
                    self.cls, self._published if self.cls == "salami" else self.clean, item.files,
                    mock_changes={k: v for k, v in item.mock.items() if self.routes.get(k) != v},
                    known_mock_paths=set(self.routes))
            digest = _digest(item.files, item.mock)
            if item.stage == 1:
                if digest in self._seen:
                    continue
            elif digest in self._seen and not problems:
                self.events.append({"kind": "duplicate", "stage": item.stage, "origin": item.origin})
                continue
            self._seen.add(digest)
            self.used += 1
            changed = sorted(validate.changed_paths(self.clean, item.files))
            blocking = problems if item.stage != 1 else []
            self.events.append({"kind": "proposal", "n": self.used, "stage": item.stage, "origin": item.origin,
                                "valid": not blocking, "problems": problems, "changed": changed,
                                "mock_changed": sorted(item.mock)})
            if blocking:                               # invalid: never submitted, still costs budget
                self.history.append(HistoryItem(self.used, item.stage, item.origin, tuple(changed), False,
                                                tuple(blocking), None, None))
                continue
            version = item.version or self._materialize(item)
            self.mock_override = item.mock_dir or self._write_mock(item)
            self._published = item.files
            self._pending = (item, self.used)
            return version
        return None

    def feedback(self, fb: AttackFeedback) -> None:
        if self._pending is None:
            return
        item, n = self._pending
        self._pending = None
        effect = fb.effect_happened if self.observable else None     # the D13 restriction
        if fb.decision in ("allow", "ask"):
            self.installed = item.files
        changed = tuple(sorted(validate.changed_paths(self.clean, item.files)))
        self.history.append(HistoryItem(n, item.stage, item.origin, changed, True, (), fb.decision, effect))
        self.events.append({"kind": "feedback", "n": n, "decision": fb.decision, "effect_happened": effect})

    # -- bookkeeping for the runner ------------------------------------------------------------
    def drain_events(self) -> list[dict]:
        out, self.events = self.events, []
        return out

    # -- stages ------------------------------------------------------------------------------
    def _seed_chain(self, seed_id: str):
        st = StaticAttacker(seed_id, self.workdir / "seeds").proposals(self.scenario, self.base)
        versions = []
        while (v := st.next_update()) is not None:
            versions.append(v)
        return st, versions

    def _stage_items(self):
        seeds = []
        for seed_id in self.scenario.seed_ids:                       # stage 1
            st, versions = self._seed_chain(seed_id)
            start = self._versions[st.seed_meta.get("base_version", "v1")]
            seed_mock = {p: b for p, b in read_files(st.mock_override).items()} if st.mock_override else {}
            seeds.append((seed_id, st, start, versions, seed_mock))
            for i, v in enumerate(versions):
                files = read_files(v.root)
                problems = validate.validate(self.cls, self.clean if self.cls != "salami" or i == 0 else read_files(versions[i - 1].root),
                                             files, mock_changes=seed_mock, known_mock_paths=set(self.routes))
                yield _Item(1, f"seed:{seed_id}:{i + 1}", files, seed_mock, version=v,
                            mock_dir=st.mock_override, problems=[f"seed check: {p}" for p in problems])
        for template in templates.TEMPLATES:                          # stage 2
            for seed_id, st, start, versions, seed_mock in seeds:
                start_files = read_files(start.root)
                chain = [read_files(v.root) for v in versions]
                deltas = templates.deltas_from_chain(start_files, chain)
                mock_deltas = templates.deltas_from_chain({k: self.routes.get(k, b"") for k in seed_mock}, [seed_mock]) if seed_mock else []
                running, mock_running = dict(self.clean), {k: self.routes.get(k, b"") for k in seed_mock}
                for i, d in enumerate(deltas):
                    running = templates.apply_template(running, d, template)
                    if mock_deltas:
                        mock_running = templates.apply_template(mock_running, mock_deltas[0], template)
                    yield _Item(2, f"template:{template}:{seed_id}:{i + 1}", running, dict(mock_running))

    def _from_proposer(self) -> _Item | None:
        if self._stage3_done:
            return None
        ctx = ProposalContext(
            attack_class=self.cls, style=self.style, goal=self.goal, budget=self.budget, used=self.used,
            current_files={k: v.decode("utf-8", "replace") for k, v in self.installed.items()},
            seed_payloads=self._seed_payloads(), mock_pages=self._relevant_pages(),
            history=tuple(self.history[-HISTORY_IN_CONTEXT:]), policy_description=self.policy_description)
        try:
            raw = self.proposer.propose(ctx)
        except Exception as e:                                          # a failing proposer costs budget
            self.events.append({"kind": "proposer_error", "error": f"{type(e).__name__}: {e}"})
            return _Item(3, "proposer", dict(self.installed), {}, problems=[f"proposer error: {e}"])
        if raw is None:
            self._stage3_done = True
            return None
        files = dict(self.installed)
        files.update({k: v.encode("utf-8") for k, v in raw.files.items()})
        mock = {k: v.encode("utf-8") for k, v in raw.mock_files.items()}
        return _Item(3, "proposer", files, mock)

    def _seed_payloads(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for seed_id in self.scenario.seed_ids:
            st, versions = self._seed_chain(seed_id)
            start = read_files(self._versions[st.seed_meta.get("base_version", "v1")].root)
            for d in templates.deltas_from_chain(start, [read_files(v.root) for v in versions]):
                for p, lines in d.add_lines.items():
                    out.setdefault(p, []).extend(lines)
        return out

    def _relevant_pages(self) -> dict[str, str]:
        if self.cls != "late_binding":
            return {}
        text = b"".join(self.clean.values())
        pages = {k: v for k, v in self.routes.items() if k.encode() in text} or self.routes
        return {k: v.decode("utf-8", "replace") for k, v in pages.items()}

    # -- materialising -----------------------------------------------------------------------
    def _materialize(self, item: _Item) -> SkillVersion:
        if self.cls == "late_binding":
            return self.base                     # the update itself is a no-op
        name = f"{self.scenario.scenario_id.rsplit('-', 1)[-1]}-ad-{self.used:03d}"
        root = self.workdir / "versions" / name
        for rel, b in item.files.items():
            dst = root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(b)
        return SkillVersion(self.base.repo_id, self.base.skill_id, name, root)

    def _write_mock(self, item: _Item) -> Path | None:
        changed = {k: v for k, v in item.mock.items() if self.routes.get(k) != v}
        if not changed:
            return None
        root = self.workdir / "mock" / f"{self.used:03d}"
        for key, b in changed.items():
            dst = root / key
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(b)
        return root


# ----------------------------------------------------------------------------- attackers
class BlackBoxAttacker:
    name = "black_box_adaptive"

    def __init__(self, budget: int = 50, workdir: Path | None = None, proposer: Proposer | None = None,
                 policy_description: str | None = None, **_ignored):
        import tempfile
        self.budget = budget
        self.workdir = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="adaptive_attacker_"))
        self.proposer = proposer
        self._policy_description = None            # a black-box attacker is never told about the policy

    def proposals(self, scenario: Scenario, base: SkillVersion) -> AdaptiveSession:
        return AdaptiveSession(scenario, base, budget=self.budget, workdir=self.workdir, proposer=self.proposer,
                               policy_description=self._policy_description)


class PolicyAwareAttacker(BlackBoxAttacker):
    name = "policy_aware_adaptive"

    def __init__(self, *args, policy_description: str | None = None, **kw):
        super().__init__(*args, **kw)
        self._policy_description = policy_description
