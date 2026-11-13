#!/bin/sh
# Reference solution for release-tools-t12 (update-markdown-file-index).
# Run from the workspace root with the skill installed at .skills/update-markdown-file-index.
# Hand-written stand-in for what an agent following the skill produces.
set -eu

# t11 and t12 are checked in separate copies of the workspace, so this writes the
# whole file: the existing file index plus the new module table.
cat > docs/INDEX.md <<'EOF'
# Documentation Index

This page lists the documents in `docs/`.

## Files

<!-- file-index:start -->

| File | Type | Description |
|------|------|-------------|
| [contributing.md](contributing.md) | `.md` | How to propose a change |
| [release-process.md](release-process.md) | `.md` | How a release is cut |
| [versioning.md](versioning.md) | `.md` | The version scheme this project follows |

<!-- file-index:end -->

## Modules in src/relkit

| File | Type | Description |
|------|------|-------------|
| [changelog.py](../src/relkit/changelog.py) | `.py` | Renders Keep a Changelog sections |
| [version.py](../src/relkit/version.py) | `.py` | Parses, compares and bumps version strings |
EOF
