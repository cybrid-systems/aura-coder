#!/usr/bin/env bash
# Run a command inside the Aura dev image (glibc / libstdc++ match the Aura build-rel binaries).
#   scripts/in-docker.sh 'python3 -m aura_coder bench'
# Mounts this repo at the same path and $AURA_BIN's checkout read-only-by-convention. Needs docker (or sudo docker).
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${AURA_IMAGE:-ghcr.io/cybrid-systems/dev:v1.0.9}"
: "${AURA_BIN:?set AURA_BIN to an Aura build-rel/aura}"
AURA_LIB="${AURA_LIB:-$(cd "$(dirname "$AURA_BIN")/../lib" && pwd)}"
DOCKER="docker"; docker info >/dev/null 2>&1 || DOCKER="sudo docker"
mounts=(-v "$REPO:$REPO")
for p in "$(dirname "$AURA_BIN")" "$AURA_LIB"; do mounts+=(-v "$p:$p"); done
# --memory: a runaway rebind (cybrid-systems/aura#4583) must not take the host down
exec $DOCKER run --rm -i --memory="${AURA_CODER_MEM:-4g}" --memory-swap="${AURA_CODER_MEM:-4g}" \
  --entrypoint bash --user "$(id -u):$(id -g)" -e HOME=/tmp "${mounts[@]}" -w "$REPO" \
  -e AURA_BIN="$AURA_BIN" -e AURA_LIB="$AURA_LIB" -e AURA_SANDBOX=off -e AURA_PIPELINE_STRICT=0 \
  "$IMAGE" -c "$*"
