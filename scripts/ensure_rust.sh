#!/bin/bash
# Copyright (c) Huawei Technologies Co., Ltd. 2025-2026. All rights reserved.
# MindIE is licensed under Mulan PSL v2.
# You can use this software according to the terms and conditions of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
#         http://license.coscl.org.cn/MulanPSL2
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the Mulan PSL v2 for more details.

# Native toolchain helpers sourced by build.sh (same shell so PATH/CXX persist):
#   motor_ensure_cargo — find rustup cargo or install it (rsproxy by default)
#   motor_ensure_cxx   — find c++/g++ or apt/dnf install g++ (kv-conductor zmq-sys)
# Override rustup with RUSTUP_DIST_SERVER / RUSTUP_UPDATE_ROOT / RUSTUP_INIT_URL.
# SKIP_RUST_INSTALL=1 / SKIP_CXX_INSTALL=1 disable the matching network install.

motor_source_cargo_env() {
    if command -v cargo >/dev/null 2>&1; then
        return 0
    fi

    local env_file bin_dir
    for env_file in \
        "${CARGO_HOME:+${CARGO_HOME}/env}" \
        "${HOME}/.cargo/env" \
        "/root/.cargo/env"; do
        if [[ -n "${env_file}" && -f "${env_file}" && -r "${env_file}" ]]; then
            # shellcheck disable=SC1090
            source "${env_file}"
            if command -v cargo >/dev/null 2>&1; then
                return 0
            fi
        fi
    done

    for bin_dir in \
        "${CARGO_HOME:+${CARGO_HOME}/bin}" \
        "${HOME}/.cargo/bin" \
        "/root/.cargo/bin"; do
        if [[ -n "${bin_dir}" && -x "${bin_dir}/cargo" ]]; then
            export PATH="${bin_dir}:${PATH}"
            return 0
        fi
    done
    return 1
}

motor_install_rustup() {
    if [[ "${SKIP_RUST_INSTALL:-0}" == "1" ]]; then
        echo "[ERROR] cargo not found and SKIP_RUST_INSTALL=1; not installing rustup." >&2
        return 1
    fi

    export RUSTUP_DIST_SERVER="${RUSTUP_DIST_SERVER:-https://rsproxy.cn}"
    export RUSTUP_UPDATE_ROOT="${RUSTUP_UPDATE_ROOT:-https://rsproxy.cn/rustup}"
    local init_url="${RUSTUP_INIT_URL:-https://rsproxy.cn/rustup-init.sh}"
    local toolchain="${RUSTUP_TOOLCHAIN:-stable}"

    echo "Installing Rust toolchain via rustup (needed to compile libmindie_workload_shm.so)..."
    echo "  RUSTUP_DIST_SERVER=${RUSTUP_DIST_SERVER}"
    echo "  RUSTUP_INIT_URL=${init_url}"

    if command -v curl >/dev/null 2>&1; then
        curl --proto '=https' --tlsv1.2 -sSf "${init_url}" | sh -s -- -y --default-toolchain "${toolchain}" --no-modify-path
    elif command -v wget >/dev/null 2>&1; then
        wget -qO- "${init_url}" | sh -s -- -y --default-toolchain "${toolchain}" --no-modify-path
    else
        echo "[ERROR] curl or wget is required to install rustup." >&2
        return 1
    fi

    motor_source_cargo_env
}

motor_ensure_cargo() {
    if motor_source_cargo_env; then
        echo "cargo ready: $(command -v cargo) ($(cargo --version 2>/dev/null || echo unknown))"
        return 0
    fi
    if ! motor_install_rustup; then
        return 1
    fi
    if ! command -v cargo >/dev/null 2>&1; then
        echo "[ERROR] rustup finished but cargo is still not on PATH." >&2
        return 1
    fi
    echo "cargo ready: $(command -v cargo) ($(cargo --version 2>/dev/null || echo unknown))"
    return 0
}

motor_cxx_on_path() {
    command -v c++ >/dev/null 2>&1 \
        || command -v g++ >/dev/null 2>&1 \
        || command -v clang++ >/dev/null 2>&1
}

motor_export_cxx() {
    if [[ -n "${CXX:-}" ]] && command -v "${CXX}" >/dev/null 2>&1; then
        export CXX
        return 0
    fi
    if command -v c++ >/dev/null 2>&1; then
        export CXX=c++
    elif command -v g++ >/dev/null 2>&1; then
        CXX="$(command -v g++)"
        export CXX
    elif command -v clang++ >/dev/null 2>&1; then
        CXX="$(command -v clang++)"
        export CXX
    fi
}

motor_report_cxx() {
    motor_export_cxx
    local ver
    ver="$(${CXX} --version 2>/dev/null || true)"
    echo "c++ ready: ${CXX} (${ver%%$'\n'*})"
}

motor_install_gxx() {
    if [[ "${SKIP_CXX_INSTALL:-0}" == "1" ]]; then
        echo "[ERROR] C++ compiler not found and SKIP_CXX_INSTALL=1; not installing g++." >&2
        return 1
    fi

    echo "Installing g++ (kv-conductor zmq-sys needs the c++ tool)..."
    if command -v apt-get >/dev/null 2>&1; then
        apt-get update
        DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends g++
    elif command -v dnf >/dev/null 2>&1; then
        dnf install -y gcc-c++
    elif command -v yum >/dev/null 2>&1; then
        yum install -y gcc-c++
    else
        echo "[ERROR] no supported package manager was found to install g++." >&2
        echo "  Ubuntu: apt-get install -y g++   (or build-essential)" >&2
        echo "  openEuler: dnf/yum install -y gcc-c++" >&2
        return 1
    fi
}

motor_ensure_cxx() {
    if motor_cxx_on_path; then
        motor_report_cxx
        return 0
    fi
    if ! motor_install_gxx; then
        return 1
    fi
    hash -r 2>/dev/null || true
    if ! motor_cxx_on_path; then
        echo "[ERROR] g++ install finished but c++/g++ is still not on PATH." >&2
        return 1
    fi
    motor_report_cxx
}

# Convenience single knob: SKIP_RUST_BUILD=1 means "no Rust source changed since
# the last successful build.sh run; skip cargo entirely for both crates and reuse
# whatever is already in workload_shm_rs/lib/ and kv_conductor/bin/". It only sets
# the per-crate flags when they were not explicitly set, so an explicit
# SKIP_WORKLOAD_SHM_BUILD=0 / SKIP_KV_CONDUCTOR_BUILD=0 still forces a rebuild of
# that one crate. It does NOT authorize shipping a wheel without workload-shm: if
# lib/libmindie_workload_shm.so is missing, build.sh ignores the skip and rebuilds
# (see the workload-shm section), so a first-time build still works unattended.
motor_apply_skip_rust_build_shorthand() {
    if [[ "${SKIP_RUST_BUILD:-0}" == "1" ]]; then
        : "${SKIP_WORKLOAD_SHM_BUILD:=1}"
        : "${SKIP_KV_CONDUCTOR_BUILD:=1}"
        export SKIP_WORKLOAD_SHM_BUILD
        export SKIP_KV_CONDUCTOR_BUILD
    fi
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    set -euo pipefail
    motor_ensure_cargo
fi
