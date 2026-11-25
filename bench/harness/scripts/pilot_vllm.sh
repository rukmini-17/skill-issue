#!/bin/bash
# B5 utility pilot on the A100 with vLLM: for each model given, start `vllm serve`,
# run all 55 tasks x 3 repeats (v1, policy none), stop the server. HUMANS RUN THIS.
#
#   bash bench/harness/scripts/pilot_vllm.sh qwen3-8b-vllm qwen3-4b-vllm
#   WORKERS=4 bash bench/harness/scripts/pilot_vllm.sh qwen3-8b-vllm    # 4 runs in parallel
#   NO_SERVE=1 bash bench/harness/scripts/pilot_vllm.sh qwen3-8b-vllm   # server already running
#
# Resumable: rerunning skips finished runs. Logs in runs/pilot/logs/.
set -u
cd "$(dirname "$0")/../../.."
PY="${PYTHON:-.venv/bin/python}"
WORKERS="${WORKERS:-4}"
export CDB_PORT="${CDB_PORT:-8000}"
mkdir -p runs/pilot/logs
[ $# -ge 1 ] || { echo "usage: $0 MODEL [MODEL...]"; exit 2; }

rc=0
for MODEL in "$@"; do
  [ "$("$PY" -m bench.backends get "$MODEL" backend)" = vllm ] || { echo "$MODEL is not a vllm model"; rc=2; continue; }
  SRV=""
  if [ -z "${NO_SERVE:-}" ]; then
    SERVE=$("$PY" -m bench.backends serve-cmd "$MODEL") || { rc=2; continue; }
    SLOG="runs/pilot/logs/vllm-$MODEL-$(date +%Y%m%dT%H%M%S).log"
    echo "starting: $SERVE  (log $SLOG)"
    eval "$SERVE" > "$SLOG" 2>&1 &
    SRV=$!
  fi
  if "$PY" -m bench.backends wait "$MODEL" --timeout 1800; then
    "$PY" -m bench.harness.pilot run --model "$MODEL" --workers "$WORKERS" --no-wait \
      2>&1 | tee -a "runs/pilot/logs/pilot-$MODEL.log"
    r=${PIPESTATUS[0]}; [ "$r" = 0 ] || rc=$r
  else
    echo "$MODEL: server not ready"; rc=3
  fi
  if [ -n "$SRV" ]; then kill "$SRV" 2>/dev/null; wait "$SRV" 2>/dev/null; fi
done
"$PY" -m bench.harness.pilot summarize
exit $rc
