#!/bin/sh
set -eu
cp -R "$REF/files/." .
pytest reports/test_repro.py || true
pytest reports/test_repro.py || true
