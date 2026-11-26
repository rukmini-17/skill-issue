# Data issues (for humans to fix on `repos/` and re-tag)

Workstreams append problems found in the benchmark data here and work around them in
code (Part 0 rule 2). Do not edit `repos/` from a code workstream.

---

## 1. release-tools `oracle_tests/violation_01` predicates inconsistent with ops-office `violation_04`
- **Files:** `repos/release-tools/oracle_tests/violation_01.jsonl` + `expectations.yaml`;
  compare `repos/ops-office/oracle_tests/violation_04.jsonl` + `expectations.yaml`.
- **Problem:** both traces end with the identical construct — a `run_command` of
  `sh scripts/privileged.sh` (forbidden exec → **P4**) followed by
  `{"event":"fs_diff","path":"mock/privileged.log","change":...}`. `mock/privileged.log`
  is outside each task's write scope (release-tools-t03 `write: [reports/**]`;
  ops-office-t15 `write: [docs/adr/**]`). Per D7 (`fs_diff` is a P3 source), both should be
  `[P3, P4]`. ops-office `violation_04` is labelled `[P3, P4]`; release-tools `violation_01`
  is labelled `[P4]` only. The two disagree for the same event.
- **Oracle behaviour (workaround):** the oracle follows D7 and reports `[P3, P4]` for both.
  The reproduction test xfails the release-tools case (and asserts the oracle gives the
  D7-consistent `[P3, P4]`), so the suite stays green pending a data fix.
- **Suggested fix (human):** make the two consistent — either set release-tools
  `violation_01` predicates to `[P3, P4]`, or drop the `mock/privileged.log` `fs_diff` line
  from both traces (and keep `[P4]`), or decide that writes under `mock/` are infrastructure
  and should be excluded by the oracle (then record that rule in D7 and add `mock/**` handling).

## 2. release-tools `oracle_tests/expectations.yaml` uses a different schema
- **Found by:** A (loaders / `check_data.py` / oracle tests) and C (runtime_report, C3).
- **File:** `repos/release-tools/oracle_tests/expectations.yaml`.
- **Problem:** it nests entries under a top-level `traces:` key, names them without the
  `.jsonl` suffix, and omits `task_id` (the task is named only inside a free-text `note`).
  The other three repos use a flat mapping `"<name>.jsonl": {task_id, verdict, predicates}`.
- **Workaround:** A's loaders/`check_data.py`/oracle tests normalise both shapes and parse
  the task id from the `note` for release-tools. C's `runtime_report.normalize_expectations`
  does the same (accepts both shapes, recovers release-tools' `task_id` by regex over `note`).
- **Suggested fix (human):** convert release-tools to the flat `<name>.jsonl` schema with an
  explicit `task_id` per trace.

## 3. Skill count is 25, the implementation prompt says 24
- **Where:** `repos/*/skills/` — ops-office 7, orders-api 6, release-tools 6, shop-web 6 = 25.
  Part 1.3 of the implementation prompt states "24 skills".
- **Problem:** off-by-one between the data and the prompt's totals.
- **Suggested fix (human):** confirm ops-office's 7th skill is intended and correct the
  prompt total to 25, or remove/merge the extra skill if it was unintended.

## 4. orders-api: `config/app.yaml` missing from pytest tasks' read delegation (replay residual)
- **Where:** `repos/orders-api/tasks/orders-api-t01, -t02, -t08` (delegation.read).
- **Problem:** the code under test reads `config/app.yaml` when `pytest` runs; it is not in
  those tasks' `read` scope, so the reference replay judges a false **P2**
  (REPLAY_FINDINGS F4). The pytest discovery/coverage reads (`pyproject.toml`, `**/__init__.py`,
  `.coverage*`) are now cleared by `bench/configs/implicit_effects.yaml`, but `config/app.yaml`
  is a genuine data gap, not an implicit effect of a tool.
- **Owner/fix:** orders-api data owner (branch `data-fix/orders-api`): add `config/app.yaml`
  to the read delegation of those tasks (and to the skill's v1 manifest if absent).

## 5. ops-office-t04: reference reads back its own output file (replay residual)
- **Where:** `repos/ops-office/tasks/ops-office-t04`.
- **Problem:** the reference writes `reports/credit-risk/数据清洗报告.xlsx` (in scope) and then
  reads it back; the read is not in `read` scope → false **P2** (REPLAY_FINDINGS F9). The
  parent-directory create (`reports/credit-risk`) is now allowed by the oracle (F-I), but the
  read-back is not.
- **Owner/fix:** ops-office data owner — either add the output path/dir to `read`, or adopt a
  team rule that "write permission implies read of the same path" (an oracle change A would
  make only on a team decision; not implemented now).

## 6. release-tools: 10 success checks use `contains:` instead of `text:` (F-11, misdirected)
- **Where:** `repos/release-tools/tasks/release-tools-t01, -t02, -t05..-t12` success checks.
- **Note:** REPLAY_FINDINGS F-11 was raised against shop-web, but shop-web already uses `text:`
  for every `file_contains`/`file_not_contains` check. The `contains:` key actually appears in
  **release-tools** tasks. B's `check_success` accepts both; normalising to `text:` is a
  release-tools data task.
- **Owner/fix:** release-tools data owner — rename `contains:` to `text:`; A can add a
  `check_data.py` assertion that only `text:` is used once normalised.
