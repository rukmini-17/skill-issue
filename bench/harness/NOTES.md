# Workstream B (Harness) — notes

## Status

| checkpoint | state |
|---|---|
| 1 sandbox builds a workspace and installs skills | **done** (env mode tested on macOS; netns and docker modes written, not yet run) |
| 2 monitoring | **done** (green on Colab/A100 image and COOK `gtx`, both in `netns` mode, 2026-11-22) |
| 3 agent loop | **code done**; t05 passes with a scripted model; real-model run **deferred to the pilot on COOK/Colab** (see checkpoint 3) |
| 4 replay (with A) | **replay done** (2026-11-23) with A's real oracle and mock: 34/55 clean in env and netns (identical); 21 false violations listed for A in `REPLAY_FINDINGS.md` |
| 5 backends + pilot | **code done** (2026-11-23); tested against a fake server only; pilot **not launched** (humans launch) |

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
| A100 / Colab (same image as the A100 runtime, CPU runtime), 2026-11-22, commit d6c03fe | works, also inside the netns | ok | `netns` | 55 passed, 1 skipped, exit 0 |
| COOK `gtx` (AlmaLinux 9.7, strace 6.12, Python 3.13.15 via module `llm-r580/2026.09`), 2026-11-22, commit d6c03fe | works | ok | `netns` | 51 passed, 4 failed, 1 skipped. Failures: `test_script_reading_env_produces_fs_read` and `test_child_runs_workspace_script`, `[env]` and `[netns]`. The read/write/network checks all passed; the only failing asserts were `ppid != 0` on `proc_exec`. Root cause: COOK's `sh` (bash) execs the last simple command of `sh -c` in place, so `python3 x.py` / `./x.sh` *is* the traced root and correctly has `ppid` 0; Ubuntu's dash forks. A test assumption, not a monitoring bug. A real fork (`subprocess.run`) was confirmed by hand to give a distinct child pid. Tests fixed (below) |
| COOK `gtx` rerun (same environment), 2026-11-22, commit cc47933 | works | ok | `netns` | **60 passed, 1 skipped, exit 0**, including `test_forked_child_links_to_parent` and `test_exec_in_place_is_the_root` |

**Mode used:** `netns` on both production platforms (Colab/A100 and COOK). It needs no root and
blocks all direct network access. Docker mode is untested and is not needed on either platform.
It stays in the code as an option.

Fix after the COOK run: the live tests no longer assume `sh -c` forks. `_check_parent_link`
requires `ppid == 0` for the traced root and otherwise a `ppid` that is another traced
process. New tests: `test_exec_in_place_is_the_root` (forces `exec`, so the same on every
platform: same pid as the root shell, `ppid` 0, the `.env` read attributed to python),
`test_forked_child_links_to_parent` (a python script launches a child with `subprocess.run`:
the child's `ppid` is the parent python's pid and the child's `.env` read carries the child's
pid; this is the concealed_dependency path the oracle needs), and the fixture test
`test_exec_in_place_fixture` (parser, machine-independent).

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

## Checkpoint 3 — agent loop

- `bench/harness/run.py`: `Harness` (loaded by D's runner as `bench.harness.run:Harness`; no
  required constructor arguments). `run(spec)`:
  1. starts the mock (A's `bench.mock.MockNetwork` when importable, else the provisional dev
     mock) and switches on `spec.mock_override`;
  2. builds the sandbox; **attack runs (`spec.scenario is not None`, as D's runner assumes)
     require netns/docker**, and a refused attack run writes `run_end: error` plus
     `meta.harness_error`;
  3. runs the agent with monitoring;
  4. runs the task's `success_check` in the sandbox (`file_contains`, `file_not_contains`,
     `command_exit`) and writes `success.json`, plus a copy in `meta.json["success"]`;
  5. writes `meta.json` and `messages.json` (the full conversation, for spot checks), then
     removes the sandbox unless `keep_workspace`.
- `meta.json` holds:
  - model, invocation, seed, the runtime policy name, the installed versions;
  - isolation, observer (and the probe error, if strace was unusable), which mock was used;
  - the model's `describe()` (backend, base_url, model, model_file, quantization, decoding);
  - the system prompt's sha256;
  - the run outcome: `run_end`, steps, tool_calls, malformed_calls, usage, skill_loads,
    final_text, problems;
  - timings (build/agent/model/success/total) and the sandbox build info (setup result and
    per-file skill hashes).
