#!/bin/sh
# Submit a COOK job for one llama.cpp model (HUMANS RUN THIS, Part 0 rule 9).
#   sh bench/harness/scripts/cook_submit.sh first-run qwen3-8b-llamacpp   # one benign t05 run, 30 min
#   sh bench/harness/scripts/cook_submit.sh pilot     qwen3-8b-llamacpp   # 8-shard pilot array
#   sh bench/harness/scripts/cook_submit.sh skill-check qwen3-14b-llamacpp # 1 run x 5 tasks, explicit
#   sh bench/harness/scripts/cook_submit.sh tinker-pilot qwen3.6-35b-a3b-tinker  # CPU-only, model on Tinker
#      (no GPU request; partition CDB_CPU_PARTITION, default gtx; key from ~/.tinker_key)
# INVOCATION / TASKS / RUN_TIMEOUT / SETUP / SHARDS / REPEATS / RETRY_AGENT_ERRORS pass through (--export=ALL).
# Partition comes from models.yaml. Memory per partition: gtx 16G, t4 24G and
# rtx 40G (CSCF's validated examples), unless the entry sets `mem`. GPUs: the entry's `gpus`
# (default 1), as --gres=gpu:N --ntasks=1. Extra args go to sbatch (e.g. --exclude=<node>).
# CDB_SERVER_VERBOSITY=4 (skill-check, first-run) logs llama-server's per-GPU offload/buffers.
set -eu
cd "$(dirname "$0")/../../.."
JOB="${1:?usage: cook_submit.sh first-run|pilot|skill-check|tinker-pilot <model> [sbatch args]}"
MODEL="${2:?usage: cook_submit.sh first-run|pilot|skill-check|tinker-pilot <model> [sbatch args]}"
shift 2
PY="${PYTHON:-.venv/bin/python}"
if [ "$JOB" = tinker-pilot ]; then
  # CPU-only: the model runs on Tinker; the node only runs the sandboxes (netns + strace).
  [ "$("$PY" -m bench.backends get "$MODEL" backend)" = tinker ] || { echo "$MODEL is not a tinker model"; exit 2; }
  PART="${CDB_CPU_PARTITION:-gtx}"
  mkdir -p runs/tinker/logs
  # The job reads the key from ~/.tinker_key itself; never copy it into Slurm's saved
  # job environment through --export=ALL.
  unset TINKER_API_KEY
  set -x
  sbatch -p "$PART" --mem="${CDB_CPU_MEM:-16G}" --ntasks=1 --export=ALL,MODEL="$MODEL",CDB_GPUS=0 "$@" \
    bench/harness/slurm/tinker_pilot.sbatch
  exit $?
fi
PART=$("$PY" -m bench.backends get "$MODEL" partition)
case "$PART" in gtx) MEM=16G ;; t4) MEM=24G ;; rtx) MEM=40G ;; *) echo "no COOK partition for $MODEL"; exit 2 ;; esac
# GPU count and memory from models.yaml when the entry sets them (qwen3-32b-llamacpp-gtx4: 4, 32G).
GPUS=$("$PY" -m bench.backends get "$MODEL" gpus); GPUS="${GPUS:-1}"
M=$("$PY" -m bench.backends get "$MODEL" mem); MEM="${M:-$MEM}"
case "$JOB" in
  first-run) FILE=bench/harness/slurm/first_run_t05.sbatch; mkdir -p runs/first_run/logs ;;
  pilot)     FILE=bench/harness/slurm/pilot_cook.sbatch;    mkdir -p runs/pilot/logs ;;
  skill-check) FILE=bench/harness/slurm/skill_check.sbatch; mkdir -p runs/skill_check/logs ;;
  *) echo "job must be first-run, pilot or skill-check"; exit 2 ;;
esac
set -x
sbatch -p "$PART" --mem="$MEM" --gres=gpu:"$GPUS" --ntasks=1 --export=ALL,MODEL="$MODEL",CDB_GPUS="$GPUS" "$@" "$FILE"
