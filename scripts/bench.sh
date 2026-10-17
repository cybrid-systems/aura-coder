#!/usr/bin/env bash
# One command: acceptance checks, closed-loop latency, then static vs restart vs adaptive (+ ablation) table.
#   AURA_BIN=~/aura/build-rel/aura scripts/bench.sh            # native, if the binary runs on this host
#   AURA_BIN=~/aura/build-rel/aura scripts/bench.sh --docker   # inside ghcr.io/cybrid-systems/dev:v1.0.9
# Extra args go to `python3 -m aura_coder bench` (e.g. --seeds 0 1 2 3 4 --n 60 --jobs 3).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
: "${AURA_BIN:?set AURA_BIN to an Aura build-rel/aura}"
run() { if [ "${DOCKER_MODE:-0}" = 1 ]; then scripts/in-docker.sh "$*"; else bash -c "$*"; fi; }
if [ "${1:-}" = "--docker" ]; then DOCKER_MODE=1; shift; fi
export AURA_SANDBOX=off AURA_PIPELINE_STRICT=0   # Soft still needs off: cybrid-systems/aura#4575
echo "== acceptance (rebind correctness) on $AURA_BIN"
run "python3 -m aura_coder acceptance" || true
echo; echo "== closed-loop latency (inside one Aura process)"
run "python3 -m aura_coder latency --n 200"
echo; echo "== stream benchmark"
run "python3 -m aura_coder bench $*"
