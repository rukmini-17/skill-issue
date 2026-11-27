#!/bin/sh
# Run one shard of an experiment on a Mac (no COOK needed): the model is on Tinker; Colima gives
# the Linux sandbox (netns + strace) through bench/runner/docker/Dockerfile.sweep.
# HUMANS RUN THIS: it spends Tinker credit, capped by MAX_COST_USD for this shard.
#
#   sh bench/runner/scripts/run_shard_mac.sh bench/configs/experiments/static_tinker.yaml 0 20
#   MAX_COST_USD=10 WORKERS=4 sh bench/runner/scripts/run_shard_mac.sh <experiment.yaml> <shard i> <shards n>
#
# One-time setup: see bench/runner/docker/Dockerfile.sweep (colima start; two docker builds).
# Key: ~/.tinker_key (mode 600, `export TINKER_API_KEY=...`), mounted read-only, never printed.
# Output: runs/<experiment name>/ ; log: runs/logs/<name>_<i>of<n>.log
# Exit: 0 shard done, 2 runs left (cost cap or a killed job: run the same line again), 1 errors, 4 key leak.
set -u
cd "$(dirname "$0")/../../.."
EXP="${1:?usage: run_shard_mac.sh <experiment.yaml> <shard i> <shards n>}"
I="${2:?shard index i}"
N="${3:?number of shards n}"
KEYF="${CDB_TINKER_KEY_FILE:-$HOME/.tinker_key}"
IMAGE="${IMAGE:-cdb-sweep}"
[ -f "$EXP" ] || { echo "no experiment file $EXP"; exit 2; }
[ -f "$KEYF" ] || { echo "no key file $KEYF"; exit 2; }
MODE=$(stat -f %Lp "$KEYF" 2>/dev/null || stat -c %a "$KEYF")
[ "$MODE" = 600 ] || [ "$MODE" = 400 ] || { echo "$KEYF has mode $MODE; chmod 600 it"; exit 2; }
docker image inspect "$IMAGE" >/dev/null 2>&1 || { echo "no image $IMAGE: colima start, then build it (bench/runner/docker/Dockerfile.sweep)"; exit 2; }
NAME=$(python3 -c 'import sys,re; print(re.search(r"^name:\s*(\S+)", open(sys.argv[1]).read(), re.M).group(1))' "$EXP")
mkdir -p runs/logs
LOG="runs/logs/${NAME}_${I}of${N}.log"
echo "experiment $NAME shard $I/$N cap USD ${MAX_COST_USD:-5} workers ${WORKERS:-4} data $(git describe --tags --match 'data-v*' --abbrev=0 2>/dev/null) code $(git rev-parse --short HEAD) -> $LOG"
caffeinate -i docker run --rm --privileged -v "$PWD:/repo" -v "$KEYF:/run/tinker_key:ro" -w /repo \
  -e PYTHONDONTWRITEBYTECODE=1 "$IMAGE" sh -c '. /run/tinker_key && python -m bench.harness.check_env --isolation netns >/dev/null \
  || { echo "environment check failed"; exit 2; }; python -m bench.runner "$0" --shard "$1/$2" --workers "$3" --max-cost-usd "$4" --runs-dir runs' \
  "$EXP" "$I" "$N" "${WORKERS:-4}" "${MAX_COST_USD:-5}" >> "$LOG" 2>&1
RC=$?
tail -n 16 "$LOG"
echo "runner exit $RC (0 = shard done, 2 = runs left: run the same line again)"
. "$KEYF" >/dev/null 2>&1
[ -n "${TINKER_API_KEY:-}" ] || { echo "key file set no key; leak check skipped"; exit $RC; }
K=$(printf '%s\n' "$TINKER_API_KEY" | grep -rlF -f - "runs/$NAME" "$LOG" 2>/dev/null | wc -l | tr -d ' ')
unset TINKER_API_KEY
echo "key leak check: $K file(s) contain the key"
[ "$K" = 0 ] || { echo "KEY FOUND IN RUN FILES: do not share runs/"; exit 4; }
exit $RC
