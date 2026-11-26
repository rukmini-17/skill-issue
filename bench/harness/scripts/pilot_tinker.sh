#!/bin/bash
# B5 pilot through Tinker. HUMANS RUN THIS; it spends Tinker credit.
# On COOK use the CPU-only job instead: cook_submit.sh tinker-pilot <model> (slurm/tinker_pilot.sbatch).
# MAX_COST_USD (default 5) is a hard USD cap for this invocation (models.yaml `price`).
# Stops starting new runs once the model's runs have used MAX_TOKENS tokens
# (prompt + completion, summed over runs/pilot/<model>/). Set MAX_TOKENS from
# Tinker's current price so the total stays inside the agreed budget.
#
#   export TINKER_API_KEY=...            # never in the repo
#   (qwen3-8b-tinker samples the base model Qwen/Qwen3-8B; $0.60 per million sampled tokens)
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
"$PY" -m bench.harness.pilot run --model "$MODEL" --invocation "${INVOCATION:-natural}" --workers "${WORKERS:-2}" \
  --repeats "${REPEATS:-3}" ${TASKS:+--tasks "$TASKS"} --max-total-tokens "$MAX_TOKENS" \
  --max-cost-usd "${MAX_COST_USD:-5}" --no-wait \
  2>&1 | tee -a "runs/pilot/logs/pilot-$MODEL.log"
exit "${PIPESTATUS[0]}"
