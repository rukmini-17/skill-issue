#!/bin/sh
# Submit an experiment against Tinker as a CPU-only Slurm array (HUMANS RUN THIS, Part 0 rule 9).
#   SHARDS=2 MAX_COST_USD=3 sh bench/runner/slurm/submit_tinker.sh bench/configs/experiments/mini_sweep_v1_1.yaml
# Variables (all optional):
#   SHARDS        array size = number of shards (default 1)
#   PARALLEL      array tasks running at once (default 2)
#   MAX_COST_USD  hard cap per array task, USD (default 5); a submission spends at most SHARDS x this
#   WORKERS       runner processes per task (default 4); the task's cap is split evenly between them
#   RUNS_ROOT     output root (default /nfs/cook-home/projects/skill-issue/runs/$USER)
#   ARRAY         explicit --array list, e.g. 1,3 to rerun shards 1 and 3 (default 0-(SHARDS-1))
#   PRINT_ONLY=1  print the sbatch command and exit
# Extra arguments go to sbatch (e.g. --exclude=<node>). Partition: CDB_CPU_PARTITION (default gtx).
# See where things stand with:  python -m bench.runner.shards <experiment.yaml> --shards $SHARDS --runs-dir $RUNS_ROOT
set -eu
cd "$(dirname "$0")/../../.."
EXPERIMENT="${1:?usage: submit_tinker.sh <experiment.yaml> [sbatch args]}"
shift
[ -f "$EXPERIMENT" ] || { echo "no such experiment file: $EXPERIMENT"; exit 2; }
case "$EXPERIMENT" in /*) ;; *) EXPERIMENT="$PWD/$EXPERIMENT" ;; esac
SHARDS="${SHARDS:-1}"
PARALLEL="${PARALLEL:-2}"
ARRAY="${ARRAY:-0-$((SHARDS - 1))}"
RUNS_ROOT="${RUNS_ROOT:-/nfs/cook-home/projects/skill-issue/runs/$USER}"
PART="${CDB_CPU_PARTITION:-gtx}"
SBATCH="${SBATCH:-sbatch}"
# The job reads the key from ~/.tinker_key itself; never copy it into Slurm's saved job
# environment through --export=ALL.
unset TINKER_API_KEY
[ "${PRINT_ONLY:-0}" = 1 ] || mkdir -p "$RUNS_ROOT/logs"
set -- -p "$PART" --mem="${CDB_CPU_MEM:-16G}" --ntasks=1 --array="$ARRAY%$PARALLEL" \
  --output="$RUNS_ROOT/logs/%x-%A_%a.out" \
  --export=ALL,EXPERIMENT="$EXPERIMENT",NSHARDS="$SHARDS",RUNS_ROOT="$RUNS_ROOT",MAX_COST_USD="${MAX_COST_USD:-5}",WORKERS="${WORKERS:-4}",CDB_GPUS=0 \
  "$@" bench/runner/slurm/tinker_sweep.sbatch
echo "$SBATCH $*"
[ "${PRINT_ONLY:-0}" = 1 ] && exit 0
exec "$SBATCH" "$@"
