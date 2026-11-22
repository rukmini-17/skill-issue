# Workstream D (attackers + runner) — notes

## Status

| checkpoint | state |
|---|---|
| 1 runner on stubs: dry run, resume after kill, sharding | **done, waiting for "continue"** |
| 2 static attacker | not started |
| 3 Slurm templates | not started |
| 4 adaptive attackers | not started |
| 5 sweeps | not started (needs M1 and a go-ahead) |

Branch `impl/d-attacks-runner`, cut from `origin/impl/c-policies` (it carries `repos/` and
`bench/interfaces.py`, which are not on `main` yet). Run tests with `.venv/bin/python -m pytest bench/tests/d`.

## Checkpoint 1 — what was built

- `bench/runner/config.py`: experiment YAML -> `ExperimentConfig`; `expand()` yields `EpisodeKey`s.
  Kinds: `attack`, `benign_updates` (benign versions as updates, then the task: unnecessary-prompt
  metric), `task_completion` (v1 only). Unknown YAML keys are rejected.
  Static attacker runs get a `seed_id` dimension; adaptive attackers do not, and skip policy `none` (D13).
- `bench/runner/episode.py`: one episode per D9. Writes `decisions.jsonl`, `trace.jsonl`, `meta.json`,
  `success.json`, and `oracle.json` last (its presence = complete).
- `bench/runner/runner.py`: grid execution, `--shard i/n`, `--workers N`, resume. A failed episode writes
  `error.json`, no `oracle.json`, and is retried on the next invocation.
- `bench/runner/components.py`: builds harness/oracle/policy/attacker. `--dry-run` = stub harness, oracle
  and mock; policies stay real (offline, deterministic); `llm_reviewer` becomes an allow-all stub.
- `bench/runner/data.py`: provisional loader (same role as A's `bench/common/data.py`). Read-only on `repos/`.
- Configs: `bench/configs/experiments/dry_run.yaml`, `dry_run_benign.yaml`.
- CLI: `python -m bench.runner bench/configs/experiments/dry_run.yaml --dry-run [--shard 0/4] [--workers 4]`.

Verified: 18 tests pass; a real `kill -9` mid-sweep followed by a rerun finishes all 330 benign runs (80 were
kept, the rest redone); the dry-run benign grid (330 episodes) and the one-scenario-per-repo attack grid run.

## Deviations from the prompt

1. **Agent-run cache and run-time policies.** D9 says two policies with the same installed state share one
   agent run. `deny_by_default_manifest` and `delegation_envelope` block tool calls, so sharing would be
   wrong; they are keyed by policy name and never share. Update-only policies still share. Needs a human OK.
2. **Sharding is by group**, not by episode: all policies of one scenario/seed/model/repeat go to the same
   shard/worker, so the cache is touched by one worker at a time.
3. `.gitignore` gets `runs/` (Part 3 says it is git-ignored; it was not yet).
4. `policy_decision` trace events (D6) are **not** written; decisions go to `decisions.jsonl` only. Reused agent
   runs would otherwise carry another policy's decision lines. Open question for A.
5. `file_contains` data fix (`contains:` -> `text:`, D1) in release-tools' 10 tasks was committed on the
   `release_tools` branch by request of the human, not on this branch.

## Open questions / needs from others

- **Success checks** (`success.json`) are `{"success": null}` for now: they must run against the final
  workspace, and `command_exit` checks need the sandbox. Proposal: B leaves the workspace path in
  `meta.json["workspace"]` (kept until the run is judged) or runs `success_check` itself. Needs a decision
  before M1. (Not written into `INTERFACE_CHANGES.md`, which only exists on `impl/b-harness`.)
- Real harness/oracle are loaded by dotted path (`components.DEFAULTS`: `bench.harness.run:Harness`,
  `bench.oracle:Oracle`); those names are guesses until B and A merge.
- Attack runs need `netns`/`docker` isolation (B's decision 1). `RunSpec` has no flag for it; the harness
  must infer "attack run" from `spec.scenario is not None`. A benign run has `scenario=None` only for
  `task_completion`/`benign_updates`.
- `models.yaml` does not exist yet; model names are opaque strings to the runner.
- Static attacker (D2) must expose `mock_override` on its session (read with `getattr`); not an interface change.

## Known weaknesses

- Adaptive search needs an agent run per proposal for P1/P5 goals (D13); the episode function here runs the
  agent once at the end. D4 will wrap it.
- Provisional loader duplicates C's `_dataload.py`; both go away when A's `bench/common/data.py` lands.
