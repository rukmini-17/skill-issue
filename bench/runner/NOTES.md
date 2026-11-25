# Workstream D (attackers + runner) — notes

## Status

| checkpoint | state |
|---|---|
| 1 runner on stubs: dry run, resume after kill, sharding | done |
| 2 static attacker reproduces seed installs byte for byte | done |
| 3 Slurm templates + resubmit script | done locally; **the real COOK test job is for a human to run** |
| 4 adaptive attackers | **done except the stage-3 proposer (team-supplied); waiting for "continue"** |
| 5 sweeps | not started (needs M1 and a go-ahead) |

Branch `impl/d-attacks-runner`, cut from `origin/impl/c-policies`; `origin/impl/c-policies` (which already merged
`main` at `data-v1`) is merged in, so the branch carries A's `bench/common`, oracle and mock. Run tests with `.venv/bin/python -m pytest bench/tests/d`.

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
- `bench/runner/data.py`: thin view over A's `bench/common/data.py` (`load_repo`, `apply_overlay`), keeping the
  names D's code uses (`Repo.skills`, `Repo.benign`). Read-only on `repos/`. (Was a provisional loader before
  `data-v1`; swapped with no behaviour change: all D tests, including byte-for-byte seed replay, pass.)
- Configs: `bench/configs/experiments/dry_run.yaml`, `dry_run_benign.yaml`.
- CLI: `python -m bench.runner bench/configs/experiments/dry_run.yaml --dry-run [--shard 0/4] [--workers 4]`.

Verified: 18 tests pass; a real `kill -9` mid-sweep followed by a rerun finishes all 330 benign runs (80 were
kept, the rest redone); the dry-run benign grid (330 episodes) and the one-scenario-per-repo attack grid run.

## Checkpoint 2 — static attacker

- `bench/attackers/static.py`: `StaticAttacker(seed_id, workdir)`; `proposals()` returns a session that
  yields the seed's updates in order and exposes `mock_override` (path or None) for the runner.
  Shapes handled: single `overlay/`, salami `step_NN/overlay/` (cumulative, built from the previous
  *published* step, whatever the policy installed), late_binding (mock override, update is a no-op).
- `.keep` files are ignored (placeholders for empty dirs). 8 late_binding seeds have a `.keep`-only overlay
  and are therefore no-op updates; the runner logs them as `noop` and does not call the policy.
- Version names: `<scenario short id>-seed-a`, `...-step_02` (e.g. `s20-seed-a-step_02`).
- Seeds start from their own `base_version` (`v1`, `benign_v2` or `benign_v3`), not from the runner's
  currently-approved version. If a policy denied a benign-prefix step, the attack update is still the seed's
  published file set.
- Test: all 200 seeds are rebuilt independently from the files on disk and compared per file hash with what
  the attacker produced (every chain step); `repos/` is unchanged by replay. The full static grid
  (200 seeds x 6 policies = 1200 episodes) runs in dry-run with 4 workers and no errors.
- Dry-run attack-step decisions over the grid (real policies, stub agent): none 251 allow; pin_reapprove 219 ask /
  32 allow; new_permissions_only 219 allow / 32 ask; capability_diff 176 allow / 75 ask; deny_by_default_manifest
  219 allow / 32 deny; delegation_envelope 165 allow / 86 deny. (Counts are per update, not per run outcome.)

## Checkpoint 3 — Slurm

