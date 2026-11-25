#!/bin/sh
# B2 monitoring check on a COOK gtx node. Submit from the repo root, after
# creating the venv on the login node (no installs on the compute node):
#
#   python3 -m venv .venv && .venv/bin/pip install pyyaml jsonschema pytest openpyxl
#   sbatch bench/harness/slurm/check_monitoring_gtx.sbatch
#   squeue -u $USER                      # job state
#   cat runs/checks/cdb-moncheck-<jobid>.out
#
# CPU only, a few minutes; far below the 2-hour limit.
#SBATCH --job-name=cdb-moncheck
#SBATCH --partition=gtx
#SBATCH --time=00:20:00
#SBATCH --cpus-per-task=2
#SBATCH --mem=4G
#SBATCH --output=runs/checks/%x-%j.out

set -u
cd "${SLURM_SUBMIT_DIR:-.}"
mkdir -p runs/checks
PYTHON="${PYTHON:-.venv/bin/python}" sh bench/harness/scripts/check_monitoring.sh
