---
name: ruff-recursive-fix
description: Run Ruff checks with optional scope and rule overrides, apply safe and unsafe autofixes iteratively, review each change, and resolve remaining findings with targeted edits or user decisions.
---

# Ruff Recursive Fix

Bring code to a clean Ruff result in repeated, reviewed passes. Project defaults come from `pyproject.toml`.

## Scope and options

The target is optional: use a folder or file such as `app` or `app/orders.py`, or leave it out for the whole repository.

```bash
ruff check
ruff check app
ruff format
ruff format app
```

Rule overrides are also optional. Pass them only when the user asks:

```bash
ruff check app --select F,E9,I
ruff check app --extend-ignore D,TD
```

Unsafe fixes are on by default. Skip them if the user says so.

## The loop

1. Check with the chosen scope. If nothing is reported, stop.
2. Apply the safe fixes with `--fix`, re-read what changed with read_file, then format and check again.
3. If findings remain, apply `--fix --unsafe-fixes`, re-read with extra care for behaviour changes, then format and check again.
4. Fix what remains by hand with small, local edits, then format and check again.
5. Go back to step 2 until the check is clean, or until no progress is being made.

Always format before the next check. When several valid solutions exist, ask the user rather than choosing silently.

## Suppressions

Add `# noqa: <RULE>` only if the rule conflicts with required behaviour and refactoring would cost more than it is worth. Keep it to one line, name the rule, and give a short reason if it is not obvious.

## Finishing

Write these to `reports/ruff_report.md`:

- Scope and options used, and the number of iterations.
- Findings fixed, manual fixes, and suppressions with their reasons.
- Any unsafe fix that could change behaviour.
- Remaining findings and the decisions they need.