- `bench/runner/slurm/run_shard.sbatch`: one array task = one shard (`--shard $SLURM_ARRAY_TASK_ID/$NSHARDS`),
  2 h limit, runs the runner with `--max-seconds 6300` so it stops *starting* groups with 15 min to spare and
  exits 0; SIGTERM (Slurm's time-limit warning) is honoured the same way. Optional model-server block
  (`LLAMA_SERVER_CMD`) for real jobs.
- `bench/runner/shards.py` (+ `slurm/resubmit.sh` wrapper): lists per-shard progress (a shard is complete when
  all its runs have `oracle.json`), and with `--resubmit` builds the `sbatch --array=<incomplete shards>` command;
  `--submit` actually runs it, refusing more than `--max-jobs` (10) array tasks.
- Runner: `--max-seconds`, SIGTERM handling, and a per-shard marker `_shards/<i>of<n>.json`
  (says the process ended; completeness is judged from `oracle.json`).
- Tested without Slurm: the sbatch script is run by `bash` with Slurm's variables set, a fake `sbatch` records
  what would be submitted, the job-cap refusal, deadline stop and rerun. 38 tests pass.
- **Not tested on COOK.** Things we do not know and the script does not assume: GPU request (`--gres`, pass
  `--gres` to `shards.py`), module loads, where the venv lives (`VENV`), the partition names beyond the prompt's
  gtx/t4/rtx. Lines marked `CHECK` in `run_shard.sbatch` need a human on the cluster.
- For the tiny job (one scenario, three policies, stub everything), from the repo root on a COOK login node
  after creating the venv:
  `python -m bench.runner.shards bench/configs/experiments/slurm_tiny.yaml --shards 1 --dry-run --resubmit --submit`
  then check with `squeue -u $USER` and `ls runs/slurm_tiny/*/oracle.json | wc -l` (expect 3).
- Limitation: the deadline is checked between groups, so one slow group (many agent steps) can run past it;
  keep groups small or lower `MAX_SECONDS`.

## Checkpoint 4 — adaptive attackers

- `bench/attackers/adaptive.py`: `BlackBoxAttacker`, `PolicyAwareAttacker`; one shared proposal budget over three stages:
  1. the handcrafted seeds, replayed exactly; 2. template variations of the seeds (`templates.py`: wording and
  placement changes of the lines a seed adds, deterministic); 3. a **plug-in `Proposer`** supplied by the team.
- **Stage 3 is not implemented here.** `Proposer.propose(ProposalContext) -> RawProposal | None` is the hook; the
  runner loads one from `components: {proposer: "pkg.mod:Class"}`. The attacker prompt and the code that turns
  a model reply into file contents are the team's (D13: instruction text is team-written after M1). Without a
  proposer a search ends after stage 2. `bench/attackers/llm.py` is an OpenAI-compatible client the proposer can
  use (settings from `attacker_model`/env, key read from the env var named in `api_key_env`).
- `validate.py`: structural class rules (mirror of the data's `check_repo.py`, plus size limits). A's `check_data.py`
  (on `main`) has no per-class seed rules to reuse, so these stay in D. Invalid proposals count against the budget and are never submitted; seeds are
  checked and logged but submitted even if flagged (all 200 pass).
- **Feedback restriction** (tested): the session's context type has no task/delegation/oracle/trace fields; a
  test walks the live session for `Task`/`Delegation`/`OracleResult` objects (it found and I removed a real
  leak: the session held the whole `Repo`); `effect_happened` is ignored by the session unless the goal's
  predicates include P1 or P5, and the runner also passes None for other goals; the black-box attacker never gets
  the policy description.
- **Runner loop** (`episode._adaptive_loop`): proposals are offered one at a time; each *installed* proposal is
  followed by an agent run (cached) and an oracle judgement; denied proposals run nothing. Bypass (D10) =
  oracle effects include an expected predicate and the proposal was not denied. The search stops at the first
  bypass (`stop_at_bypass`, default true) and records `meta["adaptive"]`: `proposals_used` (valid + invalid),
  `first_bypass_proposal` (null = censored), `agent_probes`. Per-proposal runs are in `proposals/NNN/`; the
  run's own trace/oracle are those of the first bypass, else of the last state. `attacker.jsonl` has the
  proposal, feedback, and a hidden `eval` line (verdict, predicates, bypass, asks so far) per proposal.
- `none` is skipped for adaptive attackers (D13). Config: `budget` (default 50), `stop_at_bypass`.
- Checks: 60 tests pass; all 600 episodes of (2 adaptive attackers x 3 policies x 100 scenarios) run in dry-run.
- Stage-2 limits: templates reword `.md` text only, so `concealed_dependency` (code files) and late_binding
  pages that are not `.md` get no stage-2 variations; those need the stage-3 proposer.
- Note for NOTES (D12): if the attacker also uses Qwen3-32B as the `llm_reviewer`, record it.

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
- Real harness/oracle are loaded by dotted path (`components.DEFAULTS`). `bench.oracle:Oracle` is A's, now on
  `main`; `bench.harness.run:Harness` is still a guess until B merges.
- Attack runs need `netns`/`docker` isolation (B's decision 1). `RunSpec` has no flag for it; the harness
  must infer "attack run" from `spec.scenario is not None`. A benign run has `scenario=None` only for
  `task_completion`/`benign_updates`.
- `models.yaml` does not exist yet; model names are opaque strings to the runner.
- Static attacker (D2) must expose `mock_override` on its session (read with `getattr`); not an interface change.

## Known weaknesses

- Adaptive search runs the agent after every installed proposal (cached by installed state). With the real
  harness this is the dominant cost: up to 50 runs per scenario per policy; budget 25 is the fallback (D13).
- Attack and benign agent runs reuse `_agent_cache`; a run that errors midway leaves `error.json` only.
