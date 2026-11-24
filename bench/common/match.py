"""Path, command and network matching — D2, D3, D4 of the implementation prompt.

One implementation, used by the oracle (A), the policies (C) and the harness (B).
All path inputs and patterns are workspace-relative POSIX strings (D1).
"""

from __future__ import annotations

import os
import posixpath
import re
import shlex
from functools import lru_cache
from pathlib import Path, PurePosixPath

_ALIASES_PATH = Path(__file__).resolve().parents[1] / "configs" / "command_aliases.yaml"

# --------------------------------------------------------------------------- #
# D2 — path patterns (globs)                                                  #
# --------------------------------------------------------------------------- #
# Patterns are workspace-relative. `*` matches any characters except `/`.
# `**` matches zero or more whole path segments. A pattern without wildcards
# matches exactly that path. `dir/**` matches everything under `dir/`.
#
# Before matching, a path is resolved (`.`, `..`, symlinks) and made relative to
# the workspace root. A path that resolves outside the root never matches.


def is_absolute_path(path: str) -> bool:
    """POSIX-absolute, UNC, or a Windows drive path — all rejected by D2."""
    raw = str(path).strip()
    if not raw:
        return False
    if raw.startswith("/") or raw.startswith("\\"):
        return True
    return bool(re.match(r"^[A-Za-z]:[\\/]", raw))


def normalize_rel(path: str, workspace_root: str | os.PathLike | None = None) -> str | None:
    """Resolve `path` to a workspace-relative POSIX path, or None if it does not match.

    D2: absolute paths are rejected (never match). `.`/`..` are resolved lexically; if
    `workspace_root` is a real directory on disk, symlinks are also resolved at access
    time (a symlink pointing outside the workspace is rejected). A path that resolves
    outside the workspace root never matches.
    """
    if path is None:
        return None
    if is_absolute_path(path):
        return None  # absolute paths never match (D2)
    raw = str(path).replace("\\", "/").strip()
    if not raw:
        return None

    if workspace_root is not None:
        root = os.path.realpath(workspace_root)
        real = os.path.realpath(os.path.join(root, raw))
        try:
            rel = os.path.relpath(real, root)
        except ValueError:
            return None  # different drive on Windows
        rel = rel.replace("\\", "/")
        if rel == ".." or rel.startswith("../"):
            return None
        return "" if rel == "." else rel

    # Lexical-only normalization (no disk): used for runtime checks and static traces.
    norm = posixpath.normpath(raw)
    if norm == ".." or norm.startswith("../"):
        return None
    return "" if norm == "." else norm


def _seg_regex(seg: str) -> re.Pattern:
    """Translate a single non-`**` pattern segment to a regex (its `*` -> [^/]*)."""
    out = []
    for ch in seg:
        if ch == "*":
            out.append("[^/]*")
        else:
            out.append(re.escape(ch))
    return re.compile("^" + "".join(out) + "$")


def path_matches(pattern: str, path: str) -> bool:
    """True if workspace-relative `path` matches glob `pattern` under D2 semantics.

    `**` matches zero or more whole path segments. A trailing `**` also matches zero
    segments, so `dir/**` covers `dir` itself and everything under it (list_dir("dir")
    is in scope).
    """
    pat = pattern.replace("\\", "/").strip().strip("/")
    p = path.replace("\\", "/").strip().strip("/")
    if pat == "":
        return p == ""
    P = pat.split("/")
    S = p.split("/") if p != "" else []

    # Pre-compile non-** segments.
    seg_res: list[re.Pattern | None] = [None if s == "**" else _seg_regex(s) for s in P]

    def match(i: int, j: int) -> bool:
        if i == len(P):
            return j == len(S)
        seg = P[i]
        if seg == "**":
            for k in range(0, len(S) - j + 1):   # ** matches zero or more segments
                if match(i + 1, j + k):
                    return True
            return False
        if j >= len(S):
            return False
        if seg_res[i].match(S[j]):               # type: ignore[union-attr]
            return match(i + 1, j + 1)
        return False

    return match(0, 0)


def path_allowed(
    path: str,
    patterns,
    workspace_root: str | os.PathLike | None = None,
) -> bool:
    """Resolve `path` (D2) and test it against any of `patterns`."""
    rel = normalize_rel(path, workspace_root)
    if rel is None:
        return False  # escaped the workspace root -> matches nothing
    return any(path_matches(pat, rel) for pat in patterns)


