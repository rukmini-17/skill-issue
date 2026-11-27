#!/bin/bash
# Run on the COOK login node from the repo root (read-only; no GPU, no jobs):
#   bash bench/harness/scripts/cook_probe.sh 2>&1 | tee runs/cook_probe.txt
# Prints CSCF's two example llama.cpp jobs (to align the t4/rtx server flags), the
# llama-server flags we depend on, and whether .venv runs under the t4/rtx modules.
set -u
for f in /etc/profile.d/lmod.sh /etc/profile.d/modules.sh; do
  command -v module >/dev/null 2>&1 || { [ -f "$f" ] && . "$f"; }
done
cd "$(dirname "$0")/../../.."

flags() {
  echo "-- llama-server: $(command -v llama-server)"
  llama-server --version 2>&1 | head -3
  llama-server --help 2>&1 | grep -E -- '--(jinja|reasoning-format|alias|flash-attn|cache-type-k|cache-type-v|ctx-size|n-gpu-layers|split-mode|tensor-split|parallel)\b' | cut -c1-150
}

echo "===== llm-r615-llamacpp/2026.11 (t4/rtx) ====="
module purge >/dev/null 2>&1
module load llm-r615-llamacpp/2026.11 python/3.13.15
module -t list 2>&1
echo "LLAMA_CPP_HOME=${LLAMA_CPP_HOME:-unset}"
for ex in llama-14b-t4.sbatch llama-32b-rtx.sbatch; do
  echo "----- \$LLAMA_CPP_HOME/share/examples/$ex -----"
  cat "${LLAMA_CPP_HOME:-/nonexistent}/share/examples/$ex" 2>&1
done
echo "----- other examples -----"; ls "${LLAMA_CPP_HOME:-/nonexistent}/share/examples" 2>&1
flags
echo "-- python: $(command -v python3) $(python3 -V 2>&1)"
echo "-- .venv under python/3.13.15:"
.venv/bin/python -c 'import sys, yaml, jsonschema, openai, httpx; print("OK", sys.version.split()[0], sys.executable)' 2>&1
ls -l .venv/bin/python 2>&1; grep -E '^(home|version)' .venv/pyvenv.cfg 2>&1

echo; echo "===== llm-r580-llamacpp/2026.10 (gtx) ====="
module purge >/dev/null 2>&1
module load llm-r580-llamacpp/2026.10
module -t list 2>&1
flags
echo "-- .venv under llm-r580:"
.venv/bin/python -c 'import sys, yaml, jsonschema, openai, httpx; print("OK", sys.version.split()[0])' 2>&1
echo; echo "-- GGUF files:"
ls -l /nfs/opt/models/Qwen3-*-GGUF/*/Qwen3-*-Q4_K_M.gguf 2>&1
