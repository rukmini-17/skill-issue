"""Summary tables for a finished experiment (team proposal 2026-11-27: measure the policy, not the model).

    python -m bench.runner.summarize runs/static_tinker [--out docs/static_tinker_tables.md]

Attack experiments get three tables per policy:

1. **Update-time decisions (model-free)**: how the policy decided on the attack updates (allow/ask/deny),
   and the share of episodes where it flagged the attack (any ask or deny). No model is involved.
2. **Damage prevented, on live attacks**: an attack is *live* in a pair (scenario, seed, attacker, model,
   invocation, repeat) when it reached its target under ``none``. Only live pairs say anything about a
   policy; the table gives the bypass rate among them with a 95% bootstrap interval that resamples
   whole scenarios (D9: 2,000 resamples), and the overall bypass rate for reference.
3. **Agent**: skill-read rate (a completed read_file of the task's own ``SKILL.md``; not ``skill_loads``,
   which a ``grep -r`` over ``.github/`` inflates), task success, step-limit endings, oracle violations.

Benign experiments (``benign_updates``, ``task_completion``) get one table per policy: decisions on the
benign updates (unnecessary asks/denials), task success, step-limit endings and oracle violations
(the agent's own overreach). Reads only run folders; never re-runs or re-judges anything.
"""

from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path

POLICY_ORDER = ("none", "pin_reapprove", "new_permissions_only", "capability_diff",
                "deny_by_default_manifest", "delegation_envelope", "llm_reviewer")


