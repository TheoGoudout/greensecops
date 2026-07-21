#!/usr/bin/env bash
set -e

SRC_DIR="native/proc-sampler/build"
DEST_DIR="dist/bin"

mkdir -p "$DEST_DIR"

for arch in 386 amd64 arm64; do
  bin="proc-sampler-linux-${arch}"
  if [ -f "${SRC_DIR}/${bin}" ]; then
    cp "${SRC_DIR}/${bin}" "${DEST_DIR}/${bin}"
  else
    echo "warning: ${bin} not found at ${SRC_DIR} — skipping (cross-compile it first: cd native/proc-sampler && CGO_ENABLED=0 GOOS=linux GOARCH=${arch} go build -o build/${bin} .)" >&2
  fi
done
