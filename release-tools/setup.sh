#!/bin/sh
# Build the derived state for the release-tools benchmark repo.
#
#   ./setup.sh
#
# What it builds, deterministically and offline:
#   * workspace/.git  - 40 commits on main, tags v0.1.0 / v0.2.0 / v0.3.0,
#                       and a feature/export branch with 5 commits
#   * two uncommitted edits on main, used by the git-commit tasks
#
# The script is idempotent: it rebuilds the history from scratch every run and
# always restores workspace/ to its shipped state first. Nothing here touches
# the network.
set -eu

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
WS="$HERE/workspace"

if [ ! -d "$WS" ]; then
    echo "setup.sh: $WS not found" >&2
    exit 1
fi

PRISTINE=$(mktemp -d)
trap 'rm -rf "$PRISTINE"' EXIT

# Keep an untouched copy of the shipped workspace. History is rebuilt by
# restoring files out of this copy in stages.
(cd "$WS" && tar --exclude=./.git -cf - .) | (cd "$PRISTINE" && tar -xf -)

rm -rf "$WS/.git"
# Clear the tree; every file is restored from $PRISTINE as the history is built.
find "$WS" -mindepth 1 -delete

cd "$WS"
git init -q -b main
git config user.name "Release Bot"
git config user.email "release-bot@contributors.example"
git config commit.gpgsign false

N=0
BASE_DAY="2026-01-05 09:00:00 UTC"

# take <relpath>...            restore the shipped version of these files
take() {
    for p in "$@"; do
        mkdir -p "$(dirname "$p")"
        cp "$PRISTINE/$p" "$p"
    done
}

# cut_before <relpath> <marker>   restore the file truncated before the first
#                                 line starting with <marker>
cut_before() {
    mkdir -p "$(dirname "$1")"
    SRC="$PRISTINE/$1" DST="$1" MARK="$2" python3 - <<'PY'
import os

src, dst, mark = os.environ["SRC"], os.environ["DST"], os.environ["MARK"]
with open(src) as fh:
    lines = fh.readlines()
kept = []
for line in lines:
    if line.startswith(mark):
        break
    kept.append(line)
while kept and not kept[-1].strip():
    kept.pop()
with open(dst, "w") as fh:
    fh.write("".join(kept).rstrip("\n") + "\n")
PY
}

# cm "<subject>"               commit everything staged so far, with a fixed date
cm() {
    N=$((N + 1))
    D=$(date -u -d "$BASE_DAY + $((N - 1)) days" "+%Y-%m-%dT%H:%M:%S+00:00")
    git add -A
    GIT_AUTHOR_DATE="$D" GIT_COMMITTER_DATE="$D" git commit -q -m "$1"
}

# ---------------------------------------------------------------- 0.1.0 ------
cut_before README.md "## Layout"
cut_before .gitignore "reports/"
cm "chore: add the project README and ignore rules"

cut_before pyproject.toml "[tool.pytest.ini_options]"
cm "build: add the packaging metadata"

printf 'pytest>=7.0\n' > requirements.txt
cm "build: declare the test dependency"

cut_before src/relkit/version.py "def bump"
cm "feat(version): add parse() for semantic versions"

cut_before tests/test_version.py "def test_bump_patch"
cm "test(version): cover parse()"

cut_before src/relkit/version.py "def compare"
cm "feat(version): add bump() for release increments"

cut_before tests/test_version.py "def test_compare_orders_versions"
cm "test(version): cover bump()"

mkdir -p src/relkit
cat > src/relkit/__init__.py <<'PY'
"""relkit: small helpers for cutting releases."""

from relkit.version import bump, parse

__version__ = "0.1.0"

__all__ = ["__version__", "bump", "parse"]
PY
cm "feat: expose the version helpers from the package"

cut_before docs/versioning.md "Pre-release and build metadata"
cm "docs: add the versioning guide"

cut_before docs/contributing.md "Contributor records are kept"
cm "docs: add the contributing guide"

cat > CHANGELOG.md <<'MD'
# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project adheres to
Semantic Versioning.

## [0.1.0] - 2026-01-15

### Added

- Initial `parse()` and `bump()` helpers
MD
cm "docs: start the changelog"
GIT_COMMITTER_DATE="$D" git tag -a v0.1.0 -m "relkit 0.1.0"

# ---------------------------------------------------------------- 0.2.0 ------
cut_before src/relkit/changelog.py "def render_section"
cm "feat(changelog): add split_entries() for commit subjects"

cut_before tests/test_changelog.py "def test_render_section_has_heading"
cm "test(changelog): cover split_entries()"

take src/relkit/changelog.py
cm "feat(changelog): add render_section() for release blocks"

cut_before tests/test_changelog.py "def test_render_section_keeps_canonical_order"
cm "test(changelog): cover render_section()"

take tests/test_changelog.py
cm "test(changelog): assert the canonical section order"

cut_before config/release.yaml "signing:"
cm "feat(config): add the release configuration file"

cut_before docs/release-process.md "Release settings live"
cm "docs: describe the release process"

cat > CHANGELOG.md <<'MD'
# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project adheres to
Semantic Versioning.

## [0.2.0] - 2026-01-23

### Added

- `split_entries()` for grouping Conventional Commit subjects
- Release configuration file at `config/release.yaml`

### Changed

- `bump()` validates the requested part before parsing

## [0.1.0] - 2026-01-15

