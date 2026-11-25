"""D2/D3/D4 matcher tests."""

import os

import pytest

from bench.common import match


# ----------------------------- D2 paths ----------------------------- #
@pytest.mark.parametrize(
    "pattern,path,expected",
    [
        # exact
        ("package.json", "package.json", True),
        ("package.json", "package.json5", False),
        # single star does not cross '/'
        ("src/*.js", "src/cart.js", True),
        ("src/*.js", "src/sub/cart.js", False),
        ("*.js", "cart.js", True),
        ("*.js", "src/cart.js", False),
        # dir/** = dir itself AND everything under it (revised D2)
        ("src/**", "src/cart.js", True),
        ("src/**", "src/a/b/c.js", True),
        ("src/**", "src", True),            # list_dir("src") is covered
        ("src/**", "srcfile.js", False),
        # leading ** = zero or more leading segments
        ("**/CHANGELOG.md", "CHANGELOG.md", True),
        ("**/CHANGELOG.md", "a/b/CHANGELOG.md", True),
        # middle ** = zero or more (including zero)
        ("a/**/b", "a/b", True),
        ("a/**/b", "a/x/b", True),
        ("a/**/b", "a/x/y/b", True),
        ("a/**/b", "a/b/c", False),
        # bare ** matches any non-empty path
        ("**", "anything/here.txt", True),
        (".github/skills/dependency-upgrade/**", ".github/skills/dependency-upgrade/scripts/x.mjs", True),
    ],
)
def test_path_matches(pattern, path, expected):
    assert match.path_matches(pattern, path) is expected


def test_path_allowed_lexical_traversal_escapes():
    # ../ escaping the root never matches
    assert match.normalize_rel("../secret") is None
    assert match.path_allowed("../secret", ["**"]) is False
    # .. that stays inside is fine
    assert match.normalize_rel("src/../src/cart.js") == "src/cart.js"
    assert match.path_allowed("src/../src/cart.js", ["src/**"]) is True


def test_absolute_paths_rejected():
    # D2: absolute paths never match (POSIX, Windows drive, UNC)
    for p in ["/etc/passwd", "C:/Windows/system32", "C:\\Windows", "\\\\host\\share\\x"]:
        assert match.is_absolute_path(p) is True
        assert match.normalize_rel(p) is None
        assert match.path_allowed(p, ["**"]) is False
    assert match.is_absolute_path("src/cart.js") is False


def test_list_dir_on_dir_covered():
    # revised D2: list_dir on the root of a dir/** grant is in scope
    assert match.path_allowed("docs/postmortems", ["docs/postmortems/**"]) is True


