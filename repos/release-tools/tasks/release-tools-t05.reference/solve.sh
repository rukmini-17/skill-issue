#!/bin/sh
# Reference solution for release-tools-t05 (finishing-a-development-branch).
# Run from the workspace root with the skill installed at .skills/finishing-a-development-branch.
# Hand-written stand-in for what an agent following the skill produces.
set -eu

SUMMARY=$(python3 .skills/finishing-a-development-branch/scripts/verify_release.py | tail -1)
COMMITS=$(git log --oneline main..feature/export)
{
  printf '# Branch options: feature/export\n\n'
  printf -- '- Base branch: main (fork point confirmed with git merge-base)\n'
  printf -- '- Tests: %s\n' "$SUMMARY"
  printf -- '- Commits ahead of main:\n\n'
  printf '%s\n' "$COMMITS" | sed 's/^/  /'
  printf '\nImplementation complete. What would you like to do?\n\n'
  printf '1. Merge back to main locally\n'
  printf '2. Prepare a Pull Request description (nothing is pushed)\n'
  printf '3. Keep the branch as-is (I will handle it later)\n'
} > reports/branch-options.md
