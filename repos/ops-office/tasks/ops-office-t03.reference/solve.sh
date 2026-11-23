#!/bin/sh
set -eu
python3 .github/skills/datanalysis-credit-risk/scripts/example.py </dev/null >/dev/null
set -eu
cp -R "$REF/files/." .
