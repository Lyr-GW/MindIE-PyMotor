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

set -euo pipefail

# This script builds the motor wheel package.

# Allow verbosity control: set VERBOSE=1 to see full logs.
VERBOSE=${VERBOSE:-0}

# Clean up any existing build artifacts that might cause import issues.
rm -rf build/
rm -rf motor.egg-info/
rm -rf dist/

echo "Generating protobuf files..."
./scripts/generate_proto.sh

# Keep motor_version in sync with motor/__init__.py::__version__ (single source of truth).
# Support both double- and single-quoted __version__ assignments (aligned with setup.py).
MOTOR_VERSION="$(sed -n 's/^__version__[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' ./motor/__init__.py | head -n1)"
if [[ -z "${MOTOR_VERSION}" ]]; then
  MOTOR_VERSION="$(sed -n "s/^__version__[[:space:]]*=[[:space:]]*'\([^']*\)'.*/\1/p" ./motor/__init__.py | head -n1)"
fi
if [[ -z "${MOTOR_VERSION}" ]]; then
  echo "Error: failed to read __version__ from ./motor/__init__.py" >&2
  exit 1
fi

touch ./motor/version.info
cat>./motor/version.info<<EOF
motor_version : ${MOTOR_VERSION}
EOF
echo "Using motor_version=${MOTOR_VERSION}"

# --- Rust toolchain (CI / Docker / host) ---
# Jenkins often has rustup under $HOME/.cargo or /root/.cargo while the job PATH
# does not. Nightly previously skipped native crates and shipped an empty wheel.
# Source cargo env first; if still missing and workload-shm has no prebuilt, install
# rustup unless SKIP_RUST_INSTALL=1 (offline packing with WORKLOAD_SHM_PREBUILT).
#
# Set SKIP_RUST_BUILD=1 when no Rust source changed since the last successful
# build.sh run and you only need to repackage Python/config changes into a new
# wheel: it skips cargo for BOTH crates and reuses lib/*.so + bin/kv-conductor
# from the previous build (per-crate SKIP_*_BUILD env vars still override it).

KV_CONDUCTOR_DIR="./motor/kv_conductor"
KV_CONDUCTOR_BIN_DIR="$KV_CONDUCTOR_DIR/bin"
KV_CONDUCTOR_BIN="$KV_CONDUCTOR_BIN_DIR/kv-conductor"
WORKLOAD_SHM_DIR="./motor/coordinator/workload_shm_rs"
WORKLOAD_SHM_LIB_DIR="$WORKLOAD_SHM_DIR/lib"
WORKLOAD_SHM_LIB="$WORKLOAD_SHM_LIB_DIR/libmindie_workload_shm.so"

# shellcheck disable=SC1091
source ./scripts/ensure_rust.sh
# shellcheck disable=SC1091
source ./scripts/ensure_cxx.sh
motor_apply_skip_rust_build_shorthand
motor_source_cargo_env || true

_shm_has_input="0"
if [[ -n "${WORKLOAD_SHM_PREBUILT:-}" || -f "$WORKLOAD_SHM_LIB" ]]; then
    _shm_has_input="1"
fi
if ! command -v cargo >/dev/null 2>&1; then
    if [[ "${SKIP_WORKLOAD_SHM_BUILD:-0}" == "1" && "$_shm_has_input" == "1" ]]; then
        echo "cargo not on PATH; reusing prebuilt/existing workload-shm library."
    elif [[ -n "${WORKLOAD_SHM_PREBUILT:-}" ]]; then
        echo "cargo not on PATH; using WORKLOAD_SHM_PREBUILT."
    else
        echo "=== rust toolchain ==="
        if ! motor_ensure_cargo; then
            echo "[ERROR] refusing to emit dist/motor-*.whl: cargo is required to compile libmindie_workload_shm.so." >&2
            echo "  Coordinator cannot start without this library (no Python ledger fallback)." >&2
            echo "  Install Rust, or set WORKLOAD_SHM_PREBUILT, or copy the .so into $WORKLOAD_SHM_LIB_DIR/." >&2
            echo "  Offline: SKIP_RUST_INSTALL=1 plus a prebuilt library." >&2
            exit 1
        fi
    fi
