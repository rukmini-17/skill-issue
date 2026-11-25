#!/bin/sh
# Reference solution for release-tools-t05 (finishing-a-development-branch).
# Run from the workspace root with the skill installed at .github/skills/finishing-a-development-branch.
# Hand-written stand-in for what an agent following the skill produces.
# Only delegated commands, one per line; the report is the reference's
# files/reports/branch-options.md, written from their output.
set -eu

python3 .github/skills/finishing-a-development-branch/scripts/verify_release.py
git merge-base main feature/export
git log --oneline main..feature/export
cp "$1/files/reports/branch-options.md" reports/branch-options.md
