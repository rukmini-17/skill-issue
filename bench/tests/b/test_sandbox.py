"""B1 acceptance: the sandbox builds a workspace and installs skills."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import pytest

from bench.harness.sandbox import (
    SandboxError, docker_available, make_sandbox, netns_available,
)
from bench.harness.skills import repo_install_set, skill_frontmatter, tree_hashes
from bench.interfaces import SkillVersion

from b_helpers import REPOS, ROOT, url as _url
REPO_IDS = ["ops-office", "orders-api", "release-tools", "shop-web"]

MODES = ["env"]
if netns_available():
    MODES.append("netns")
if docker_available():
    MODES.append("docker")


def _repo_status() -> str:
    return subprocess.run(["git", "status", "--porcelain", "--ignored", "--", "repos"], cwd=ROOT,
                          capture_output=True, text=True).stdout


@pytest.fixture(scope="module")
def repos_status_before():
    return _repo_status()


# ------------------------------------------------------------------ tests ---

@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("repo_id", REPO_IDS)
def test_build_installs_every_skill(repo_id, mode, tmp_path, repos_status_before):
    root = REPOS / repo_id
    installed = repo_install_set(root)
    assert installed, "repo has skills"
    with make_sandbox(root, "http://127.0.0.1:9", isolation=mode, work_root=tmp_path) as sb:
        info = sb.build(installed)
        assert info.isolation == mode
        assert info.setup.exit == 0
        ws = sb.workspace
        assert ws.is_dir() and ws.resolve() == ws
        assert not ws.is_relative_to(REPOS.resolve())
        assert {s.skill_id for s in info.skills} == set(installed)
        for s in info.skills:
            dest = ws / ".github" / "skills" / s.skill_id
            assert s.path == f".github/skills/{s.skill_id}"
            assert (dest / "SKILL.md").is_file()
            assert s.version == "v1"
            # byte-for-byte copy of the snapshot
            assert tree_hashes(dest) == tree_hashes(installed[s.skill_id].root) == s.files
        # the workspace really is the repo's workspace (one shipped file per repo)
        shipped = sorted(p for p in (root / "workspace").rglob("*") if p.is_file() and ".git" not in p.parts)
        assert shipped
        for p in shipped[:20]:
            assert (ws / p.relative_to(root / "workspace")).exists()
        json.dumps(info.to_json())
    # building never modifies the benchmark data
    assert _repo_status() == repos_status_before


def test_setup_derived_state(tmp_path):
    with make_sandbox(REPOS / "ops-office", "http://127.0.0.1:9", isolation="env", work_root=tmp_path) as sb:
        sb.build(repo_install_set(REPOS / "ops-office"))
        assert (sb.workspace / "finance" / "expenses.xlsx").is_file()
        assert (sb.workspace / "drafts").is_dir()
    with make_sandbox(REPOS / "release-tools", "http://127.0.0.1:9", isolation="env", work_root=tmp_path) as sb:
        sb.build(repo_install_set(REPOS / "release-tools"))
        r = sb.run("git rev-list --count main && git tag")
        assert r.exit == 0
        assert int(r.stdout.split()[0]) >= 40 and "v0.3.0" in r.stdout  # setup.sh header says 40; it makes 41
        # skills installed after setup.sh (which rebuilds the tree) survive
        assert (sb.workspace / ".github/skills/git-commit/SKILL.md").is_file()


def test_target_version_overrides_v1(tmp_path):
    root = REPOS / "ops-office"
    v2 = SkillVersion("ops-office", "meeting-minutes", "benign_v2",
                      root / "skills/meeting-minutes/versions/benign_v2")
    installed = repo_install_set(root, {"meeting-minutes": v2})
    with make_sandbox(root, "http://127.0.0.1:9", isolation="env", work_root=tmp_path) as sb:
        info = sb.build(installed)
        mm = {s.skill_id: s for s in info.skills}["meeting-minutes"]
        assert mm.version == "benign_v2"
        got = (sb.workspace / ".github/skills/meeting-minutes/SKILL.md").read_bytes()
        assert got == (v2.root / "SKILL.md").read_bytes()
        others = [s for s in info.skills if s.skill_id != "meeting-minutes"]
        assert others and all(s.version == "v1" for s in others)


def test_sandboxes_are_independent(tmp_path):
    root = REPOS / "orders-api"
    a = make_sandbox(root, "http://127.0.0.1:9", isolation="env", work_root=tmp_path)
    b = make_sandbox(root, "http://127.0.0.1:9", isolation="env", work_root=tmp_path)
    with a, b:
        a.build(repo_install_set(root))
        b.build(repo_install_set(root))
        assert a.workspace != b.workspace
        assert a.run("echo hi > reports/x.txt").exit == 0
        assert not (b.workspace / "reports/x.txt").exists()


def test_close_removes_stage_unless_keep(tmp_path):
    root = REPOS / "orders-api"
    sb = make_sandbox(root, "http://127.0.0.1:9", isolation="env", work_root=tmp_path)
    sb.build(repo_install_set(root))
    stage = sb.stage
    sb.close()
    assert not stage.exists()
    sb = make_sandbox(root, "http://127.0.0.1:9", isolation="env", work_root=tmp_path, keep=True)
    sb.build(repo_install_set(root))
    sb.close()
    assert sb.workspace.is_dir()


@pytest.mark.parametrize("mode", MODES)
def test_command_timeout_kills_group(mode, tmp_path):
    root = REPOS / "orders-api"
    with make_sandbox(root, "http://127.0.0.1:9", isolation=mode, work_root=tmp_path,
                      command_timeout=1) as sb:
        sb.build(repo_install_set(root))
        t0 = time.monotonic()
        r = sb.run("sleep 30; echo late")
        assert r.timed_out and r.exit == 124
        assert time.monotonic() - t0 < 15
        assert "late" not in r.stdout
        # background children do not outlive the command
        t0 = time.monotonic()
        r = sb.run("(sleep 2; echo bg > reports/bg.txt) & echo started")
        assert r.exit == 0 and "started" in r.stdout and not r.timed_out
        time.sleep(3)
        assert not (sb.workspace / "reports/bg.txt").exists()


def test_default_timeout_is_60s():
    from bench.harness import sandbox
    assert sandbox.COMMAND_TIMEOUT == 60


@pytest.mark.parametrize("mode", MODES)
def test_exit_code_output_and_cwd(mode, tmp_path):
    root = REPOS / "orders-api"
    with make_sandbox(root, "http://127.0.0.1:9", isolation=mode, work_root=tmp_path) as sb:
        sb.build(repo_install_set(root))
        r = sb.run("pwd; echo err >&2; exit 3")
        assert r.exit == 3
        assert Path(r.stdout.strip()).resolve() == sb.workspace
        assert r.stderr.strip() == "err"


@pytest.mark.parametrize("mode", MODES)
def test_environment_is_clean(mode, tmp_path, monkeypatch):
    monkeypatch.setenv("CDB_TEST_SECRET_KEY", "sk-should-not-leak")
    root = REPOS / "orders-api"
    with make_sandbox(root, "http://127.0.0.1:9", isolation=mode, work_root=tmp_path) as sb:
        sb.build(repo_install_set(root))
        r = sb.run("env")
        env = dict(line.split("=", 1) for line in r.stdout.splitlines() if "=" in line)
        assert "CDB_TEST_SECRET_KEY" not in env
        assert "sk-should-not-leak" not in r.stdout
        assert Path(env["HOME"]).resolve() == sb.home
        for k in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"):
            assert env[k].startswith("http://127.0.0.1:")
        assert env["NO_PROXY"] == "" and env["no_proxy"] == ""
        assert env["PYTHONDONTWRITEBYTECODE"] == "1"
        assert env["PYTEST_ADDOPTS"] == "-p no:cacheprovider"


@pytest.mark.parametrize("mode", MODES)
def test_no_python_caches_in_workspace(mode, tmp_path):
    root = REPOS / "orders-api"
    with make_sandbox(root, "http://127.0.0.1:9", isolation=mode, work_root=tmp_path) as sb:
        sb.build(repo_install_set(root))
        (sb.workspace / "reports/m.py").write_text("X = 1\n")
        (sb.workspace / "reports/test_m.py").write_text("from m import X\n\ndef test_x():\n    assert X == 1\n")
        r = sb.run("python3 -c 'import sys; sys.path.insert(0, \"reports\"); import m'")
        assert r.exit == 0, r.stderr
        r = sb.run("cd reports && python3 -m pytest -q test_m.py")
        assert r.exit == 0, r.stdout + r.stderr
        made = [p for p in sb.workspace.rglob("*") if p.name in ("__pycache__", ".pytest_cache")]
        assert made == []


@pytest.mark.parametrize("mode", MODES)
def test_http_goes_through_proxy(mode, proxy, tmp_path):
    root = REPOS / "ops-office"
    with make_sandbox(root, _url(proxy), isolation=mode, work_root=tmp_path) as sb:
        sb.build(repo_install_set(root))
        # a child process (python) honouring HTTP_PROXY
        r = sb.run("python3 -c \"import urllib.request as u; "
                   "print(u.urlopen('http://templates.example/minutes/x.md', timeout=10).read().decode())\"")
        assert r.exit == 0, r.stderr
        assert r.stdout.strip() == "ok"
        # curl too (also honours http_proxy), with a body
        if subprocess.run(["sh", "-c", "command -v curl"], capture_output=True).returncode == 0:
            r = sb.run("curl -s -X POST --data hello http://mail.example/send")
            assert r.exit == 0 and r.stdout == "ok", r.stderr
    paths = [s["path"] for s in proxy.seen]
    assert "http://templates.example/minutes/x.md" in paths
    hosts = {s["host"] for s in proxy.seen}
    assert "templates.example" in hosts


@pytest.mark.skipif("netns" not in MODES and "docker" not in MODES,
                    reason="needs Linux user/network namespaces or Docker")
@pytest.mark.parametrize("mode", [m for m in MODES if m != "env"])
def test_direct_network_is_denied(mode, proxy, tmp_path):
    root = REPOS / "orders-api"
    port = proxy.server_address[1]
    with make_sandbox(root, _url(proxy), isolation=mode, work_root=tmp_path) as sb:
        sb.build(repo_install_set(root))
        # bypassing the proxy: connect straight to the host's proxy port
        r = sb.run(f"python3 -c \"import socket; socket.create_connection(('127.0.0.1', {port}), timeout=3)\"")
        assert r.exit != 0
        r = sb.run("python3 -c \"import socket; socket.create_connection(('192.0.2.1', 80), timeout=3)\"")
        assert r.exit != 0


def test_bad_inputs(tmp_path):
    with pytest.raises(SandboxError):
        make_sandbox(REPOS / "ops-office", "127.0.0.1:9", isolation="env", work_root=tmp_path)
    with pytest.raises(SandboxError):
        make_sandbox(tmp_path, "http://127.0.0.1:9", isolation="env", work_root=tmp_path)
    with pytest.raises(ValueError):
        make_sandbox(REPOS / "ops-office", "http://127.0.0.1:9", isolation="bogus")
    root = REPOS / "orders-api"
    with make_sandbox(root, "http://127.0.0.1:9", isolation="env", work_root=tmp_path) as sb:
        with pytest.raises(SandboxError):
            sb.run("true")                       # before build
        bad = {"x": SkillVersion("orders-api", "x", "v1", tmp_path)}
        with pytest.raises(ValueError):
            sb.build(bad)                        # snapshot without SKILL.md


@pytest.mark.parametrize("repo_id", REPO_IDS)
def test_every_skill_has_name_and_description(repo_id):
    for sid, sv in repo_install_set(REPOS / repo_id).items():
        fm = skill_frontmatter(sv.root / "SKILL.md")
        assert fm.get("name") and fm.get("description"), sid


def test_git_add_all_never_stages_skills(tmp_path):
    root = REPOS / "release-tools"
    with make_sandbox(root, "http://127.0.0.1:9", isolation="env", work_root=tmp_path) as sb:
        sb.build(repo_install_set(root))
        ex = (sb.workspace / ".git/info/exclude").read_text().splitlines()
        assert ".github/skills/" in ex
        st = sb.run("git status --porcelain --untracked-files=all")
        assert ".github/skills" not in st.stdout
        r = sb.run("git add -A && git diff --cached --name-only")
        assert r.exit == 0, r.stderr
        assert r.stdout.strip(), "the pending edits are staged"
        assert ".github/skills" not in r.stdout
        # idempotent
        from bench.harness.sandbox import exclude_skills_from_git
        assert exclude_skills_from_git(sb.workspace)
        assert (sb.workspace / ".git/info/exclude").read_text().count(".github/skills/") == 1


def test_no_git_repo_no_exclude(tmp_path):
    root = REPOS / "orders-api"
    with make_sandbox(root, "http://127.0.0.1:9", isolation="env", work_root=tmp_path) as sb:
        sb.build(repo_install_set(root))
        assert not (sb.workspace / ".git").exists()


def test_attack_runs_refuse_env_mode(tmp_path):
    with pytest.raises(SandboxError):
        make_sandbox(REPOS / "orders-api", "http://127.0.0.1:9", isolation="env",
                     require_network_isolation=True, work_root=tmp_path)
    if "env" == __import__("bench.harness.sandbox", fromlist=["x"]).detect_isolation():
        with pytest.raises(SandboxError):
            make_sandbox(REPOS / "orders-api", "http://127.0.0.1:9", isolation="auto",
                         require_network_isolation=True, work_root=tmp_path)


def test_check_env_fails_loudly_on_a_missing_module(monkeypatch, capsys):
    from bench.harness import check_env
    real = check_env.requirement_lines
    monkeypatch.setattr(check_env, "requirement_lines",
                        lambda: real() + [("test", "cdb-definitely-not-installed", "")])
    assert check_env.main(["--isolation", "env"]) == 1
    err = capsys.readouterr().err
    assert "ENVIRONMENT CHECK FAILED" in err and "cdb_definitely_not_installed" in err
    assert "pip install -r bench/harness/requirements.txt" in err


def test_check_env_requirements_cover_skill_files():
    from bench.harness import check_env
    dists = {d for _, d, _ in check_env.requirement_lines()}
    assert {"markitdown", "pytest-cov", "coverage", "openpyxl", "pandas", "numpy", "pytest", "ruff"} <= dists
