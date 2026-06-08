#!/usr/bin/env bash
# Launch the pyMotor observability stack via Docker Compose.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
cd "${SCRIPT_DIR}"
. "${SCRIPT_DIR}/scripts/load-dotenv.sh"

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "[start] created .env from .env.example"
fi

PROFILES=""
STACK_MODE="${OBS_STACK_MODE:-minimal}"
WITH_MOCK=0
LOKI_MODE="docker"
LOKI_GRAFANA_URL="http://loki:3100"
LOKI_OTEL_ENDPOINT="http://loki:3100/loki/api/v1/push"
LOKI_COMPOSE_SCALE=()

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
  --minimal          start core stack with Loki (default)
  --full             add node-exporter/cAdvisor infra exporters
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
load_dotenv "${DISCOVERED_ENV}"

render_loki_url() {
  local src="$1"
  local dst="$2"
  sed "s|http://loki:3100|${LOKI_GRAFANA_URL}|g" "${src}" > "${dst}"
}

render_otel_loki_endpoint() {
  local src="$1"
  local dst="$2"
  sed "s|http://loki:3100/loki/api/v1/push|${LOKI_OTEL_ENDPOINT}|g" "${src}" > "${dst}"
}

prepare_minimal_provisioning() {
  local out_dir="${SCRIPT_DIR}/generated/grafana-provisioning-minimal"
  mkdir -p "${out_dir}/datasources" "${out_dir}/dashboards"
  cp -f "${SCRIPT_DIR}/grafana/provisioning/dashboards/dashboard-providers.yml" "${out_dir}/dashboards/dashboard-providers.yml"
  render_loki_url \
    "${SCRIPT_DIR}/grafana/provisioning/datasources/datasources-minimal.yml" \
    "${out_dir}/datasources/datasources.yml"
  GRAFANA_PROVISIONING_DIR="./generated/grafana-provisioning-minimal"
  export GRAFANA_PROVISIONING_DIR
}

prepare_full_provisioning() {
  if [[ "${LOKI_MODE}" == "native" ]]; then
    local out_dir="${SCRIPT_DIR}/generated/grafana-provisioning-runtime"
    mkdir -p "${out_dir}/datasources" "${out_dir}/dashboards"
    cp -f "${SCRIPT_DIR}/grafana/provisioning/dashboards/dashboard-providers.yml" "${out_dir}/dashboards/dashboard-providers.yml"
    render_loki_url \
      "${SCRIPT_DIR}/grafana/provisioning/datasources/datasources.yml" \
      "${out_dir}/datasources/datasources.yml"
    GRAFANA_PROVISIONING_DIR="./generated/grafana-provisioning-runtime"
    export GRAFANA_PROVISIONING_DIR
  else
    GRAFANA_PROVISIONING_DIR="./grafana/provisioning"
    export GRAFANA_PROVISIONING_DIR
  fi
}

prepare_otel_config() {
  local src="$1"
  local dst="$2"
  mkdir -p "$(dirname "${dst}")"
  if [[ "${LOKI_MODE}" == "native" ]]; then
    render_otel_loki_endpoint "${src}" "${dst}"
  else
    cp -f "${src}" "${dst}"
  fi
  OTEL_CONFIG_FILE="${dst}"
  export OTEL_CONFIG_FILE
}

prepare_minimal_prometheus() {
  local input_file="${PROMETHEUS_CONFIG_FILE:-${SCRIPT_DIR}/generated/prometheus.yml}"
  if [[ ! -f "${input_file}" ]]; then
    input_file="${SCRIPT_DIR}/prometheus/prometheus-minimal.yml"
  fi
  local output_file="${SCRIPT_DIR}/generated/prometheus-minimal.runtime.yml"
  mkdir -p "${SCRIPT_DIR}/generated"
  cp "${input_file}" "${output_file}"
  PROMETHEUS_CONFIG_FILE="./generated/prometheus-minimal.runtime.yml"
  export PROMETHEUS_CONFIG_FILE
}

start_host_helpers() {
  if [[ -f "${DISCOVERED_ENV}" ]]; then
    "${SCRIPT_DIR}/scripts/run-k8s-port-forwards-host.sh" --env-file "${DISCOVERED_ENV}"
  fi
}

ensure_loki() {
  local prefix="${REGISTRY_PREFIX:-}"
  local lv="${LOKI_VERSION:-3.3.0}"
  local loki_img="${prefix}grafana/loki:${lv}"
  local docker_bin="${DOCKER_BIN:-docker}"

  if "${docker_bin}" image inspect "${loki_img}" >/dev/null 2>&1; then
    echo "[start] Loki Docker image available: ${loki_img}"
    return 0
  fi

  echo "[start] pulling Loki image: ${loki_img}"
  if "${docker_bin}" pull "${loki_img}" >/dev/null 2>&1; then
    return 0
  fi

  if [[ -n "${prefix}" ]] && "${docker_bin}" pull "grafana/loki:${lv}" >/dev/null 2>&1; then
    echo "[start] tagging grafana/loki:${lv} -> ${loki_img}"
    "${docker_bin}" tag "grafana/loki:${lv}" "${loki_img}"
    return 0
  fi

  echo "[start] Docker Loki unavailable, falling back to native Loki"
  LOKI_MODE="native"
  LOKI_GRAFANA_URL="http://host.docker.internal:${LOKI_PORT:-3100}"
  LOKI_OTEL_ENDPOINT="http://host.docker.internal:${LOKI_PORT:-3100}/loki/api/v1/push"
  LOKI_COMPOSE_SCALE=(--scale loki=0)
  "${SCRIPT_DIR}/scripts/loki-native.sh" start
}