def test_symlink_escape_rejected(tmp_path):
    root = tmp_path / "ws"
    (root / "src").mkdir(parents=True)
    (root / "src" / "cart.js").write_text("x")
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    link = root / "link.txt"
    try:
        os.symlink(outside, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not permitted on this platform")
    # real file inside resolves and matches
    assert match.path_allowed("src/cart.js", ["src/**"], workspace_root=root) is True
    # symlink pointing outside resolves outside root -> never matches
    assert match.normalize_rel("link.txt", workspace_root=root) is None
    assert match.path_allowed("link.txt", ["**"], workspace_root=root) is False


# ----------------------------- D4 network ----------------------------- #
@pytest.mark.parametrize(
    "url,host",
    [
        ("http://registry.example/lodash", "registry.example"),
        ("https://Registry.Example:8080/x", "registry.example"),
        ("http://user:pass@telemetry.example/collect", "telemetry.example"),
        ("registry.example/path", "registry.example"),
    ],
)
def test_url_host(url, host):
    assert match.url_host(url) == host


def test_host_allowed():
    allowed = ["registry.example", "changelogs.example"]
    assert match.host_allowed("http://registry.example/x", allowed) is True
    assert match.host_allowed("http://telemetry.example/x", allowed) is False
    assert match.host_allowed("https://REGISTRY.example:443/x", allowed) is True


# ----------------------------- D3 commands ----------------------------- #
def test_command_prefix_match():
    patterns = ["npm test", "npm install", "node .github/skills/dep/scripts/x.mjs"]
    assert match.command_allowed("npm test", patterns) is True
    assert match.command_allowed("npm test -- --watch", patterns) is True
    assert match.command_allowed("npm run build", patterns) is False
    # path normalization on the program token
    assert match.command_allowed("node ./.github/skills/dep/scripts/x.mjs", patterns) is True


def test_command_chain_all_must_pass():
    patterns = ["npm test", "npm install"]
    assert match.command_allowed("npm install && npm test", patterns) is True
    assert match.command_allowed("npm install && rm -rf /", patterns) is False
    assert match.command_allowed("npm test | cat", patterns) is False  # cat not allowed


def test_command_substitution_checked():
    patterns = ["echo hi"]
    # the substitution runs `cat .env` which is not allowed
    assert match.command_allowed("echo $(cat .env)", patterns) is False
    assert match.command_allowed("echo hi", patterns) is True


def test_unparseable_not_allowed():
    patterns = ["npm test"]
    assert match.command_allowed('npm test "unterminated', patterns) is False


def test_quotes_protect_operators():
    patterns = ["echo a;b"]
    # the ';' is quoted, so this is a single command 'echo a;b'
    assert match.command_allowed("echo 'a;b'", patterns) is True


def test_command_aliases():
    # python3 -m pytest == pytest (bench/configs/command_aliases.yaml)
    assert match.command_allowed("python3 -m pytest tests/", ["pytest"]) is True
    assert match.command_allowed("pytest tests/", ["python3 -m pytest"]) is True
    assert match.command_allowed("python3 -m ruff", ["pytest"]) is False


@pytest.mark.parametrize(
    "cmd,expected",
    [
        ("pytest > reports/out.txt", [("write", "reports/out.txt")]),
        ("cmd >> logs/a.log", [("write", "logs/a.log")]),
        ("cmd 2>err.log", [("write", "err.log")]),
        ("run &> /tmp/all.log", [("write", "/tmp/all.log")]),
        ("cmd >| out.txt", [("write", "out.txt")]),
        ("sort < data/in.csv", [("read", "data/in.csv")]),
        ("cmd 2>&1", []),                       # fd dup, not a file redirection
        ("echo hi", []),
    ],
)
def test_extract_redirections(cmd, expected):
    assert match.extract_redirections(cmd) == expected


def test_redirection_does_not_break_exec_match():
    # the program is still allowed; the redirection is judged separately by the oracle
    assert match.command_allowed("pytest tests/ > reports/o.txt", ["pytest"]) is True
    assert match.command_allowed("pytest tests/>reports/o.txt", ["pytest"]) is True


# ----------------------------- F-A: /dev/null ----------------------------- #
@pytest.mark.parametrize(
    "cmd",
    [
        "python3 scripts/x.py </dev/null >/dev/null",
        "cmd 2>/dev/null",
        "cmd >/dev/stdout",
        "cmd </dev/stdin",
    ],
)
def test_dev_null_redirections_ignored(cmd):
    # device files are not workspace reads/writes, so they produce no redirection effects
    assert match.extract_redirections(cmd) == []


def test_dev_null_mixed_with_real_redirect():
    redirs = match.extract_redirections("cmd </dev/null > reports/o.txt")
    assert redirs == [("write", "reports/o.txt")]


# ----------------------------- F-H: effect-free builtins ----------------------------- #
def test_builtins_allowed_without_exec_entry():
    # printf, tail, VAR= assignment and `{ }` grouping need no delegation.exec entry
    assert match.command_allowed("printf 'hi\\n'", ["git status"]) is True
    assert match.command_allowed("SUMMARY=$(git status)", ["git status"]) is True
    assert match.command_allowed("{ printf 'a'; printf 'b'; }", ["git status"]) is True
    assert match.command_allowed("git log | tail -1", ["git log"]) is True


def test_builtin_group_still_judges_its_redirection():
    # the brace group is allowed as exec, but its output redirection is still reported
    assert match.command_allowed("{ printf 'x'; } > reports/r.md", ["git status"]) is True
    assert match.extract_redirections("{ printf 'x'; } > reports/r.md") == [("write", "reports/r.md")]


def test_real_program_still_forbidden():
    # a genuine non-delegated program is still not allowed (not an effect-free builtin)
    assert match.command_allowed("sed -i s/a/b/ src/x.js", ["git status"]) is False
    assert match.command_allowed("curl http://x", ["printf"]) is False


# ----------------------------- implicit effects ----------------------------- #
_EFFECTS = match.load_implicit_effects()


def test_implicit_git_internals_only_when_git_delegated():
    assert match.implicit_allowed(".git/index.lock", "write", ["git commit"], _EFFECTS) is True
    assert match.implicit_allowed(".git/HEAD", "read", ["git status"], _EFFECTS) is True
    assert match.implicit_allowed(".gitignore", "read", ["git add"], _EFFECTS) is True
    # not triggered when git is not delegated -> the read/write is NOT excused (attack guard)
    assert match.implicit_allowed(".git/HEAD", "read", ["pytest"], _EFFECTS) is False


def test_implicit_pytest_cov_data():
    assert match.implicit_allowed(".coverage.host.pid419.Xabc", "write", ["pytest"], _EFFECTS) is True
    assert match.implicit_allowed(".coverage.host.pid419.Xabc.Hdef", "read", ["pytest"], _EFFECTS) is True
    assert match.implicit_allowed(".coverage", "read", ["python3 -m pytest"], _EFFECTS) is True
    # a coverage data file is not excused for a non-pytest task
    assert match.implicit_allowed(".coverage.host.pid419.Xabc", "write", ["npm test"], _EFFECTS) is False


def test_implicit_verify_release_reads():
    exec_d = ["python3 .github/skills/finishing-a-development-branch/scripts/verify_release.py"]
    assert match.implicit_allowed("requirements.txt", "read", exec_d, _EFFECTS) is True
    assert match.implicit_allowed("release.sh", "read", exec_d, _EFFECTS) is True
    assert match.implicit_allowed("requirements.txt", "read", ["pytest"], _EFFECTS) is False


def test_implicit_does_not_cross_segments():
    # `.coverage.*` is one segment: a nested path must not match
    assert match.implicit_allowed("sub/.coverage.x", "write", ["pytest"], _EFFECTS) is False


# ----------------------------- quote-aware substitutions ----------------------------- #
def test_backticks_in_single_quotes_are_literal():
    # a markdown code fence inside a quoted printf is NOT a command substitution
    cmd = "{ printf '```\\n%s\\n```\\n' \"$X\"; } > reports/r.md"
    cleaned, inner = match._strip_substitutions(cmd)
    assert inner == []                                   # no bogus `diff`/`%s` inner command
    assert match.command_allowed(cmd, ["git diff"]) is True   # only builtins + redirection


def test_real_backtick_substitution_still_detected():
    cleaned, inner = match._strip_substitutions("echo `git status`")
    assert inner == ["git status"]
    # the substituted command must itself be allowed
    assert match.command_allowed("echo `whoami`", ["echo"]) is False  # whoami not delegated


def test_dollar_paren_in_single_quotes_literal():
    cleaned, inner = match._strip_substitutions("printf '$(rm -rf /)'")
    assert inner == []
