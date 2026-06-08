#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
STACK_DIR="$(cd -- "${SCRIPT_DIR}/.." &>/dev/null && pwd)"
PID_FILE="${STACK_DIR}/generated/controller-proxy.pid"

if [[ -f "${PID_FILE}" ]]; then
  pid="$(<"${PID_FILE}")"
  if [[ -n "${pid}" ]] && kill -0 "${pid}" >/dev/null 2>&1; then
    echo "[controller-proxy-stop] stopping pid=${pid}"
    kill "${pid}" || true
  fi
  rm -f "${PID_FILE}"
fi

echo "[controller-proxy-stop] done."
