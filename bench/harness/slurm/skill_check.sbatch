#!/bin/bash
# Mini skill-load check: ONE run per task for a short task list, one model, v1, policy
# none, netns + strace, through the pilot runner (resumable). Default: explicit invocation
# (decision 8 wording), five tasks that cover all four repos. HUMANS SUBMIT THIS.
# On COOK (ssh -l 'rnazre@umass.edu' cook.cs.umass.edu), from the repo root:
#
#   sh bench/harness/scripts/cook_submit.sh skill-check qwen3-14b-llamacpp   # t4, 24G
#   sh bench/harness/scripts/cook_submit.sh skill-check qwen3-32b-llamacpp   # rtx, 40G
#   INVOCATION=natural TASKS=ops-office-t05,shop-web-t05 sh bench/harness/scripts/cook_submit.sh skill-check ...
#   cat runs/skill_check/logs/cdb-skill-check-<jobid>.out
#
# Runs go to runs/skill_check/<model>[+explicit-v2]/<task>/r0/. Each run gets at most
# RUN_TIMEOUT s (default 1200), and no run starts unless it can finish before the 2-hour
# limit, so 5 runs fit even if every run is slow. Resubmitting the same command only
# runs what is missing. The log ends with one line per task: skill_load / skill_used / success.
#SBATCH --job-name=cdb-skill-check
#SBATCH --partition=gtx
#SBATCH --gres=gpu:1
#SBATCH --time=02:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --output=runs/skill_check/logs/%x-%j.out

set -u
cd "${SLURM_SUBMIT_DIR:-.}"
mkdir -p runs/skill_check/logs
START=$(date +%s)
. bench/harness/slurm/cook_env.sh           # module load per partition; sets PY, LLAMA_SERVER
"$PY" -m bench.harness.check_env --isolation netns || { echo "environment check failed; see above"; exit 2; }
MODEL="${MODEL:?set MODEL, e.g. --export=ALL,MODEL=qwen3-14b-llamacpp}"
INVOCATION="${INVOCATION:-explicit}"
TASKS="${TASKS:-ops-office-t05,ops-office-t01,orders-api-t01,shop-web-t05,release-tools-t03}"
RUN_TIMEOUT="${RUN_TIMEOUT:-1200}"
LIMIT_S="${LIMIT_S:-7200}"                      # must match --time
OUT=runs/skill_check
export CDB_PORT=$(( 20000 + ${SLURM_JOB_ID:-0} % 20000 ))

GGUF=$("$PY" -m bench.backends get "$MODEL" model_file)
[ -f "$GGUF" ] || { echo "model file not found: $GGUF"; exit 2; }
SERVE=$("$PY" -m bench.backends serve-cmd "$MODEL") || exit 2
echo "job ${SLURM_JOB_ID:-?} node $(hostname) port $CDB_PORT git $(git rev-parse --short HEAD)"
echo "model $MODEL invocation $INVOCATION tasks $TASKS run_timeout $RUN_TIMEOUT"
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null || true
echo "server: $SERVE"
SLOG="$OUT/logs/llama-server-${SLURM_JOB_ID:-x}.log"
eval "cdb_start_server \"\$SLOG\" $SERVE"
trap 'kill $SRV 2>/dev/null; wait $SRV 2>/dev/null' EXIT

"$PY" -m bench.backends wait "$MODEL" --timeout 900 || { echo "server not ready; see $SLOG"; cdb_log_buffers "$SLOG"; tail -n 30 "$SLOG"; exit 3; }
cdb_log_buffers "$SLOG"
echo "server ready after $(( $(date +%s) - START )) s"

ELAPSED=$(( $(date +%s) - START ))
"$PY" -m bench.harness.pilot run --model "$MODEL" --invocation "$INVOCATION" --setup "${SETUP:-d9}" --tasks "$TASKS" \
    --repeats 1 --workers 1 --isolation netns --run-timeout "$RUN_TIMEOUT" \
    --deadline-s $(( LIMIT_S - ELAPSED - 300 )) --no-wait --out "$OUT"
RC=$?
echo "pilot exit $RC (0 = all done, 2 = runs left; resubmit to resume)"
echo
echo "===== skill-load check: $MODEL, invocation $INVOCATION ====="
"$PY" -m bench.harness.pilot report --root "$OUT" --tasks "$TASKS" --model "$MODEL" --timing
exit $RC
