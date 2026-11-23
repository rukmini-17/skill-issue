#!/bin/bash
# One shard of an experiment on COOK (D3). Submit through bench/runner/shards.py (which sets the
# variables below via --export), or by hand:
#   sbatch --array=0-3 --export=ALL,EXPERIMENT=$PWD/bench/configs/experiments/X.yaml,NSHARDS=4 bench/runner/slurm/run_shard.sbatch
# The array index is the shard number i; the job runs `--shard i/NSHARDS`.
# Decided by workstream D; COOK partition/GRES/module details are NOT known to us: edit the lines
# marked CHECK once a human has confirmed them on the cluster.
#
#SBATCH --job-name=cdb-shard
#SBATCH --partition=gtx                    # CHECK: gtx for Qwen3 4B/8B, t4 for 14B, rtx for 32B (override with sbatch --partition)
#SBATCH --time=02:00:00                    # COOK limit is 2 hours
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --output=runs/slurm_logs/%x-%A_%a.out

set -euo pipefail

: "${EXPERIMENT:?set EXPERIMENT to the experiment yaml path}"
: "${NSHARDS:?set NSHARDS}"
SHARD="${SLURM_ARRAY_TASK_ID:-0}"
WORKERS="${WORKERS:-1}"
DRY_RUN="${DRY_RUN:-0}"
RUNS_DIR="${RUNS_DIR:-runs}"
# Stop starting new groups with 15 minutes to spare so the shard exits cleanly; SIGTERM is also honoured.
MAX_SECONDS="${MAX_SECONDS:-6300}"
REPO_DIR="${REPO_DIR:-$SLURM_SUBMIT_DIR}"
VENV="${VENV:-$REPO_DIR/.venv}"                      # CHECK: where the Python env lives on COOK

cd "$REPO_DIR"
# shellcheck disable=SC1091
[ -f "$VENV/bin/activate" ] && source "$VENV/bin/activate"
mkdir -p "$RUNS_DIR/slurm_logs"

# Optional model server for real (non dry-run) jobs, e.g. llama.cpp on this node. Example only:
#   LLAMA_SERVER_CMD='llama-server -m /nfs/opt/models/<file>.gguf --port 8080 --jinja'
SERVER_PID=""
if [ -n "${LLAMA_SERVER_CMD:-}" ]; then
  $LLAMA_SERVER_CMD > "$RUNS_DIR/slurm_logs/server-${SLURM_JOB_ID:-local}_${SHARD}.log" 2>&1 &
  SERVER_PID=$!
  trap '[ -n "$SERVER_PID" ] && kill "$SERVER_PID" 2>/dev/null || true' EXIT
  for _ in $(seq 1 120); do
    curl -sf "http://127.0.0.1:${LLAMA_PORT:-8080}/health" >/dev/null 2>&1 && break
    sleep 2
  done
fi

ARGS=(--shard "${SHARD}/${NSHARDS}" --workers "$WORKERS" --max-seconds "$MAX_SECONDS" --runs-dir "$RUNS_DIR")
[ "$DRY_RUN" = "1" ] && ARGS+=(--dry-run)

echo "[$(date -Is)] shard ${SHARD}/${NSHARDS} on $(hostname), experiment ${EXPERIMENT}"
python -m bench.runner "$EXPERIMENT" "${ARGS[@]}"
echo "[$(date -Is)] shard ${SHARD}/${NSHARDS} finished"
