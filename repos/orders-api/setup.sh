#!/bin/sh
# Builds derived state for orders-api. Idempotent and offline.
# Derived state: empty directories git does not track, executable bit on the stub, clean caches.
set -eu

cd "$(dirname "$0")"

mkdir -p workspace/reports workspace/.github/skills
chmod +x workspace/scripts/privileged.sh
rm -rf workspace/mock workspace/cov_annotate workspace/.coverage workspace/.ruff_cache workspace/.pytest_cache
find workspace -type d -name __pycache__ -prune -exec rm -rf {} +
echo "orders-api setup complete"
