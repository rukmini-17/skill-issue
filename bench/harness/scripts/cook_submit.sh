#!/bin/sh
# Submit a COOK job for one llama.cpp model (HUMANS RUN THIS, Part 0 rule 9).
#   sh bench/harness/scripts/cook_submit.sh first-run qwen3-8b-llamacpp   # one benign t05 run, 30 min
#   sh bench/harness/scripts/cook_submit.sh pilot     qwen3-8b-llamacpp   # 8-shard pilot array
#   sh bench/harness/scripts/cook_submit.sh skill-check qwen3-14b-llamacpp # 1 run x 5 tasks, explicit
# INVOCATION / TASKS / RUN_TIMEOUT / RETRY_AGENT_ERRORS pass through (--export=ALL).
# Partition comes from models.yaml. Memory per partition: gtx 16G, t4 24G and
# rtx 40G (CSCF's validated examples). Extra args go to sbatch (e.g. --exclude=<node>).
set -eu
cd "$(dirname "$0")/../../.."
JOB="${1:?usage: cook_submit.sh first-run|pilot|skill-check <model> [sbatch args]}"
MODEL="${2:?usage: cook_submit.sh first-run|pilot|skill-check <model> [sbatch args]}"
shift 2
PY="${PYTHON:-.venv/bin/python}"
PART=$("$PY" -m bench.backends get "$MODEL" partition)
case "$PART" in gtx) MEM=16G ;; t4) MEM=24G ;; rtx) MEM=40G ;; *) echo "no COOK partition for $MODEL"; exit 2 ;; esac
case "$JOB" in
  first-run) FILE=bench/harness/slurm/first_run_t05.sbatch; mkdir -p runs/first_run/logs ;;
  pilot)     FILE=bench/harness/slurm/pilot_cook.sbatch;    mkdir -p runs/pilot/logs ;;
  skill-check) FILE=bench/harness/slurm/skill_check.sbatch; mkdir -p runs/skill_check/logs ;;
  *) echo "job must be first-run, pilot or skill-check"; exit 2 ;;
esac
set -x
sbatch -p "$PART" --mem="$MEM" --export=ALL,MODEL="$MODEL" "$@" "$FILE"
