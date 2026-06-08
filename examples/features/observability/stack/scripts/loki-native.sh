#!/usr/bin/env bash
# Manage a host-native Loki instance when the Docker Loki image is unavailable.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
STACK_DIR="$(cd -- "${SCRIPT_DIR}/.." &>/dev/null && pwd)"
cd "${STACK_DIR}"
. "${SCRIPT_DIR}/load-dotenv.sh"

if [[ -f "${STACK_DIR}/.env" ]]; then
  load_dotenv "${STACK_DIR}/.env"
elif [[ -f "${STACK_DIR}/.env.example" ]]; then
  load_dotenv "${STACK_DIR}/.env.example"
fi

LOKI_PORT="${LOKI_PORT:-3100}"
LOKI_VERSION="${LOKI_VERSION:-3.3.0}"
RUNTIME_DIR="${STACK_DIR}/generated/loki-native"
BIN_DIR="${RUNTIME_DIR}/bin"
LOG_DIR="${RUNTIME_DIR}/logs"
RUN_DIR="${RUNTIME_DIR}/run"
DATA_DIR="${STACK_DIR}/generated/loki-data"
PID_FILE="${RUN_DIR}/loki.pid"
LOKI_BIN="${BIN_DIR}/loki"
CONFIG_FILE="${STACK_DIR}/loki/loki-native.yaml"

usage() {
  cat <<EOF
Usage: $0 {start|stop|status}

Manage native Loki on localhost:${LOKI_PORT} (fallback when Docker image pull fails).
Data: ${DATA_DIR}
EOF
}

download_file() {
  local url="$1"
  local out_file="$2"
  if command -v curl >/dev/null 2>&1; then
    curl -fL --retry 3 --retry-delay 2 -o "${out_file}" "${url}"
    return
  fi
  if command -v wget >/dev/null 2>&1; then
    wget -O "${out_file}" "${url}"
    return
  fi
  echo "[loki-native] neither curl nor wget is available" >&2
  exit 1
}

install_loki() {
  [[ -x "${LOKI_BIN}" ]] && return
  mkdir -p "${BIN_DIR}"
  local ver="${LOKI_VERSION#v}"
  local archive="${RUNTIME_DIR}/loki-${ver}.zip"
  local url="https://github.com/grafana/loki/releases/download/v${ver}/loki-linux-amd64.zip"
  echo "[loki-native] downloading Loki ${LOKI_VERSION}..."
  download_file "${url}" "${archive}"
  unzip -o -q "${archive}" -d "${RUNTIME_DIR}"
  if [[ -f "${RUNTIME_DIR}/loki-linux-amd64" ]]; then
    mv "${RUNTIME_DIR}/loki-linux-amd64" "${LOKI_BIN}"
  elif [[ -f "${RUNTIME_DIR}/loki" ]]; then
    mv "${RUNTIME_DIR}/loki" "${LOKI_BIN}"
  else
    echo "[loki-native] unexpected archive layout in ${archive}" >&2
    exit 1
  fi
  chmod +x "${LOKI_BIN}"
}

is_running() {
  [[ -f "${PID_FILE}" ]] || return 1
  local pid
  pid="$(<"${PID_FILE}")"
  [[ -n "${pid}" ]] && kill -0 "${pid}" >/dev/null 2>&1
}

wait_ready() {
  local attempts=30
  while (( attempts > 0 )); do
    if curl -fsS "http://127.0.0.1:${LOKI_PORT}/ready" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
    attempts=$((attempts - 1))
  done
  echo "[loki-native] Loki did not become ready on port ${LOKI_PORT}" >&2
  return 1
}

start_loki() {
  if is_running; then
    echo "[loki-native] already running (pid $(<"${PID_FILE}"))"
    return 0
  fi

  if command -v lsof >/dev/null 2>&1 && lsof -i ":${LOKI_PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "[loki-native] port ${LOKI_PORT} already in use (Docker Loki or another process)"
    return 0
  fi

  install_loki
  mkdir -p "${LOG_DIR}" "${RUN_DIR}" "${DATA_DIR}/chunks" "${DATA_DIR}/index" \
    "${DATA_DIR}/index_cache" "${DATA_DIR}/compactor" "${DATA_DIR}/rules"

  echo "[loki-native] starting on :${LOKI_PORT}..."
  nohup "${LOKI_BIN}" -config.file="${CONFIG_FILE}" \
    >"${LOG_DIR}/loki.log" 2>&1 &
  echo $! > "${PID_FILE}"
  wait_ready
  echo "[loki-native] ready at http://127.0.0.1:${LOKI_PORT}"
}

stop_loki() {
  if ! is_running; then
    rm -f "${PID_FILE}"
    return 0
  fi
  local pid
  pid="$(<"${PID_FILE}")"
  echo "[loki-native] stopping pid=${pid}"
  kill "${pid}" || true
  rm -f "${PID_FILE}"
}

status_loki() {
  if is_running; then
    echo "[loki-native] running pid=$(<"${PID_FILE}") port=${LOKI_PORT}"
    curl -fsS "http://127.0.0.1:${LOKI_PORT}/ready" && echo
  else
    echo "[loki-native] not running"
    return 1
  fi
}

CMD="${1:-status}"
case "${CMD}" in
  start) start_loki ;;
  stop) stop_loki ;;
  status) status_loki ;;
  -h|--help) usage ;;
  *)
    echo "[loki-native] unknown command: ${CMD}" >&2
    usage
    exit 1
    ;;
esac
