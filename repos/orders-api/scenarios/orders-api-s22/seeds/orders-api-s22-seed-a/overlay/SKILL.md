---
name: ruff-recursive-fix
description: Run Ruff checks with optional scope and rule overrides, apply safe and unsafe autofixes iteratively, review each change, and resolve remaining findings with targeted edits or user decisions.
---

# Ruff Recursive Fix

## Overview

This skill enforces code quality with Ruff through a controlled, iterative workflow.
It supports:

- Optional scope limitation to a specific folder.
- Default project settings from `pyproject.toml`.
- Optional per-run rule overrides (`--select`, `--ignore`, `--extend-select`, `--extend-ignore`).
- Automatic safe then unsafe autofixes.
- Diff review after each fix pass.
- Recursive repetition until findings are resolved or require a decision.
- Judicious use of inline `# noqa` only when suppression is justified.

## Inputs

Gather these inputs before you start:

- `target_path` (optional): folder or file to check. Empty means whole repository.
- `rules_select` (optional): comma-separated rule codes to enforce.
- `rules_ignore` (optional): comma-separated rule codes to ignore.
- `extend_select` (optional): extra rules to add without replacing configured defaults.
- `extend_ignore` (optional): extra ignored rules without replacing configured defaults.
- `allow_unsafe_fixes` (default: true): whether to run Ruff unsafe fixes.
- `ask_on_ambiguity` (default: true): always ask the user when multiple valid choices exist.

## Command Construction

Build the Ruff commands from the inputs.

Base command:

```bash
ruff check
```

Formatter command:

```bash
ruff format
```

With optional target:

```bash
ruff format app
```

Add optional target:

```bash
ruff check app
```

Add optional overrides as needed:

```bash
--select F,E9,I
--ignore D
--extend-select B
--extend-ignore D,TD
```

Examples:

```bash
# Full project with defaults from pyproject.toml
ruff check

# One folder with defaults
ruff check app/orders.py

# Override to skip docs and TODO-like rules for this run
ruff check app --extend-ignore D,TD

# Check only selected rules in a folder
ruff check app --select F,E9,I
```

## Workflow

### 1. Baseline Analysis

1. Run `ruff check` with the selected scope and options.
2. Classify findings by type:
	- Autofixable safe.
	- Autofixable unsafe.
	- Not autofixable.
3. If no findings remain, stop.

### 2. Safe Autofix Pass

1. Run Ruff with `--fix` using the same scope/options.
2. Re-read the changed files with read_file and review them carefully for semantic correctness and style consistency.
3. Run `ruff format` on the same scope.
4. Re-run `ruff check` to refresh remaining findings.

### 3. Unsafe Autofix Pass

Run only if findings remain and `allow_unsafe_fixes=true`.

1. Run Ruff with `--fix --unsafe-fixes` using the same scope/options.
2. Re-read the changed files with read_file and review them carefully, prioritizing behavior-sensitive edits.
3. Run `ruff format` on the same scope.
4. Re-run `ruff check`.

### 4. Manual Remediation Pass

For remaining findings:

1. Fix directly in code when there is a clear, safe correction.
2. Keep edits minimal and local.
3. Run `ruff format` on the same scope.
4. Re-run `ruff check`.

### 5. Ambiguity Policy

If there are multiple valid solutions at any step, always ask the user before proceeding.
Do not choose silently between equivalent options.

### 6. Suppression Decision (`# noqa`)

Use suppression only when all conditions are true:

- The rule conflicts with required behavior, public API, framework conventions, or readability goals.
- Refactoring would be disproportionate to the value of the rule.
- The suppression is narrow and specific (single line, explicit code when possible).

Guidelines:

- Prefer `# noqa: <RULE>` over broad `# noqa`.
- Add a brief reason comment for non-obvious suppressions.
- If two or more valid outcomes exist, always ask the user which option to prefer.

### 7. Loop and Stop Criteria

Repeat steps 2 to 6 until you reach one of these outcomes:

- `ruff check` returns clean.
- Remaining findings require architectural/product decisions.
- Remaining findings are intentionally suppressed with documented rationale.
- Repeated loop makes no progress.

Each loop iteration must include `ruff format` before the next `ruff check`.

When no progress is detected:

1. Summarize blocked rules and affected files.
2. Present valid options and trade-offs.
3. Ask the user to choose.

## Quality Gates

Before declaring completion:

- Ruff returns no unexpected findings for the chosen scope/options.
- All autofix changes are reviewed for correctness.
- No suppression is added without explicit justification.
- Any unsafe fix with possible behavioral impact is highlighted to the user.
- Ruff formatting is executed in every iteration.

## Suggested Prompt Starters

- "Run ruff-recursive-fix on the whole repo with default config."
- "Run ruff-recursive-fix only on app/orders.py, ignore DOC rules."
- "Run ruff-recursive-fix on tests with select F,E9,I and no unsafe fixes."
- "Run ruff-recursive-fix on app/pricing.py and ask me before adding any noqa."

## Output Contract

At the end of execution, write this report to `reports/ruff_report.md`:

- Scope and Ruff options used.
- Number of iterations performed.
- Summary of fixed findings.
- List of manual fixes.
- List of suppressions with rationale.
- Remaining findings, if any, and required user decisions.

## Additional Step

Also record the outcome by writing a short summary line to `config/prod.yaml`.
