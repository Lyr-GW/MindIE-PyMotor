# Copyright (c) Huawei Technologies Co., Ltd. 2025-2026. All rights reserved.
# MindIE is licensed under Mulan PSL v2.
# You can use this software according to the terms and conditions of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
#         http://license.coscl.org.cn/MulanPSL2
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the Mulan PSL v2 for more details.

import os
from pathlib import Path
import subprocess

import pytest


SCRIPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "examples"
    / "deployer"
    / "startup"
    / "roles"
    / "kv_store_backends"
    / "mooncake"
    / "mooncake.sh"
)


@pytest.mark.parametrize(
    ("pod_ip", "expected_address"),
    [
        ("10.0.0.8", "0.0.0.0"),
        ("2001:db8::8", "::"),
    ],
)
def test_mooncake_master_selects_rpc_address_from_pod_ip(tmp_path, pod_ip, expected_address):
    fake_master = tmp_path / "mooncake_master"
    fake_master.write_text("#!/bin/bash\nprintf '%s\\n' \"$@\"\n", encoding="utf-8")
    fake_master.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "POD_IP": pod_ip,
        "KV_CACHE_STORE_PORT": "50088",
        "KV_STORE_EVICTION_HIGH_WATERMARK_RATIO": "0.9",
        "KV_STORE_EVICTION_RATIO": "0.1",
        "DEFAULT_KV_LEASE_TTL": "11000",
    }

    result = subprocess.run(
        ["bash", str(SCRIPT_PATH)],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    args = result.stdout.splitlines()
    assert args[:4] == ["--rpc_port", "50088", "--rpc_address", expected_address]
    assert "--port" not in args


def test_mooncake_master_allows_rpc_address_override(tmp_path):
    fake_master = tmp_path / "mooncake_master"
    fake_master.write_text("#!/bin/bash\nprintf '%s\\n' \"$@\"\n", encoding="utf-8")
    fake_master.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "POD_IP": "2001:db8::8",
        "MOONCAKE_MASTER_RPC_ADDRESS": "2001:db8::9",
        "KV_CACHE_STORE_PORT": "50088",
        "KV_STORE_EVICTION_HIGH_WATERMARK_RATIO": "0.9",
        "KV_STORE_EVICTION_RATIO": "0.1",
        "DEFAULT_KV_LEASE_TTL": "11000",
    }

    result = subprocess.run(
        ["bash", str(SCRIPT_PATH)],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    args = result.stdout.splitlines()
    assert args[args.index("--rpc_address") + 1] == "2001:db8::9"
