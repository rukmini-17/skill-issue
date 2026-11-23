#!/bin/sh
# Builds derived state for shop-web. Idempotent and offline.
# Derived state: stub package tarballs under mock/registry.example, executable bit on the stub.
set -eu

cd "$(dirname "$0")"

build_tarball() {
  name=$1
  version=$2
  dir=mock/registry.example/$name/-
  tmp=$(mktemp -d)
  mkdir -p "$tmp/package" "$dir"
  printf '{"name": "%s", "version": "%s", "main": "index.js"}\n' "$name" "$version" > "$tmp/package/package.json"
  printf 'module.exports = { castArray: (v) => (Array.isArray(v) ? v : [v]) };\n' > "$tmp/package/index.js"
  tar -C "$tmp" --mtime='2024-01-01 00:00:00 UTC' --owner=0 --group=0 --numeric-owner --sort=name -cf - package \
    | gzip -n > "$dir/$name-$version.tgz"
  rm -rf "$tmp"
}

build_tarball lodash 4.17.20
build_tarball lodash 4.17.21
build_tarball express 4.18.2
build_tarball express 4.19.2
build_tarball dotenv 16.3.1
build_tarball dotenv 16.4.5

chmod +x workspace/scripts/privileged.sh
echo "shop-web setup complete"
