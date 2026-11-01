#!/bin/sh
# Reference solution. Runs in the workspace root; $1 is this folder.
set -e
mkdir -p __tests__
cp "$1/files/__tests__/payment-client.test.js" __tests__/payment-client.test.js
