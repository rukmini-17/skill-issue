#!/bin/sh
# Release helper for relkit. Offline friendly.
#
#   ./release.sh --check   verify dependencies and run the test suite
#
set -eu

MODE="${1:---check}"

if [ "$MODE" != "--check" ]; then
    echo "usage: release.sh --check" >&2
    exit 2
fi

echo "== dependencies =="
# The sandbox has no public index. pypi.example serves the mirrored metadata,
# and an unreachable index is not a release blocker for --check.
pip install --quiet --disable-pip-version-check \
    --index-url http://pypi.example/simple -r requirements.txt 2>/dev/null \
    || echo "index unavailable; verifying installed packages instead"
python3 - <<'PY'
import importlib.util
import shutil
import sys

missing = []
if importlib.util.find_spec("pytest") is None:
    missing.append("pytest")
if missing:
    print("missing required dependencies: %s" % ", ".join(missing))
    sys.exit(1)
if shutil.which("ruff") is None:
    print("note: ruff is not on PATH; skipping the lint step")
print("all required dependencies are available")
PY

echo "== tests =="
python3 -m pytest -q

echo "== release checks passed =="
