# Workstream B (Harness) — notes

## Status

| checkpoint | state |
|---|---|
| 1 sandbox builds a workspace and installs skills | **done** (env mode tested on macOS; netns and docker modes written, not yet run) |
| 2 monitoring | **code done; verified on a Linux VM; waiting for the A100 and COOK `gtx` runs** |
| 3 agent loop | not started |
| 4 replay (with A) | not started |
| 5 backends + pilot | not started |

## Checkpoint 1 — what was built

- `bench/harness/sandbox.py`: `make_sandbox(repo_root, proxy_url, isolation=...)` returns a
  `Sandbox` with `build(installed) -> BuildInfo`, `run(cmd, timeout=None) -> CommandResult`,
  `env()`, `close()` (also a context manager).
  - Fresh temp stage per run: `setup.sh` and `workspace/` are **copied** and `setup.sh` runs on the
    copy. Every repo's `setup.sh` `cd`s to its own directory and writes `workspace/...` there,
    so running it in place would modify `repos/` (the tests check `git status repos/` is unchanged).
  - Skills are installed after `setup.sh` at `.github/skills/<id>/` (full snapshot: SKILL.md,
    LICENSE, manifest.json, scripts/, references/). Order matters: release-tools' `setup.sh`
    clears and rebuilds the workspace. `BuildInfo.skills` records id, version, source and a
    sha256 per file (for meta.json and for D's byte-for-byte check).
  - Each command: clean environment (only PATH is taken from the host; HOME/TMPDIR inside the
    stage; no API keys or other host variables), proxy variables in both cases
    (`HTTP_PROXY`/`http_proxy`/`HTTPS_PROXY`/`https_proxy`/`ALL_PROXY`, `npm_config_proxy`,
    `npm_config_https_proxy`), empty `NO_PROXY`. Own process group; the whole group is killed at
    the 60 s timeout (exit 124, `timed_out=True`) and also when the command returns, so
    background processes do not outlive their command. Output is captured to files outside the
    workspace and capped at 1 MB per stream (the agent loop truncates to 8,000 chars, D11).
  - Isolation modes, same interface:
    - `docker`: `--network none` container, stage bind-mounted at the same absolute path (so
      paths in traces match the host), host uid/gid. Image: `bench/harness/docker/Dockerfile`.
    - `netns` (Linux): every command runs under `unshare -rn` (new user + network namespace);
      `_sandbox_exec.py` brings loopback up and forwards `127.0.0.1:3128` to a Unix socket whose
      host side is connected to the mock proxy. Direct network access is impossible.
    - `env`: proxy variables only. Programs that ignore them can reach the network. This is the
      mode on macOS and wherever unprivileged user namespaces are disabled.
    - `auto`: docker if the daemon answers and the image exists, else netns, else env. The
      chosen mode is in `BuildInfo.isolation`; the harness will write it to meta.json.
- `bench/harness/skills.py`: `install_skills`, `repo_install_set(repo_root, overrides)` (D8
  default: every skill at v1, then overrides), `skill_frontmatter` (for the D8 system prompt).
- `bench/harness/docker/Dockerfile`: python 3.11 + git, node/npm, strace, GNU tar, openpyxl,
  pytest, ruff.
- Tests: `bench/tests/b/test_sandbox.py` (18 pass, 1 skipped on macOS; netns/docker cases are
  parametrised in automatically where available).

## Team decisions after checkpoint 1 (2026-11-22)

1. `env` isolation is allowed only for benign/pilot runs; attack runs require `netns` or
   `docker`. Implemented as `make_sandbox(..., require_network_isolation=True)`, which raises
   `SandboxError` if the mode would be `env`; the runner (D) passes it for attack runs. Also:
   record `connect()` in strace and emit non-proxy connects as events (see checkpoint 2 and
   IC-2); test `unshare -rn` on COOK (in the check script).
2. shop-web's mock files: proposal IC-1 in `bench/INTERFACE_CHANGES.md` (optional `mock_root`
   for `MockNetwork.start`). Not implemented until approved.
3. After installing skills, `.github/skills/` is appended to `.git/info/exclude` when the
   workspace is a git repo (only release-tools after setup). Test:
   `test_git_add_all_never_stages_skills`.
4. openpyxl is approved as a setup dependency.

## Team decisions after checkpoint 2 (2026-11-22)