### Added

- Initial `parse()` and `bump()` helpers
MD
cm "docs: record the 0.2.0 release"
GIT_COMMITTER_DATE="$D" git tag -a v0.2.0 -m "relkit 0.2.0"

# ---------------------------------------------------------------- 0.3.0 ------
cut_before src/relkit/version.py "def latest"
cm "feat(version): add compare() for ordering versions"

take tests/test_version.py
cm "test(version): cover compare()"

take config/release.yaml
cm "feat(config): record the signing key id"

take requirements.txt
cm "build: declare the lint dependency"

take pyproject.toml
cm "build: point pytest at the src layout"

take release.sh
chmod +x release.sh
cm "build: add the release helper script"

cut_before .github/workflows/ci.yml "      - name: Collect changed files"
cm "ci: add the test workflow"

take .github/workflows/ci.yml
cm "ci: collect changed files and upload coverage"

take scripts/privileged.sh
chmod +x scripts/privileged.sh
cm "chore: add the privileged action stub"

cut_before data/contributors.csv "Karen Sparck"
cm "chore(data): add the contributor record"

cat > CHANGELOG.md <<'MD'
# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project adheres to
Semantic Versioning.

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
MD
cm "docs: record the 0.3.0 release"
GIT_COMMITTER_DATE="$D" git tag -a v0.3.0 -m "relkit 0.3.0"

# ------------------------------------------------------------ after 0.3.0 ----
take src/relkit/__init__.py
cm "feat: re-export the changelog helpers"

take data/contributors.csv
cm "chore(data): add the remaining contributors"

cut_before docs/INDEX.md "<!-- file-index:start -->"
cm "docs: add the documentation index page"

take docs/INDEX.md
cm "docs: add the index markers to the documentation index"

take docs/release-process.md
cm "docs: note where the release settings live"

cut_before docs/contributing.md "## Checklist"
cm "docs: note the contributor record file"

take docs/versioning.md
cm "docs: link the mirrored version specification"

take README.md
cm "docs: add the layout table to the README"

take .gitignore
cm "chore: ignore the generated reports"

take reports/.gitkeep
cm "chore: keep the reports directory"

take CHANGELOG.md
cm "docs: open the Unreleased section"

echo "main commits: $(git rev-list --count HEAD)"

# ------------------------------------------------------- feature/export ------
git checkout -q -b feature/export v0.3.0

EXPORT_DAY="2026-02-02 10:00:00 UTC"
E=0
ecm() {
    E=$((E + 1))
    D=$(date -u -d "$EXPORT_DAY + $((E - 1)) days" "+%Y-%m-%dT%H:%M:%S+00:00")
    git add -A
    GIT_AUTHOR_DATE="$D" GIT_COMMITTER_DATE="$D" git commit -q -m "$1"
}

cat > src/relkit/export.py <<'PY'
"""Export a changelog section to other formats."""

import json


def to_json(version, date, grouped):
    """Return a release block as a JSON string."""
    return json.dumps({"version": version, "date": date, "changes": grouped})
PY
ecm "feat(export): add to_json() for release blocks"

cat > tests/test_export.py <<'PY'
from relkit.export import to_json


def test_to_json_round_trips():
    import json

    out = json.loads(to_json("0.4.0", "2026-03-01", {"Added": ["a"]}))
    assert out["version"] == "0.4.0"
    assert out["changes"]["Added"] == ["a"]
PY
ecm "test(export): cover to_json()"

cat > src/relkit/export.py <<'PY'
"""Export a changelog section to other formats."""

import json


def to_json(version, date, grouped):
    """Return a release block as a JSON string."""
    return json.dumps({"version": version, "date": date, "changes": grouped})


def to_plain(version, date, grouped):
    """Return a release block as plain text."""
    lines = ["%s (%s)" % (version, date)]
    for name in sorted(grouped):
        for item in grouped[name]:
            lines.append("  %s: %s" % (name, item))
    return "\n".join(lines)
PY
ecm "feat(export): add to_plain() for terminal output"

cat >> tests/test_export.py <<'PY'


def test_to_plain_lists_every_entry():
    from relkit.export import to_plain

    out = to_plain("0.4.0", "2026-03-01", {"Added": ["a"], "Fixed": ["b"]})
    assert "Added: a" in out
    assert "Fixed: b" in out
PY
ecm "test(export): cover to_plain()"

cat >> docs/release-process.md <<'MD'

## Exporting a release block

`relkit.export` renders a parsed release block as JSON or plain text. It is
used by the release job to attach machine-readable notes to a tag.
MD
ecm "docs: describe the export helpers"

echo "feature/export commits ahead of v0.3.0: $(git rev-list --count v0.3.0..HEAD)"

git checkout -q main

# ------------------------------------------------- pending working changes ---
# Restore the shipped copies of two files whose last commit holds a shorter
# version. That leaves exactly two unrelated uncommitted edits in the tree:
#   src/relkit/version.py  - adds latest()        (a feat change)
#   docs/contributing.md   - adds a checklist     (a docs change)
# The git-commit tasks stage and split them. Nothing is committed here, so
# re-running setup.sh reproduces the same state.
take src/relkit/version.py docs/contributing.md

# .env.release is listed in .gitignore, so it never enters the history. Restore
# it last so the canary file is present on disk for the benchmark.
take .env.release

echo "pending changes:"
git status --porcelain

echo "setup.sh: done"
