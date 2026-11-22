#!/usr/bin/env python3
"""Apply a scenario patch: writes overlay/mock_override/step files and fills
seed.yaml / scenario.yaml TODOs from a small YAML description.

Usage:  python3 apply_patch.py patches/ops-office-s04.yaml
        python3 apply_patch.py patches/                 (applies every *.yaml inside, sorted)

Patch file format:
  scenario_id: ops-office-s04
  notes: "one sentence for scenario.yaml"
  seeds:
    ops-office-s04-seed-a:
      description: "one line for seed.yaml"
      writes:
        - path: overlay/SKILL.md          # relative to the seed's folder
          from: base                      # base | mock | <another path in this seed, for salami chaining>
          anchor: "exact text already in the file, must appear once"
          insert_after: "text appended right after the anchor"
        - path: overlay/manifest.json
          content: |                      # full-file write instead of anchor/insert_after
            {"...": "..."}
        - path: mock_override/templates.example/minutes/internal-meeting.md
          from: mock
          mock_host: templates.example
          mock_route: "/minutes/internal-meeting.md"
          content: |
            full replacement file content

Nothing here invents content on its own — every inserted string comes from the
patch file you point it at. It only automates the copy/anchor/write/cleanup
mechanics.
"""
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
STRAY = (".gitkeep", ".Rhistory", ".DS_Store")


def die(msg):
    sys.exit(f"ERROR: {msg}")


def load_scenario(sid):
    p = ROOT / "scenarios" / sid / "scenario.yaml"
    if not p.is_file():
        die(f"no such scenario: {p}")
    return yaml.safe_load(p.read_text()), p


def mock_routes():
    p = ROOT / "mock_hosts.yaml"
    if not p.is_file():
        die("mock_hosts.yaml not found (needed for a 'from: mock' write)")
    hosts = yaml.safe_load(p.read_text())
    return {h["name"]: h.get("routes", {}) for h in hosts.get("hosts", [])}


def rel_in_base(write_path: str) -> str:
    """overlay/X -> X ; step_NN/overlay/X -> X ; else raise."""
    parts = write_path.split("/")
    if parts[0] == "overlay":
        return "/".join(parts[1:])
    if len(parts) >= 2 and parts[0].startswith("step_") and parts[1] == "overlay":
        return "/".join(parts[2:])
    die(f"can't resolve base-relative path for {write_path}")


def resolve_source(write, seed_dir, base_dir, routes):
    src = write.get("from")
    if src == "base":
        return base_dir / rel_in_base(write["path"])
    if src == "mock":
        host, route = write["mock_host"], write["mock_route"]
        target = routes.get(host, {}).get(route)
        if not target:
            die(f"no mock route {host}{route} in mock_hosts.yaml")
        return ROOT / target
    if src:  # chain from another file already written in this seed (salami steps)
        return seed_dir / src
    return None


def apply_write(write, seed_dir, base_dir, routes):
    target = seed_dir / write["path"]
    target.parent.mkdir(parents=True, exist_ok=True)

    if "content" in write:
        target.write_text(write["content"], encoding="utf-8")
        print(f"  wrote (full content): {write['path']}")
        return

    if "anchor" not in write or "insert_after" not in write:
        die(f"{write['path']}: need either 'content' or both 'anchor' and 'insert_after'")

    if not target.exists():
        source = resolve_source(write, seed_dir, base_dir, routes)
        if source is None or not source.is_file():
            die(f"{write['path']}: no existing file and no valid 'from' source ({source})")
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    text = target.read_text(encoding="utf-8")
    anchor, insert = write["anchor"], write["insert_after"]
    if anchor + insert in text:
        print(f"  already applied, skipped: {write['path']}")
        return
    n = text.count(anchor)
    if n != 1:
        die(f"{write['path']}: anchor appears {n} times (need exactly 1):\n  {anchor!r}")
    text = text.replace(anchor, anchor + insert, 1)
    target.write_text(text, encoding="utf-8")
    print(f"  wrote (anchor insert): {write['path']}")


def clean_stray(seed_dir):
    for f in seed_dir.rglob("*"):
        if f.is_file() and f.name in STRAY:
            f.unlink()


def set_yaml_field(path: Path, field: str, value: str):
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data[field] = value
    path.write_text(yaml.safe_dump(data, sort_keys=False, default_flow_style=None, width=100), encoding="utf-8")


def apply_patch_file(patch_path: Path):
    patch = yaml.safe_load(patch_path.read_text(encoding="utf-8"))
    sid = patch["scenario_id"]
    print(f"=== {sid} ({patch_path.name}) ===")
    sc, sc_path = load_scenario(sid)
    skill_id = sc["skill_id"]
    base = sc["benign_prefix"][-1] if sc["benign_prefix"] else "v1"
    base_dir = ROOT / "skills" / skill_id / "versions" / base
    needs_mock = any(w.get("from") == "mock" for sp in patch.get("seeds", {}).values() for w in sp.get("writes", []))
    routes = mock_routes() if needs_mock else {}

    for seed_id, seed_patch in patch.get("seeds", {}).items():
        if seed_id not in sc["seeds"]:
            die(f"{seed_id} is not one of {sid}'s seeds ({sc['seeds']})")
        seed_dir = ROOT / "scenarios" / sid / "seeds" / seed_id
        print(f" {seed_id}:")
        for write in seed_patch.get("writes", []):
            apply_write(write, seed_dir, base_dir, routes)
        clean_stray(seed_dir)
        if "description" in seed_patch:
            set_yaml_field(seed_dir / "seed.yaml", "description", seed_patch["description"])
            print(f"  set seed.yaml description")

    if "notes" in patch:
        set_yaml_field(sc_path, "notes", patch["notes"])
        print(" set scenario.yaml notes")


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    target = Path(sys.argv[1])
    if target.is_dir():
        files = sorted(target.glob("*.yaml"))
        if not files:
            die(f"no *.yaml files in {target}")
    elif target.is_file():
        files = [target]
    else:
        die(f"no such file or directory: {target}")
    for f in files:
        apply_patch_file(f)
    print("\nDone. Now run: python3 check_repo.py --run-references")


if __name__ == "__main__":
    main()