- `bench/harness/agent.py`: the loop.
  - The system prompt comes from `prompts/system.md`, with `{skills}` filled by one line per
    installed skill: `- <name>: <description> (path: .github/skills/<id>/SKILL.md)`, from the
    SKILL.md frontmatter (D8). The user message is the task prompt unchanged, or prefixed with
    `/<skill_id> ` for `explicit` invocation.
  - The loop stops when a turn has no tool call (`done`), at 25 model turns (`step_limit`, D11),
    at 1,800 s of wall clock (`timeout`, B's choice, to revisit after the pilot), or on a model
    error (`error`).
  - Malformed calls (unknown tool, bad JSON, missing or extra or mistyped arguments) go back to
    the model as `error: malformed tool call: ...`. They are logged in
    `meta.malformed_calls` and are not executed, so they get no tool line.
- `bench/harness/tools.py`: the five OpenAI tool schemas and `ToolExecutor`.
  - Each call writes `requested`, then calls `policy.on_tool_call(ToolCall, installed target
    version, task)`.
  - On block: a `policy_decision` event (phase `runtime`, `decision: "block"`), then
    `status: blocked` with `blocked_by`, and the model gets "blocked by the security policy".
  - Otherwise the call executes, and the command's monitor events and the mock's new
    `net_observed` lines are written before the final `completed`/`failed` line.
  - A policy that raises is treated as a block (fail closed) and recorded in `meta.problems`.
  - File tools reject absolute paths and paths whose real location leaves the workspace
    (failed call; the tool line keeps the path as written).
  - `skill_load` is written when `read_file`, or a monitored command (`fs_read`), reads an
    installed `SKILL.md`.
  - Results are truncated to 8,000 characters; `out_bytes` is the UTF-8 size of what the model
    got.
  - `http_request` goes through the mock proxy from the harness process (http and https;
    the agent's own `Host:` header is passed through).
  - A command that times out is `failed` with `exit: 124`.
- `bench/harness/model.py`: `ChatModel` protocol, `OpenAIChatModel` (any OpenAI-compatible
  endpoint; temperature 0.2, max_tokens 4096, seed = `spec.seed`), and `ScriptedModel` for
  tests. Qwen3 handling: `<think>` blocks are removed from the kept history (stored as
  reasoning), and `<tool_call>` JSON in the content is parsed when the server returned no
  structured calls (`parsed_from_content`).
- `bench/harness/_devmock.py`: **provisional** mock that follows A5's rules (routes, sinks,
  403 for non-`.example`, overrides, routing by URL host, D6 `net_observed` log; CONNECT
  refused). It is replaced automatically when `bench/mock` lands.
- (replaced in checkpoint 5) `models.example.yaml` became `bench/configs/models.yaml`.
  `runs/` was added to `.gitignore` at the team's request.
- `bench/harness/run_task.py`: `python -m bench.harness.run_task <task_id> --model <name>` runs one
  benign run into `runs/dev/` and prints a summary that never includes tool outputs.
- Tests: `test_agent_loop.py` (17), offline with scripted models and a fake OpenAI server.
  - t05 end to end: valid v2 trace, `skill_load`, a served `net_observed`, success true,
    sandbox removed.
  - Runtime block gives `status: blocked`; a raising policy fails closed.
  - Absolute and escaping paths fail; output is truncated; command events sit between the
    requested and final lines.
  - Malformed calls, step limit, model error, attack run refused in env, stub mock.
  - System prompt and explicit invocation; Qwen3 parsing; the OpenAI client (structured and
    hermes calls, decoding params); dev-mock rules.
  - The structural D6 check is in `b_helpers.check_trace_v2` until A's schema lands.

### Real-model run: deferred (2026-11-22)

The planned local run of t05 with Qwen3-8B through Ollama on the Mac was dropped. `ollama pull
qwen3:8b` (5.2 GB) ran at about 180 KB/s, roughly 8 hours, so it was stopped at about 1%. The
first real-model run of the agent loop, including whether Qwen3's tool calls parse through a
real server, moves to the pilot on COOK (llama.cpp) / Colab (vLLM), B5. Until then the loop is
tested only with scripted models and a fake OpenAI-compatible server (`test_agent_loop.py`).

### Decisions B made in checkpoint 3 (please review)

- The harness runs `success_check` itself (D's NOTES asked B to either run it or keep the
  workspace). **Team note for D (2026-11-22):** the runner should read `meta.json["success"]`
  and not recompute it. D's current `SuccessChecker` stub overwrites `success.json` with
  `{"success": null}`.
- Runtime blocks also emit `policy_decision` with `decision: "block"`. **IC-3** (pending A) asks
  A's `trace_schema.json` to allow `block` for `phase: "runtime"`.
- The file tools are confined to the workspace (a path resolving outside it is a failed call,
  never executed). The oracle still sees the attempt.
- The system prompt draft says not to ask the user questions (no human is available during a
  run). The team reviews the wording.

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

## Checkpoint 4 — reference replay (2026-11-23)

- Merged `main` (data-v1 + A's oracle, mock, match, loaders, check_data) at `ea17394`;
  `interfaces.py` and `bench/__init__.py` taken from main. B tests after the merge: 89 passed,
  9 skipped on the Mac; 115 passed, 1 skipped in the Linux container (live strace and netns).
- `make_mock("auto")` now uses A's `bench.mock.MockServer` (it was looking for a
  `MockNetwork` class name and would have fallen back to the dev mock).
- `bench/harness/replay.py`: `plan_reference` (solve.sh -> tool calls), `ScriptedAgent`
  (a `ChatModel`, so replay goes through the same loop, executor, monitor and trace writer),
  `replay_task` (harness run + `Oracle.judge` + per-line attribution), CLI and report rendering.
  Tests: `bench/tests/b/test_replay.py`.
- `bench/harness/docker/Dockerfile.linux` + `scripts/replay_docker.sh`: a local Linux
  container (privileged, developer machine only) that gives the Mac strace and netns.
- `check_success` accepts both `text` and `contains` (both occur in the task data).
- Result: 34/55 clean, identical in env and netns. Findings F1–F11 for A in
  `bench/harness/REPLAY_FINDINGS.md`. F10 (mock serves from `repos/` instead of the sandbox
  copy, so shop-web's npm tarballs are missing) needs IC-1.
- B-side question raised by F9: the monitor records `mkdir` as `fs_write` (op `create`) of the
  directory; A and B to agree on how the matcher treats ancestor directories of allowed targets.
- Slip: while diagnosing F10 I printed `repos/shop-web/workspace/.npmrc` to the terminal,
  which shows a (fake) canary value. Rule 12 says canaries are secrets in terminal output;
  nothing was written to files or sent anywhere.

## Checkpoint 5 — backends and pilot scripts (2026-11-23)

Checkpoint 4 (reference replay) is a joint A+B step and was skipped for now.

### What was built

- `bench/backends/`: `base.py` (`OpenAICompatModel`: request building, retries, error
  classes, health, metadata), `vllm.py`, `llamacpp.py`, `tinker.py`, `hermes.py` (prompt-mode
  tool calling in Qwen3's format), `__init__.py` (`make_model(name, **overrides)`, config
  loading with `${VAR:-default}` expansion), `__main__.py` (CLI for the job scripts: `list`,
  `show`, `get`, `serve-cmd`, `wait`; it never sends a chat request).
  - One interface: `chat(messages, tools=None) -> AssistantTurn`, `describe()`, and
    `complete(messages) -> str` for C's `llm_reviewer` and D's attacker (no tools; override
    `temperature` in `make_model`). `bench.harness.model.OpenAIChatModel` is now an alias.
  - Errors are `BackendError(kind)`: `connection`, `timeout`, `server`, `rate_limit` are
    retried (`retries`, exponential `retry_backoff`); `context_length`, `bad_request`, `auth`,
    `not_found`, `bad_response` fail at once. The run ends with `run_end: error` and meta.json
    gets `agent_error_kind`. The openai client's own retries are off.
  - `tool_mode: native` sends `tools`; `prompt` writes them into the system message the way
    Qwen3's chat template does, renders earlier calls as `<tool_call>` text and results as
    `<tool_response>` user turns, and parses the reply. Tinker defaults to `prompt`.
  - `describe()` adds `server_info` (vLLM `/v1/models`: `max_model_len`, weights root;
    llama.cpp `/props`: model path, `n_ctx`); best effort, never fails a run.
- `bench/configs/models.yaml` (**shared config, proposed, needs team approval**): Qwen3
  4B/8B/14B/32B for vLLM (bf16, A100) and llama.cpp (Q4_K_M, COOK gtx/gtx/t4/rtx), two Tinker
  entries (not pilot candidates), Ollama for the Mac. `$CDB_MODELS` still overrides it.
- New meta.json fields: `skill_id`, `agent_error_kind`, `truncated_turns` (turns with
  `finish_reason: length`).
- `bench/harness/pilot.py`: `run` (55 tasks x 3 repeats, seeds 0-2, v1, policy `none`,
  natural invocation; `--shard i/n`, `--workers`, `--deadline-s`, `--max-total-tokens`,
  `--dry-run`; resumable; `progress.jsonl`) and `summarize` (task success, clean rate,
  skill-load rate, run_end mix, malformed calls, time, tokens; per model and per repo; Wilson
  intervals; `--update-md` fills `PILOT.md` between markers, `--csv`).
- Job files (**not launched**): `slurm/pilot_cook.sbatch` (array of 8 shards per model; each
  starts llama-server on a per-job port, waits, runs its shard with a deadline inside the
  2-hour limit, stops the server), `scripts/pilot_vllm.sh` (A100), `scripts/pilot_tinker.sh`
  (requires `MAX_TOKENS`).
- `bench/harness/PILOT.md`: the report template.
- Tests: `bench/tests/b/test_backends.py` (30) and `test_pilot.py` (8) against
  `b_fake_openai.py`, a stdlib fake OpenAI-compatible server. Full B suite on the Mac:
  89 passed, 9 skipped.

### Decisions B made in checkpoint 5 (please review)

1. Qwen3 thinking stays at the model default (on) for the pilot, with 4096 max tokens per turn.
   `truncated_turns` shows whether that is too small.
2. Context: 32768 tokens on both backends (Qwen3's native length), one llama.cpp slot (`-np 1`).
3. A COOK array of 8 shards per model counts as 8 Slurm jobs; 4 models = 32 jobs, so humans
   launch it (above my 10-job cap).
4. The pilot's `run_id` is readable (`pilot-<model>-<task>-r<k>`), not D's short hash; the
   pilot is B's own tool, not a D9 episode.
5. 32B on vLLM: bf16 needs an 80 GB A100. On a 40 GB card use `Qwen/Qwen3-32B-AWQ` as a
   separate entry (a different quantization, so a separate row).

## Known weaknesses (checkpoint 5)

- Nothing has talked to a real vLLM, llama.cpp or Tinker server yet. Request fields that real
  servers may reject or ignore: `chat_template_kwargs` and `cache_prompt` (llama.cpp, depends
  on the build), `seed` (Tinker).
- The `context_length` classification matches on error text, which differs between servers;
  check it with one real overflow.
- `--max-total-tokens` is checked before each run starts, so the cap can be overshot by up to
  `--workers` runs.
- Clean rate stays n/a until A's oracle lands and someone writes `oracle.json` for the runs.

## Known weaknesses (checkpoint 3)

- `env` isolation does not confine the file system. On the Mac, a real model's `run_command`
  can write anywhere the user can, not only inside the workspace (benign runs only, but
  still). A macOS `sandbox-exec` profile (writes only inside the stage, network only to the
  proxy port) would close this for Mac development; not built yet.
- The context window is not managed: 25 steps of up to 8,000-character outputs can exceed
  Qwen3-8B's 32k-token context, which then shows up as a model error. To size after the pilot.
- The dev mock is not A's mock; behaviour may differ once A5 lands.

## Open questions

1. IC-1, IC-2 and IC-3 are pending A's review.
2. (closed) Docker mode: untested and not needed, since `netns` works on Colab/A100 and COOK.
3. COOK: exact GGUF file names under `/nfs/opt/models` (models.yaml guesses
   `Qwen3-<size>-Q4_K_M.gguf`); where `llama-server` lives (the job uses `$LLAMA_SERVER`, else
   `llama-server` on PATH) and whether that build has `--jinja` and `--reasoning-format`;
   whether `--gres=gpu:1` is the right GPU request.
4. A100: 40 or 80 GB (decides the 32B entry); is `vllm` installed in the venv or a separate env?
5. Tinker: which `tinker://` sampler paths to use for base Qwen3-8B/32B, whether
   `/chat/completions` accepts `tools` (if so, switch to `tool_mode: native`), and the token
   price, to set `MAX_TOKENS`.
