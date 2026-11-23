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
