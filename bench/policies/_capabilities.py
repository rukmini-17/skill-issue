"""Shared helpers for the policies: loading manifests, hashing files, glob
matching, and pulling capabilities out of a version.

Note (see NOTES.md): C1 says to reuse `bench/common/match.py` for the glob and
command matching, but that's A's module and it doesn't exist yet. So the matching
and the capability extractor live here for now, ported from each repo's
check_repo.py. When A's match.py lands, swap the glob helpers below for it. The
functions to swap are capabilities(), glob_within() and file_hashes().
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

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
# Glob subsumption (D2-style; provisional until common/match.py)
# ---------------------------------------------------------------------------


def glob_regex(pattern: str) -> re.Pattern:
    """Compile a workspace glob (``*`` = non-slash run, ``**`` = any segments)."""
    out, i = "", 0
    while i < len(pattern):
        if pattern[i:i + 3] == "**/":
            out += "(?:.*/)?"
            i += 3
        elif pattern[i:i + 2] == "**":
            out += ".*"
            i += 2
        elif pattern[i] == "*":
            out += "[^/]*"
            i += 1
        else:
            out += re.escape(pattern[i])
            i += 1
    return re.compile(out + r"\Z")


def path_matches(path: str, patterns) -> bool:
    return any(glob_regex(p).match(path) for p in patterns)


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
LITERAL_PATH = re.compile(
    r"(?<![\w/.-])("
    r"(?:\.github|app|tests|data|config|scripts|reports|issues|cov_annotate|mock)/[\w./*-]+"
    r"|\.env[\w.]*"
    r"|[\w-]+\.(?:yaml|yml|toml|csv|txt|sh|log)"
    r")(?![\w])"
)
CMD_START = re.compile(r"^(python3?|pip3?|pytest|ruff|npm|node|bash|sh|curl|wget|git|chmod|rm|cat|\./)")
CODE_BLOCK = re.compile(r"```(\w*)\n(.*?)```", re.S)

CAP_KINDS = ("hosts", "paths", "commands", "deps")


def capabilities(version_root: Path) -> dict[str, set[str]]:
    """Extract {hosts, paths, commands, deps} from every file except LICENSE/manifest.json.

    Ported from check_repo.py. Hosts come from URLs, paths from literal workspace
    paths, commands from bash/sh code blocks, deps from requirements.txt + python
    imports (stdlib removed).
    """
    caps: dict[str, set[str]] = {k: set() for k in CAP_KINDS}
    for f in sorted(version_root.rglob("*")):
        if not f.is_file() or f.name in ("LICENSE", "manifest.json"):
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        caps["hosts"] |= set(URL.findall(text))
        caps["paths"] |= set(LITERAL_PATH.findall(text))
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
