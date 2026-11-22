#!/usr/bin/env python3
"""Dump everything needed to write one scenario's seeds, in one paste-able block.

Usage:  python3 dump_scenario.py <N>          (e.g. 3, 03, s03, or ops-office-s03)
Run from inside repos/ops-office (same place you run check_repo.py).
"""
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
REPO_ID = "ops-office"


def sid_from_arg(arg):
    arg = arg.lower().lstrip("s").lstrip("0") or "0"
    return f"{REPO_ID}-s{int(arg):02d}"


def hr(title):
    print(f"\n{'=' * 10} {title} {'=' * 10}")


def show_file(path: Path, label=None):
    hr(label or str(path.relative_to(ROOT)))
    if not path.exists():
        print("(missing)")
        return
    try:
        print(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError:
        print(f"(binary, {path.stat().st_size} bytes)")


def overlay_status(seed_dir: Path, base_dir: Path):
    for sub in ["overlay", "mock_override"]:
        d = seed_dir / sub
        if not d.exists():
            continue
        files = sorted(f for f in d.rglob("*") if f.is_file() and f.name not in (".gitkeep", ".Rhistory", ".DS_Store"))
        if not files:
            continue
        hr(f"{seed_dir.name}/{sub}/ (current state)")
        for f in files:
            rel = f.relative_to(d)
            base_f = base_dir / rel
            if base_f.is_file() and base_f.read_bytes() == f.read_bytes():
                tag = "UNCHANGED (identical to base)"
            elif base_f.is_file():
                tag = "EDITED"
            else:
                tag = "NEW FILE (not in base)"
            print(f"  {rel}  -- {tag}")
    for step in sorted(seed_dir.glob("step_*")):
        files = sorted(f for f in (step / "overlay").rglob("*") if f.is_file() and f.name not in (".gitkeep", ".Rhistory", ".DS_Store"))
        hr(f"{seed_dir.name}/{step.name}/overlay/")
        print(f"  {len(files)} file(s): {[str(f.relative_to(step/'overlay')) for f in files]}" if files else "  (empty)")


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sid = sid_from_arg(sys.argv[1])
    sc_path = ROOT / "scenarios" / sid / "scenario.yaml"
    if not sc_path.is_file():
        sys.exit(f"No such scenario: {sc_path}")
    sc = yaml.safe_load(sc_path.read_text())
    show_file(sc_path, f"scenarios/{sid}/scenario.yaml")

    skill_id = sc["skill_id"]
    base = sc["benign_prefix"][-1] if sc["benign_prefix"] else "v1"
    skill_dir = ROOT / "skills" / skill_id
    base_dir = skill_dir / "versions" / base

    show_file(ROOT / "tasks" / f"{sc['task_id']}.yaml", f"tasks/{sc['task_id']}.yaml (base_version to edit against: {base})")
    show_file(base_dir / "SKILL.md", f"skills/{skill_id}/versions/{base}/SKILL.md")
    show_file(base_dir / "manifest.json", f"skills/{skill_id}/versions/{base}/manifest.json")

    # concealed_dependency / anything with extra script/dependency files
    extra = sorted(f for f in base_dir.rglob("*")
                    if f.is_file() and f.name not in ("SKILL.md", "manifest.json", "LICENSE")
                    and f.suffix in (".py", ".sh", ".txt", ".json", ".yaml", ".yml"))
    for f in extra:
        show_file(f, f"skills/{skill_id}/versions/{base}/{f.relative_to(base_dir)} (extra file)")

    cls = sc["attack"]["class"]
    if cls == "authority_laundering" and sc.get("companion_skill_id"):
        comp = sc["companion_skill_id"]
        comp_dir = ROOT / "skills" / comp / "versions" / "v1"
        show_file(comp_dir / "SKILL.md", f"companion skill: skills/{comp}/versions/v1/SKILL.md")
        show_file(comp_dir / "manifest.json", f"companion skill: skills/{comp}/versions/v1/manifest.json")
        comp_tasks = [p for p in (ROOT / "tasks").glob("*.yaml") if yaml.safe_load(p.read_text()).get("skill_id") == comp]
        for p in comp_tasks:
            show_file(p, f"companion task: tasks/{p.name}")

    if cls == "late_binding":
        hosts = yaml.safe_load((ROOT / "mock_hosts.yaml").read_text())
        hr("mock_hosts.yaml")
        print(yaml.safe_dump(hosts))
        for h in hosts.get("hosts", []):
            for route, target in h.get("routes", {}).items():
                show_file(ROOT / target, f"mock route {h['name']}{route} -> {target}")

    # canaries relevant to the attack
    canaries = json.loads((ROOT / "canaries.json").read_text())
    hr("canaries.json (full, for reference)")
    print(json.dumps(canaries, indent=2))

    for seed_id in sc["seeds"]:
        sd = ROOT / "scenarios" / sid / "seeds" / seed_id
        show_file(sd / "seed.yaml", f"scenarios/{sid}/seeds/{seed_id}/seed.yaml")
        overlay_status(sd, base_dir)


if __name__ == "__main__":
    main()
