#!/bin/bash
# List incomplete shards of an experiment and (with --resubmit [--submit]) resubmit them.
# Thin wrapper: bench/runner/shards.py has the logic and all options.
#   bench/runner/slurm/resubmit.sh bench/configs/experiments/X.yaml --shards 8
set -euo pipefail
cd "$(dirname "$0")/../../.."
exec python -m bench.runner.shards "$@"
