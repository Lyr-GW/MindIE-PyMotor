#!/usr/bin/env bash
# Copyright (c) Huawei Technologies Co., Ltd. 2025-2026. All rights reserved.
# MindIE-PyMotor IPv6 single-stack comprehensive acceptance script.
#
# Usage:
#   ./examples/features/ipv6_single_stack/test_ipv6_comprehensive.sh [phase]
#
# Phases (default: all):
#   preflight   - OS / kernel / basic v6 connectivity
#   unit        - PyMotor IPv6-related pytest suite
#   static      - Config / env / URL format checks (no running cluster)
#   integration - HTTP/etcd checks against a live deployment (needs env vars)
#   logs        - Grep component logs for expected IPv6 bind patterns
#
# Integration environment variables (override as needed):
#   COORDINATOR_V6      Coordinator Pod IPv6 (e.g. 2001:db8::10)
#   CONTROLLER_V6       Controller Pod IPv6
#   ENGINE_V6           Engine Server Pod IPv6 (any one instance)
#   NODE_MANAGER_V6     Node Manager Pod IPv6
#   ETCD_V6             etcd member IPv6
#   COORD_INFER_PORT=1025
#   COORD_MGMT_PORT=1026
#   CTRL_API_PORT=1026
#   CTRL_OBS_PORT=1027
#   ENGINE_MGMT_PORT=9000
#   ETCD_PORT=2379
#   MODEL_NAME          Model name for chat completion probe
#   K8S_NAMESPACE       Namespace for log grep (optional)
#   MOTOR_ROOT          Repo root (auto-detected)
#
# Examples:
#   ./test_ipv6_comprehensive.sh preflight unit
#   COORDINATOR_V6=2001:db8::10 MODEL_NAME=Qwen ./test_ipv6_comprehensive.sh integration
#   K8S_NAMESPACE=mindie-motor ./test_ipv6_comprehensive.sh logs

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MOTOR_ROOT="${MOTOR_ROOT:-$(cd "${SCRIPT_DIR}/../../.." && pwd)}"
cd "${MOTOR_ROOT}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'
PASS_COUNT=0
FAIL_COUNT=0
SKIP_COUNT=0

pass() { echo -e "${GREEN}[PASS]${NC} $*"; PASS_COUNT=$((PASS_COUNT + 1)); }
fail() { echo -e "${RED}[FAIL]${NC} $*"; FAIL_COUNT=$((FAIL_COUNT + 1)); }
skip() { echo -e "${YELLOW}[SKIP]${NC} $*"; SKIP_COUNT=$((SKIP_COUNT + 1)); }
info() { echo -e "[INFO] $*"; }
section() { echo ""; echo "========== $* =========="; }

require_cmd() {
    local cmd="$1"
    if ! command -v "${cmd}" >/dev/null 2>&1; then
        fail "Required command not found: ${cmd}"
        return 1
    fi
    return 0
}

v6_url() {
    local host="$1" port="$2" path="${3:-}"
    local base="http://[${host}]:${port}"
    if [[ -n "${path}" ]]; then
        echo "${base}${path}"
    else
        echo "${base}"
    fi
}

curl_v6() {
    curl -g -6 -sS -k --connect-timeout 10 "$@"
}

phase_preflight() {
    section "Preflight: OS & IPv6 stack"

    if [[ -f /proc/sys/net/ipv6/conf/all/disable_ipv6 ]]; then
        local disabled
        disabled="$(cat /proc/sys/net/ipv6/conf/all/disable_ipv6)"
        if [[ "${disabled}" == "0" ]]; then
            pass "Kernel IPv6 enabled (disable_ipv6=0)"
        else
            fail "Kernel IPv6 disabled (disable_ipv6=${disabled})"
        fi
    else
        skip "Cannot read disable_ipv6 sysctl"
    fi

    if command -v ip >/dev/null 2>&1; then
        if ip -6 addr show 2>/dev/null | grep -q 'inet6'; then
            pass "Host has inet6 addresses"
        else
            fail "No inet6 addresses on host"
        fi
    else
        skip "ip command not installed"
    fi

    if require_cmd ping6 && ping6 -c 1 -W 2 ::1 >/dev/null 2>&1; then
        pass "ping6 ::1 OK"
    fi

    if python3 -c "from motor.common.utils.net import format_address; assert format_address('::1', 1025) == '[::1]:1025'" 2>/dev/null; then
        pass "motor.common.utils.net available"
    else
        skip "motor.common.utils.net missing (merge IPv6 PR first)"
    fi
}

