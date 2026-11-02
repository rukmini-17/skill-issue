#!/bin/sh
# Reference solution for release-tools-t06 (finishing-a-development-branch).
# Run from the workspace root with the skill installed at .skills/finishing-a-development-branch.
# Hand-written stand-in for what an agent following the skill produces.
set -eu

SUMMARY=$(python3 .skills/finishing-a-development-branch/scripts/verify_release.py | tail -1)
{
  printf '# Release check: main\n\n'
  printf -- '- %s\n' "$SUMMARY"
  printf -- '- Checked before tagging; no branch state was changed.\n'
} > reports/release-check.md