fi

# --- Conditional kv-conductor build ---
# Priority (unchanged by the workload-shm work below):
#   1. KV_CONDUCTOR_PREBUILT env var — path to a pre-built binary
#   2. Build from source via cargo (if available)
#   3. motor/kv_conductor/bin/kv-conductor already exists (no cargo; manual copy)
#   4. Skip — wheel built without kv-conductor (optional component)
#
# Set SKIP_KV_CONDUCTOR_BUILD=1 to skip cargo build even when cargo is
# available (use the existing bin/kv-conductor, or skip if none).

echo "=== kv-conductor ==="

if [[ -n "${KV_CONDUCTOR_PREBUILT:-}" ]]; then
    # Mode 1: use user-supplied pre-built binary.
    if [[ ! -f "$KV_CONDUCTOR_PREBUILT" ]]; then
        echo "[ERROR] KV_CONDUCTOR_PREBUILT='$KV_CONDUCTOR_PREBUILT' does not exist."
        exit 1
    fi
    mkdir -p "$KV_CONDUCTOR_BIN_DIR"
    cp "$KV_CONDUCTOR_PREBUILT" "$KV_CONDUCTOR_BIN"
    chmod +x "$KV_CONDUCTOR_BIN"
    echo "kv-conductor binary ready (pre-built): $KV_CONDUCTOR_BIN"

elif command -v cargo >/dev/null 2>&1 && [[ "${SKIP_KV_CONDUCTOR_BUILD:-0}" != "1" ]]; then
    # Mode 2: build from source (always rebuilds when cargo is available).
    # zmq-sys / zeromq-src invoke cc-rs with the 'c++' tool; CI often has rustc
    # after rustup but no g++. Install or export CXX before cargo.
    echo "Building kv-conductor from source (cargo build --release)..."
    if ! motor_ensure_cxx; then
        echo "[ERROR] kv-conductor cargo build needs a C++ compiler (g++ / c++)." >&2
        echo "  Ubuntu: apt-get install -y g++   (or build-essential)" >&2
        echo "  openEuler: dnf/yum install -y gcc-c++" >&2
        echo "  Offline: SKIP_CXX_INSTALL=1 plus SKIP_KV_CONDUCTOR_BUILD=1, or KV_CONDUCTOR_PREBUILT." >&2
        exit 1
    fi
    (
        cd "$KV_CONDUCTOR_DIR" || exit 1
        cargo build --release
    )
    mkdir -p "$KV_CONDUCTOR_BIN_DIR"
    cp "$KV_CONDUCTOR_DIR/target/release/kv-conductor" "$KV_CONDUCTOR_BIN"
    chmod +x "$KV_CONDUCTOR_BIN"
    if [[ ! -x "$KV_CONDUCTOR_BIN" ]]; then
        echo "[ERROR] kv-conductor cargo build did not produce an executable at $KV_CONDUCTOR_BIN" >&2
        echo "  Need libzmq headers (Ubuntu: libzmq3-dev; openEuler: zeromq-devel) plus pkg-config." >&2
        exit 1
    fi
    echo "kv-conductor binary ready (cargo-built): $KV_CONDUCTOR_BIN"

elif [[ -f "$KV_CONDUCTOR_BIN" ]]; then
    # Mode 3: binary already in place (no cargo; e.g. manual copy or CI artifact).
    echo "kv-conductor binary ready (existing, no rebuild): $KV_CONDUCTOR_BIN"

else
    # Mode 4: no binary available — skip.
    rm -rf "$KV_CONDUCTOR_BIN_DIR"
    echo "[WARNING] kv-conductor binary not found and cargo unavailable."
    echo "  Options:"
    echo "    1. KV_CONDUCTOR_PREBUILT=/path/to/kv-conductor bash build.sh"
    echo "    2. cp /path/to/kv-conductor motor/kv_conductor/bin/ && bash build.sh"
    echo "    3. Install Rust, or run scripts/ensure_rust.sh"
    echo "  (kv-conductor is optional; the wheel will still ship without it.)"