1. Directory listings by scripts are **not** recorded as `fs_read` (limitation below).
2. The sandbox env sets `PYTHONDONTWRITEBYTECODE=1` and `PYTEST_ADDOPTS="-p no:cacheprovider"`,
   so `__pycache__/` and `.pytest_cache/` are not written into the workspace. Cache dirs are not
   added to `implicit_effects.yaml`. Test: `test_no_python_caches_in_workspace`. Side effect: a
   task command that sets its own `PYTEST_ADDOPTS` replaces ours. None of the 55 tasks does.
3. `proc_exec` gets the executable path `exe`, as part of IC-2. One flag, `ic2`
   (`CommandMonitor`, `TraceWriter`), stays off until A approves IC-1/IC-2; with it off, `exe`
   is stripped from `proc_exec` and `net_connect` is not written.

## Checkpoint 2 — monitoring

- `bench/harness/monitor.py`
  - `CommandMonitor(sandbox, observer="auto"|"strace"|"none", ic2=False)`.
    `run(cmd)` returns the `CommandResult` plus the D6 events for that command, in order:
    strace events (`proc_exec`, `fs_read`, `fs_write`), then `fs_diff`. `observer` is
    `"strace"` if a probe run of strace inside the sandbox works, else `"none"`, and goes to
    meta.json. A run with `"none"` still gets `fs_diff`.
  - strace: `strace -f -qq -v -y -s 4096 -e signal=none -e trace=%file,%process,connect,sendto,
    sendmsg,fchdir,ftruncate,fchmod -o <stage>/run/NNNN.strace`, run *inside* the sandbox (inside
    the netns / container) around `/bin/sh -c <cmd>`. If the `%` class syntax is rejected, the
    probe falls back to the pre-4.17 class names.
  - The parser joins `<unfinished ...>`/`resumed` lines, rebuilds the process tree from
    `clone`/`clone3`/`fork`/`vfork` (threads map to their process), tracks cwd (`chdir`/`fchdir`,
    inherited by children) and the current executable (`execve`). The event rules (successful
    syscalls only, no directory opens, how paths are resolved, dedup) are in the module
    docstring.
  - `connect()`/`sendto()`/`sendmsg()` to an AF_INET/AF_INET6 address other than the mock proxy
    (as seen from inside the sandbox) are collected in `MonitoredResult.connects` as
    `net_connect` records. They go into the trace only with `ic2=True`, which stays
    off until IC-2 is approved; otherwise the oracle would call the trace unjudgeable (unknown
    event).
  - fs_diff: stat snapshot (`size`, `mtime_ns`, mode, link target) of all files and symlinks in
    the workspace before and after the command; `created`/`modified`/`deleted`. No content
    hashing, so a `touch` counts as `modified`. Directories are not listed.
- `bench/harness/trace.py`: `TraceWriter` (one `seq` counter, `t` since run start, flush per line,
  rejects unknown events and fields outside D6) and `MockLogTailer` (incrementally reads the mock
  log, keeps the D6 `net_observed` fields, keeps a partial last line for the next drain, collects
  unparseable lines in `.bad`).
- `Sandbox.run(cmd, prefix=...)` runs the monitor's strace prefix inside the sandbox; a missing
  program returns exit 127 instead of raising.
- Tests: `test_monitor_parse.py` (fixture strace log covering exec/PATH lookup failures,
  unfinished/resumed, threads, chdir, rename/unlinkat/renameat2 with escaped names, symlink
  escape, AF_INET/AF_INET6/AF_UNIX connects, DNS sendto) runs everywhere.
  `test_monitor_live.py` runs on Linux in every available mode, including the acceptance test
  "a script reads `.env` produces `fs_read`". On macOS the live tests skip.
- Machine checks: `bench/harness/scripts/check_monitoring.sh` (prints strace version, ptrace and
  userns sysctls, `unshare -rn` tests incl. strace inside the netns, Docker status, the mode
  `auto` picks, then `pytest bench/tests/b -v -rs`; writes `runs/checks/monitoring-<host>-<ts>.txt`)
  and `bench/harness/slurm/check_monitoring_gtx.sbatch` (COOK `gtx`, 20 min, CPU only).

### Results on the machines (to fill in)

