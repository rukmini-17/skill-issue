#!/bin/bash
# First real run (acceptance item): Qwen3-8B (llama.cpp, Q4_K_M) on one gtx GPU,
# ONE benign run of ops-office-t05, v1 skills, policy none, through the real
# harness (netns isolation, strace), judged by A's oracle. HUMANS SUBMIT THIS.
# On COOK (ssh -l 'rnazre@umass.edu' cook.cs.umass.edu), from the repo root:
#
#   mkdir -p runs/first_run/logs        # Slurm does not create the --output dir
#   sbatch bench/harness/slurm/first_run_t05.sbatch
#   squeue -u $USER
#   cat runs/first_run/logs/cdb-first-run-<jobid>.out
#
# The last block of the log is a JSON summary: trace_valid, verdict, predicates,
# success, run_end (plus steps, tool calls, timings). The run directory is
# runs/first_run/ops-office-t05-qwen3-8b-llamacpp-<time>/.
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
MODEL="${MODEL:-qwen3-8b-llamacpp}"
TASK="${TASK:-ops-office-t05}"
export CDB_PORT=$(( 20000 + ${SLURM_JOB_ID:-0} % 20000 ))

GGUF=$("$PY" -m bench.backends get "$MODEL" model_file)
[ -f "$GGUF" ] || { echo "model file not found: $GGUF"; exit 2; }
SERVE=$("$PY" -m bench.backends serve-cmd "$MODEL") || exit 2
echo "job ${SLURM_JOB_ID:-?} node $(hostname) port $CDB_PORT git $(git rev-parse --short HEAD)"
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null || true
echo "server: $SERVE"
SLOG="runs/first_run/logs/llama-server-${SLURM_JOB_ID:-x}.log"
eval "$SERVE" > "$SLOG" 2>&1 &
SRV=$!
trap 'kill $SRV 2>/dev/null; wait $SRV 2>/dev/null' EXIT

"$PY" -m bench.backends wait "$MODEL" --timeout 600 || { echo "server not ready; see $SLOG"; tail -n 30 "$SLOG"; exit 3; }
echo "server ready after $SECONDS s"

"$PY" -m bench.harness.run_task "$TASK" --model "$MODEL" --isolation netns --observer strace \
    --judge --out runs/first_run
RC=$?
echo "run_task exit $RC"
exit $RC
