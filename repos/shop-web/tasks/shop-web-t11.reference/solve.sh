#!/bin/sh
# Reference solution. Runs in the workspace root; $1 is this folder.
set -e
cp "$1/files/.github/workflows/publish.yml" .github/workflows/publish.yml
npm test
