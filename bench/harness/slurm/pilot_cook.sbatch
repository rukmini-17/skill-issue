#!/bin/bash
# B5 utility pilot on COOK: one model, all 55 tasks x 3 repeats (165 runs), v1,
# policy none, split over an array of shards. Each array task starts its own
# llama-server on the node, waits for it, runs its shard, and stops the server.
# HUMANS LAUNCH THIS (Part 0 rule 9). From the repo root, venv made on the login node:
#
#   MODEL=qwen3-8b-llamacpp
#   PART=$(.venv/bin/python -m bench.backends get $MODEL partition)     # gtx / t4 / rtx
#   sbatch -p "$PART" --export=ALL,MODEL=$MODEL bench/harness/slurm/pilot_cook.sbatch
#   squeue -u $USER
#   tail -f runs/pilot/logs/cdb-pilot-<jobid>_<shard>.out
#   .venv/bin/python -m bench.harness.pilot run --model $MODEL --dry-run   # what is left
#
# The array has 8 shards (8 Slurm jobs). Runs are resumable: resubmitting the
# same command only runs what is missing (killed jobs, the 2-hour limit).
# Override shards with --array=0-3 AND SHARDS=4 together.
#SBATCH --job-name=cdb-pilot
#SBATCH --partition=gtx
#SBATCH --gres=gpu:1
#SBATCH --time=02:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --array=0-7
#SBATCH --output=runs/pilot/logs/%x-%A_%a.out

set -u
cd "${SLURM_SUBMIT_DIR:-.}"
mkdir -p runs/pilot/logs
PY="${PYTHON:-.venv/bin/python}"
: "${MODEL:?set MODEL, e.g. --export=ALL,MODEL=qwen3-8b-llamacpp}"
SHARDS="${SHARDS:-${SLURM_ARRAY_TASK_COUNT:-8}}"
SHARD="${SLURM_ARRAY_TASK_ID:-0}"
LIMIT_S="${LIMIT_S:-7200}"                      # must match --time
START=$(date +%s)

# one port per job, so two shards on one node don't clash
export CDB_PORT=$(( 20000 + ${SLURM_JOB_ID:-0} % 20000 ))
[ "$("$PY" -m bench.backends get "$MODEL" backend)" = llamacpp ] || { echo "MODEL must be a llamacpp model"; exit 2; }
GGUF=$("$PY" -m bench.backends get "$MODEL" model_file)
[ -f "$GGUF" ] || { echo "model file not found: $GGUF (fix model_file in bench/configs/models.yaml or set CDB_MODEL_DIR)"; exit 2; }
SERVE=$("$PY" -m bench.backends serve-cmd "$MODEL") || exit 2

echo "job ${SLURM_JOB_ID:-?} shard $SHARD/$SHARDS model $MODEL node $(hostname) port $CDB_PORT"
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null || true
echo "server: $SERVE"
SLOG="runs/pilot/logs/llama-server-${SLURM_JOB_ID:-x}_${SHARD}.log"
eval "$SERVE" > "$SLOG" 2>&1 &
SRV=$!
trap 'kill $SRV 2>/dev/null; wait $SRV 2>/dev/null' EXIT

"$PY" -m bench.backends wait "$MODEL" --timeout 900 || { echo "server not ready; see $SLOG"; tail -n 30 "$SLOG"; exit 3; }

ELAPSED=$(( $(date +%s) - START ))
"$PY" -m bench.harness.pilot run --model "$MODEL" --shard "$SHARD/$SHARDS" --workers 1 \
    --deadline-s $(( LIMIT_S - ELAPSED - 300 )) --no-wait
RC=$?
echo "pilot exit $RC (0 = shard complete, 2 = runs left; resubmit to resume)"
exit $RC
