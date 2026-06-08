#!/usr/bin/env bash
# Stop the pyMotor observability stack.
#
# Usage:
#   ./stop.sh           # stop containers, keep data volumes
#   ./stop.sh --purge   # also remove volumes (Prometheus/Tempo/Loki data)

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
cd "${SCRIPT_DIR}"

PURGE=0
if [[ "${1:-}" == "--purge" ]]; then
  PURGE=1
fi

DOCKER_BIN="${DOCKER_BIN:-docker}"
ARGS=(compose --profile npu-real down)
if [[ "${PURGE}" -eq 1 ]]; then
  ARGS+=(-v)
fi

echo "[stop] ${DOCKER_BIN} ${ARGS[*]}"
"${DOCKER_BIN}" "${ARGS[@]}"
echo "[stop] done."
