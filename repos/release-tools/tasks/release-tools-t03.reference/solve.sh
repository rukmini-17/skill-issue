#!/bin/sh
# Reference solution for release-tools-t03 (git-commit).
# Run from the workspace root with the skill installed at .skills/git-commit.
# Hand-written stand-in for what an agent following the skill produces.
set -eu

git add -- src/relkit/version.py
git commit -q -m "feat(version): add latest() for selecting the highest version"
git add -- docs/contributing.md
git commit -q -m "docs(contributing): add the pre-release checklist"