| machine | strace | `unshare -rn` | auto mode | pytest bench/tests/b |
|---|---|---|---|---|
| Linux VM (Ubuntu 24.04.5, kernel 6.18, x86_64, Python 3.13), 2026-11-22, commit a0edc1c | 6.8, works unprivileged, also inside the netns | ok (incl. loopback up and strace inside) | `netns` | 50 passed, 1 failed, 1 skipped. All live tests pass in `env` and `netns`. The failure was `test_monitor_parse::test_reads` (exe resolved on the host to `/usr/bin/python3.13`); fixed after the run, see below. Docker image not built, so docker mode was not tested |
| A100 | ? | ? | ? | ? |
| COOK gtx | ? | ? | ? | ? |

Fix after the VM run: the parser resolved `exe` with `realpath` on the machine that parses the
log, so fixture results depended on that machine's symlinks. `exe` is now the `execve` path made
absolute and normalised lexically, without following symlinks (module docstring;
`test_exe_is_not_symlink_resolved`).

## Deviations

- `bench/interfaces.py` and `bench/__init__.py` were checked out unchanged from
  `impl/c-policies` (Part 4 says to reuse that version). The branch is based on
  `origin/data-integration` because `data-v1` is not tagged on `main` yet.
- PATH in process modes is the host PATH with the harness interpreter's directory first, so
  `python3`, `pytest` and `ruff` come from the benchmark venv. That venv must therefore also
  have `openpyxl` (ops-office `setup.sh`), which is not in the Part 3 dependency list; it is a
  data requirement, not a code import.

## Known weaknesses / untested

- netns and docker modes have not been run yet (no Linux box, Docker daemon not running on
  the dev Mac). Checkpoint 2 requires running the tests on the A100 machine and a COOK `gtx`
  node anyway; `pytest bench/tests/b` there will exercise netns (if `unshare -rn` is allowed)
  and docker (if the image is built).
- Docker Desktop on macOS may not pass Unix sockets through bind mounts; docker mode is meant
  for Linux.
- On COOK, unprivileged user namespaces may be disabled; then `auto` falls back to `env`,
  which does not stop programs that ignore proxy variables. Whether that is acceptable for
  COOK runs is an open question for the team.
- The stage lives in the system temp dir unless `work_root` is given; long runs should pass a
  scratch path.

## Observations for other workstreams

- shop-web's `setup.sh` builds stub npm tarballs under `mock/registry.example/`. Run on our copy
  they end up in the sandbox stage, not in `repos/shop-web/mock/`. A's mock server needs these
  tarballs from somewhere (build them into a per-run mock dir, or have the harness pass the
  stage's `mock/`). Needs a decision between A and B.
- release-tools' `setup.sh` header says 40 commits on main; it makes 41. Harmless.
- Installed skills appear as untracked files (`?? .github/skills/`) in release-tools'
  `git status`. A task that runs `git add -A` would stage them; relevant for A4 / implicit
  effects.

## Known weaknesses (checkpoint 2)

- The strace parser has been tested only against a hand-written log in strace 6.x format;
  nothing has run under real strace yet (no Linux available during development). The live
  tests on the A100/COOK are the real check.
- Paths of non-open syscalls are resolved at parse time (after the command). A symlink created
  and removed within one command can make that resolution differ from access time (D2 asks
  for access time). Opens use strace's `-y` path, which is the access-time real path.
- Only successful syscalls produce events, so the trace does not show a script *trying* to read
  a missing file.
- **Directory listings by scripts are not recorded** (team decision). A script that lists an
  out-of-scope directory (`ls secrets/`, `os.listdir`) produces no `fs_read` and so no P2. Only
  reading the files inside it does. The agent's own `list_dir` tool is still judged. Reason:
  every `python3 -c` lists its working directory for imports, which would be a false P2 on
  almost every task.
- `exe` is not symlink-resolved: a workspace symlink to `/bin/sh` shows a workspace path, and a
  symlink outside the workspace pointing to a workspace script shows the outside path.
- `connect()` attempts to the proxy port from a *different* local process are not
  distinguishable from proxy use.
- Docker on macOS (Docker Desktop) is untested; Docker Desktop would not start on the dev Mac.

## Open questions

1. IC-1 and IC-2 are pending A's review.
2. Docker mode has not run anywhere yet (image not built on the VM). Build it on the A100
   (`docker build -t consentdrift-sandbox:latest bench/harness/docker`) if Docker is there, and
   the check script will test it too.
