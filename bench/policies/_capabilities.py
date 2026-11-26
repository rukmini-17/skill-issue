"""Shared helpers for the policies: loading manifests, hashing files, glob
matching, and pulling capabilities out of a version.

Glob matching is A's shared `bench.common.match` (C1 says to reuse it); `path_matches`
and `glob_within` below are thin C-side wrappers over it for capability subsumption.
The capability *extractor* (`capabilities`, `repo_top_folders/files`) stays here — A's
NOTES record that text-level capability extraction is C's job per the revised D12.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

from bench.common import match

# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

PERM_KEYS = ("fs_read", "fs_write", "exec", "network")
# Map a Task.delegation field -> manifest permission key (from check_repo.py).
DELEGATION_KEYS = {"read": "fs_read", "write": "fs_write", "exec": "exec", "network": "network"}


def load_manifest(version_root: Path) -> dict:
    """Parse ``manifest.json`` for a version snapshot."""
    return json.loads((version_root / "manifest.json").read_text(encoding="utf-8"))


def permissions(manifest: dict) -> dict[str, list[str]]:
    """Return the four permission lists, defaulting missing keys to []."""
    perms = manifest.get("permissions", {}) or {}
    return {key: list(perms.get(key, []) or []) for key in PERM_KEYS}


# ---------------------------------------------------------------------------
# File hashing (pin_reapprove)
# ---------------------------------------------------------------------------


def file_hashes(version_root: Path) -> dict[str, str]:
    """Map workspace-relative POSIX path -> sha256 of each file in the snapshot."""
    out: dict[str, str] = {}
    for f in sorted(version_root.rglob("*")):
        if f.is_file():
            rel = f.relative_to(version_root).as_posix()
            out[rel] = hashlib.sha256(f.read_bytes()).hexdigest()
    return out


# ---------------------------------------------------------------------------
# Glob subsumption (D2) — matching is A's bench.common.match; subsumption is C's
# ---------------------------------------------------------------------------


def path_matches(path: str, patterns) -> bool:
    """True if ``path`` matches any glob in ``patterns`` under D2 (A's matcher).

    ``*`` matches a run of non-slash characters, ``**`` zero or more whole segments,
    and ``dir/**`` covers ``dir`` itself, so a ``list_dir("dir")`` is in a ``dir/**`` grant.
    """
    return any(match.path_matches(pat, path) for pat in patterns)


def glob_within(inner: str, outer) -> bool:
    """True if everything glob ``inner`` allows is also allowed by some glob in ``outer``."""
    probe = inner.replace("**", "x/y").replace("*", "x")
    return inner in outer or path_matches(probe, outer)


def gained_entries(new_list, approved_list) -> list[str]:
    """Entries in ``new_list`` not already subsumed by ``approved_list`` (glob-aware)."""
    return [p for p in new_list if not glob_within(p, approved_list)]


# ---------------------------------------------------------------------------
# Capability extractor (ported from check_repo.py:capabilities)
# ---------------------------------------------------------------------------

PY_IMPORT = re.compile(r"^\s*(?:from|import)\s+([A-Za-z_][\w]*)", re.M)
URL = re.compile(r"[a-z][a-z0-9+]*://([A-Za-z0-9.-]+)[^\s\"'`)]*")
CMD_START = re.compile(r"^(python3?|pip3?|pytest|ruff|npm|node|bash|sh|curl|wget|git|chmod|rm|cat|\./)")
CODE_BLOCK = re.compile(r"```(\w*)\n(.*?)```", re.S)

CAP_KINDS = ("hosts", "paths", "commands", "deps")


def _repo_root_for(version_root: Path) -> Path | None:
    """Walk up from a version snapshot to the repo root (the dir that holds ``workspace/``)."""
    for p in [version_root, *version_root.parents]:
        if (p / "workspace").is_dir():
            return p
    return None


def repo_top_folders(version_root: Path) -> list[str]:
    """The repo's recognised top-level folders, read from its ``workspace/`` plus ``.github`` (D12).

    D12 requires path recognition not to depend on a fixed folder list: the list is
    built per repo from that repo's ``workspace/``. If no workspace is found (e.g. a
    synthetic unit-test snapshot), fall back to ``.github`` only.

    Known limitation: only entries present in the static ``workspace/`` are listed.
    Top-level dirs created by ``setup.sh`` or by tools at run time (``node_modules``,
    ``.ruff_cache``, ``cov_annotate``, …) are not, so a path named only under one of
    those is not recognised. Documented in NOTES.md.
    """
    folders = {".github"}
    root = _repo_root_for(version_root)
    if root is not None:
        folders |= {d.name for d in (root / "workspace").iterdir() if d.is_dir()}
    return sorted(folders)


def repo_top_files(version_root: Path) -> list[str]:
    """The repo's recognised top-level files, read from its ``workspace/`` (e.g.
    ``package.json``, ``CHANGELOG.md``, ``.npmrc``, ``requirements.txt``)."""
    root = _repo_root_for(version_root)
    if root is None:
        return []
    return sorted(f.name for f in (root / "workspace").iterdir() if f.is_file())


def _literal_path_re(folders: list[str], files: list[str] | None = None) -> re.Pattern:
    """A literal-path matcher keyed on this repo's top-level folders and files.

    Matches ``<folder>/<rest>`` for any recognised folder, an exact recognised
    top-level file, plus ``.env*`` and bare config-ish filenames
    (``*.yaml``/``*.csv``/``*.sh``/…) that name a file directly.
    """
    alt = "|".join(re.escape(f) for f in folders) or r"\.github"
    file_alt = "|".join(re.escape(f) for f in (files or []))
    file_branch = rf"|(?:{file_alt})" if file_alt else ""
    return re.compile(
        r"(?<![\w/.-])("
        rf"(?:{alt})/[\w./*-]+"
        rf"{file_branch}"
        r"|\.env[\w.]*"
        r"|[\w-]+\.(?:yaml|yml|toml|csv|txt|sh|log)"
        r")(?![\w])"
    )


def capabilities(
    version_root: Path,
    folders: list[str] | None = None,
    files: list[str] | None = None,
) -> dict[str, set[str]]:
    """Extract {hosts, paths, commands, deps} from every file except LICENSE/manifest.json.

    Hosts come from URLs, paths from literal workspace paths (recognised against the
    repo's own top-level folders and files, D12), commands from bash/sh code blocks,
    deps from requirements.txt + python imports (stdlib removed). ``folders``/``files``
    override the per-repo lists (used by the extractor test); otherwise they are
    derived from the repo's ``workspace/``.
    """
    if folders is None:
        folders = repo_top_folders(version_root)
    if files is None:
        files = repo_top_files(version_root)
    literal_path = _literal_path_re(folders, files)
    caps: dict[str, set[str]] = {k: set() for k in CAP_KINDS}
    for f in sorted(version_root.rglob("*")):
        if not f.is_file() or f.name in ("LICENSE", "manifest.json"):
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        caps["hosts"] |= set(URL.findall(text))
        caps["paths"] |= set(literal_path.findall(text))
        if f.name == "requirements.txt":
            caps["deps"] |= {
                re.split(r"[<>=\[ ]", l.strip())[0]
                for l in text.splitlines()
                if l.strip() and not l.startswith(("#", "-"))
            }
        if f.suffix == ".py":
            caps["deps"] |= set(PY_IMPORT.findall(text)) - set(sys.stdlib_module_names)
        if f.suffix == ".md":
            for lang, block in CODE_BLOCK.findall(text):
                if lang in ("", "bash", "sh"):
                    caps["commands"] |= {l.strip() for l in block.splitlines() if CMD_START.match(l.strip())}
                if lang == "python":
                    caps["deps"] |= set(PY_IMPORT.findall(block)) - set(sys.stdlib_module_names)
    return caps


def capability_gains(new_root: Path, approved_root: Path) -> dict[str, list[str]]:
    """Per-kind entries the new version has that the approved version did not."""
    new_caps = capabilities(new_root)
    old_caps = capabilities(approved_root)
    return {kind: sorted(new_caps[kind] - old_caps[kind]) for kind in CAP_KINDS}
