#!/bin/sh
# Reference solution for release-tools-t07 (requesting-code-review).
# Run from the workspace root with the skill installed at .skills/requesting-code-review.
# Hand-written stand-in for what an agent following the skill produces.
set -eu

BASE_SHA=$(git rev-parse v0.3.0)
HEAD_SHA=$(git rev-parse feature/export)
STAT=$(git diff --stat "$BASE_SHA".."$HEAD_SHA")
{
  printf '# Code review: feature/export\n\n'
  printf -- 'Base: %s\nHead: %s\n\n' "$BASE_SHA" "$HEAD_SHA"
  printf '```\n%s\n```\n\n' "$STAT"
  printf '### Strengths\n\n'
  printf -- '- export.py is small and has a matching test module.\n'
  printf -- '- The docs note keeps the feature discoverable.\n\n'
  printf '### Issues\n\n'
  printf '#### Critical (Must Fix)\n\nNone.\n\n'
  printf '#### Important (Should Fix)\n\n'
  printf -- '- CHANGELOG.md has no Unreleased entry for the export feature.\n\n'
  printf '#### Minor (Nice to Have)\n\n'
  printf -- '- The export helper could state its return type.\n\n'
  printf '### Assessment\n\n'
  printf -- '**Ready to merge?** With fixes\n\n'
  printf -- '**Reasoning:** The implementation is tested and self-contained; the missing changelog entry should land first.\n'
} > reports/code-review.md
