"""Per-run sandbox (workstream B, B1).

A sandbox owns one fresh copy of a repo's workspace and runs commands in it.

Layout of one sandbox (``stage`` is a fresh temp dir, real path)::

    stage/setup.sh       copy of the repo's setup.sh (it cd's to its own dir)
    stage/workspace/     copy of the repo's workspace/  -> the agent's workspace root
    stage/home/          $HOME for every command (git/npm/pip caches land here)
    stage/tmp/           $TMPDIR
    stage/run/           captured command output (outside the workspace)

``setup.sh`` is run on the *copy*, never in ``repos/`` (every repo's setup.sh
writes relative to its own directory). Skills are installed after setup.sh,
because release-tools' setup.sh clears and rebuilds the whole workspace.

Isolation modes (same interface; recorded in ``BuildInfo.isolation``):

``docker``  container with ``--network none``; the stage is bind-mounted at
            the same path so paths match the host's. Proxy reached through a
            Unix-socket bridge.
``netns``   Linux process sandbox: each command runs under ``unshare -rn``
            (new user + network namespace, loopback only); proxy reached
            through the same Unix-socket bridge. Other network is impossible.
``env``     process sandbox with proxy environment variables only. Programs
            that ignore ``HTTP_PROXY`` can still reach the network. Used where
            neither of the above is available (e.g. macOS development).

``auto`` picks docker (daemon reachable and image present), else netns, else
env.

Every command runs with a clean environment (nothing inherited except PATH in
the process modes), in its own process group, and is killed with its whole
group after ``command_timeout`` seconds (60 s, B1). Background processes are
killed when the command returns.
"""

from __future__ import annotations

import os
import shutil
import signal
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from bench.interfaces import SkillVersion
from bench.harness.skills import InstalledSkill, install_skills

Isolation = Literal["docker", "netns", "env"]

COMMAND_TIMEOUT = 60.0          # seconds per command (B1)
SETUP_TIMEOUT = 300.0           # seconds for setup.sh (release-tools builds 45 commits)
OUTPUT_CAP = 1_000_000          # bytes kept per stream; the agent loop truncates further (D11)
INNER_PROXY_PORT = 3128         # proxy port inside the isolated namespace / container
DOCKER_IMAGE = "consentdrift-sandbox:latest"
HELPER = Path(__file__).with_name("_sandbox_exec.py")
_GRACE = 10.0                   # extra host-side wait for the in-sandbox timeout to fire


class SandboxError(RuntimeError):
    pass


@dataclass
class CommandResult:
    cmd: str
    exit: int
    stdout: str
    stderr: str
    timed_out: bool
    duration: float
    stdout_bytes: int           # full size before OUTPUT_CAP
    stderr_bytes: int


@dataclass
class BuildInfo:
    workspace: Path
    isolation: Isolation
    setup: CommandResult
    skills: list[InstalledSkill] = field(default_factory=list)

    def to_json(self) -> dict:
        return {"workspace": str(self.workspace), "isolation": self.isolation,
                "setup": {"exit": self.setup.exit, "duration": round(self.setup.duration, 3),
                          "timed_out": self.setup.timed_out},
                "skills": [s.to_json() for s in self.skills]}


# --------------------------------------------------------------------------
# Host side of the proxy bridge: Unix socket -> mock proxy TCP port.
# --------------------------------------------------------------------------

class _BridgeHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        host, port = self.server.target  # type: ignore[attr-defined]
        try:
            up = socket.create_connection((host, port), timeout=10)
        except OSError:
            return
        up.settimeout(None)

        def pump(src: socket.socket, dst: socket.socket) -> None:
            try:
                while True:
                    data = src.recv(65536)
                    if not data:
                        break
                    dst.sendall(data)
            except OSError:
                pass
            finally:
                try:
                    dst.shutdown(socket.SHUT_WR)
                except OSError:
                    pass

        t = threading.Thread(target=pump, args=(up, self.request), daemon=True)
        t.start()
        pump(self.request, up)
        t.join(timeout=30)
        up.close()


class _UnixServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


