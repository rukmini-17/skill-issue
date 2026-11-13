# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project adheres to
Semantic Versioning.

## [Unreleased]

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
