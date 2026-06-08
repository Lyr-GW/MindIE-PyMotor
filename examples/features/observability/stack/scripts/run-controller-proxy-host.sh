#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
STACK_DIR="$(cd -- "${SCRIPT_DIR}/.." &>/dev/null && pwd)"
ENV_FILE="${STACK_DIR}/generated/discovered.env"
RUN_DIR="${STACK_DIR}/generated"
LOG_DIR="${RUN_DIR}/logs"
PID_FILE="${RUN_DIR}/controller-proxy.pid"

usage() {
  echo "Usage: $0 [--env-file <generated/discovered.env>]"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env-file)
      [[ $# -lt 2 ]] && { echo "[controller-proxy] missing value for --env-file" >&2; exit 1; }
      ENV_FILE="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[controller-proxy] unknown option: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ -f "${ENV_FILE}" ]]; then
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
fi

mkdir -p "${RUN_DIR}" "${LOG_DIR}"
PROXY_PORT="${CONTROLLER_PROXY_PORT:-9106}"
CONTROLLER_METRICS_URL="${CONTROLLER_METRICS_URL:-http://host.docker.internal:1027/observability/metrics}"

is_pid_running() {
  local pid="$1"
  [[ -n "${pid}" ]] && kill -0 "${pid}" >/dev/null 2>&1
}

if [[ -f "${PID_FILE}" ]]; then
  old_pid="$(<"${PID_FILE}")"
  if is_pid_running "${old_pid}"; then
    echo "[controller-proxy] already running pid=${old_pid}"
    exit 0
  fi
fi

CONTROLLER_METRICS_URL="${CONTROLLER_METRICS_URL}" \
PROXY_PORT="${PROXY_PORT}" \
python3 "${STACK_DIR}/controller-proxy/main.py" >"${LOG_DIR}/controller-proxy.log" 2>&1 &
pid=$!
echo "${pid}" >"${PID_FILE}"
sleep 0.5
if ! is_pid_running "${pid}"; then
  echo "[controller-proxy] failed to start, see ${LOG_DIR}/controller-proxy.log" >&2
  exit 1
fi
echo "[controller-proxy] started pid=${pid} port=${PROXY_PORT} upstream=${CONTROLLER_METRICS_URL}"
