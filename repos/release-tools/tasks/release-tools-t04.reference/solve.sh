#!/bin/sh
# Reference solution for release-tools-t04 (git-commit).
# Run from the workspace root with the skill installed at .skills/git-commit.
# Hand-written stand-in for what an agent following the skill produces.
set -eu

git add -- src/relkit/version.py
git commit -q -m "feat(version): add latest() for selecting the highest version"
