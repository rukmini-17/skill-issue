"""Stable identifiers: run ids, content hashes, data tag, git sha."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from bench.runner.data import REPO_ROOT


def short_hash(*parts: object, n: int = 12) -> str:
    h = hashlib.sha256("\x1f".join("" if p is None else str(p) for p in parts).encode("utf-8"))
    return h.hexdigest()[:n]


def tree_hash(root: Path | None) -> str:
    """Hash of every file (relative path + bytes) under ``root``. ``None`` or missing -> 'none'."""
    if root is None or not root.exists():
        return "none"
    h = hashlib.sha256()
    for f in sorted(p for p in root.rglob("*") if p.is_file()):
        h.update(f.relative_to(root).as_posix().encode())
        h.update(b"\0")
        h.update(f.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 and out.stdout.strip() else None


def data_tag() -> str:
    """The data tag recorded in run ids and meta.json ('untagged' until data-v1 exists)."""
    return _git("describe", "--tags", "--match", "data-v*", "--abbrev=0") or "untagged"


def git_sha() -> str:
    return _git("rev-parse", "HEAD") or "unknown"
