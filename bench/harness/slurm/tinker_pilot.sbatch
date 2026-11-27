#!/bin/bash
# Pilot row against Tinker from a CPU-only COOK job. The model runs on Tinker; the node runs
# the sandboxes (netns + strace) and the harness. No GPU is requested.
# HUMANS LAUNCH THIS (Part 0 rule 9); it spends Tinker credit, capped by MAX_COST_USD.
#
#   sh bench/harness/scripts/cook_submit.sh tinker-pilot qwen3.6-35b-a3b-tinker
#   tail -f runs/tinker/logs/cdb-tinker-<jobid>.out
#
# Defaults: explicit-v2 invocation, setup d9, REPEATS=1 (55 runs), WORKERS=4,
# RUN_TIMEOUT=1200, MAX_COST_USD=5 (hard cap for this job: no request is sent that could pass
# it; runs it stops are rerun by the next job). Override in front of the command, e.g.
# MAX_COST_USD=1 TASKS=ops-office-t05 sh ... for a one-task smoke run.
#
# API key: sourced from ~/.tinker_key (a file that does `export TINKER_API_KEY=...`, mode 600;
# CDB_TINKER_KEY_FILE overrides). The key is never echoed, never passed on a command line,
# never given to the sandbox (agent commands get a clean environment), and the job checks at
# the end that no run file or log contains it.
#SBATCH --job-name=cdb-tinker
#SBATCH --partition=gtx
#SBATCH --time=02:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=16G
#SBATCH --output=runs/tinker/logs/%x-%j.out

set -u
set +x                                       # never trace: the key is in the environment
cd "${SLURM_SUBMIT_DIR:-.}"
mkdir -p runs/tinker/logs
export CDB_GPUS=0
. bench/harness/slurm/cook_env.sh            # CPU mode: python module only; sets PY
: "${MODEL:?set MODEL, e.g. via cook_submit.sh tinker-pilot <model>}"
LIMIT_S="${LIMIT_S:-7200}"                   # must match --time
START=$(date +%s)
INVOCATION="${INVOCATION:-explicit}"
SETUP="${SETUP:-d9}"

[ "$("$PY" -m bench.backends get "$MODEL" backend)" = tinker ] || { echo "MODEL must be a tinker model"; exit 2; }
"$PY" -c 'import openai, httpx; print("openai", openai.__version__, "httpx", httpx.__version__)' \
  || { echo "venv lacks openai/httpx: pip install -r bench/harness/requirements.txt"; exit 2; }

KEYF="${CDB_TINKER_KEY_FILE:-$HOME/.tinker_key}"
[ -f "$KEYF" ] || { echo "no key file $KEYF"; exit 2; }
MODE=$(stat -c %a "$KEYF" 2>/dev/null || stat -f %Lp "$KEYF")
[ "$MODE" = 600 ] || [ "$MODE" = 400 ] || { echo "$KEYF has mode $MODE; chmod 600 it"; exit 2; }
. "$KEYF" >/dev/null 2>&1
[ -n "${TINKER_API_KEY:-}" ] || { echo "$KEYF did not set TINKER_API_KEY"; exit 2; }
export TINKER_API_KEY
echo "Tinker key: loaded from $KEYF (not shown)"

# Same sandbox checks as the GPU jobs (venv python, commands, node, the skill scripts).
"$PY" -m bench.harness.check_env --isolation netns || { echo "environment check failed; see above"; exit 2; }

echo "job ${SLURM_JOB_ID:-?} model $MODEL ($("$PY" -m bench.backends get "$MODEL" model)) node $(hostname)"
echo "invocation $INVOCATION setup $SETUP repeats ${REPEATS:-1} workers ${WORKERS:-4} cap USD ${MAX_COST_USD:-5}"
ELAPSED=$(( $(date +%s) - START ))
"$PY" -m bench.harness.pilot run --model "$MODEL" --invocation "$INVOCATION" --setup "$SETUP" \
    --repeats "${REPEATS:-1}" ${TASKS:+--tasks "$TASKS"} --workers "${WORKERS:-4}" \
    --isolation netns --observer strace --run-timeout "${RUN_TIMEOUT:-1200}" \
    --deadline-s $(( LIMIT_S - ELAPSED - 300 )) --max-cost-usd "${MAX_COST_USD:-5}" --no-wait
RC=$?
echo "pilot exit $RC (0 = all done, 2 = runs left; resubmit to resume)"
echo
echo "===== $MODEL ($INVOCATION, $SETUP) ====="
"$PY" -m bench.harness.pilot report --model "$MODEL" ${TASKS:+--tasks "$TASKS"} --timing | tail -n 12

# The key must not be in any run file or log. grep reads it from a pipe, not from argv.
N=$(printf '%s\n' "$TINKER_API_KEY" | grep -rlF -f - runs/pilot/"$MODEL"* runs/tinker/logs 2>/dev/null | wc -l)
echo "key leak check: $N file(s) contain the key"
[ "$N" = 0 ] || { echo "KEY FOUND IN RUN FILES: do not share runs/; tell B"; RC=4; }
unset TINKER_API_KEY
exit $RC
