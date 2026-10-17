#!/usr/bin/env bash
# Unit tests. Control-plane tests need AURA_BIN (skipped otherwise). Use --docker to run in the dev image.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
if [ "${1:-}" = "--docker" ]; then exec scripts/in-docker.sh "python3 -m unittest discover -s tests -v"; fi
exec python3 -m unittest discover -s tests -v