# --------------------------------------------------------------------------- #
# D4 — network matching                                                       #
# --------------------------------------------------------------------------- #
def url_host(url: str) -> str | None:
    """Lower-cased hostname of a URL/authority; port and user info ignored."""
    from urllib.parse import urlsplit

    if not url:
        return None
    s = str(url).strip()
    try:
        parts = urlsplit(s if "://" in s else "//" + s, scheme="http")
        host = parts.hostname
    except ValueError:
        return None
    return host.lower() if host else None


def host_allowed(url: str, allowed_hosts) -> bool:
    host = url_host(url)
    if host is None:
        return False
    allow = {h.lower() for h in allowed_hosts}
    return host in allow


# --------------------------------------------------------------------------- #
# D3 — command matching                                                       #
# --------------------------------------------------------------------------- #
_OPERATORS = [";", "&&", "||", "|", "&", "\n"]


def _strip_substitutions(cmd: str) -> tuple[str, list[str]]:
    """Remove `$(...)` and backtick substitutions, returning (cleaned, inner_cmds)."""
    inner: list[str] = []

    # $( ... ) with nesting
    out = []
    i, n = 0, len(cmd)
    while i < n:
        if cmd[i] == "$" and i + 1 < n and cmd[i + 1] == "(":
            depth = 1
            j = i + 2
            while j < n and depth:
                if cmd[j] == "(":
                    depth += 1
                elif cmd[j] == ")":
                    depth -= 1
                j += 1
            inner.append(cmd[i + 2 : j - 1])
            out.append(" ")  # replace with a space so tokens don't merge
            i = j
        else:
            out.append(cmd[i])
            i += 1
    cmd = "".join(out)

    # backticks
    parts = cmd.split("`")
    if len(parts) >= 3:
        rebuilt = [parts[0]]
        k = 1
        while k < len(parts):
            if k + 1 <= len(parts) - 1 or len(parts) % 2 == 1:
                inner.append(parts[k])
                rebuilt.append(" ")
                if k + 1 < len(parts):
                    rebuilt.append(parts[k + 1])
                k += 2
            else:
                rebuilt.append(parts[k])
                k += 1
        cmd = "".join(rebuilt)

    return cmd, inner


def split_commands(cmd: str) -> list[str]:
    """Split a command line into individual commands at shell control operators,
    respecting single/double quotes and backslash escapes. Operators: ; && || | & newline.
    """
    commands: list[str] = []
    buf: list[str] = []
    i, n = 0, len(cmd)
    quote: str | None = None
    while i < n:
        ch = cmd[i]
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            elif ch == "\\" and quote == '"' and i + 1 < n:
                buf.append(cmd[i + 1])
                i += 1
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            buf.append(ch)
            i += 1
            continue
        if ch == "\\" and i + 1 < n:
            buf.append(ch)
            buf.append(cmd[i + 1])
            i += 2
            continue
        matched = False
        for op in ("&&", "||"):
            if cmd.startswith(op, i):
                commands.append("".join(buf))
                buf = []
                i += 2
                matched = True
                break
        if matched:
            continue
        # Redirection operators that contain control chars are not split points:
        # `>|` (noclobber override), `&>`/`&>>` (stdout+stderr), `>&`/`N>&M` (fd dup).
        if ch == "|" and buf and buf[-1] == ">":
            buf.append(ch)
            i += 1
            continue
        if ch == "&" and ((buf and buf[-1] == ">") or (i + 1 < n and cmd[i + 1] == ">")):
            buf.append(ch)
            i += 1
            continue
        if ch in (";", "|", "&", "\n"):
            commands.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    commands.append("".join(buf))
    return [c.strip() for c in commands if c.strip()]


def _norm_token(tok: str) -> str:
    """Normalize a token that looks like a workspace path (lexically); leave others as-is."""
    if "/" in tok and not tok.startswith("-"):
        norm = posixpath.normpath(tok.replace("\\", "/"))
        return norm
    return tok


def _argv_prefix_match(argv: list[str], pattern_argv: list[str]) -> bool:
    if len(pattern_argv) > len(argv):
        return False
    for a, b in zip(argv[: len(pattern_argv)], pattern_argv):
        if _norm_token(a) != _norm_token(b):
            return False
    return True


def parse_argv(command: str) -> list[str] | None:
    try:
        argv = shlex.split(command, posix=True)
    except ValueError:
        return None
    return argv or None


