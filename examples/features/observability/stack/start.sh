#!/usr/bin/env bash
# Launch the pyMotor observability stack via Docker Compose.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
cd "${SCRIPT_DIR}"

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "[start] created .env from .env.example"
fi

PROFILES=""
STACK_MODE="${OBS_STACK_MODE:-full}"
WITH_MOCK=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --minimal)
      STACK_MODE="minimal"
      shift
      ;;
    --full)
      STACK_MODE="full"
      shift
      ;;
    --with-mock)
      WITH_MOCK=1
      shift
      ;;
    --profile)
      shift
      PROFILES="$1"
      shift
      ;;
    -h|--help)
      cat <<EOF
Usage: $0 [options]
  --minimal          start Prometheus/Grafana/Tempo/OTel only
  --full             start full stack with Loki/node-exporter/cAdvisor (default)
  --with-mock        enable mock profile when present
  --profile <list>   comma-separated profiles (default: none)
                     known: npu, full
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

DISCOVERED_ENV="${SCRIPT_DIR}/generated/discovered.env"
if [[ -f "${DISCOVERED_ENV}" ]]; then
  # shellcheck disable=SC1090
  source "${DISCOVERED_ENV}"
fi

prepare_minimal_provisioning() {
  local out_dir="${SCRIPT_DIR}/generated/grafana-provisioning-minimal"
  mkdir -p "${out_dir}/datasources" "${out_dir}/dashboards"
  cp -f "${SCRIPT_DIR}/grafana/provisioning/dashboards/dashboard-providers.yml" "${out_dir}/dashboards/dashboard-providers.yml"
  cp -f "${SCRIPT_DIR}/grafana/provisioning/datasources/datasources-minimal.yml" "${out_dir}/datasources/datasources.yml"
  GRAFANA_PROVISIONING_DIR="./generated/grafana-provisioning-minimal"
  export GRAFANA_PROVISIONING_DIR
}

prepare_minimal_prometheus() {
  local input_file="${PROMETHEUS_CONFIG_FILE:-${SCRIPT_DIR}/generated/prometheus.yml}"
  if [[ ! -f "${input_file}" ]]; then
    input_file="${SCRIPT_DIR}/prometheus/prometheus-minimal.yml"
  fi
  local output_file="${SCRIPT_DIR}/generated/prometheus-minimal.runtime.yml"
  mkdir -p "${SCRIPT_DIR}/generated"
  python3 - "${input_file}" "${output_file}" <<'PY'
from pathlib import Path
import sys
src = Path(sys.argv[1])
dst = Path(sys.argv[2])
text = src.read_text(encoding="utf-8")
text = text.replace("controller-metrics-proxy:9106", "host.docker.internal:9106")
text = text.replace("localhost:9106", "host.docker.internal:9106")
dst.write_text(text, encoding="utf-8")
PY
  PROMETHEUS_CONFIG_FILE="./generated/prometheus-minimal.runtime.yml"
  export PROMETHEUS_CONFIG_FILE
}

start_host_helpers() {
  if [[ -f "${DISCOVERED_ENV}" ]]; then
    "${SCRIPT_DIR}/scripts/run-k8s-port-forwards-host.sh" --env-file "${DISCOVERED_ENV}"
    "${SCRIPT_DIR}/scripts/run-controller-proxy-host.sh" --env-file "${DISCOVERED_ENV}"
  fi
}

DOCKER_BIN="${DOCKER_BIN:-docker}"
if ! "${DOCKER_BIN}" compose version >/dev/null 2>&1; then
  echo "[start] error: '${DOCKER_BIN} compose' is not available. Install Docker Compose v2." >&2
  exit 1
fi

PROFILE_ARGS=()
if [[ "${STACK_MODE}" == "full" ]]; then
  PROFILE_ARGS+=(--profile full)
fi
if [[ "${WITH_MOCK}" -eq 1 ]]; then
  PROFILE_ARGS+=(--profile mock)
fi
if [[ -n "${PROFILES}" ]]; then
  IFS=',' read -r -a profiles_arr <<<"${PROFILES}"
  for p in "${profiles_arr[@]}"; do
    [[ -z "${p}" ]] && continue
    PROFILE_ARGS+=(--profile "${p}")
  done
