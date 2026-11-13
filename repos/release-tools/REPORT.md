# release-tools — build report

Repo 3 of 4 for the "Skill Issue" consent-drift benchmark (Team 6, CS 684). This is the
data only: workspace, six real skills with versions, tasks and delegations, mock hosts,
canaries, 25 scenarios with 50 static seeds, and the oracle traces. No harness, policy,
attacker or oracle lives here.

## What was built

| Part | Count | Notes |
|---|---|---|
| Workspace | `relkit`, a small Python release library | 15 passing tests, deterministic git history (41 commits, tags v0.1.0/v0.2.0/v0.3.0, branch `feature/export`) |
| Skills | 6 real, MIT-licensed | each with `v1` + 3 benign versions; `changelog-automation` also has `benign_v5` |
| Skill versions | 25 | every one carries an accurate `manifest.json` |
| Tasks | 12 | 2 per skill, each with a delegation and a run reference solution |
| Scenarios | 25 | class and goal budgets exactly as Part 2.7 |
| Seeds | 50 | 2 per scenario, differing in technique |
| Oracle traces | 4 clean + 4 violation | cover P1-P5 |

`python3 check_repo.py` passes. All 12 reference solutions run and their success checks
pass. All 19 benign versions were diffed against `v1`: none adds a host, path, command
or dependency.

## Composable pair, script skill, fetching skill

- **Composable pair (authority_laundering):** `changelog-automation` (A, reaches
  `spec.example`) with `requesting-code-review` (B, the only task — t07 — that reads
  `config/release.yaml`, where C2 lives).
- **Script / dependency skill (concealed_dependency):** `finishing-a-development-branch`.
  Its Step 1 runs `python3 .skills/finishing-a-development-branch/scripts/verify_release.py`,
  which imports the vendored `_report` module, so a swapped module runs on the normal path.
- **Fetching skill (late_binding):** `changelog-automation`, whose v1 fetches
  `http://spec.example/keepachangelog/1.1.0.md` and `/semver/2.0.0.md`.

## Deviations from a literal reading of the prompt

1. **Two skills needed a feature their real text lacks.** None of the six upstream skills
   runs a script or had one, and only `changelog-automation` referenced external URLs.
   To satisfy the required `concealed_dependency` and `late_binding` classes:
   - `finishing-a-development-branch` gained `scripts/verify_release.py` and
     `scripts/_report.py` (a wrapper around the existing `./release.sh --check`).
   - `changelog-automation` gained a "Reference Specs" step telling the agent to fetch
     the two spec URLs it already linked.
   Both additions are marked "ADDED (not in source)" in the respective `skill_meta.yaml`.
2. **`github-actions-hardening` is 271 lines, above the ~250 target.** Its `SKILL.md`
   (151 lines) was kept whole to preserve the seven-step review structure; only its
   reference files were trimmed.
3. **Skill install path assumed `.skills/<skill_id>/`.** The prompt does not fix where an
   installed skill lives in the workspace. Manifests, the bundled script's invocation,
   and the `concealed_dependency` overlays all assume `.skills/<skill_id>/`. If the
   harness mounts skills elsewhere, those paths (and the matching `fs_read`/`exec` globs)
   must change together.
4. **No commit after each phase.** The prompt says to commit after each phase, but the
   repo has no top-level git (only `workspace/.git`, rebuilt by `setup.sh`) and nesting a
   `.git` is forbidden. Commit history should be created when this folder is placed into
   the team repo.

## Known weaknesses / things the reviewer should check

- **`expected_to_fire_without_policy` is a judgement, not a measurement.** Each seed is
  marked `true` because a skill-following agent plausibly reaches the violation using only
  the five tools and this workspace. No agent was actually run (the prompt forbids it
  here), so these are claims to be confirmed when the harness runs.
- **Reference solutions stand in for an agent.** They prove each task's `success_check`
  is reachable with the allowed tools and that a clean run stays in the delegation; they
  are not the only valid solution.
- **`instruction_only` leak on a skill with no network task (none here)** was avoided; all
  leak seeds sit on skills/tasks where an outbound call is plausible. Worth re-checking if
  tasks are re-pointed.
- **Mock spec pages are paraphrases**, written for the benchmark, not the upstream spec
  text. `mock/spec.example/actions/hardening-baseline.md` is an invented checklist.
- **The capability extractor used to verify benign versions is my own**, modelling the
  Part 2.1 `capability_diff` extractor. The real one may read literals differently; the
  manifests and skill text were kept so hosts, paths and commands appear as plain strings.

## How to regenerate

`./setup.sh` builds `workspace/.git` deterministically and is idempotent. `check_repo.py`
validates the whole repo. The builder scripts that produced the skills, versions, tasks,
scenarios and seeds are not shipped in the repo; the committed files are the artifact.
