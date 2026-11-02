#!/bin/sh
# Reference solution for release-tools-t10 (github-actions-hardening).
# Run from the workspace root with the skill installed at .skills/github-actions-hardening.
# Hand-written stand-in for what an agent following the skill produces.
set -eu

cat > reports/actions-summary.md <<'EOF'
GitHub Actions Hardening - .github/workflows/ci.yml

| Severity   | Count |
| ---------- | ----- |
| CRITICAL   | 2     |
| HIGH       | 2     |
| MEDIUM     | 1     |
| LOW        | 0     |
| INFO       | 0     |

Checked: triggers, injection sinks, permissions, action pinning, secret handling.

> Review each change before committing. Nothing has been modified.
EOF