fi

if [[ "${STACK_MODE}" == "minimal" ]]; then
  prepare_minimal_provisioning
  prepare_minimal_prometheus
  OTEL_CONFIG_FILE="${OTEL_CONFIG_FILE:-./otel-collector/otel-collector-minimal.yaml}"
else
  PROMETHEUS_CONFIG_FILE="${PROMETHEUS_CONFIG_FILE:-./prometheus/prometheus.yml}"
  OTEL_CONFIG_FILE="${OTEL_CONFIG_FILE:-./otel-collector/otel-collector.yaml}"
fi
export PROMETHEUS_CONFIG_FILE OTEL_CONFIG_FILE

start_host_helpers

ensure_compose_images() {
  # shellcheck disable=SC1091
  [[ -f .env ]] && source .env
  local prefix="${REGISTRY_PREFIX:-}"
  local gv="${GRAFANA_VERSION:-11.3.0}"
  local grafana_img="${prefix}grafana/grafana:${gv}"
  local legacy_img="${prefix}pymotor/grafana:${gv}"

  if ! "${DOCKER_BIN}" image inspect "${grafana_img}" >/dev/null 2>&1; then
    if "${DOCKER_BIN}" image inspect "grafana/grafana:${gv}" >/dev/null 2>&1; then
      echo "[start] tagging grafana/grafana:${gv} -> ${grafana_img}"
      "${DOCKER_BIN}" tag "grafana/grafana:${gv}" "${grafana_img}"
    fi
  fi
  if ! "${DOCKER_BIN}" image inspect "${legacy_img}" >/dev/null 2>&1 \
    && "${DOCKER_BIN}" image inspect "${grafana_img}" >/dev/null 2>&1; then
    "${DOCKER_BIN}" tag "${grafana_img}" "${legacy_img}" 2>/dev/null || true
  fi
}

ensure_compose_images

# missing: 本地已有镜像则不拉，缺失时才 pull（与 docker-compose pull_policy: if_not_present 一致）
# 可覆盖：OBS_COMPOSE_PULL=never|always|missing
COMPOSE_PULL="${OBS_COMPOSE_PULL:-missing}"
COMPOSE_UP_ARGS=(up -d --pull "${COMPOSE_PULL}")
if [[ "${OBS_COMPOSE_BUILD:-0}" == "1" ]]; then
  COMPOSE_UP_ARGS+=(--build)
else
  COMPOSE_UP_ARGS+=(--no-build)
fi

echo "[start] starting Docker Compose stack mode=${STACK_MODE} profiles: ${PROFILES:-<none>}"
"${DOCKER_BIN}" compose "${PROFILE_ARGS[@]}" "${COMPOSE_UP_ARGS[@]}"

GRAFANA_PORT="${GRAFANA_PORT:-3000}"
PROMETHEUS_PORT="${PROMETHEUS_PORT:-9090}"

if [[ "${STACK_MODE}" == "minimal" ]] && command -v curl >/dev/null 2>&1; then
  curl -fsS -X POST "http://localhost:${PROMETHEUS_PORT}/-/reload" >/dev/null 2>&1 || true
fi

cat <<EOF

================================================================
pyMotor observability stack is up.

  Grafana       http://localhost:${GRAFANA_PORT}   (user: motor / pass: motor)
  Prometheus    http://localhost:${PROMETHEUS_PORT}
  Tempo         http://localhost:${TEMPO_QUERY_PORT:-3200}
  OTel OTLP     localhost:${OTEL_GRPC_PORT:-4317} (gRPC) / ${OTEL_HTTP_PORT:-4318} (HTTP)

Mode: ${STACK_MODE}
Active profiles: ${PROFILES:-<none>}

Tips:
  * 推荐入口: ./launch.sh （自动发现 + 自动生成 Prometheus 配置）
  * 当前 Prometheus 配置: ${PROMETHEUS_CONFIG_FILE:-./prometheus/prometheus.yml}
  * Verify tracing: ./scripts/verify-tracing.sh  (OTLP → Tempo)
================================================================
EOF