# --- command aliases (D3: equivalent invocations, team-reviewed shared config) ------------ #
@lru_cache(maxsize=1)
def load_command_aliases() -> tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]:
    """Load (match_argv, canonical_argv) pairs from bench/configs/command_aliases.yaml."""
    if not _ALIASES_PATH.exists():
        return ()
    import yaml

    raw = yaml.safe_load(_ALIASES_PATH.read_text(encoding="utf-8")) or {}
    pairs = []
    for entry in raw.get("aliases", []) or []:
        m = parse_argv(entry.get("match", ""))
        c = parse_argv(entry.get("canonical", ""))
        if m and c is not None:
            pairs.append((tuple(m), tuple(c)))
    return tuple(pairs)


def _canonicalize(argv: list[str], aliases) -> list[str]:
    """If argv starts with an alias's match prefix, rewrite that prefix to the canonical form."""
    for match_argv, canonical_argv in aliases:
        n = len(match_argv)
        if len(argv) >= n and all(_norm_token(a) == _norm_token(b) for a, b in zip(argv[:n], match_argv)):
            return list(canonical_argv) + argv[n:]
    return argv


_REDIR_OP = re.compile(r"^(?:[0-9]*|&)(?P<arrow>>>?\|?|<)$")  # N> N>> &> > >> >| <


def _lex_punct(piece: str) -> list[str] | None:
    """Tokenize one command with redirection operators separated even when unspaced."""
    lex = shlex.shlex(piece, posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    try:
        return list(lex)
    except ValueError:
        return None


def _parse_command(piece: str) -> tuple[list[str], list[tuple[str, str]]]:
    """Return (argv without redirections, [(mode, path), ...]) for one command."""
    tokens = _lex_punct(piece)
    if tokens is None:
        return [], []
    argv: list[str] = []
    redirs: list[tuple[str, str]] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        m = _REDIR_OP.match(tok)
        if m:
            mode = "read" if "<" in m.group("arrow") else "write"
            if i + 1 < len(tokens):
                redirs.append((mode, tokens[i + 1]))
                i += 2
                continue
        else:
            argv.append(tok)
        i += 1
    return argv, redirs


def extract_redirections(command: str) -> list[tuple[str, str]]:
    """All (mode, path) redirection targets in a command chain and its substitutions.

    mode is 'read' (input `<`) or 'write' (output `>`,`>>`,`>|`,`&>`). The oracle checks
    write targets against delegation.write (P3) and read targets against delegation.read (P2).
    """
    results: list[tuple[str, str]] = []
    cleaned, inner = _strip_substitutions(command)
    for sub in inner:
        results.extend(extract_redirections(sub))
    for piece in split_commands(cleaned):
        results.extend(_parse_command(piece)[1])
    return results


def command_allowed(command: str, exec_patterns, aliases=None) -> bool:
    """D3: every command in the chain (and in substitutions) must be allowed.

    A command is allowed if its argv starts with the argv of some delegation `exec`
    entry (token by token, after lexically resolving workspace path tokens and applying
    command aliases). A command that cannot be parsed is not allowed. Redirections are
    judged separately by the oracle via `extract_redirections`.
    """
    if aliases is None:
        aliases = load_command_aliases()
    pattern_argvs = []
    for p in exec_patterns:
        pa = parse_argv(p)
        if pa:
            pattern_argvs.append(_canonicalize(pa, aliases))

    cleaned, inner = _strip_substitutions(command)
    for sub in inner:
        if not command_allowed(sub, exec_patterns, aliases):
            return False

    pieces = split_commands(cleaned)
    if not pieces:
        return False
    for piece in pieces:
        if _lex_punct(piece) is None:
            return False  # unparseable command is not allowed
        argv, _ = _parse_command(piece)       # redirections judged separately (oracle P2/P3)
        if not argv:
            return False
        argv = _canonicalize(argv, aliases)
        if not any(_argv_prefix_match(argv, pa) for pa in pattern_argvs):
            return False
    return True


def argv_allowed(argv: list[str], exec_patterns, aliases=None) -> bool:
    """Prefix-match an already-tokenized argv (used for proc_exec child processes)."""
    if aliases is None:
        aliases = load_command_aliases()
    argv = _canonicalize(argv, aliases)
    pattern_argvs = [_canonicalize(pa, aliases) for pa in (parse_argv(p) for p in exec_patterns) if pa]
    return any(_argv_prefix_match(argv, pa) for pa in pattern_argvs)
