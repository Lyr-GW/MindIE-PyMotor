#!/usr/bin/env bash
# Launch the pyMotor observability stack.
#
# Usage:
#   ./start.sh                    # core stack (Prometheus/Grafana/Tempo/Loki/OTel)
#   ./start.sh --profile npu-real # additionally enable Ascend npu-exporter

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
cd "${SCRIPT_DIR}"

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "[start] created .env from .env.example"
fi

PROFILES=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile)
      shift
      PROFILES="$1"
      shift
      ;;
    -h|--help)
      cat <<EOF
Usage: $0 [options]
  --profile <list>   comma-separated profiles (default: none)
                     known: npu-real
  -h, --help         show this help
EOF
      exit 0
      ;;
    *)
      echo "[start] unknown option: $1" >&2
      exit 1
      ;;
  esac
done

DOCKER_BIN="${DOCKER_BIN:-docker}"
if ! "${DOCKER_BIN}" compose version >/dev/null 2>&1; then
  echo "[start] error: '${DOCKER_BIN} compose' is not available. Install Docker Compose v2." >&2
  exit 1
fi

PROFILE_ARGS=()
if [[ -n "${PROFILES}" ]]; then
  IFS=',' read -r -a profiles_arr <<<"${PROFILES}"
  for p in "${profiles_arr[@]}"; do
    [[ -z "${p}" ]] && continue
    PROFILE_ARGS+=(--profile "${p}")
  done
fi

echo "[start] starting stack with profiles: ${PROFILES:-<none>}"
"${DOCKER_BIN}" compose "${PROFILE_ARGS[@]}" up -d --build

# shellcheck disable=SC2046
GRAFANA_PORT="$(grep -E '^GRAFANA_PORT=' .env 2>/dev/null | tail -n1 | cut -d= -f2)"
GRAFANA_PORT="${GRAFANA_PORT:-3000}"

cat <<EOF

================================================================
pyMotor observability stack is up.

  Grafana       http://localhost:${GRAFANA_PORT}   (user: motor / pass: motor)
  Prometheus    http://localhost:9090
  Tempo         http://localhost:3200
  Loki          http://localhost:3100
  OTel OTLP     localhost:4317 (gRPC) / 4318 (HTTP)
  Controller    http://localhost:9106/metrics  (controller-metrics-proxy)

Active profiles: ${PROFILES:-<none>}

Tips:
  * Wire pyMotor metrics: edit prometheus/prometheus.yml (or set
    PROMETHEUS_CONFIG_FILE in .env) and replace placeholder targets.
  * Send traces: set OTEL_EXPORTER_OTLP_TRACES_ENDPOINT to
    http://<this-host>:4317 in your motor_coordinator_env.
================================================================
EOF
