"""Reference replay (workstream B, B4; checkpoint 4 with A's A4).

For each task, its reference solution (``tasks/<id>.reference/solve.sh`` and
``files/``) is turned into the tool calls an agent with the five harness tools
would make, and replayed by ``ScriptedAgent`` through the real harness: the same
agent loop, ``ToolExecutor``, sandbox, strace monitor, A's mock (``bench.mock``)
and trace writer as a model run. The trace is then judged by A's
``bench.oracle.Oracle`` against the task's delegation (A's ``bench.common.data``
loader). Every reference should come out ``clean``; anything else is a finding
for A (``implicit_effects.yaml``, ``command_aliases.yaml`` or ``match.py``).

How ``solve.sh`` becomes tool calls (``plan_reference``):

* the run starts with ``read_file .github/skills/<skill_id>/SKILL.md`` (an agent
  reads the skill first; D8). ``--no-skill-read`` turns this off;
* ``cp [-R] "$REF/files/<p>" <dest>`` (also ``$1``) -> one ``write_file`` per file;
* ``cat > <path> <<'EOF'`` (quoted heredoc) -> ``write_file``;
  ``cat >> <path> <<'EOF'`` -> ``read_file`` then ``write_file`` with the text appended;
* ``set -e...`` and ``mkdir -p <dir>`` are dropped (``write_file`` creates parents);
* a trailing ``|| true`` is dropped (it only exists for ``set -e``; the replay
  does not stop on a failed command, it records it);
* every other statement is one ``run_command`` with the statement's text as written.
  Statements from the first shell-variable assignment to the end of that run of
  commands are one ``run_command`` (they share shell variables), as an agent would
  have to send them.

The translation is the replay's, not A's; ``plan.json`` in each run directory
lists every step with the ``solve.sh`` statement it came from.

    python -m bench.harness.replay --isolation env               # all 55
    python -m bench.harness.replay --isolation netns --tasks ops-office-t05,shop-web
    python -m bench.harness.replay --findings bench/harness/REPLAY_FINDINGS.md \\
        --reports runs/replay/env/report.json runs/replay/netns/report.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from bench.harness.model import AssistantTurn, ToolCallRequest
from bench.harness.run import REPO_ROOT, REPOS, Harness
from bench.harness.skills import repo_install_set
from bench.harness.tools import MAX_OUTPUT_CHARS
from bench.interfaces import RunSpec, StubPolicy, Task

REPLAY_ROOT = REPO_ROOT / "runs" / "replay"

_REF = r"(?:\$REF|\$\{REF\}|\$1|\$\{1\})"
_CP = re.compile(r'^cp\s+(?:-[A-Za-z]+\s+)*"?' + _REF + r'/files(?:/([^"\s]*))?"?\s+"?([^"\s]+)"?\s*$')
_HEREDOC = re.compile(r"^cat\s*(>>|>)\s*(\S+)\s*<<(-?)\s*(['\"])(\w+)\4\s*$")
_HEREDOC_ANY = re.compile(r"<<-?\s*['\"]?\w+")
_MKDIR = re.compile(r"^mkdir\s+-p\s+\S+\s*$")
_SET = re.compile(r"^set\s+[-+][a-z]+(\s+[-+][a-z]+)*\s*$")
_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_OR_TRUE = re.compile(r"\s*\|\|\s*true\s*$")


class PlanError(ValueError):
    pass


@dataclass
class Step:
    kind: str                      # read | write | append | command
    path: str = ""
    content: str = ""
    cmd: str = ""
    source: str = ""               # solve.sh statement(s) it came from
    note: str = ""


# --------------------------------------------------------------- planning ---

def _scan(line: str, quote: str | None) -> str | None:
    """Quote state after ``line`` (None = outside quotes). Backslash escapes outside single quotes."""
    i = 0
    while i < len(line):
        c = line[i]
        if quote == "'":
            if c == "'":
                quote = None
        elif c == "\\":
            i += 1
        elif quote == '"':
            if c == '"':
                quote = None
        elif c in "'\"":
            quote = c
        elif c == "#" and (i == 0 or line[i - 1] in " \t;"):
            break
        i += 1
    return quote


def split_statements(text: str) -> list[tuple[str, str | None]]:
    """``solve.sh`` -> [(statement, heredoc_body_or_None)]; comments and blank lines removed."""
    lines = text.splitlines()
    out: list[tuple[str, str | None]] = []
    buf: list[str] = []
    quote: str | None = None
    depth = 0
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        s = line.strip()
        if not buf and (not s or s.startswith("#")):
            continue
        if not buf:
            m = _HEREDOC.match(s)
            if m:
                delim, body = m.group(5), []
                while i < len(lines) and (lines[i].strip() if m.group(3) else lines[i]) != delim:
                    body.append(lines[i].lstrip("\t") if m.group(3) else lines[i])
                    i += 1
                if i >= len(lines):
                    raise PlanError(f"heredoc {delim!r} not closed")
                i += 1
                out.append((s, "".join(b + "\n" for b in body)))
                continue
            if _HEREDOC_ANY.search(s):
                raise PlanError(f"unsupported heredoc: {s!r}")
        buf.append(line)
        before = quote
        quote = _scan(line, quote)
        if before is None and quote is None:           # braces only on lines wholly outside quotes
            if s == "{" or s.endswith("{"):
                depth += 1
            if s.startswith("}"):
                depth -= 1
        if quote is None and depth == 0 and not s.endswith(("\\", "|", "&&", "||")):
            out.append(("\n".join(buf).strip(), None))
            buf = []
    if buf:
        raise PlanError(f"unterminated statement: {buf[0][:80]!r}")
    return out


def _ref_files(ref: Path, sub: str, dest: str) -> list[Step]:
    files = ref / "files"
    src = (files / sub) if sub not in ("", ".") else files
    src = Path(os.path.normpath(src))
    if not src.is_relative_to(files):
        raise PlanError(f"cp source outside files/: {sub}")
    steps = []
    if src.is_dir():
        for p in sorted(x for x in src.rglob("*") if x.is_file()):
            rel = os.path.normpath(os.path.join(dest, p.relative_to(src).as_posix()))
            steps.append(Step("write", path=rel, content=p.read_text(encoding="utf-8")))
    elif src.is_file():
        target = os.path.join(dest, src.name) if dest in (".", "./") or dest.endswith("/") else dest
        steps.append(Step("write", path=os.path.normpath(target), content=src.read_text(encoding="utf-8")))
    else:
        raise PlanError(f"cp source missing: files/{sub}")
    return steps


def plan_reference(task: Task, ref: Path | None = None, skill_read: bool = True) -> list[Step]:
    ref = Path(ref or task.reference_dir)
    solve = ref / "solve.sh"
    steps: list[Step] = []
    if skill_read:
        steps.append(Step("read", path=f".github/skills/{task.skill_id}/SKILL.md", source="(agent reads the skill)"))
    if not solve.is_file():
        if (ref / "files").is_dir():
            return steps + [dict_note(s, "files/ (no solve.sh)") for s in _ref_files(ref, "", ".")]
        raise PlanError(f"{ref}: no solve.sh and no files/")
    pending: list[str] = []               # consecutive shell statements
    stateful = False

    def flush():
        nonlocal pending, stateful
        if not pending:
            return
        if stateful:
            first = next(k for k, p in enumerate(pending) if _ASSIGN.match(p))
            for p in pending[:first]:
                steps.append(Step("command", cmd=p, source=p))
            joined = "\n".join(pending[first:])
            steps.append(Step("command", cmd=joined, source=joined, note="one command: shares shell variables"))
        else:
            for p in pending:
                steps.append(Step("command", cmd=p, source=p))
        pending, stateful = [], False

    for stmt, body in split_statements(solve.read_text(encoding="utf-8")):
        if body is not None:
            flush()
            m = _HEREDOC.match(stmt)
            op, path = m.group(1), m.group(2).strip("'\"")
            if op == ">":
                steps.append(Step("write", path=os.path.normpath(path), content=body, source=stmt))
            else:
                steps.append(Step("read", path=os.path.normpath(path), source=stmt, note="read before append"))
                steps.append(Step("append", path=os.path.normpath(path), content=body, source=stmt))
            continue
        if _SET.match(stmt) or _MKDIR.match(stmt):
            continue
        m = _CP.match(stmt)
        if m:
            flush()
            steps += [dict_note(s, stmt) for s in _ref_files(ref, m.group(1) or "", m.group(2))]
            continue
        cmd = _OR_TRUE.sub("", stmt)
        if re.search(_REF, cmd):
            raise PlanError(f"statement uses the reference folder: {stmt[:120]!r}")
        if _ASSIGN.match(cmd):
            stateful = True
        pending.append(cmd)
    flush()
    return steps


def dict_note(step: Step, source: str) -> Step:
    step.source = source
    return step


# ----------------------------------------------------------- the "model" ---

class ReplayError(RuntimeError):
    pass


class ScriptedAgent:
    """A ``ChatModel`` that replays a plan: one tool call per turn, then a final answer.

    ``append`` steps take the file text from the preceding ``read_file`` result
    (the conversation), so the replay never reads the workspace behind the
    harness's back.
    """

    def __init__(self, steps: list[Step], name: str = "replay"):
        self.name = name
        self.family = ""
        self.steps = list(steps)
        self.i = 0

    def describe(self) -> dict:
        return {"name": self.name, "backend": "replay", "model": "reference", "model_file": None,
                "quantization": None, "family": None, "decoding": {}, "steps": len(self.steps)}

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> AssistantTurn:
        if self.i >= len(self.steps):
            return AssistantTurn("Reference solution replayed.", [])
        s = self.steps[self.i]
        self.i += 1
        cid = f"replay_{self.i}"
        if s.kind == "read":
            call = ("read_file", {"path": s.path})
        elif s.kind == "write":
            call = ("write_file", {"path": s.path, "content": s.content})
        elif s.kind == "append":
            prev = messages[-1] if messages and messages[-1].get("role") == "tool" else {}
            text = prev.get("content") or ""
            if text.startswith("error: ") and "does not exist" in text:
                text = ""
            elif text.startswith("error: ") or "[output truncated:" in text or len(text) >= MAX_OUTPUT_CHARS:
                raise ReplayError(f"cannot append to {s.path}: read result unusable ({text[:80]!r})")
            call = ("write_file", {"path": s.path, "content": text + s.content})
        elif s.kind == "command":
            call = ("run_command", {"cmd": s.cmd})
        else:
            raise ReplayError(f"unknown step {s.kind}")
        return AssistantTurn("", [ToolCallRequest(cid, call[0], json.dumps(call[1]))])


# ---------------------------------------------------------------- judging ---

def _mask(text: str, canaries: list[dict]) -> str:
    for c in canaries:
        v = c.get("value")
        if v and v in text:
            text = text.replace(v, f"<canary:{c.get('id')}>")
    return text


def offending_lines(trace_path: Path, task: Task, canaries: list[dict]) -> list[dict]:
    """Per-line predicates, for the findings only (the verdict comes from Oracle.judge).

    Uses the oracle's own per-line function so the attribution matches its verdict.
    """
    from bench.common import match
    from bench.oracle import oracle as o
    effects = match.load_implicit_effects()
    vals = o._canary_values(task, canaries)
    enc = {v: o._encoded_forms(v) for v in vals}
    out = []
    for raw in Path(trace_path).read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        line = json.loads(raw)
        preds, _ = o._line_predicates(line, task, vals, enc, None, effects)
        if not preds:
            continue
        effect = "event" in line or o._status(line) == "completed"
        out.append({"seq": line.get("seq"), "predicates": sorted(preds), "effect": effect,
                    "line": _mask(json.dumps(line, ensure_ascii=False), canaries)})
    return out


# ------------------------------------------------------------------- run ---

def replay_task(task: Task, canaries: list[dict], out_dir: Path, isolation: str, observer: str,
                skill_read: bool = True, keep_workspace: bool = False) -> dict:
    from bench.oracle import Oracle
    out_dir.mkdir(parents=True, exist_ok=True)
    rec: dict = {"task_id": task.task_id, "repo_id": task.repo_id, "skill_id": task.skill_id}
    try:
        steps = plan_reference(task, skill_read=skill_read)
    except PlanError as e:
        rec.update(verdict="plan_error", error=str(e))
        return rec
    (out_dir / "plan.json").write_text(json.dumps([asdict(s) for s in steps], indent=1, ensure_ascii=False))
    agent = ScriptedAgent(steps)
    h = Harness(model_factory=lambda name, seed: agent, mock="a", isolation=isolation, observer=observer,
                keep_workspace=keep_workspace, max_steps=len(steps) + 2)
    spec = RunSpec(run_id=f"replay-{task.task_id}", scenario=None, task=task,
                   installed=repo_install_set(REPOS / task.repo_id), policy=StubPolicy(), model="reference",
                   invocation="natural", mock_override=None, out_dir=out_dir, seed=0)
    t0 = time.monotonic()
    trace = h.run(spec)
    meta = json.loads((out_dir / "meta.json").read_text())
    res = Oracle().judge(trace, task, canaries)
    (out_dir / "oracle.json").write_text(json.dumps(asdict(res), indent=1))
    lines = [json.loads(l) for l in trace.read_text().splitlines() if l.strip()]
    failed = [l for l in lines if l.get("tool") and l.get("status") != "requested"
              and (l.get("status") == "failed" or (l.get("exit") not in (None, 0)))]
    rec.update(verdict=res.verdict, predicates=res.predicates, attempts=res.attempts, p5_match=res.p5_match,
               problems=res.problems, success=(meta.get("success") or {}).get("success"),
               run_end=meta.get("run_end"), observer=meta.get("observer"), isolation=meta.get("isolation"),
               mock=meta.get("mock"), steps=len(steps), harness_error=meta.get("harness_error"),
               agent_error=meta.get("agent_error"), seconds=round(time.monotonic() - t0, 1),
               failed_calls=[{"seq": l["seq"], "tool": l["tool"],
                              "args": _mask(json.dumps(l["args"])[:300], canaries), "exit": l.get("exit")}
                             for l in failed],
               events=len([l for l in lines if "event" in l]))
    if res.verdict != "clean":
        rec["offending"] = offending_lines(trace, task, canaries)
    return rec


def load_all(only: set[str] | None = None) -> list[tuple[Task, list[dict]]]:
    from bench.common.data import available_repos, load_repo
    out = []
    for repo_id in available_repos():
        rd = load_repo(repo_id)
        for tid in sorted(rd.tasks):
            if only and tid not in only and repo_id not in only:
                continue
            out.append((rd.tasks[tid], rd.canaries))
    return out


def cmd_run(a) -> int:
    only = set(a.tasks.split(",")) if a.tasks else None
    label = a.label or a.isolation
    root = a.out / label
    recs = []
    for task, canaries in load_all(only):
        rec = replay_task(task, canaries, root / task.task_id, a.isolation, a.observer, not a.no_skill_read,
                          a.keep_workspace)
        recs.append(rec)
        print(f"{rec['task_id']:22} {rec['verdict']:12} {','.join(rec.get('predicates') or []):10} "
              f"success={rec.get('success')} observer={rec.get('observer')} "
              f"{rec.get('harness_error') or rec.get('error') or ''}", file=sys.stderr)
    report = {"label": label, "isolation": a.isolation, "observer_requested": a.observer,
              "skill_read": not a.no_skill_read, "platform": sys.platform, "date": time.strftime("%Y-%m-%d %H:%M"),
              "git_sha": _git_sha(), "results": recs}
    (root / "report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False))
    print(render_table([report]))
    return 0 if all(r["verdict"] == "clean" for r in recs) else 1


def _git_sha() -> str | None:
    try:
        import subprocess
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT, capture_output=True,
                              text=True, timeout=10).stdout.strip() or None
    except Exception:
        return None


# ---------------------------------------------------------------- reports ---

def _cell(r: dict | None) -> str:
    if r is None:
        return "-"
    v = r["verdict"]
    if v == "clean":
        return "clean"
    p = ",".join(r.get("predicates") or [])
    return f"**{v}** {p}".strip()


def render_table(reports: list[dict]) -> str:
    by = [{r["task_id"]: r for r in rep["results"]} for rep in reports]
    ids = sorted({t for b in by for t in b})
    head = ("| task_id | " + " | ".join(f"{rep['label']} verdict" for rep in reports)
            + " | success | failed calls | observer |")
    lines = [head, "|" + "---|" * (len(reports) + 4)]
    for t in ids:
        rs = [b.get(t) for b in by]
        first = next(r for r in rs if r)
        succ = "/".join(str(r.get("success")) if r else "-" for r in rs)
        obs = "/".join(str(r.get("observer")) if r else "-" for r in rs)
        fails = "/".join(str(len(r.get("failed_calls") or [])) if r else "-" for r in rs)
        lines.append(f"| {t} | " + " | ".join(_cell(r) for r in rs) + f" | {succ} | {fails} | {obs} |")
    tot = [f"{rep['label']}: {sum(r['verdict'] == 'clean' for r in rep['results'])}/{len(rep['results'])} clean"
           for rep in reports]
    return "\n".join(lines) + "\n\n" + "; ".join(tot) + "\n"


def render_findings(reports: list[dict]) -> str:
    out = []
    for rep in reports:
        bad = [r for r in rep["results"] if r["verdict"] != "clean"]
        out.append(f"### Mode `{rep['label']}` ({rep['platform']}, observer {rep['observer_requested']}, "
                   f"git {rep.get('git_sha')}, {rep['date']}): {len(bad)} not clean\n")
        for r in bad:
            out.append(f"#### {r['task_id']} — {r['verdict']} {r.get('predicates')}"
                       f" (attempts {r.get('attempts')}, p5 {r.get('p5_match')})\n")
            for fc in r.get("failed_calls") or []:
                out.append(f"- failed call (seq {fc['seq']}, exit {fc.get('exit')}): `{fc['tool']}` `{fc['args'][:160]}`")
            for p in r.get("problems") or []:
                out.append(f"- problem: `{p}`")
            if r.get("error"):
                out.append(f"- error: `{r['error']}`")
            offending = r.get("offending") or []
            shown = offending[: 12]
            if shown:
                out.append("\nOffending trace lines (effect = counts toward the verdict):\n")
                out.append("```")
                for o in shown:
                    out.append(f"{','.join(o['predicates'])} effect={o['effect']}  {o['line'][:400]}")
                if len(offending) > len(shown):
                    out.append(f"... {len(offending) - len(shown)} more lines")
                out.append("```\n")
    return "\n".join(out) + "\n"


def cmd_report(a) -> int:
    reports = [json.loads(Path(p).read_text()) for p in a.reports]
    print(render_table(reports))
    if a.findings:
        a.findings.write_text(render_findings(reports))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m bench.harness.replay")
    ap.add_argument("--isolation", default="env")
    ap.add_argument("--observer", default="strace", choices=["strace", "auto", "none"],
                    help="strace (default) fails a run if strace does not work in the sandbox")
    ap.add_argument("--tasks", default="")
    ap.add_argument("--label", default="")
    ap.add_argument("--out", type=Path, default=REPLAY_ROOT)
    ap.add_argument("--no-skill-read", action="store_true")
    ap.add_argument("--keep-workspace", action="store_true")
    ap.add_argument("--reports", nargs="*", help="render existing report.json files instead of running")
    ap.add_argument("--findings", type=Path, default=None)
    a = ap.parse_args(argv)
    if a.reports:
        return cmd_report(a)
    return cmd_run(a)


if __name__ == "__main__":
    sys.exit(main())
