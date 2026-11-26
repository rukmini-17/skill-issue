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
set -u
: "${CUDA_VISIBLE_DEVICES:?Slurm GPU assignment is missing (submit with --gres=gpu:1)}"
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK:-4}"
PY="${PYTHON:-.venv/bin/python}"
export LLAMA_SERVER="${LLAMA_SERVER:-$(command -v llama-server || echo "${LLAMA_CPP_HOME:-}/bin/llama-server")}"
"$PY" -c 'import sys, yaml, jsonschema, openai, httpx' \
  || { echo "harness Python $PY cannot import its dependencies under the $CDB_PART modules"; exit 2; }
echo "partition $CDB_PART node $(hostname); modules: $(module -t list 2>&1 | tr '\n' ' ')"
echo "python $PY ($("$PY" -V 2>&1)); llama-server $LLAMA_SERVER; CUDA_VISIBLE_DEVICES=$CUDA_VISIBLE_DEVICES"

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

# cdb_log_buffers LOG: print llama-server's GPU offload and memory lines (model, KV
# cache and compute buffers, context). CSCF validated only -c 2048; these lines show
# what 16384 costs. Copy them into NOTES.md ("Memory at 16384") for the first job per
# partition.
cdb_log_buffers() {
  echo "----- llama-server memory ($1) -----"
  grep -E 'offloaded|model buffer size|KV buffer size|compute buffer size|n_ctx|CUDA0.*(total|free)|out of memory' "$1" \
    | sed 's/^[0-9.]* //' | head -n 40
  echo "-----"
}
