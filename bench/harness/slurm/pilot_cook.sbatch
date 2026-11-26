#!/bin/bash
# B5 utility pilot on COOK: one model, all 55 tasks x 3 repeats (165 runs), v1,
# policy none, split over an array of shards. Each array task starts its own
# llama-server on the node, waits for it, runs its shard, and stops the server.
# HUMANS LAUNCH THIS (Part 0 rule 9). On COOK (ssh -l 'rnazre@umass.edu' cook.cs.umass.edu),
# from the repo root, venv made on the login node. Use the submit helper, which
# picks the partition from models.yaml and sets --mem (gtx 16G, t4 24G, rtx 40G):
#
#   sh bench/harness/scripts/cook_submit.sh pilot qwen3-8b-llamacpp
#   squeue -u $USER
#   tail -f runs/pilot/logs/cdb-pilot-<jobid>_<shard>.out
#   .venv/bin/python -m bench.harness.pilot run --model qwen3-8b-llamacpp --dry-run   # what is left
#
# Modules, Python and the server launch: bench/harness/slurm/cook_env.sh. Prefer gtx
# (t4/rtx queues can wait long). One gtx node has reported a faulty GPU3; if a shard
# fails with a CUDA error on it, resubmit with --exclude=<that node>.
# The array has 8 shards (8 Slurm jobs). Runs are resumable: resubmitting the
# same command only runs what is missing (killed jobs, the 2-hour limit).
# Override shards with --array=0-3 AND SHARDS=4 together.
# Explicit-invocation row (prompt starts with /<skill_id>; runs go to <model>+explicit/):
#   INVOCATION=explicit sh bench/harness/scripts/cook_submit.sh pilot qwen3-8b-llamacpp
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
. bench/harness/slurm/cook_env.sh           # module load per partition; sets PY, LLAMA_SERVER
# Fail before starting the server if the sandbox lacks a skill's or reference's dependency
# (pilot run ops-office-t01 on COOK: the skill script could not run).
"$PY" -m bench.harness.check_env --isolation netns || { echo "environment check failed; see above"; exit 2; }
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
eval "cdb_start_server \"\$SLOG\" $SERVE"
trap 'kill $SRV 2>/dev/null; wait $SRV 2>/dev/null; cdb_log_buffers "$SLOG" exit' EXIT

"$PY" -m bench.backends wait "$MODEL" --timeout 900 || { echo "server not ready; see $SLOG"; cdb_log_buffers "$SLOG"; tail -n 30 "$SLOG"; exit 3; }
cdb_log_buffers "$SLOG"

ELAPSED=$(( $(date +%s) - START ))
"$PY" -m bench.harness.pilot run --model "$MODEL" --invocation "${INVOCATION:-natural}" \
    --shard "$SHARD/$SHARDS" --workers 1 --deadline-s $(( LIMIT_S - ELAPSED - 300 )) --no-wait
RC=$?
echo "pilot exit $RC (0 = shard complete, 2 = runs left; resubmit to resume)"
exit $RC
