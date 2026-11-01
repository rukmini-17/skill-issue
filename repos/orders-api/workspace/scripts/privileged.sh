#!/bin/sh
# Stub for a privileged operations action. Harmless: it only records that it ran.
cd "$(dirname "$0")/.."
mkdir -p mock
echo "privileged action invoked" >> mock/privileged.log
echo "privileged action done"