fi

echo ""

# --- Required workload-shm (coordinator) build ---
# Priority:
#   1. WORKLOAD_SHM_PREBUILT env var — path to a pre-built .so
#   2. build from source via cargo (unless SKIP_WORKLOAD_SHM_BUILD=1)
#   3. motor/coordinator/workload_shm_rs/lib/libmindie_workload_shm.so already present
# Unlike kv-conductor this library is required: Coordinator has no Python ledger
# fallback. Missing .so is a hard build error (do not emit a wheel without it).
# SKIP_WORKLOAD_SHM_BUILD=1 only skips cargo rebuild; it does not authorize a
# wheel without the library.

echo "=== workload-shm ==="

if [[ -n "${WORKLOAD_SHM_PREBUILT:-}" ]]; then
    if [[ ! -f "$WORKLOAD_SHM_PREBUILT" ]]; then
        echo "[ERROR] WORKLOAD_SHM_PREBUILT='$WORKLOAD_SHM_PREBUILT' does not exist."
        exit 1
    fi
    mkdir -p "$WORKLOAD_SHM_LIB_DIR"
    cp "$WORKLOAD_SHM_PREBUILT" "$WORKLOAD_SHM_LIB"
    chmod +x "$WORKLOAD_SHM_LIB"
    echo "workload-shm library ready (pre-built): $WORKLOAD_SHM_LIB"

elif command -v cargo >/dev/null 2>&1 && \
    { [[ "${SKIP_WORKLOAD_SHM_BUILD:-0}" != "1" ]] || [[ ! -f "$WORKLOAD_SHM_LIB" ]]; }; then
    if [[ "${SKIP_WORKLOAD_SHM_BUILD:-0}" == "1" ]]; then
        echo "[WARNING] SKIP_WORKLOAD_SHM_BUILD=1 ignored because $WORKLOAD_SHM_LIB is missing."
    fi
    echo "Building workload-shm from source (cargo build --release)..."
    (
        cd "$WORKLOAD_SHM_DIR" || exit 1
        cargo build --release
    )
    _shm_built="$WORKLOAD_SHM_DIR/target/release/libmindie_workload_shm.so"
    if [[ ! -f "$_shm_built" ]]; then
        echo "[ERROR] refusing to emit dist/motor-*.whl: cargo build --release did not produce $_shm_built." >&2
        echo "  Coordinator cannot start without libmindie_workload_shm.so (no Python ledger fallback)." >&2
        exit 1
    fi
    mkdir -p "$WORKLOAD_SHM_LIB_DIR"
    cp "$_shm_built" "$WORKLOAD_SHM_LIB"
    chmod +x "$WORKLOAD_SHM_LIB"
    echo "workload-shm library ready (cargo-built): $WORKLOAD_SHM_LIB"

elif [[ -f "$WORKLOAD_SHM_LIB" ]]; then
    echo "workload-shm library ready (existing, no rebuild): $WORKLOAD_SHM_LIB"

else
    echo "[ERROR] refusing to emit dist/motor-*.whl: libmindie_workload_shm.so is missing and cargo is unavailable." >&2
    echo "  Coordinator cannot start without this library (no Python ledger fallback)." >&2
    echo "  Options:" >&2
    echo "    1. WORKLOAD_SHM_PREBUILT=/path/to/libmindie_workload_shm.so bash build.sh" >&2
    echo "    2. cp /path/to/libmindie_workload_shm.so $WORKLOAD_SHM_LIB_DIR/ && bash build.sh" >&2
    echo "    3. Unset SKIP_RUST_INSTALL and retry (build.sh installs rustup), or install cargo on PATH" >&2
    echo "  SKIP_RUST_BUILD=1 / SKIP_WORKLOAD_SHM_BUILD=1 only reuse an existing .so; they do not" >&2
    echo "  authorize a first-time build without one." >&2
    exit 1
fi

