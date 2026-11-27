#!/bin/bash
# One shard of an attack/benign experiment against a Tinker model, from a CPU-only COOK job.
# Same job shape as B's bench/harness/slurm/tinker_pilot.sbatch: the model runs on Tinker; this
# node runs the sandboxes (netns + strace) and the runner. No GPU is requested.
# HUMANS LAUNCH THIS (Part 0 rule 9). It spends Tinker credit, capped per array task by
# MAX_COST_USD (B's Budget: no request is sent that could pass it; the runner splits the cap evenly
# over its WORKERS processes). Total spend of a submission <= number of array tasks x MAX_COST_USD.
#
# Submit with bench/runner/slurm/submit_tinker.sh (it sets the variables below), e.g.
#   SHARDS=2 MAX_COST_USD=3 sh bench/runner/slurm/submit_tinker.sh bench/configs/experiments/mini_sweep_v1_1.yaml
#
# Outputs: $RUNS_ROOT/<experiment name>/<run_id>/ (default RUNS_ROOT=/nfs/cook-home/projects/skill-issue/runs/$USER),
# logs in $RUNS_ROOT/logs/. Other COOK users can read that folder: no keys, nothing private.
# Exit codes: 0 = shard done, 2 = runs left (deadline or cost cap; resubmit to resume), 1 = errors, 4 = key leak.
#
# API key: sourced from ~/.tinker_key (a file that does `export TINKER_API_KEY=...`, mode 600;
# CDB_TINKER_KEY_FILE overrides). Never echoed, never on a command line, never in the sandbox.
#SBATCH --job-name=cdb-sweep
#SBATCH --partition=gtx
#SBATCH --time=02:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=16G

set -u
set +x                                       # never trace: the key is in the environment
cd "${SLURM_SUBMIT_DIR:-.}"
export CDB_GPUS=0
. bench/harness/slurm/cook_env.sh            # CPU mode: python module only; sets PY
: "${EXPERIMENT:?set EXPERIMENT to the experiment yaml (submit_tinker.sh does)}"
: "${NSHARDS:?set NSHARDS}"
SHARD="${SLURM_ARRAY_TASK_ID:-0}"
RUNS_ROOT="${RUNS_ROOT:-/nfs/cook-home/projects/skill-issue/runs/$USER}"
LIMIT_S="${LIMIT_S:-7200}"                   # must match --time
START=$(date +%s)

"$PY" -c 'import openai, httpx' || { echo "venv lacks openai/httpx: pip install -r bench/harness/requirements.txt"; exit 2; }
for M in $("$PY" -c 'import sys,yaml; print(" ".join(yaml.safe_load(open(sys.argv[1]))["models"]))' "$EXPERIMENT"); do
  [ "$("$PY" -m bench.backends get "$M" backend)" = tinker ] || { echo "model $M is not a tinker model"; exit 2; }
done

KEYF="${CDB_TINKER_KEY_FILE:-$HOME/.tinker_key}"
[ -f "$KEYF" ] || { echo "no key file $KEYF"; exit 2; }
MODE=$(stat -c %a "$KEYF" 2>/dev/null || stat -f %Lp "$KEYF")
[ "$MODE" = 600 ] || [ "$MODE" = 400 ] || { echo "$KEYF has mode $MODE; chmod 600 it"; exit 2; }
. "$KEYF" >/dev/null 2>&1
[ -n "${TINKER_API_KEY:-}" ] || { echo "$KEYF did not set TINKER_API_KEY"; exit 2; }
export TINKER_API_KEY
echo "Tinker key: loaded from $KEYF (not shown)"

# Same sandbox checks as the pilot jobs (venv python, commands, node, the skills' scripts).
"$PY" -m bench.harness.check_env --isolation netns || { echo "environment check failed; see above"; exit 2; }

mkdir -p "$RUNS_ROOT"
echo "job ${SLURM_JOB_ID:-?} shard $SHARD/$NSHARDS node $(hostname) experiment $EXPERIMENT"
echo "runs $RUNS_ROOT workers ${WORKERS:-4} cap USD ${MAX_COST_USD:-5} data $(git describe --tags --match 'data-v*' --abbrev=0 2>/dev/null) code $(git rev-parse --short HEAD)"
ELAPSED=$(( $(date +%s) - START ))
# Stop starting new groups with time to spare for the slowest group to finish.
MAX_SECONDS="${MAX_SECONDS:-$(( LIMIT_S - ELAPSED - ${RUN_TIMEOUT:-1200} - 300 ))}"
"$PY" -m bench.runner "$EXPERIMENT" --shard "$SHARD/$NSHARDS" --workers "${WORKERS:-4}" \
    --max-seconds "$MAX_SECONDS" --max-cost-usd "${MAX_COST_USD:-5}" --runs-dir "$RUNS_ROOT"
RC=$?
echo "runner exit $RC (0 = shard done, 2 = runs left; resubmit to resume)"

# The key must not be in any run file or log. grep reads it from a pipe, not from argv.
NAME=$("$PY" -c 'import sys,yaml; print(yaml.safe_load(open(sys.argv[1]))["name"])' "$EXPERIMENT")
N=$(printf '%s\n' "$TINKER_API_KEY" | grep -rlF -f - "$RUNS_ROOT/$NAME" "$RUNS_ROOT/logs" 2>/dev/null | wc -l)
echo "key leak check: $N file(s) contain the key"
[ "$N" = 0 ] || { echo "KEY FOUND IN RUN FILES: delete them from the shared folder now and tell the team"; RC=4; }
unset TINKER_API_KEY
exit $RC
