# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
# MindIE is licensed under Mulan PSL v2.
# You can use this software according to the terms and conditions of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
#         http://license.coscl.org.cn/MulanPSL2
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the Mulan PSL v2 for more details.

import importlib.util
import sys
from argparse import Namespace
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[3] / "examples/features/observability/stack/scripts/discover-targets.py"
SPEC = importlib.util.spec_from_file_location("discover_targets", SCRIPT_PATH)
DISCOVER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = DISCOVER
SPEC.loader.exec_module(DISCOVER)
LOAD_SCRIPT_PATH = SCRIPT_PATH.with_name("simulate-business-load.py")
LOAD_SPEC = importlib.util.spec_from_file_location("simulate_business_load", LOAD_SCRIPT_PATH)
LOAD = importlib.util.module_from_spec(LOAD_SPEC)
assert LOAD_SPEC.loader is not None
sys.modules[LOAD_SPEC.name] = LOAD
LOAD_SPEC.loader.exec_module(LOAD)


def _service(name="mindie-motor-kvs-master", ip="10.0.0.7", ports=None):
    return {
        "metadata": {"name": name, "namespace": "chosen-ns"},
        "spec": {"clusterIP": ip, "ports": ports if ports is not None else [{"name": "metrics", "port": 50090}]},
    }


def test_pool_target_uses_selected_namespace_labels():
    pool = DISCOVER._discover_pool_target([_service()], "chosen-ns")

    result = DISCOVER.DiscoveryResult(
        namespace="chosen-ns",
        node_ip="127.0.0.1",
        obs_host="localhost",
        mode="kubernetes",
        runtime="native",
        coordinator_target="127.0.0.1:1027",
        coordinator_pod_name="",
        coordinator_is_primary=False,
        engine_targets=[],
        pool_targets=[
            {
                "target": "10.0.0.17:50090",
                "labels": {"cluster": "chosen-ns", "motor_component": "kv_pool", "pool_service": pool["name"]},
            }
        ],
        port_forwards=[],
        warnings=[],
    )
    config = DISCOVER._build_prometheus_config(result)

    assert "job_name: motor-kv-pool" in config
    assert "cluster: chosen-ns" in config
    assert "motor_component: kv_pool" in config
    assert "pool_service: mindie-motor-kvs-master" in config


def test_docker_pool_target_uses_host_gateway_and_forward_spec(monkeypatch):
    monkeypatch.setattr(DISCOVER, "_is_kubectl_ready", lambda: True)

    def _kubectl_json(args):
        if "svc" in args:
            return {"items": [_service()]}
        if "endpoints" in args:
            return {
                "subsets": [
                    {
                        "addresses": [{"ip": "10.0.0.17", "targetRef": {"name": "pool-pod-0"}}],
                        "ports": [{"name": "metrics", "port": 50090}],
                    }
                ]
            }
        return {"items": []}

    monkeypatch.setattr(DISCOVER, "_run_kubectl_json", _kubectl_json)
    monkeypatch.setattr(DISCOVER, "_discover_coordinator_pod", lambda namespace: None)
    monkeypatch.setattr(DISCOVER, "_discover_engine_targets_from_services", lambda **kwargs: [])
    monkeypatch.setattr(DISCOVER, "_discover_engine_targets_from_pods", lambda **kwargs: [])

    def _add_existing_forward(result, base_port):
        result.port_forwards.append(
            DISCOVER.PortForwardSpec("chosen-ns", "10.0.0.2", 1027, base_port, "coordinator-pod")
        )

    monkeypatch.setattr(DISCOVER, "_apply_docker_gateway", _add_existing_forward)
    args = Namespace(
        namespace="chosen-ns",
        runtime="docker",
        obs_host=None,
        engine_business_port=10000,
        port_forward_base=19100,
        node_ip="127.0.0.1",
    )

    discovered = DISCOVER._discover("chosen-ns", "127.0.0.1", args)

    assert discovered.pool_targets[0]["target"] == "host.docker.internal:19101"
    assert discovered.port_forwards[-1].to_env_value() == "chosen-ns|10.0.0.17|50090|19101|pool-pod-0"


def test_missing_pool_service_creates_no_pool_target():
    assert DISCOVER._discover_pool_target([], "chosen-ns") is None
    assert DISCOVER._discover_pool_target([_service(ports=[])], "chosen-ns") is None


def test_multiple_pool_services_fail_closed():
    with pytest.raises(RuntimeError, match="multiple KV pool services"):
        DISCOVER._discover_pool_target([_service(), _service("mindie-motor-kvs-master-blue", "10.0.0.8")], "chosen-ns")


def test_ipv6_pool_endpoint_is_bracketed(monkeypatch):
    monkeypatch.setattr(
        DISCOVER,
        "_run_kubectl_json",
        lambda args: {
            "subsets": [
                {
                    "addresses": [{"ip": "2001:db8::8", "targetRef": {"name": "pool-v6"}}],
                    "ports": [{"name": "metrics", "port": 50090}],
                }
            ]
        },
    )

    endpoints = DISCOVER._discover_pool_endpoints("mindie-motor-kvs-master", "chosen-ns")

    assert endpoints[0]["target"] == "[2001:db8::8]:50090"


def test_unique_prefix_token_precedes_repeated_prompt():
    prompt = LOAD._build_prompt("shared prompt", unique_prefixes=True)

    assert prompt.startswith("Request token: ")
    assert prompt.endswith("\nshared prompt")