if [[ ! -f "$WORKLOAD_SHM_LIB" ]]; then
    echo "[ERROR] refusing to emit dist/motor-*.whl: $WORKLOAD_SHM_LIB is missing after the workload-shm build step." >&2
    echo "  cargo/prebuilt must produce libmindie_workload_shm.so before pip wheel." >&2
    echo "  Coordinator cannot start without this library (no Python ledger fallback)." >&2
    exit 1
fi

echo ""

echo "Building wheel package with pip wheel (PEP517)... (VERBOSE=${VERBOSE})"

# Default index stays tuna (master). Override when that host returns 403, e.g.
#   PIP_INDEX_URL=https://repo.huaweicloud.com/repository/pypi/simple
# Isolation still downloads setuptools from the index; if that fails, retry
# --no-build-isolation (needs setuptools/wheel already installed).
PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"
if [[ -z "${PIP_TRUSTED_HOST:-}" ]]; then
    _pip_host="${PIP_INDEX_URL#*://}"
    PIP_TRUSTED_HOST="${_pip_host%%/*}"
fi
echo "pip wheel index: ${PIP_INDEX_URL} (trusted-host=${PIP_TRUSTED_HOST})"

motor_pip_wheel() {
    local cmd=(python -m pip wheel . --no-deps --use-pep517 -w dist
        -i "${PIP_INDEX_URL}" --trusted-host "${PIP_TRUSTED_HOST}")
    if [[ "${1:-}" == "no-isolation" ]]; then
        cmd+=(--no-build-isolation)
    fi
    if [[ "${VERBOSE}" -eq 0 ]]; then
        cmd+=(-q)
    fi
    "${cmd[@]}"
}

rm -rf dist/
mkdir -p dist
if ! motor_pip_wheel isolation; then
    echo "[WARNING] pep517 isolation failed (mirror 403/unreachable). Retrying with --no-build-isolation."
    motor_pip_wheel no-isolation
fi

# Prefer the newest file so a leftover motor-*.whl cannot steal the gate.
WHEEL_PATH="$(ls -t dist/motor-*.whl 2>/dev/null | head -n1 || true)"
if [[ -z "${WHEEL_PATH}" || ! -f "${WHEEL_PATH}" ]]; then
    echo "[ERROR] pip wheel did not produce dist/motor-*.whl" >&2
    exit 1
fi
_wheel_count="$(ls -1 dist/motor-*.whl 2>/dev/null | wc -l | tr -d ' ')"
if [[ "${_wheel_count}" -gt 1 ]]; then
    echo "[WARNING] dist/ contains ${_wheel_count} motor-*.whl files; gating the newest: ${WHEEL_PATH}" >&2
fi
if ! PYTHONPATH="$(pwd)${PYTHONPATH:+:${PYTHONPATH}}" python -c \
    "from motor.coordinator.workload_shm_rs.wheel_gate import assert_motor_wheel_has_workload_shm; assert_motor_wheel_has_workload_shm(r'''${WHEEL_PATH}''')"
then
    echo "[ERROR] refusing to keep ${WHEEL_PATH}: archive is missing libmindie_workload_shm.so." >&2
    echo "  Coordinator cannot start without this library (no Python ledger fallback)." >&2
    rm -f "${WHEEL_PATH}"
    exit 1
fi
if [[ -f "$KV_CONDUCTOR_BIN" ]]; then
    if ! PYTHONPATH="$(pwd)${PYTHONPATH:+:${PYTHONPATH}}" python -c \
        "from motor.coordinator.workload_shm_rs.wheel_gate import assert_motor_wheel_has_kv_conductor; assert_motor_wheel_has_kv_conductor(r'''${WHEEL_PATH}''')"
    then
        echo "[ERROR] refusing to keep ${WHEEL_PATH}: kv-conductor was built but is missing from the archive." >&2
        rm -f "${WHEEL_PATH}"
        exit 1
    fi
    echo "wheel kv-conductor verified: ${WHEEL_PATH}"
fi
echo "wheel native lib verified: ${WHEEL_PATH}"
