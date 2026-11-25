# Workstream A — NOTES

Log of what A built, deviations, known weaknesses and what humans must do next. Feeds the
paper appendix. Checkpoints follow Part 5 of the revised implementation prompt.

## Status
- **Checkpoint 1 (data freeze + `check_data.py`): done, pending human git actions.**
  `python -m bench.check_data` → 2607/2607 checks pass across all 4 repos (1 known-data-bug
  warning). Humans still need to merge `data-integration` → `main` and tag `data-v1`.
- **Checkpoint 2 (match + oracle, 32 oracle tests + fixtures): done.**
  `pytest bench/tests/a` → 97 passed, 2 skipped (Windows symlinks), 1 xfailed (data bug).
  Oracle reproduces 31/32 oracle tests exactly; the 32nd is a data bug (xfailed, oracle is
  D7-correct). 18 A3 fixtures + a symlink-escape test cover every D6 event type and the D2/D3
  edge cases.
- **Checkpoint 3 (mock network): done.** `bench/mock/server.py` — stdlib forward proxy.
  `pytest bench/tests/a` → 105 passed, 2 skipped, 1 xfailed. Tests cover routes, sinks,
  refusal (403), late-binding override, routing by URL host (not `Host:`), full logging to
  file, and the real `start(repo_id, …)` path.
- Checkpoints 4 (reference check, needs B), 5 (analysis): not started.

## Built so far
- `common/match.py` — D2 paths (revised: `dir/**` covers `dir`, absolute paths rejected),
  D3 commands (redirections → P2/P3, `$()`/backtick substitutions, quote-aware splitting,
  `command_aliases.yaml`), D4 network.
- `common/trace_schema.json` — D6 v2 (v1 lines without `status` read as `completed`).
- `common/data.py` — `load_repo`, `apply_overlay`, seed loading (single-step / salami steps / late-binding mock_override).
- `oracle/oracle.py` — D5-D7 `judge()` (redirection reads/writes wired in).
- `mock/server.py` — stdlib HTTP forward proxy (routes/sinks/refusal, late-binding overrides, logs `net_observed` to file; routes by URL host, logs `host_header` too). `served=True` only for a real route/override; sinks and refusals are `served=False`.
- `check_data.py` — unified validator over all repos, reusing the above; recomputes oracle predicates for every repo (release-tools' own script does not).
- `configs/command_aliases.yaml` — shared config (seed: `python3 -m pytest` == `pytest`); needs team review before adding entries.
- `tests/a/` — `test_match.py`, `test_oracle_repro.py`, `test_check_data.py`, `test_fixtures.py` + `fixtures/` (18 traces + `expectations.yaml`).

## Decisions / deviations (with reasons)
- **Revised D2 applied:** `dir/**` matches `dir` itself (so `list_dir("dir")` is in scope);
  absolute paths (POSIX, Windows-drive, UNC) are rejected and never match.
- **`ok: false` ⇒ failed** for v1 trace lines (and `run_command` with non-zero `exit`).
  D6 says a status-less v1 line is `completed`, but a line explicitly flagged failed is read
  as `failed`, so its predicate is an *attempt*, not an *effect* (D7). Needed for ops-office
  `clean_02` (a failed `list_dir`). Harmless given the revised `dir/**` rule, but kept because
  it is the correct general reading of a failed call.
- **P5 headline = exact only.** Encoded leaks set `p5_match="encoded"` but do not add P5 to
  the headline predicates (D5: "the headline P5 number is exact").
- **Oracle is D7-faithful on `fs_diff`** (counts it as a P3 source). See DATA_ISSUES #1: this
  makes release-tools `violation_01` disagree with its committed `[P4]`; the oracle reports the
  D7-consistent `[P3, P4]` (matching ops-office `violation_04`), and the test xfails it.

## Known weaknesses / deferred
- **Capability extraction** (text-level hosts/paths/commands/deps from skill files) is C's
  per revised D12; `check_data.py` checks benign-version **manifest** subset only, not the
  text-extracted capability subset. When C's extractor lands, add that check here.
- **Repo-specific asset checks** (exact protected-write target, privileged-exec stub) from the
  per-repo `check_repo.py` scripts are not all ported; `check_data.py` does the data-driven
  canary-reach guard instead. Port the rest if the team wants parity.
- **Runtime vs oracle path resolution:** the oracle resolves symlinks (real path at access
  time); runtime checks (C) resolve `.`/`..` lexically only — symlink escapes are invisible to
  runtime checks. Documented per D2; will matter for C's runtime policies.
- **Symlink fixture skips on Windows** (needs developer mode); it will run in the Linux sandbox.

## For humans / next
1. Merge `data-integration` → `main` and tag `data-v1` once `check_data` is green (checkpoint 1 handoff).
2. Resolve DATA_ISSUES.md #1-#3 (privileged.log predicate inconsistency, release-tools
   expectations schema, 25-vs-24 skill count) and re-tag.
3. M0: replace the locally-drafted `bench/interfaces.py` with the canonical copy from
   `impl/c-policies` (the revised prompt says merge it, not rewrite).
