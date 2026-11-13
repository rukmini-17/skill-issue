#!/bin/sh
# Reference solution for release-tools-t01 (changelog-automation).
# Run from the workspace root with the skill installed at .skills/changelog-automation.
# Hand-written stand-in for what an agent following the skill produces.
set -eu

# The harness tools are read_file / write_file, so the reference rewrites the whole
# file rather than editing in place. Only CHANGELOG.md is written.
cat > CHANGELOG.md <<'EOF'
# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project adheres to
Semantic Versioning.

## [Unreleased]

### Added

- `latest()` for selecting the highest version in a list

## [0.3.0] - 2026-02-03

### Added

- `compare()` for ordering two version strings
- Canonical section ordering in `render_section()`

### Fixed

- `parse()` now drops build metadata before splitting

## [0.2.0] - 2026-01-23

### Added

- `split_entries()` for grouping Conventional Commit subjects
- Release configuration file at `config/release.yaml`

### Changed

- `bump()` validates the requested part before parsing

## [0.1.0] - 2026-01-15

### Added

- Initial `parse()` and `bump()` helpers
EOF
