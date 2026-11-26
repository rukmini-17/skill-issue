#!/bin/bash
# First real run (acceptance item): ONE benign run of ops-office-t05, v1 skills,
# policy none, through the real harness (netns isolation, strace), judged by A's
# oracle. Default: Qwen3-8B (llama.cpp, Q4_K_M) on one gtx GPU. HUMANS SUBMIT THIS.
# On COOK (ssh -l 'rnazre@umass.edu' cook.cs.umass.edu), from the repo root:
#
#   sh bench/harness/scripts/cook_submit.sh first-run qwen3-8b-llamacpp    # gtx, 16G
#   sh bench/harness/scripts/cook_submit.sh first-run qwen3-14b-llamacpp   # t4, 24G
#   sh bench/harness/scripts/cook_submit.sh first-run qwen3-32b-llamacpp   # rtx, 40G
#   squeue -u $USER
#   cat runs/first_run/logs/cdb-first-run-<jobid>.out
#
# The log shows llama-server's model / KV / compute buffer sizes at ctx 16384
# (record them in NOTES.md, "Memory at 16384"), then a JSON summary: trace_valid,
# verdict, predicates, success, run_end (plus steps, tool calls, timings). Run dir:
# runs/first_run/ops-office-t05-<model>-<time>/.
#SBATCH --job-name=cdb-first-run
#SBATCH --partition=gtx
#SBATCH --gres=gpu:1
#SBATCH --time=00:30:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --output=runs/first_run/logs/%x-%j.out

set -u
cd "${SLURM_SUBMIT_DIR:-.}"
mkdir -p runs/first_run/logs
. bench/harness/slurm/cook_env.sh           # module load per partition; sets PY, LLAMA_SERVER
# Fail before starting the server if the sandbox lacks a skill's or reference's dependency
# (pilot run ops-office-t01 on COOK: the skill script could not run).
"$PY" -m bench.harness.check_env --isolation netns || { echo "environment check failed; see above"; exit 2; }
MODEL="${MODEL:-qwen3-8b-llamacpp}"
TASK="${TASK:-ops-office-t05}"
export CDB_PORT=$(( 20000 + ${SLURM_JOB_ID:-0} % 20000 ))

GGUF=$("$PY" -m bench.backends get "$MODEL" model_file)
[ -f "$GGUF" ] || { echo "model file not found: $GGUF"; exit 2; }
SERVE=$("$PY" -m bench.backends serve-cmd "$MODEL") || exit 2
# Jobs 3249-3251 logged no buffer sizes at the default verbosity; CSCF's examples use
# --verbosity 4 for these lines. First runs only (the pilot keeps the default).
SERVE="$SERVE --verbosity ${CDB_SERVER_VERBOSITY:-4}"
echo "job ${SLURM_JOB_ID:-?} node $(hostname) port $CDB_PORT git $(git rev-parse --short HEAD)"
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null || true
echo "server: $SERVE"
SLOG="runs/first_run/logs/llama-server-${SLURM_JOB_ID:-x}.log"
eval "cdb_start_server \"\$SLOG\" $SERVE"
trap 'kill $SRV 2>/dev/null; wait $SRV 2>/dev/null; cdb_log_buffers "$SLOG" exit' EXIT

"$PY" -m bench.backends wait "$MODEL" --timeout 600 || { echo "server not ready; see $SLOG"; cdb_log_buffers "$SLOG"; tail -n 30 "$SLOG"; exit 3; }
cdb_log_buffers "$SLOG"
echo "server ready after $SECONDS s"

"$PY" -m bench.harness.run_task "$TASK" --model "$MODEL" --isolation netns --observer strace \
    --judge --out runs/first_run
RC=$?
echo "run_task exit $RC"
exit $RC
