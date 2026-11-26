#!/bin/sh
# Submit the COOK utility pilot for one llama.cpp model (HUMANS RUN THIS, Part 0 rule 9).
#   sh bench/harness/scripts/pilot_cook_submit.sh qwen3-8b-llamacpp [extra sbatch args]
# Partition comes from models.yaml; rtx (Qwen3-32B) gets --mem=40G (CSCF's 32B
# example used 40 GiB of system RAM).
set -eu
cd "$(dirname "$0")/../../.."
MODEL="${1:?usage: pilot_cook_submit.sh <model> [sbatch args]}"; shift
PY="${PYTHON:-.venv/bin/python}"
PART=$("$PY" -m bench.backends get "$MODEL" partition)
MEM=16G
[ "$PART" = rtx ] && MEM=40G
mkdir -p runs/pilot/logs
set -x
sbatch -p "$PART" --mem="$MEM" --export=ALL,MODEL="$MODEL" "$@" bench/harness/slurm/pilot_cook.sbatch
