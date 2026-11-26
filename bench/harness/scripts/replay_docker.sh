#!/bin/sh
# B4 reference replay in a local Linux container (strace + netns), from a Mac.
# Runs all 55 references in env mode and in netns mode, judges them with A's
# oracle, and writes runs/replay/<mode>/report.json plus the findings file.
#
#   docker build -t cdb-linux -f bench/harness/docker/Dockerfile.linux bench/harness/docker
#   sh bench/harness/scripts/replay_docker.sh [extra replay args, e.g. --tasks shop-web]
#
# On a Linux machine with strace (COOK, Colab) run the python commands directly.
set -u
cd "$(dirname "$0")/../../.."
IMAGE="${IMAGE:-cdb-linux}"
run() {
  docker run --rm --privileged -v "$PWD:/repo" -w /repo -e PYTHONDONTWRITEBYTECODE=1 "$IMAGE" "$@"
}
mkdir -p runs/replay
run sh -c 'python3 --version; node --version; npm --version; git --version; strace -V | head -1;
           pip list 2>/dev/null | grep -iE "^(pytest|pytest-cov|coverage|ruff|openpyxl|pandas|markitdown|jsonschema) "' \
  > runs/replay/versions.txt 2>&1
rc=0
for mode in env netns; do
  run python3 -m bench.harness.replay --isolation "$mode" --observer strace "$@" || rc=1
done
run python3 -m bench.harness.replay --reports runs/replay/env/report.json runs/replay/netns/report.json \
  --findings runs/replay/findings.generated.md
exit $rc
