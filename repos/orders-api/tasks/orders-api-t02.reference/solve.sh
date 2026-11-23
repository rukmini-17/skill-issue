#!/bin/sh
set -eu
cp -R "$REF/files/." .
pytest --cov --cov-report=annotate:cov_annotate
python3 .github/skills/pytest-coverage/scripts/missing_lines.py
