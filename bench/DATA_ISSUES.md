# DATA_ISSUES

Problems found in the benchmark data under `repos/`. Workstreams append here and
work around; a human fixes the data and re-tags (Part 0, rule 2). Do not edit
`repos/` to fix these.

## Cross-repo: `oracle_tests/expectations.yaml` schema is inconsistent

- **Found by:** C (runtime_report, C3).
- **Problem:** the four repos use two different schemas.
  - `orders-api`, `ops-office`, `shop-web`: flat mapping
    `"<file>.jsonl": {task_id, verdict, predicates}`.
  - `release-tools`: nested under a top-level `traces:` key, keys have **no**
    `.jsonl` extension (`clean_01` not `clean_01.jsonl`), and there is **no
    `task_id` field** — the task id is only embedded in free-text `note`
    (e.g. `"git-commit / release-tools-t03: ..."`).
- **Suggested fix:** normalize all four to the flat schema with an explicit
  `task_id` field and `.jsonl` keys. A's unified `check_data.py` (A1) should enforce
  one schema.
- **Workaround (C):** `runtime_report.normalize_expectations` accepts both shapes
  and recovers release-tools' `task_id` by regex over the `note`.
