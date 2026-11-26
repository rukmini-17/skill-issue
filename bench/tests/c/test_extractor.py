"""C1 extractor test (D12).

The capability extractor's path recognition must not depend on a fixed folder list:
the recognised top-level folders come from each repo's own ``workspace/`` (plus
``.github``). This test checks that, for every repo, the repo-specific targets an
attacker might name in a ``SKILL.md`` are actually extracted:

- each canary ``location`` (the protected read/leak targets), from ``canaries.json``;
- each **write target** the tasks delegate (``delegation.write``), standing in for the
  protected-write surface;
- each **exec target** the tasks delegate (``delegation.exec``), standing in for the
  forbidden-exec surface.

We embed these literally in a synthetic ``SKILL.md`` and assert the extractor, driven
by the per-repo folder list, recovers them. Using the delegation write/exec entries
keeps the targets grounded in real repo data without reaching into attack seeds.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from bench.policies._capabilities import (
    CMD_START,
    capabilities,
    repo_top_files,
    repo_top_folders,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
REPOS = REPO_ROOT / "repos"
REPO_IDS = ("orders-api", "ops-office", "shop-web", "release-tools")


def _repo_folders(repo_id: str) -> list[str]:
    ws = REPOS / repo_id / "workspace"
    folders = {".github"}
    if ws.is_dir():
        folders |= {d.name for d in ws.iterdir() if d.is_dir()}
    return sorted(folders)


def _repo_files(repo_id: str) -> list[str]:
    ws = REPOS / repo_id / "workspace"
    return sorted(f.name for f in ws.iterdir() if f.is_file()) if ws.is_dir() else []


def _grounded(target: str, folders: list[str], files: list[str]) -> bool:
    """A target is recognisable if its top-level segment is a known folder/file (or .env*).

    Targets whose top-level entry exists only after setup.sh (node_modules, .ruff_cache,
    cov_annotate, __tests__, .coverage) are not in the static workspace and so are a
    documented gap, not a test failure.
    """
    head = target.split("/", 1)[0]
    return head in folders or target in files or target.startswith(".env")


def _canary_locations(repo_id: str) -> list[str]:
    import json

    f = REPOS / repo_id / "canaries.json"
    if not f.exists():
        return []
    return [c["location"] for c in json.loads(f.read_text()) if c.get("location")]


def _delegation_targets(repo_id: str) -> tuple[set[str], set[str]]:
    """(write targets, exec commands) gathered from every task's delegation."""
    writes: set[str] = set()
    execs: set[str] = set()
    tdir = REPOS / repo_id / "tasks"
    for tf in sorted(tdir.glob("*.yaml")):
        d = yaml.safe_load(tf.read_text()) or {}
        deleg = d.get("delegation", {}) or {}
        writes |= {w for w in (deleg.get("write") or []) if "/" in w or "." in w}
        execs |= {e for e in (deleg.get("exec") or []) if e.strip()}
    return writes, execs


def _is_path_like(s: str) -> bool:
    return ("/" in s) or s.startswith(".env") or ("." in s.split("/")[-1])


@pytest.mark.parametrize("repo_id", REPO_IDS)
def test_extractor_recovers_repo_targets(repo_id, tmp_path):
    if not (REPOS / repo_id).is_dir():
        pytest.skip(f"{repo_id} not present")

    folders = _repo_folders(repo_id)
    files = _repo_files(repo_id)
    canary_locs = [c for c in _canary_locations(repo_id) if _is_path_like(c)]
    write_targets, exec_cmds = _delegation_targets(repo_id)
    path_targets = sorted(set(canary_locs) | {w for w in write_targets if _is_path_like(w)})

    # A SKILL.md naming every target literally: paths in prose, commands in a bash block.
    lines = ["# attack-shaped skill", ""]
    lines += [f"- touches `{p}`" for p in path_targets]
    lines += ["", "```bash"]
    lines += list(sorted(exec_cmds))
    lines += ["```", ""]
    version = tmp_path / repo_id
    version.mkdir()
    (version / "SKILL.md").write_text("\n".join(lines), encoding="utf-8")

    caps = capabilities(version, folders=folders, files=files)

    # Every canary location must be extracted (D12 names these explicitly).
    missing_canaries = [c for c in canary_locs if c not in caps["paths"]]
    assert not missing_canaries, f"{repo_id}: canary locations not extracted: {missing_canaries}"

    # Every workspace-grounded path target is extracted. Targets whose top-level entry
    # only exists after setup.sh are a documented gap (NOTES.md), not a failure.
    grounded = [p for p in path_targets if _grounded(p, folders, files)]
    missing_paths = [p for p in grounded if p not in caps["paths"]]
    assert not missing_paths, f"{repo_id}: grounded paths not extracted: {missing_paths} (folders={folders})"

    # Every exec target whose leading token is a recognised command is extracted.
    expected_cmds = [c for c in exec_cmds if CMD_START.match(c.strip())]
    missing_cmds = [c for c in expected_cmds if c.strip() not in caps["commands"]]
    assert not missing_cmds, f"{repo_id}: commands not extracted: {missing_cmds}"


def test_folder_list_comes_from_workspace(tmp_path):
    """repo_top_folders reads the repo's workspace/ (not a hardcoded list), plus .github."""
    ws = tmp_path / "workspace"
    for d in ("widgets", "ledger", "secret_stuff"):
        (ws / d).mkdir(parents=True)
    version = tmp_path / "skills" / "s" / "versions" / "v1"
    version.mkdir(parents=True)

    folders = repo_top_folders(version)
    assert ".github" in folders
    assert {"widgets", "ledger", "secret_stuff"} <= set(folders)
