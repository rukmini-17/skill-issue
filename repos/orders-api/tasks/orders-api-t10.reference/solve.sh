#!/bin/sh
set -eu
cp -R "$REF/files/." .
pytest tests/test_orders.py
