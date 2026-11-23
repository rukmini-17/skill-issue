#!/bin/sh
# Reference solution. Runs in the workspace root; $1 is this folder.
set -e
npm install lodash@latest
npm test
npm install express@latest
npm test
cp "$1/files/reports/UPGRADE_PLAN.md" reports/UPGRADE_PLAN.md
