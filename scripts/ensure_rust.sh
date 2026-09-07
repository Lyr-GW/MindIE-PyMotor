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

# Locate or install cargo for motor native crates (workload-shm + kv-conductor).
# Source from build.sh (same shell) so PATH changes persist.
# Defaults use rsproxy (China). Override with RUSTUP_DIST_SERVER / RUSTUP_UPDATE_ROOT /
# RUSTUP_INIT_URL. Set SKIP_RUST_INSTALL=1 to disable network install (offline PREBUILT).

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
