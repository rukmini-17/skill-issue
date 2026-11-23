#!/bin/bash
# B5 pilot through Tinker. HUMANS RUN THIS; it spends Tinker credit.
# Stops starting new runs once the model's runs have used MAX_TOKENS tokens
# (prompt + completion, summed over runs/pilot/<model>/). Set MAX_TOKENS from
# Tinker's current price so the total stays inside the agreed budget.
#
#   export TINKER_API_KEY=...            # never in the repo
#   export CDB_TINKER_QWEN3_8B=tinker://...   # sampler path for Qwen3-8B
#   MAX_TOKENS=2000000 bash bench/harness/scripts/pilot_tinker.sh qwen3-8b-tinker
#   TASKS=ops-office-t05 REPEATS=1 MAX_TOKENS=100000 bash ...    # smoke test first
set -u
cd "$(dirname "$0")/../../.."
PY="${PYTHON:-.venv/bin/python}"
MODEL="${1:?usage: $0 MODEL}"
: "${MAX_TOKENS:?set MAX_TOKENS (token cap for this model; protects the credit budget)}"
: "${TINKER_API_KEY:?set TINKER_API_KEY}"
[ "$("$PY" -m bench.backends get "$MODEL" backend)" = tinker ] || { echo "$MODEL is not a tinker model"; exit 2; }
mkdir -p runs/pilot/logs
"$PY" -m bench.harness.pilot run --model "$MODEL" --workers "${WORKERS:-2}" \
  --repeats "${REPEATS:-3}" ${TASKS:+--tasks "$TASKS"} --max-total-tokens "$MAX_TOKENS" --no-wait \
  2>&1 | tee -a "runs/pilot/logs/pilot-$MODEL.log"
exit "${PIPESTATUS[0]}"
