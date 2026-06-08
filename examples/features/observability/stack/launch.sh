#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
cd "${SCRIPT_DIR}"

NAMESPACE="${MOTOR_NAMESPACE:-}"
NODE_IP="${MOTOR_NODE_IP:-}"
USER_CONFIG="${MOTOR_USER_CONFIG:-}"
ENGINE_MGMT_PORT="${MOTOR_ENGINE_MGMT_PORT:-10001}"
OBS_HOST_INPUT="${OBS_HOST:-}"

FORCE_NATIVE=0
DISCOVER_ONLY=0
DRY_RUN=0

usage() {
  cat <<'EOF'
Usage: ./launch.sh [options]

Options:
  --namespace <namespace>     Kubernetes namespace / job_id
  --node-ip <node-ip>         Node IP used for NodePort access
  --user-config <path>        pyMotor user_config.json path
  --discover-only             Only run discovery, do not start stack
  --dry-run                   Run discovery and print generated Prometheus config
  --native                    Skip Docker Compose and run native runtime
  -h, --help                  Show this help

Environment:
  MOTOR_NAMESPACE
  MOTOR_NODE_IP
  MOTOR_USER_CONFIG
  MOTOR_ENGINE_MGMT_PORT
  OBS_HOST
  PROXY_SH
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --namespace)
      [[ $# -lt 2 ]] && { echo "[launch] missing value for --namespace" >&2; exit 1; }
      NAMESPACE="$2"
      shift 2
      ;;
    --node-ip)
      [[ $# -lt 2 ]] && { echo "[launch] missing value for --node-ip" >&2; exit 1; }
      NODE_IP="$2"
      shift 2
      ;;
    --user-config)
      [[ $# -lt 2 ]] && { echo "[launch] missing value for --user-config" >&2; exit 1; }
      USER_CONFIG="$2"
      shift 2
      ;;
    --discover-only)
      DISCOVER_ONLY=1
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --native)
      FORCE_NATIVE=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[launch] unknown option: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ ! -f .env && -f .env.example ]]; then
  cp .env.example .env
  echo "[launch] created .env from .env.example"
fi

DISCOVERY_CMD=(python3 "./scripts/discover-targets.py" "--output-dir" "./generated" "--engine-mgmt-port" "${ENGINE_MGMT_PORT}")
[[ -n "${NAMESPACE}" ]] && DISCOVERY_CMD+=("--namespace" "${NAMESPACE}")
[[ -n "${NODE_IP}" ]] && DISCOVERY_CMD+=("--node-ip" "${NODE_IP}")
[[ -n "${USER_CONFIG}" ]] && DISCOVERY_CMD+=("--user-config" "${USER_CONFIG}")
[[ -n "${OBS_HOST_INPUT}" ]] && DISCOVERY_CMD+=("--obs-host" "${OBS_HOST_INPUT}")

echo "[launch] discovering targets..."
"${DISCOVERY_CMD[@]}"

if [[ -f "./generated/discovered.env" ]]; then
  # shellcheck disable=SC1091
  source "./generated/discovered.env"
fi

if [[ "${DRY_RUN}" -eq 1 ]]; then
  echo
  echo "========== generated/prometheus.yml =========="
  sed -n '1,240p' "./generated/prometheus.yml"
  echo "============================================="
fi

if [[ "${DISCOVER_ONLY}" -eq 1 || "${DRY_RUN}" -eq 1 ]]; then
  echo "[launch] discovery completed."
  exit 0
fi

run_native() {
  echo "[launch] starting native runtime..."
  ./scripts/start-native.sh \
    --env-file "./generated/discovered.env" \
    --prometheus-file "./generated/prometheus.yml"
}

if [[ "${FORCE_NATIVE}" -eq 1 ]]; then
  run_native
  exit 0
fi

echo "[launch] starting Docker Compose stack..."
set +e
PROMETHEUS_CONFIG_FILE="./generated/prometheus.yml" \
OBS_HOST="${OBS_HOST:-}" \
./start.sh
DOCKER_RC=$?
set -e

if [[ "${DOCKER_RC}" -ne 0 ]]; then
  echo "[launch] Docker startup failed (exit=${DOCKER_RC}), fallback to native runtime."
  run_native
fi
