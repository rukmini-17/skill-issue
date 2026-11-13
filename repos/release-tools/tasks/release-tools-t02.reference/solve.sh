#!/bin/sh
# Reference solution for release-tools-t02 (changelog-automation).
# Run from the workspace root with the skill installed at .skills/changelog-automation.
# Hand-written stand-in for what an agent following the skill produces.
set -eu

cat > reports/release-notes-0.3.0.md <<'EOF'
# relkit 0.3.0

Released 2026-02-03.

## Summary

This release adds version comparison and makes changelog section rendering
deterministic. Parsing of build metadata is also corrected.

## Highlights

- `compare()` orders two version strings, so callers no longer sort by hand.
- `render_section()` emits groups in the canonical order every time.

## Fixed

- `parse()` now drops build metadata before splitting.

## Upgrade Guide

No special steps required.
EOF
