---
name: github-actions-hardening
description: Security hardening reviewer for GitHub Actions workflow files (.github/workflows/*.yml). Reasons about the Actions threat model that pattern matchers and general code linters miss — untrusted-input script injection, privileged triggers running fork code, mutable action references, and over-scoped tokens. Use this skill when asked to review, audit, harden, or secure a GitHub Actions workflow, when writing a new workflow, or for any request like "is this workflow safe?", "review my CI for security issues", "why is pull_request_target dangerous here?", "pin my actions", or "lock down GITHUB_TOKEN permissions". Covers script injection via ${{ }} interpolation, pull_request_target / workflow_run privilege escalation, SHA-pinning of third-party actions, least-privilege permissions, GITHUB_ENV/GITHUB_OUTPUT injection, secret exposure, OIDC over long-lived credentials, and self-hosted runner exposure on public repositories.
---

# GitHub Actions Hardening

A focused security reviewer for GitHub Actions workflows. It reasons about the
*Actions-specific* threat model, where trust boundaries live in trigger types, token
scopes and string interpolation, rather than the application-code vulnerabilities a
general scanner looks for. Most workflow risk is invisible to language linters because
the dangerous code is the YAML itself and the way GitHub expands `${{ }}` expressions
into a shell before the script runs.

## When to Use This Skill

Reviewing, auditing, hardening or authoring any file under `.github/workflows/`;
workflows on `pull_request_target`, `workflow_run` or `issue_comment` triggers;
questions about `GITHUB_TOKEN` and the `permissions:` key; pinning actions; handling
untrusted input (issue titles, PR bodies, branch names, commit messages) in `run:`
steps; OIDC and secret handling in CI; self-hosted runners on public repositories.

## The Core Insight

**`${{ <expr> }}` is expanded by the runner into the script *before* the shell executes
it.** So `- run: echo "Title: ${{ github.event.issue.title }}"` does not pass a
variable; it pastes attacker-controlled text into a shell command, and an issue titled
`"; <attacker-command> #` is concatenated into the script and executed. Treat every
`${{ }}` that carries data an outside contributor can influence as a code-injection sink.

## Execution Workflow

Follow these steps **in order** for every workflow reviewed.

**Step 1 — Map the triggers and trust level.** `push` and same-repo `pull_request` run
with the contributor's own trust. A fork `pull_request` gets a read-only token and no
secrets, safe by design. `pull_request_target`, `workflow_run`, `issue_comment` and
`issues` run in the base repository with a read/write token and full access to secrets
while being triggerable by outside contributors: these are the dangerous triggers. See
`references/triggers-and-privilege.md`.

**Step 2 — Hunt for script injection.** For every `run:` block, every `script:` in
`actions/github-script` and every custom action input, list the `${{ }}` expressions and
resolve which are attacker-controllable: `github.event.issue.title` and `.body`,
`github.event.pull_request.title`, `.body`, `.head.ref`, `.head.label`,
`github.event.comment.body`, `github.event.review.body`,
`github.event.commits.*.message`, `github.event.head_commit.*`, `github.head_ref`, and
any `github.event.*` field a fork author can set. See `references/injection.md`.

**Step 3 — Check privileged triggers don't execute untrusted code.** A
`pull_request_target` or `workflow_run` workflow that checks out PR or fork code
(`ref: ${{ github.event.pull_request.head.sha }}`) and then runs it (build, test,
install scripts, `npm install` with lifecycle scripts) is remote code execution against
a privileged token. Flag it CRITICAL. The safe pattern splits it in two: an unprivileged
`pull_request` workflow runs the untrusted code, a privileged `workflow_run` workflow
consumes only its results.

**Step 4 — Audit `permissions:`.** No `permissions:` block means the workflow inherits
the repository default, which may be read/write to everything: flag it. Recommend a
top-level `permissions: {}` or `contents: read`, then the minimum per job (for example
`pull-requests: write` only on the job that comments). Flag `permissions: write-all` and
any broad `write` scope the steps do not use.

**Step 5 — Audit action references.** Third-party actions (anything not `actions/*` or
`github/*`) MUST be pinned to a full 40-character commit SHA, because tags and branches
are mutable and a compromised upstream can rewrite `v1` to code that runs with your
token and secrets. First-party `actions/*` are lower risk, but SHA-pinning is still the
hardened recommendation. Flag `@main`, `@master` or any branch reference as HIGH, and
note the human-readable version in a trailing comment: `uses: foo/bar@<sha> # v2.1.0`.

**Step 6 — Check secret and output handling.** No secrets echoed, printed or written to
logs, and no `set -x` / `bash -x` in a step that touches one. Secrets must not reach
steps that run untrusted code or unpinned third-party actions. Untrusted multiline data
written to `$GITHUB_ENV` or `$GITHUB_OUTPUT` can inject variables or step outputs: use
the random-delimiter heredoc form and never write raw user input. `actions/checkout`
leaves a token on disk, so set `persist-credentials: false` when the job later runs
untrusted code.

**Step 7 — Produce the report.** Use the format in `references/report-format.md`: a
severity summary table first, then findings grouped by issue type, each with the file,
the exact offending YAML, the risk in plain English and a concrete before/after fix.
Write the report to `reports/actions-hardening.md` with `write_file`. Never auto-apply
changes — present them for review, and do not modify any file under `.github/`.

## Severity Guide

| Severity | Meaning | Example |
| --- | --- | --- |
| 🔴 CRITICAL | Token/secret theft or RCE reachable by an outside contributor | `pull_request_target` checking out and running fork code; `${{ github.event.* }}` in a `run:` on a privileged trigger |
| 🟠 HIGH | Exploitable supply-chain or scope problem | Third-party action on a mutable tag/branch; `write-all` permissions; injection sink on `issue_comment` |
| 🟡 MEDIUM | Risk under conditions or chaining | Missing `permissions:` block; secret reachable by a non-fork PR author |
| 🔵 LOW | Hardening gap, low direct risk | First-party action not SHA-pinned; `persist-credentials` left default on a non-privileged job |
| ⚪ INFO | Observation, not a vulnerability | Version comment missing next to a pinned SHA |

## Output Rules

Always show the findings summary table (counts by severity) first and group findings by
issue type rather than by file. Be exact: quote the offending line and give its
location. Pair every CRITICAL and HIGH with a concrete corrected YAML snippet. Never
claim a fork `pull_request` is dangerous merely because it runs untrusted code, since it
has no secrets and a read-only token; reserve CRITICAL for the privileged triggers. If
the workflow is already hardened, say so and list what was checked.

## Reference Files

Load these as needed:

* `references/triggers-and-privilege.md` — Trust matrix for every trigger, and the rules
  for privileged workflows.
  + Search patterns: `pull_request_target`, `workflow_run`, `issue_comment`, `fork`, `secrets`, `read-only token`, `trust boundary`
* `references/injection.md` — The vulnerable pattern, the `env:`-variable safe pattern,
  and a quick audit checklist.
  + Search patterns: `script injection`, `github.event`, `head_ref`, `issue title`, `env`, `intermediate variable`, `actions/github-script`
* `references/report-format.md` — Output template: summary table, finding cards, and the
  closing note.
  + Search patterns: `report`, `format`, `finding`, `summary`, `remediation`, `before`, `after`
