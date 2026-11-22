# Workstream B (Harness) — notes

## Status

| checkpoint | state |
|---|---|
| 1 sandbox builds a workspace and installs skills | **done** (env mode tested on macOS; netns and docker modes written, not yet run) |
| 2 monitoring | not started |
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

## Open questions

1. Is `env` isolation acceptable for COOK runs if user namespaces are unavailable there?
2. Who builds shop-web's mock tarballs for the mock server (see above)?
