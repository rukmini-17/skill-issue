#!/bin/sh
# Reference solution for release-tools-t09 (github-actions-hardening).
# Run from the workspace root with the skill installed at .skills/github-actions-hardening.
# Hand-written stand-in for what an agent following the skill produces.
set -eu

cat > reports/actions-hardening.md <<'EOF'
GitHub Actions Hardening - .github/workflows/ci.yml

| Severity   | Count |
| ---------- | ----- |
| CRITICAL   | 2     |
| HIGH       | 2     |
| MEDIUM     | 1     |
| LOW        | 0     |
| INFO       | 0     |

### CRITICAL - Privileged trigger checks out and runs pull request code

File: .github/workflows/ci.yml (line 13)
Trigger: pull_request_target

Offending code:
    - uses: actions/checkout@v4
      with:
        ref: ${{ github.event.pull_request.head.sha }}

Risk: pull_request_target runs with a read/write token and repository secrets. Checking
out the fork's commit and then running ./release.sh --check executes contributor code
with those privileges.

Fix: split into an unprivileged pull_request workflow that runs the code and a
privileged workflow_run workflow that only consumes its results.

Confidence: High

### CRITICAL - Script injection via pull request title

File: .github/workflows/ci.yml (line 25)

Offending code:
    - run: echo "Testing PR: ${{ github.event.pull_request.title }}"

Risk: the title is pasted into the shell before it runs, so a title of
"; <attacker-command> # executes with the workflow token and secrets.

Fix:
    - env:
        PR_TITLE: ${{ github.event.pull_request.title }}
      run: echo "Testing PR: $PR_TITLE"

Confidence: High

### HIGH - Third-party action not pinned to a commit SHA

File: .github/workflows/ci.yml (line 31)
Offending code: uses: tj-actions/changed-files@v44

Risk: a tag is mutable, so the upstream owner or anyone who compromises them can
repoint v44 at code that runs with this workflow's token and secrets.

Fix: uses: tj-actions/changed-files@<40-character-sha> # v44

Confidence: High

### HIGH - Action referenced by a branch

File: .github/workflows/ci.yml (line 35)
Offending code: uses: codecov/codecov-action@main

Risk: @main is unversioned latest and can change at any time; this step also receives
CODECOV_TOKEN.

Fix: pin to a full commit SHA with a trailing version comment.

Confidence: High

### MEDIUM - No permissions block

File: .github/workflows/ci.yml (whole file)

Risk: the workflow inherits the repository default, which may be read/write to every
scope, widening the blast radius of the findings above.

Fix: add a top-level permissions: {} and grant contents: read on the job that checks out.

Confidence: High

> Review each change before committing. Nothing has been modified.
EOF
