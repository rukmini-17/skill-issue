"""Path helpers for the B tests (unique module name so it can't clash with other test folders)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
REPOS = ROOT / "repos"


def url(srv) -> str:
    """Proxy URL of a test proxy server."""
    return f"http://127.0.0.1:{srv.server_address[1]}"
