#!/bin/sh
# Reference solution. Runs in the workspace root; $1 is this folder.
set -e
npm install express@latest
npm test