class ProxyBridge:
    """Forwards connections on a Unix socket to ``host:port`` (the mock proxy)."""

    def __init__(self, sock_path: Path, host: str, port: int):
        self.sock_path = sock_path
        self._srv = _UnixServer(str(sock_path), _BridgeHandler)
        self._srv.target = (host, port)  # type: ignore[attr-defined]
        os.chmod(sock_path, 0o777)       # container user may differ in docker mode
        self._t = threading.Thread(target=self._srv.serve_forever, daemon=True)
        self._t.start()

    def close(self) -> None:
        self._srv.shutdown()
        self._srv.server_close()
        try:
            self.sock_path.unlink()
        except FileNotFoundError:
            pass


# --------------------------------------------------------------------------
# Availability probes
# --------------------------------------------------------------------------

def docker_available(image: str = DOCKER_IMAGE) -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        r = subprocess.run(["docker", "image", "inspect", image], capture_output=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0


def netns_available() -> bool:
    if not sys.platform.startswith("linux") or shutil.which("unshare") is None:
        return False
    try:
        r = subprocess.run(["unshare", "-rn", sys.executable, "-I", str(HELPER), "--lo-up",
                            "--", "true"], capture_output=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0


def detect_isolation(image: str = DOCKER_IMAGE) -> Isolation:
    if docker_available(image):
        return "docker"
    if netns_available():
        return "netns"
    return "env"


# --------------------------------------------------------------------------
# Sandbox
# --------------------------------------------------------------------------

def _read_capped(p: Path) -> tuple[str, int]:
    size = p.stat().st_size if p.exists() else 0
    if not size:
        return "", 0
    with p.open("rb") as fh:
        data = fh.read(OUTPUT_CAP)
    return data.decode("utf-8", errors="replace"), size


GIT_EXCLUDE_LINE = ".github/skills/"


def exclude_skills_from_git(workspace: Path) -> bool:
    """Add the installed skills to ``.git/info/exclude`` (team decision, checkpoint 1 review).

    So ``git add -A`` in a task never stages them. Only for a workspace that is a
    git repo after setup.sh (``.git`` directory). Returns True if the file was written.
    """
    git = workspace / ".git"
    if not git.is_dir() or git.is_symlink():
        return False
    ex = git / "info" / "exclude"
    ex.parent.mkdir(parents=True, exist_ok=True)
    text = ex.read_text() if ex.exists() else ""
    if GIT_EXCLUDE_LINE in text.splitlines():
        return True
    if text and not text.endswith("\n"):
        text += "\n"
    ex.write_text(text + "# installed by the ConsentDriftBench harness\n" + GIT_EXCLUDE_LINE + "\n")
    return True


def _kill_group(pid: int) -> None:
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def new_stage(work_root: Path | None = None) -> Path:
    """A fresh, empty stage directory (real path). setup.sh runs with it as its own
    directory, so files setup.sh derives (e.g. shop-web's npm tarballs under
    ``mock/``) land at ``stage/<path in repo>``: the run's IC-1 ``mock_root``."""
    if work_root is not None:
        Path(work_root).mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="cdb-", dir=work_root)).resolve()


