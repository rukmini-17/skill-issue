"""C2 — the offline static decision matrix.

For every policy, record its update-time decision over:
  * every benign version, as an update from v1;
  * benign prefix chains (v1 -> prefix[0] -> prefix[1] -> ...), per scenario;
  * every attack seed step, as an update from its base or previous step.

Writes bench/policies/reports/static_decisions.csv. No harness, no models (the
six non-LLM policies); pass --with-llm and a completion function to include
llm_reviewer. This is the first real result of the project (M2).

Run:  python -m bench.policies.make_static_matrix [--repos orders-api,ops-office,...]
"""

from __future__ import annotations

import argparse
import csv
import tempfile
from collections import Counter
from pathlib import Path

from bench.policies import POLICY_NAMES, get_policy
from bench.policies._dataload import (
    REPOS,
    benign_versions,
    list_skills,
    load_scenarios,
    load_task,
    seed_transitions,
    skill_versions,
)

DEFAULT_REPOS = ("orders-api", "ops-office", "shop-web", "release-tools")
FIELDS = [
    "repo_id", "kind", "skill_id", "scenario_id", "seed_id", "class", "step",
    "from_version", "to_version", "task_id", "policy", "decision", "reason",
]


def _tasks_by_skill(repo_id: str) -> dict[str, str]:
    """skill_id -> a representative task_id (first one), for benign-from-v1 rows."""
    out: dict[str, str] = {}
    tdir = REPOS / repo_id / "tasks"
    for f in sorted(tdir.glob("*.yaml")):
        task = load_task(repo_id, f.stem)
        out.setdefault(task.skill_id, task.task_id)
    return out


def _decide(policies, approved, candidate, task, base_row, rows):
    for name, pol in policies:
        decision, reason = pol.on_update(approved, candidate, task)
        rows.append({**base_row, "policy": name, "decision": decision, "reason": reason[:300]})


def build_matrix(repo_ids, policies, workdir: Path) -> list[dict]:
    rows: list[dict] = []
    for repo_id in repo_ids:
        skill_task = _tasks_by_skill(repo_id)

        # 1) benign versions as updates from v1
        for skill_id in list_skills(repo_id):
            versions = skill_versions(repo_id, skill_id)
            if "v1" not in versions:
                continue
            v1 = versions["v1"]
            task_id = skill_task.get(skill_id)
            task = load_task(repo_id, task_id) if task_id else None
            for bname in benign_versions(repo_id, skill_id):
                if bname not in versions:
                    continue
                base_row = dict.fromkeys(FIELDS, "")
                base_row.update(repo_id=repo_id, kind="benign_from_v1", skill_id=skill_id,
                                step="update", from_version="v1", to_version=bname,
                                task_id=task_id or "")
                _decide(policies, v1, versions[bname], task, base_row, rows)

        # 2) benign prefix chains + 3) seed steps, per scenario
        for scen in load_scenarios(repo_id):
            task = load_task(repo_id, scen.task_id)
            versions = skill_versions(repo_id, scen.skill_id)

            if scen.benign_prefix:
                approved = versions.get("v1")
                for bname in scen.benign_prefix:
                    cand = versions.get(bname)
                    if approved is None or cand is None:
                        break
                    base_row = dict.fromkeys(FIELDS, "")
                    base_row.update(repo_id=repo_id, kind="benign_prefix", skill_id=scen.skill_id,
                                    scenario_id=scen.scenario_id, step="prefix",
                                    from_version=approved.version, to_version=bname, task_id=scen.task_id)
                    _decide(policies, approved, cand, task, base_row, rows)
                    approved = cand

            for seed_id in scen.seed_ids:
                for tr in seed_transitions(repo_id, scen, seed_id, workdir):
                    base_row = dict.fromkeys(FIELDS, "")
                    base_row.update(repo_id=repo_id, kind="seed_step", skill_id=scen.skill_id,
                                    scenario_id=scen.scenario_id, seed_id=seed_id,
                                    **{"class": scen.attack.get("class", "")},
                                    step=tr.step, from_version=tr.approved.version,
                                    to_version=tr.candidate.version, task_id=scen.task_id)
                    _decide(policies, tr.approved, tr.candidate, task, base_row, rows)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repos", default=",".join(DEFAULT_REPOS))
    ap.add_argument("--out", default=str(Path(__file__).parent / "reports" / "static_decisions.csv"))
    ap.add_argument("--with-llm", action="store_true", help="include llm_reviewer (needs a wired model)")
    ap.add_argument("--model", default=None,
                    help="llm_reviewer model key from bench/configs/models.yaml "
                         "(default: $CDB_REVIEWER_MODEL or qwen3-32b-vllm)")
    args = ap.parse_args()

    repo_ids = [r.strip() for r in args.repos.split(",") if r.strip()]
    names = POLICY_NAMES if args.with_llm else tuple(n for n in POLICY_NAMES if n != "llm_reviewer")
    policies = [(n, get_policy(n, model=args.model) if n == "llm_reviewer" else get_policy(n))
                for n in names]

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        rows = build_matrix(repo_ids, policies, Path(tmp))

    with out_path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)

    # summary
    print(f"wrote {len(rows)} rows -> {out_path}")
    per_policy = {n: Counter() for n, _ in policies}
    for r in rows:
        per_policy[r["policy"]][r["decision"]] += 1
    print(f"\n{'policy':26} {'allow':>7} {'ask':>7} {'deny':>7}")
    for n, _ in policies:
        c = per_policy[n]
        print(f"{n:26} {c['allow']:>7} {c['ask']:>7} {c['deny']:>7}")

    # benign false-positive view (benign rows only): ask+deny fraction
    benign = [r for r in rows if r["kind"].startswith("benign")]
    print(f"\nbenign rows: {len(benign) // max(len(policies),1)} per policy")
    print(f"{'policy':26} {'benign ask/deny (false positives)':>34}")
    for n, _ in policies:
        b = [r for r in benign if r["policy"] == n]
        fp = sum(1 for r in b if r["decision"] in ("ask", "deny"))
        pct = (fp / len(b) * 100) if b else 0
        print(f"{n:26} {f'{fp}/{len(b)}  ({pct:.0f}%)':>34}")

    # attack steps by class: how each policy decides on seed-step updates (C2)
    steps = [r for r in rows if r["kind"] == "seed_step"]
    classes = sorted({r["class"] for r in steps if r["class"]})
    print(f"\nattack seed-step decisions (allow/ask/deny) by class:")
    print(f"{'policy':26} " + " ".join(f"{c:>22}" for c in classes))
    for n, _ in policies:
        cells = []
        for c in classes:
            cc = Counter(r["decision"] for r in steps if r["policy"] == n and r["class"] == c)
            cells.append(f"{cc['allow']}/{cc['ask']}/{cc['deny']}")
        print(f"{n:26} " + " ".join(f"{cell:>22}" for cell in cells))


if __name__ == "__main__":
    main()
