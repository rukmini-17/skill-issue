# Sourced by the COOK sbatch files (not run on its own). Mirrors the setup of CSCF's
# validated llama.cpp example jobs: `. /etc/profile`, `module purge`, the partition's
# llama.cpp module, a check that Slurm assigned a GPU. Sets PY, LLAMA_SERVER,
# OMP_NUM_THREADS, and defines cdb_start_server and cdb_log_buffers.
#
#   gtx     llm-r580-llamacpp/2026.10 (pulls in llm-r580/2026.09 with Python 3.13.15; sm_52/61)
#   t4/rtx  llm-r615-llamacpp/2026.11 (CUDA 12.8; sm_75/sm_120) + python/3.13.15
#           (llm-r615 leaves the Python selection alone).
#
# One venv for all partitions: .venv's python links to python/3.13.15, and the probe
# (scripts/cook_probe.sh, 2026-11-25) imported the harness dependencies under both
# module sets. PYTHON=... overrides.

: "${SLURM_JOB_ID:?submit with sbatch}"
set +u                                      # /etc/profile and module scripts use unset variables
. /etc/profile
module purge
CDB_PART="${CDB_PART:-${SLURM_JOB_PARTITION:-gtx}}"
case "$CDB_PART" in
  gtx)    module load llm-r580-llamacpp/2026.10 || { echo "module load llm-r580-llamacpp/2026.10 failed"; exit 2; } ;;
  t4|rtx) module load llm-r615-llamacpp/2026.11 python/3.13.15 \
            || { echo "module load llm-r615-llamacpp/2026.11 python/3.13.15 failed"; exit 2; } ;;
  *)      echo "unknown partition $CDB_PART (expected gtx, t4 or rtx)"; exit 2 ;;
esac
# Node.js: COOK has no node module. A user install (Node v22.23.5 at ~/opt/node, see
# PILOT.md) goes on PATH for every partition; npm needs it there (`#!/usr/bin/env node`).
# The harness passes its PATH on to the sandbox, so agent commands see it too.
CDB_NODE_DIR="${CDB_NODE_DIR:-$HOME/opt/node/bin}"
if [ -x "$CDB_NODE_DIR/node" ] && [ -x "$CDB_NODE_DIR/npm" ]; then
  export PATH="$CDB_NODE_DIR:$PATH"
  export CDB_NODE_DIR
else
  echo "node/npm not found in CDB_NODE_DIR=$CDB_NODE_DIR (install Node at ~/opt/node, see PILOT.md)"; exit 2
fi
set -u
: "${CUDA_VISIBLE_DEVICES:?Slurm GPU assignment is missing (submit with --gres=gpu:1)}"
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK:-4}"
PY="${PYTHON:-.venv/bin/python}"
export LLAMA_SERVER="${LLAMA_SERVER:-$(command -v llama-server || echo "${LLAMA_CPP_HOME:-}/bin/llama-server")}"
"$PY" -c 'import sys, yaml, jsonschema, openai, httpx' \
  || { echo "harness Python $PY cannot import its dependencies under the $CDB_PART modules"; exit 2; }
echo "partition $CDB_PART node $(hostname); modules: $(module -t list 2>&1 | tr '\n' ' ')"
echo "python $PY ($("$PY" -V 2>&1)); llama-server $LLAMA_SERVER; CUDA_VISIBLE_DEVICES=$CUDA_VISIBLE_DEVICES"
echo "node $(command -v node) ($(node --version 2>&1)); npm $(npm --version 2>&1)"

# cdb_start_server LOG CMD...: start llama-server in the background, SRV=<pid>.
# Launched directly when the batch step sees the GPU (nvidia-smi lists it); otherwise
# through `srun --ntasks=1 --gres=gpu:1`, as CSCF's examples do.
cdb_start_server() {
  local log="$1"; shift
  if nvidia-smi -L >/dev/null 2>&1 && [ -n "$(nvidia-smi -L 2>/dev/null)" ]; then
    echo "server launch: direct (GPU visible in the batch step)"
    "$@" >"$log" 2>&1 &
  else
    echo "server launch: srun --ntasks=1 --gres=gpu:1 (GPU not visible in the batch step)"
    srun --ntasks=1 --gres=gpu:1 --cpus-per-task="${SLURM_CPUS_PER_TASK:-4}" "$@" >"$log" 2>&1 &
  fi
  SRV=$!
}

# cdb_log_buffers LOG [WHEN]: print llama-server's GPU offload and memory lines (model,
# KV cache and compute buffers, context, the memory breakdown llama.cpp prints at exit).
# CSCF validated only -c 2048; these lines show what 16384 costs. Copy them into NOTES.md
# ("Memory at 16384").
cdb_log_buffers() {
  local pat='buffer size|offload|kv_cache|kv self|KV self|n_ctx|memory breakdown|memory_breakdown|CUDA0 \(|MiB|out of memory|failed to allocate'
  echo "----- llama-server memory (${2:-after start}: $1) -----"
  grep -Ei "$pat" "$1" | sed 's/^[0-9.]* //' | head -n 60
  grep -Eqi 'buffer size' "$1" || echo "(no buffer-size lines in the log; run with --verbosity 4, as first_run_t05.sbatch does)"
  echo "-----"
}