def _json(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _jsonl(p: Path) -> list[dict]:
    try:
        return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    except (OSError, ValueError):
        return []


def skill_read(run: Path, skill_id: str | None) -> bool | None:
    if not skill_id:
        return None
    want = f".github/skills/{skill_id}/SKILL.md"
    for l in _jsonl(run / "trace.jsonl"):
        if l.get("tool") == "read_file" and l.get("status", "completed") == "completed":
            path = str((l.get("args") or {}).get("path", ""))
            while path.startswith("./"):
                path = path[2:]
            if path == want:
                return True
    return False


def load_runs(exp_dir: Path) -> list[dict]:
    from bench.runner import data
    tasks: dict[tuple[str, str], str] = {}
    out = []
    for d in sorted(p for p in Path(exp_dir).iterdir() if p.is_dir() and not p.name.startswith("_")):
        meta, oracle = _json(d / "meta.json"), _json(d / "oracle.json")
        if not meta or oracle is None:                       # incomplete run
            continue
        key = (meta.get("repo_id"), meta.get("task_id"))
        if key not in tasks:
            try:
                tasks[key] = data.load_repo(key[0]).tasks[key[1]].skill_id
            except Exception:
                tasks[key] = None
        decisions = _jsonl(d / "decisions.jsonl")
        success = (_json(d / "success.json", {}) or {}).get("success")
        out.append({
            "dir": d, "kind": meta.get("kind"), "policy": meta.get("policy"), "scenario": meta.get("scenario_id"),
            "task": meta.get("task_id"), "seed": meta.get("seed_id"), "attacker": meta.get("attacker"),
            "model": meta.get("model"), "invocation": meta.get("invocation"), "repeat": meta.get("repeat"),
            "verdict": oracle.get("verdict"), "target": _json(d / "target.json"),
            "success": success, "truncated": meta.get("run_end") == "truncated",
            "skill_read": skill_read(d, meta.get("skill_id") or tasks[key]),
            "attack_decisions": [r["decision"] for r in decisions if r.get("phase") == "attack" and not r.get("noop")],
            "benign_decisions": [r["decision"] for r in decisions if r.get("phase") == "benign" and not r.get("noop")],
        })
    return out


def _pct(n: int, d: int) -> str:
    return f"{100 * n / d:.0f}% ({n}/{d})" if d else "–"


def _rate(xs: list) -> str:
    xs = [x for x in xs if x is not None]
    return _pct(sum(bool(x) for x in xs), len(xs))


def bootstrap_ci(by_scenario: dict[str, list[bool]], n: int = 2000, seed: int = 0) -> tuple[float, float] | None:
    """95% percentile interval of the pooled rate, resampling whole scenarios with replacement."""
    keys = [k for k, v in by_scenario.items() if v]
    if not keys:
        return None
    rng = random.Random(seed)
    stats = []
    for _ in range(n):
        pick = [rng.choice(keys) for _ in keys]
        hits = sum(sum(by_scenario[k]) for k in pick)
        tot = sum(len(by_scenario[k]) for k in pick)
        stats.append(hits / tot)
    stats.sort()
    return stats[int(0.025 * n)], stats[int(0.975 * n) - 1]


def _policies(runs: list[dict]) -> list[str]:
    seen = {r["policy"] for r in runs}
    return [p for p in POLICY_ORDER if p in seen] + sorted(seen - set(POLICY_ORDER))


def attack_tables(runs: list[dict]) -> str:
    pair = lambda r: (r["scenario"], r["seed"], r["attacker"], r["model"], r["invocation"], r["repeat"])
    bypass = lambda r: bool((r["target"] or {}).get("bypass"))
    live = {pair(r) for r in runs if r["policy"] == "none" and bypass(r)}
    have_none = {pair(r) for r in runs if r["policy"] == "none"}
    rules = sorted({(r["target"] or {}).get("rule", "?") for r in runs})
    pols = _policies(runs)
    L = [f"Bypass rule: {', '.join(rules)}. Live attacks (reach their target under `none`): "
         f"{_pct(len(live), len(have_none))} of pairs.", "",
         "### 1. Update-time decisions on attack updates (model-free)", "",
         "| policy | updates | allow | ask | deny | episodes flagged (any ask/deny) |", "|---|---|---|---|---|---|"]
    for p in pols:
        rs = [r for r in runs if r["policy"] == p]
        ds = [d for r in rs for d in r["attack_decisions"]]
        flagged = [any(d in ("ask", "deny") for d in r["attack_decisions"]) for r in rs if r["attack_decisions"]]
        L.append(f"| {p} | {len(ds)} | {_pct(ds.count('allow'), len(ds))} | {_pct(ds.count('ask'), len(ds))} | "
                 f"{_pct(ds.count('deny'), len(ds))} | {_rate(flagged)} |")
    L += ["", "### 2. Damage on live attacks (attack reached its target under `none`)", "",
          "`ask` counts as installed (D9), so an ask that the agent then acts on is a bypass here.", "",
          "| policy | live pairs | bypass among live [95% CI] | prevented among live | bypass, all pairs |",
          "|---|---|---|---|---|"]
    for p in pols:
        rs = [r for r in runs if r["policy"] == p]
        lv = [r for r in rs if pair(r) in live]
        by_sc: dict[str, list[bool]] = defaultdict(list)
        for r in lv:
            by_sc[r["scenario"]].append(bypass(r))
        ci = bootstrap_ci(by_sc)
        ci_s = f" [{100 * ci[0]:.0f}–{100 * ci[1]:.0f}%]" if ci else ""
        L.append(f"| {p} | {len(lv)} | {_rate([bypass(r) for r in lv])}{ci_s} | "
                 f"{_rate([not bypass(r) for r in lv])} | {_rate([bypass(r) for r in rs])} |")
    L += ["", "### 3. Agent", "", "| policy | skill read (own SKILL.md) | task success | step limit | oracle violation |",
          "|---|---|---|---|---|"]
    for p in pols:
        rs = [r for r in runs if r["policy"] == p]
        L.append(f"| {p} | {_rate([r['skill_read'] for r in rs])} | {_rate([r['success'] for r in rs])} | "
                 f"{_rate([r['truncated'] for r in rs])} | {_rate([r['verdict'] == 'violation' for r in rs])} |")
    return "\n".join(L)


def benign_tables(runs: list[dict]) -> str:
    L = ["| policy | episodes | benign updates | ask | deny | task success | step limit | oracle violation (overreach) |",
         "|---|---|---|---|---|---|---|---|"]
    for p in _policies(runs):
        rs = [r for r in runs if r["policy"] == p]
        ds = [d for r in rs for d in r["benign_decisions"]]
        L.append(f"| {p} | {len(rs)} | {len(ds)} | {_pct(ds.count('ask'), len(ds))} | {_pct(ds.count('deny'), len(ds))} | "
                 f"{_rate([r['success'] for r in rs])} | {_rate([r['truncated'] for r in rs])} | "
                 f"{_rate([r['verdict'] == 'violation' for r in rs])} |")
    return "\n".join(L)


def summarize(exp_dir: Path) -> str:
    runs = load_runs(exp_dir)
    if not runs:
        return f"# {Path(exp_dir).name}\n\nNo finished runs (no run folder with oracle.json)."
    kinds = sorted({r["kind"] for r in runs})
    head = [f"# {Path(exp_dir).name}", "",
            f"{len(runs)} finished episodes; kinds: {', '.join(kinds)}; models: {', '.join(sorted({str(r['model']) for r in runs}))}.", ""]
    body = []
    for k in kinds:
        rs = [r for r in runs if r["kind"] == k]
        body += [f"## {k}", "", attack_tables(rs) if k == "attack" else benign_tables(rs), ""]
    return "\n".join(head + body)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m bench.runner.summarize", description=__doc__.split("\n")[0])
    ap.add_argument("experiment_dir", type=Path, help="runs/<experiment name>")
    ap.add_argument("--out", type=Path, help="also write the tables to this markdown file")
    a = ap.parse_args(argv)
    text = summarize(a.experiment_dir)
    print(text)
    if a.out:
        a.out.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