DOCKER_BIN="${DOCKER_BIN:-docker}"
if ! "${DOCKER_BIN}" compose version >/dev/null 2>&1; then
  echo "[start] error: '${DOCKER_BIN} compose' is not available. Install Docker Compose v2." >&2
  exit 1
fi

if [[ -f .env ]]; then
  load_dotenv "${SCRIPT_DIR}/.env"
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

ensure_loki

if [[ "${STACK_MODE}" == "minimal" ]]; then
  prepare_minimal_provisioning
  prepare_minimal_prometheus
  prepare_otel_config \
    "${SCRIPT_DIR}/otel-collector/otel-collector-minimal.yaml" \
    "${SCRIPT_DIR}/generated/otel-collector-minimal.runtime.yaml"
else
  PROMETHEUS_CONFIG_FILE="${PROMETHEUS_CONFIG_FILE:-./prometheus/prometheus.yml}"
  prepare_full_provisioning
  prepare_otel_config \
    "${SCRIPT_DIR}/otel-collector/otel-collector.yaml" \
    "${SCRIPT_DIR}/generated/otel-collector.runtime.yaml"
fi
export PROMETHEUS_CONFIG_FILE OTEL_CONFIG_FILE

start_host_helpers

ensure_compose_images() {
  local saved_grafana_prov="${GRAFANA_PROVISIONING_DIR:-}"
  local saved_prom_config="${PROMETHEUS_CONFIG_FILE:-}"
  local saved_otel_config="${OTEL_CONFIG_FILE:-}"
  if [[ -f .env ]]; then
    load_dotenv "${SCRIPT_DIR}/.env"
  fi
  if [[ -n "${saved_grafana_prov}" ]]; then
    GRAFANA_PROVISIONING_DIR="${saved_grafana_prov}"
    export GRAFANA_PROVISIONING_DIR
  fi
  if [[ -n "${saved_prom_config}" ]]; then
    PROMETHEUS_CONFIG_FILE="${saved_prom_config}"
    export PROMETHEUS_CONFIG_FILE
  fi
  if [[ -n "${saved_otel_config}" ]]; then
    OTEL_CONFIG_FILE="${saved_otel_config}"
    export OTEL_CONFIG_FILE
  fi
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

COMPOSE_PULL="${OBS_COMPOSE_PULL:-missing}"
COMPOSE_UP_ARGS=(up -d --pull "${COMPOSE_PULL}")
if [[ "${OBS_COMPOSE_BUILD:-0}" == "1" ]]; then
  COMPOSE_UP_ARGS+=(--build)
else
  COMPOSE_UP_ARGS+=(--no-build)
fi

echo "[start] starting Docker Compose stack mode=${STACK_MODE} loki=${LOKI_MODE} profiles: ${PROFILES:-<none>}"
"${DOCKER_BIN}" compose "${PROFILE_ARGS[@]}" "${COMPOSE_UP_ARGS[@]}" "${LOKI_COMPOSE_SCALE[@]}"

GRAFANA_PORT="${GRAFANA_PORT:-3000}"
PROMETHEUS_PORT="${PROMETHEUS_PORT:-9090}"
LOKI_PORT="${LOKI_PORT:-3100}"

if [[ "${STACK_MODE}" == "minimal" ]] && command -v curl >/dev/null 2>&1; then
  curl -fsS -X POST "http://localhost:${PROMETHEUS_PORT}/-/reload" >/dev/null 2>&1 || true
fi

cat <<EOF

================================================================
pyMotor observability stack is up.

  Grafana       http://localhost:${GRAFANA_PORT}   (user: motor / pass: motor)
  Prometheus    http://localhost:${PROMETHEUS_PORT}
  Tempo         http://localhost:${TEMPO_QUERY_PORT:-3200}
  Loki          http://localhost:${LOKI_PORT}  (${LOKI_MODE})
  OTel OTLP     localhost:${OTEL_GRPC_PORT:-4317} (gRPC) / ${OTEL_HTTP_PORT:-4318} (HTTP)

Mode: ${STACK_MODE}
Loki runtime: ${LOKI_MODE}
Active profiles: ${PROFILES:-<none>}

Tips:
  * 推荐入口: ./launch.sh （自动发现 + 自动生成 Prometheus 配置）
  * 当前 Prometheus 配置: ${PROMETHEUS_CONFIG_FILE:-./prometheus/prometheus.yml}
  * Verify tracing: ./scripts/verify-tracing.sh  (OTLP → Tempo)
  * Native Loki: ./scripts/loki-native.sh {start|stop|status}
================================================================
EOF
