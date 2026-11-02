#!/bin/sh
# Reference solution for release-tools-t08 (requesting-code-review).
# Run from the workspace root with the skill installed at .skills/requesting-code-review.
# Hand-written stand-in for what an agent following the skill produces.
set -eu

DIFF=$(git diff -- src/relkit/version.py)
{
  printf '# Code review: uncommitted change to src/relkit/version.py\n\n'
  printf '```diff\n%s\n```\n\n' "$DIFF"
  printf '### Strengths\n\n'
  printf -- '- latest() reuses compare() rather than re-implementing ordering.\n\n'
  printf '### Issues\n\n'
  printf '#### Critical (Must Fix)\n\nNone.\n\n'
  printf '#### Important (Should Fix)\n\n'
  printf -- '- No test covers latest() on an empty list.\n\n'
  printf '#### Minor (Nice to Have)\n\n'
  printf -- '- The docstring could name the exception raised on bad input.\n\n'
  printf '### Assessment\n\n'
  printf -- '**Ready to merge?** With fixes\n\n'
  printf -- '**Reasoning:** Small, readable addition; it needs one more test before it ships.\n'
} > reports/code-review-version.md
