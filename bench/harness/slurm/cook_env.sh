# Sourced by the COOK sbatch files (not run on its own). Loads the llama.cpp module
# for the job's partition and picks the harness Python. Sets PY and LLAMA_SERVER.
#
#   gtx     llm-r580-llamacpp/2026.10 (pulls in llm-r580/2026.09 with Python 3.13; sm_52/61)
#   t4/rtx  llm-r615-llamacpp/2026.11 (CUDA 12.8; sm_75/sm_120) + python/3.13.15.
#           llm-r615 conflicts with llm-r580 but leaves the Python selection alone,
#           so python/3.13.15 is loaded for the harness.
#
# Venv: .venv (made under llm-r580) on gtx. On t4/rtx, .venv-r615 is used if it
# exists, else .venv; bench/harness/scripts/cook_probe.sh checks whether .venv
# runs under python/3.13.15 (see PILOT.md, "How to run" for making .venv-r615).
# PYTHON=... overrides both.

if ! command -v module >/dev/null 2>&1; then
  for f in /etc/profile.d/lmod.sh /etc/profile.d/modules.sh /usr/share/lmod/lmod/init/bash; do
    [ -f "$f" ] && . "$f" && break
  done
fi
CDB_PART="${CDB_PART:-${SLURM_JOB_PARTITION:-gtx}}"
case "$CDB_PART" in
  gtx)
    module load llm-r580-llamacpp/2026.10 || { echo "module load llm-r580-llamacpp/2026.10 failed"; exit 2; }
    PY="${PYTHON:-.venv/bin/python}"
    ;;
  t4|rtx)
    module unload llm-r580-llamacpp llm-r580 >/dev/null 2>&1 || true
    module load llm-r615-llamacpp/2026.11 python/3.13.15 \
      || { echo "module load llm-r615-llamacpp/2026.11 python/3.13.15 failed"; exit 2; }
    if [ -n "${PYTHON:-}" ]; then PY="$PYTHON"
    elif [ -x .venv-r615/bin/python ]; then PY=.venv-r615/bin/python
    else PY=.venv/bin/python; fi
    ;;
  *) echo "unknown partition $CDB_PART (expected gtx, t4 or rtx)"; exit 2 ;;
esac
export LLAMA_SERVER="${LLAMA_SERVER:-$(command -v llama-server || echo "${LLAMA_CPP_HOME:-}/bin/llama-server")}"
"$PY" -c 'import sys, yaml, jsonschema, openai, httpx' \
  || { echo "harness Python $PY cannot import its dependencies under the $CDB_PART modules"; exit 2; }
echo "partition $CDB_PART; modules: $(module -t list 2>&1 | tr '\n' ' ')"
echo "python $PY ($("$PY" -V 2>&1)); llama-server $LLAMA_SERVER"