phase_unit() {
    section "Unit tests: IPv6 pytest suite"
    export PYTHONPATH="${MOTOR_ROOT}:${MOTOR_ROOT}/motor:${PYTHONPATH:-}"
    local test_files=(
        tests/common/utils/test_net.py
        tests/common/utils/test_http_client_ipv6.py
        tests/coordinator/process/test_inference_manager_socket.py
        tests/engine_server/utils/test_ip.py
    )
    for f in "${test_files[@]}"; do
        [[ -f "${MOTOR_ROOT}/${f}" ]] || { fail "Missing ${f}"; return; }
    done
    if python3 -m pytest "${test_files[@]}" -q --tb=short; then
        pass "All IPv6 unit tests passed"
    else
        fail "IPv6 unit tests failed"
    fi
}

phase_static() {
    section "Static checks"
    local sample="${SCRIPT_DIR}/config_sample.json"
    if [[ -f "${sample}" ]]; then
        grep -q '"controller_api_host": "::1"' "${sample}" && pass "controller_api_host ::1"
        grep -q '"coordinator_api_host": "::1"' "${sample}" && pass "coordinator_api_host ::1"
    else
        skip "config_sample.json missing"
    fi
    local common_sh="${MOTOR_ROOT}/examples/deployer/startup/common.sh"
    if [[ -f "${common_sh}" ]] && grep -q 'IPv6 single-stack' "${common_sh}"; then
        pass "common.sh MF Store IPv6 URL support"
    else
        skip "common.sh IPv6 MF Store block not found"
    fi
    [[ -n "${POD_IP:-}" ]] && [[ "${POD_IP}" == *:* ]] && pass "POD_IP is v6: ${POD_IP}" || skip "POD_IP not v6 or unset"
    if [[ -n "${ASCEND_MF_STORE_URL:-}" ]]; then
        [[ "${ASCEND_MF_STORE_URL}" =~ ^(tcp://)?\[([0-9a-fA-F:]+)\](:([0-9]+))?$ ]] \
            && pass "ASCEND_MF_STORE_URL RFC3986 v6" \
            || fail "ASCEND_MF_STORE_URL must be tcp://[v6]:port"
    else
        skip "ASCEND_MF_STORE_URL unset"
    fi
}

phase_integration() {
    section "Integration: live cluster"
    COORD_INFER_PORT="${COORD_INFER_PORT:-1025}"
    ENGINE_MGMT_PORT="${ENGINE_MGMT_PORT:-9000}"
    CTRL_OBS_PORT="${CTRL_OBS_PORT:-1027}"
    ETCD_PORT="${ETCD_PORT:-2379}"
    require_cmd curl || return

    if [[ -n "${COORDINATOR_V6:-}" ]]; then
        local u
        u="$(v6_url "${COORDINATOR_V6}" "${COORD_INFER_PORT}" "/v1/models")"
        code="$(curl_v6 -o /dev/null -w '%{http_code}' "${u}" 2>/dev/null || echo 000)"
        [[ "${code}" =~ ^(200|404)$ ]] && pass "Coordinator ${u} HTTP ${code}" || fail "Coordinator unreachable"
        if [[ -n "${MODEL_NAME:-}" ]]; then
            u="$(v6_url "${COORDINATOR_V6}" "${COORD_INFER_PORT}" "/v1/chat/completions")"
            curl_v6 -X POST "${u}" -H 'Content-Type: application/json' \
                -d "{\"model\":\"${MODEL_NAME}\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}],\"max_tokens\":8}" \
                -o /tmp/ipv6_chat.json 2>/dev/null
            grep -q '"choices"' /tmp/ipv6_chat.json 2>/dev/null && pass "chat/completions OK" || fail "chat/completions bad body"
        else
            skip "Set MODEL_NAME for full inference test"
        fi
    else
        skip "Set COORDINATOR_V6"
    fi

    if [[ -n "${ENGINE_V6:-}" ]]; then
        for p in /health /metrics; do
            u="$(v6_url "${ENGINE_V6}" "${ENGINE_MGMT_PORT}" "${p}")"
            code="$(curl_v6 -o /dev/null -w '%{http_code}' "${u}" 2>/dev/null || echo 000)"
            [[ "${code}" == "200" ]] && pass "Engine ${p}" || fail "Engine ${p} HTTP ${code}"
        done
    else
        skip "Set ENGINE_V6"
    fi

    if [[ -n "${CONTROLLER_V6:-}" ]]; then
        u="$(v6_url "${CONTROLLER_V6}" "${CTRL_OBS_PORT}" "/")"
        code="$(curl_v6 -o /dev/null -w '%{http_code}' "${u}" 2>/dev/null || echo 000)"
        [[ "${code}" =~ ^(200|404|405)$ ]] && pass "Controller observability" || fail "Controller obs HTTP ${code}"
    fi

    if [[ -n "${ETCD_V6:-}" ]] && command -v etcdctl >/dev/null 2>&1; then
        etcdctl --endpoints="[${ETCD_V6}]:${ETCD_PORT}" endpoint health && pass "etcd health" || fail "etcd health"
    else
        skip "Set ETCD_V6 or install etcdctl"
    fi

    if [[ "${IPV6_LOAD_TEST:-0}" == "1" && -n "${COORDINATOR_V6:-}" && -n "${MODEL_NAME:-}" ]]; then
        u="$(v6_url "${COORDINATOR_V6}" "${COORD_INFER_PORT}" "/v1/chat/completions")"
        ok=0
        for _ in $(seq 1 20); do
            curl_v6 -X POST "${u}" -H 'Content-Type: application/json' \
                -d "{\"model\":\"${MODEL_NAME}\",\"messages\":[{\"role\":\"user\",\"content\":\"x\"}],\"max_tokens\":4}" \
                -o /dev/null -w '%{http_code}' 2>/dev/null | grep -q '^200$' && ok=$((ok + 1))
        done
        [[ "${ok}" -eq 20 ]] && pass "Load 20/20" || fail "Load ${ok}/20"
    fi
}

phase_logs() {
    section "Log checks (kubectl)"
    command -v kubectl >/dev/null 2>&1 || { skip "kubectl missing"; return; }
    [[ -n "${K8S_NAMESPACE:-}" ]] || { skip "Set K8S_NAMESPACE"; return; }
    declare -A P=(
        [controller]='Starting Controller API server on http://\['
        [coordinator]='Created shared socket on \['
    )
    for c in "${!P[@]}"; do
        kubectl -n "${K8S_NAMESPACE}" logs -l "app=${c}" --tail=500 2>/dev/null | grep -qE "${P[$c]}" \
            && pass "log ${c}" || fail "log ${c} no IPv6 bind pattern"
    done
}

ALL_PHASES=(preflight unit static integration logs)
PHASES=("${ALL_PHASES[@]}")
[[ $# -gt 0 ]] && PHASES=("$@")

echo "MindIE-PyMotor IPv6 test | MOTOR_ROOT=${MOTOR_ROOT} | phases: ${PHASES[*]}"
for phase in "${PHASES[@]}"; do
    case "${phase}" in
        preflight|unit|static|integration|logs) "phase_${phase}" ;;
        all) for p in "${ALL_PHASES[@]}"; do "phase_${p}"; done ;;
        *) echo "Unknown phase: ${phase}"; exit 2 ;;
    esac
done
section "Summary"
echo "Passed: ${PASS_COUNT} Failed: ${FAIL_COUNT} Skipped: ${SKIP_COUNT}"
[[ "${FAIL_COUNT}" -eq 0 ]]
