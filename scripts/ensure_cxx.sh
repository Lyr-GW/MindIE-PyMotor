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

# Locate or install a C++ compiler for kv-conductor (zmq-sys / zeromq-src).
# Source from build.sh (same shell) so CXX / PATH changes persist.
# Set SKIP_CXX_INSTALL=1 to disable package-manager install (offline / locked CI).

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
        export CXX
        CXX="$(command -v g++)"
    elif command -v clang++ >/dev/null 2>&1; then
        export CXX
        CXX="$(command -v clang++)"
    fi
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
        motor_export_cxx
        _motor_cxx_ver="$(${CXX} --version 2>/dev/null || true)"
        echo "c++ ready: ${CXX} (${_motor_cxx_ver%%$'\n'*})"
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
    motor_export_cxx
    _motor_cxx_ver="$(${CXX} --version 2>/dev/null || true)"
    echo "c++ ready: ${CXX} (${_motor_cxx_ver%%$'\n'*})"
    return 0
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    set -euo pipefail
    motor_ensure_cxx
fi