class Sandbox:
    """One fresh workspace for one run. Use :func:`make_sandbox` to create one.

    ``proxy_url`` is what ``MockNetwork.start`` returned (``http://host:port``).
    """

    isolation: Isolation = "env"

    def __init__(self, repo_root: Path, proxy_url: str, work_root: Path | None = None,
                 command_timeout: float = COMMAND_TIMEOUT, keep: bool = False,
                 stage: Path | None = None):
        self.repo_root = Path(repo_root).resolve()
        if not (self.repo_root / "workspace").is_dir():
            raise SandboxError(f"{self.repo_root} has no workspace/")
        self.proxy_url = proxy_url
        u = urlsplit(proxy_url)
        if u.scheme != "http" or not u.hostname or u.port is None:
            raise SandboxError(f"proxy URL must be http://host:port, got {proxy_url!r}")
        self._proxy_host, self._proxy_port = u.hostname, u.port
        self.command_timeout = command_timeout
        self.keep = keep
        if work_root is not None:
            Path(work_root).mkdir(parents=True, exist_ok=True)
        # ``stage`` may be made beforehand with :func:`new_stage` so the mock can be
        # started with ``mock_root=stage`` (IC-1) before the sandbox exists.
        if stage is not None:
            stage = Path(stage).resolve()
            if not stage.is_dir() or any(stage.iterdir()):
                raise SandboxError(f"stage {stage} must be an existing empty directory")
            self.stage = stage
        else:
            self.stage = new_stage(work_root)
        self.workspace = self.stage / "workspace"
        self.home = self.stage / "home"
        self.tmp = self.stage / "tmp"
        self.rundir = self.stage / "run"
        self._n = 0
        self._closed = False
        self.built: BuildInfo | None = None

    # -- public API ---------------------------------------------------------

    def build(self, installed: dict[str, SkillVersion]) -> BuildInfo:
        """Copy the workspace, run setup.sh on the copy, install the skills."""
        if self.built is not None:
            raise SandboxError("sandbox already built")
        shutil.copytree(self.repo_root / "workspace", self.workspace, symlinks=True)
        for d in (self.home, self.tmp, self.rundir):
            d.mkdir()
        self._start()
        setup_src = self.repo_root / "setup.sh"
        if setup_src.is_file():
            shutil.copy2(setup_src, self.stage / "setup.sh")
            setup = self._exec(["/bin/sh", str(self.stage / "setup.sh")], cwd=self.stage,
                               timeout=SETUP_TIMEOUT, label="setup.sh")
            if setup.exit != 0:
                raise SandboxError(f"setup.sh failed (exit {setup.exit}, isolation {self.isolation}):\n"
                                   f"{setup.stdout[-2000:]}\n{setup.stderr[-4000:]}")
        else:
            setup = CommandResult("setup.sh", 0, "", "no setup.sh", False, 0.0, 0, 0)
        skills = install_skills(self.workspace, installed)
        exclude_skills_from_git(self.workspace)
        self.built = BuildInfo(self.workspace, self.isolation, setup, skills)
        return self.built

    def run(self, cmd: str, timeout: float | None = None, prefix: list[str] | None = None) -> CommandResult:
        """Run a shell command with the workspace as working directory.

        ``prefix`` is prepended inside the sandbox (the monitor passes ``strace ...``).
        """
        if self.built is None:
            raise SandboxError("build() first")
        return self._exec([*(prefix or []), "/bin/sh", "-c", cmd], cwd=self.workspace,
                          timeout=self.command_timeout if timeout is None else timeout, label=cmd)

    def proxy_inside(self) -> tuple[str, int]:
        """(address, port) of the mock proxy as commands inside the sandbox see it."""
        u = urlsplit(self._inner_proxy_url())
        return u.hostname or "", u.port or 0

    def new_run_file(self, suffix: str) -> Path:
        """A fresh file path in the stage's run/ dir (outside the workspace, visible inside)."""
        self._n += 1
        return self.rundir / f"{self._n:04d}{suffix}"

    def env(self) -> dict[str, str]:
        """The environment every command gets (clean; no host secrets)."""
        proxy = self._inner_proxy_url()
        env = {
            "HOME": str(self.home), "TMPDIR": str(self.tmp), "USER": "agent", "LOGNAME": "agent",
            "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TERM": "dumb", "SHELL": "/bin/sh",
            "PATH": self._path(),
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0",
            "PIP_NO_INPUT": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            # No __pycache__/ or .pytest_cache/ writes in the workspace (team decision
            # after checkpoint 2; these are not listed as implicit effects instead).
            "PYTHONDONTWRITEBYTECODE": "1", "PYTEST_ADDOPTS": "-p no:cacheprovider",
            "NO_UPDATE_NOTIFIER": "1", "npm_config_update_notifier": "false",
            "npm_config_fund": "false", "npm_config_audit": "false",
            "npm_config_proxy": proxy, "npm_config_https_proxy": proxy,
            "NO_PROXY": "", "no_proxy": "",
        }
        for k in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"):
            env[k] = proxy
        return env

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._stop()
        if not self.keep:
            shutil.rmtree(self.stage, ignore_errors=True)

    def __enter__(self) -> "Sandbox":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- hooks for subclasses -----------------------------------------------

    def _start(self) -> None: ...
    def _stop(self) -> None: ...

    def _path(self) -> str:
        # The harness's own interpreter dir first, so python3/pytest/ruff and the
        # packages setup.sh needs (openpyxl) come from the benchmark's venv.
        # Then $CDB_NODE_DIR (COOK: a user-installed Node, no module), then the host PATH.
        host = os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")
        parts = [str(Path(sys.executable).parent)]
        node_dir = os.environ.get("CDB_NODE_DIR")
        if node_dir and Path(node_dir).is_dir():
            parts.append(node_dir)
        return os.pathsep.join(parts + [p for p in host.split(os.pathsep) if p and p not in parts])

    def _inner_proxy_url(self) -> str:
        return self.proxy_url

    def _argv(self, argv: list[str], cwd: Path, timeout: float) -> list[str]:
        return argv

    def _has_inner_timeout(self) -> bool:
        return False

    # -- execution ------------------------------------------------------------

    def _exec(self, argv: list[str], cwd: Path, timeout: float, label: str) -> CommandResult:
        self._n += 1
        out_p = self.rundir / f"{self._n:04d}.out"
        err_p = self.rundir / f"{self._n:04d}.err"
        full = self._argv(argv, cwd, timeout)
        host_timeout = timeout + _GRACE if self._has_inner_timeout() else timeout
        t0 = time.monotonic()
        timed_out = False
        with out_p.open("wb") as out, err_p.open("wb") as err:
            try:
                proc = subprocess.Popen(full, cwd=cwd, env=self.env() if self._pass_env() else self._host_env(),
                                        stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                        start_new_session=True)
            except OSError as e:                 # e.g. the monitor's strace prefix is not installed
                return CommandResult(label, 127, "", f"{full[0]}: {e.strerror}", False,
                                     time.monotonic() - t0, 0, len(e.strerror or ""))
            try:
                rc = proc.wait(timeout=host_timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                rc = 124
            _kill_group(proc.pid)
            proc.wait()
        duration = time.monotonic() - t0
        if rc == 124 and self._has_inner_timeout() and duration >= timeout:
            timed_out = True
        if rc < 0:
            rc = 128 - rc
        so, so_n = _read_capped(out_p)
        se, se_n = _read_capped(err_p)
        return CommandResult(label, rc, so, se, timed_out, duration, so_n, se_n)

    def _pass_env(self) -> bool:
        return True

    def _host_env(self) -> dict[str, str]:
        return {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}


class ProcessSandbox(Sandbox):
    """``env`` or ``netns`` process sandbox."""

    def __init__(self, *a, netns: bool = False, sock_dir: Path | None = None, **kw):
        super().__init__(*a, **kw)
        self.isolation = "netns" if netns else "env"
        self._sock_dir_arg = sock_dir
        self._bridge: ProxyBridge | None = None
        self._sock_dir: Path | None = None

    def _start(self) -> None:
        if self.isolation == "netns":
            # Unix socket paths are limited to ~104 bytes, so keep it short.
            self._sock_dir = Path(tempfile.mkdtemp(prefix="cdbs-", dir=self._sock_dir_arg or "/tmp"))
            self._bridge = ProxyBridge(self._sock_dir / "p.sock", self._proxy_host, self._proxy_port)

    def _stop(self) -> None:
        if self._bridge:
            self._bridge.close()
        if self._sock_dir:
            shutil.rmtree(self._sock_dir, ignore_errors=True)

    def _inner_proxy_url(self) -> str:
        if self.isolation == "netns":
            return f"http://127.0.0.1:{INNER_PROXY_PORT}"
        return self.proxy_url

    def _has_inner_timeout(self) -> bool:
        return self.isolation == "netns"

    def _argv(self, argv: list[str], cwd: Path, timeout: float) -> list[str]:
        if self.isolation != "netns":
            return argv
        assert self._bridge is not None
        return ["unshare", "-rn", sys.executable, "-I", str(HELPER), "--lo-up",
                "--sock", str(self._bridge.sock_path), "--port", str(INNER_PROXY_PORT),
                "--timeout", str(timeout), "--", *argv]


class DockerSandbox(Sandbox):
    """Container with ``--network none``; commands via ``docker exec``."""

    isolation: Isolation = "docker"

    def __init__(self, *a, image: str = DOCKER_IMAGE, sock_dir: Path | None = None, **kw):
        super().__init__(*a, **kw)
        self.image = image
        self._sock_dir_arg = sock_dir
        self._cid: str | None = None
        self._bridge: ProxyBridge | None = None
        self._sock_dir: Path | None = None

    def _start(self) -> None:
        self._sock_dir = Path(tempfile.mkdtemp(prefix="cdbs-", dir=self._sock_dir_arg or "/tmp")).resolve()
        self._bridge = ProxyBridge(self._sock_dir / "p.sock", self._proxy_host, self._proxy_port)
        name = f"cdb-{uuid.uuid4().hex[:12]}"
        r = subprocess.run(
            ["docker", "run", "-d", "--rm", "--name", name, "--network", "none",
             "--user", f"{os.getuid()}:{os.getgid()}",
             "-v", f"{self.stage}:{self.stage}", "-v", f"{self._sock_dir}:{self._sock_dir}",
             "-v", f"{HELPER.parent}:/opt/cdb:ro", "-w", str(self.stage),
             self.image, "sleep", "infinity"],
            capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            raise SandboxError(f"docker run failed: {r.stderr.strip()}")
        self._cid = r.stdout.strip()

    def _stop(self) -> None:
        if self._cid:
            subprocess.run(["docker", "rm", "-f", self._cid], capture_output=True, timeout=60)
        if self._bridge:
            self._bridge.close()
        if self._sock_dir:
            shutil.rmtree(self._sock_dir, ignore_errors=True)

    def _path(self) -> str:
        return "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

    def _inner_proxy_url(self) -> str:
        return f"http://127.0.0.1:{INNER_PROXY_PORT}"

    def _has_inner_timeout(self) -> bool:
        return True

    def _pass_env(self) -> bool:
        return False                # env goes to the container via -e, not to the docker client

    def _host_env(self) -> dict[str, str]:
        return dict(os.environ)     # the docker client itself runs on the host

    def _argv(self, argv: list[str], cwd: Path, timeout: float) -> list[str]:
        assert self._cid and self._bridge
        envs: list[str] = []
        for k, v in self.env().items():
            envs += ["-e", f"{k}={v}"]
        return ["docker", "exec", "-w", str(cwd), *envs, self._cid,
                "python3", "-I", "/opt/cdb/_sandbox_exec.py",
                "--sock", str(self._bridge.sock_path), "--port", str(INNER_PROXY_PORT),
                "--timeout", str(timeout), "--", *argv]


def make_sandbox(repo_root: Path, proxy_url: str, isolation: str = "auto", *,
                 require_network_isolation: bool = False, **kw) -> Sandbox:
    """Create a sandbox. ``isolation``: ``auto`` | ``docker`` | ``netns`` | ``env``.

    ``require_network_isolation=True`` refuses ``env`` (raises ``SandboxError``).
    Team decision (checkpoint 1 review): ``env`` is allowed only for benign and
    pilot runs; attack runs must pass True.
    """
    image = kw.pop("image", DOCKER_IMAGE)
    if isolation == "auto":
        isolation = detect_isolation(image)
    if require_network_isolation and isolation == "env":
        raise SandboxError("network isolation required (attack run) but only env mode is available "
                           "or was requested; use docker or netns")
    if isolation == "docker":
        return DockerSandbox(repo_root, proxy_url, image=image, **kw)
    if isolation == "netns":
        return ProcessSandbox(repo_root, proxy_url, netns=True, **kw)
    if isolation == "env":
        return ProcessSandbox(repo_root, proxy_url, netns=False, **kw)
    raise ValueError(f"unknown isolation {isolation!r}")
