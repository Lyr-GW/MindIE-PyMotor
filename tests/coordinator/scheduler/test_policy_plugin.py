# Copyright (c) Huawei Technologies Co., Ltd. 2025-2026. All rights reserved.
# MindIE is licensed under Mulan PSL v2.
# You can use this software according to the terms and conditions of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
#         http://license.coscl.org.cn/MulanPSL2
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the Mulan PSL v2 for more details.

"""Real entry-point/subprocess execution and scheduler allocation regression coverage."""

import asyncio
import json
import os
import time
from dataclasses import replace
from unittest.mock import AsyncMock, Mock

import pytest

from motor.common.resources.endpoint import Endpoint, Workload, WorkloadAction
from motor.common.resources.instance import Instance, PDRole
from motor.config.coordinator import CoordinatorConfig, PolicyPluginConfig
from motor.coordinator.models.request import RequestInfo
from motor.coordinator.domain.scheduling import UpdateWorkloadParams
from motor.coordinator.scheduler.policy.api import CandidateId, CandidateSnapshot, RequestContext, SelectionInput
from motor.coordinator.scheduler.policy.plugin_runner import PolicyRunner
from motor.coordinator.scheduler.runtime.scheduler_client import AsyncSchedulerClient, SchedulerClientConfig
from motor.coordinator.scheduler.runtime.workload_shm.native import STATUS_BLOCKED, STATUS_CHANGED, STATUS_OK


@pytest.fixture
def plugin_distribution(tmp_path, monkeypatch):
    """A real installed-distribution layout discovered by the child interpreter."""
    (tmp_path / "customer_policy.py").write_text(
        '''
import os
import time
from motor.coordinator.scheduler.policy.api import EndpointSelectionPolicy, RankedCandidate

class Policy(EndpointSelectionPolicy):
    def __init__(self, options=None):
        super().__init__(options)
        print("constructor output is not protocol data")
        if self.options.get("startup_hang"):
            time.sleep(60)

    def rank(self, selection):
        mode = self.options.get("mode")
        if mode == "error" or self.options.get("error_role") == selection.request.role:
            raise RuntimeError("customer failure")
        if mode == "hang" or self.options.get("hang_role") == selection.request.role:
            time.sleep(60)
        if mode == "exit":
            os._exit(3)
        if mode == "empty":
            return []
        if mode == "invalid":
            return [RankedCandidate(selection.candidates[0].id, float("nan"))]
        candidates = sorted(selection.candidates, key=lambda c: c.active_tokens, reverse=mode != "light")
        return [RankedCandidate(c.id, -c.active_tokens) for c in candidates]
''',
        encoding="utf-8",
    )
    metadata = tmp_path / "customer_policy-0.1.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text("Name: customer-policy\nVersion: 0.1\n", encoding="utf-8")
    (metadata / "entry_points.txt").write_text(
        "[mindie_motor.scheduling_policies]\ncustomer.test = customer_policy:Policy\n", encoding="utf-8"
    )
    monkeypatch.setenv("PYTHONPATH", str(tmp_path) + os.pathsep + os.environ.get("PYTHONPATH", ""))
    return PolicyPluginConfig(role=["prefill"], name="customer.test", timeout_ms=100, startup_timeout_ms=3000)


def selection():
    return SelectionInput(
        request=RequestContext("req", "prefill", "model", 10, 20),
        candidates=(
            CandidateSnapshot(CandidateId(1, 0), 2.0, 2.0, "node1", "vllm"),
            CandidateSnapshot(CandidateId(2, 0), 9.0, 9.0, "node2", "vllm"),
        ),
        excluded=frozenset(),
        attempt=0,
    )


@pytest.mark.asyncio
async def test_real_entry_point_ranks_and_shutdown_reaps_child(plugin_distribution):
    runner = PolicyRunner(plugin_distribution)
    try:
        await runner.start()
        process = runner._process
        assert process is not None
        ranked = await runner.rank(selection())
        assert [item.id.instance_id for item in ranked] == [2, 1]
        assert 'motor_policy_loads_total{policy="customer.test",role="prefill"} 1' in runner.metrics_text()
    finally:
        await runner.close()
    assert process.returncode is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["error", "hang", "exit", "empty", "invalid"])
async def test_repeated_plugin_failure_is_bounded_and_cools_down(plugin_distribution, mode):
    runner = PolicyRunner(replace(plugin_distribution, options={"mode": mode}))
    try:
        await runner.start()
        process = runner._process
        started = time.monotonic()
        assert await runner.rank(selection()) is None
        for _ in range(20):
            assert await runner.rank(selection()) is None
        assert time.monotonic() - started < 2
        assert process.returncode is not None
        assert runner._counts["calls"] == 1
        assert runner._counts["fallbacks"] == 21
        assert runner._counts["timeouts"] == (1 if mode == "hang" else 0)
    finally:
        await runner.close()


@pytest.mark.asyncio
async def test_missing_and_hung_loader_fall_back(plugin_distribution):
    for spec in (
        replace(plugin_distribution, name="missing"),
        replace(plugin_distribution, options={"startup_hang": True}, startup_timeout_ms=300),
    ):
        runner = PolicyRunner(spec)
        try:
            await runner.start()
            assert runner._process is None
            assert await runner.rank(selection()) is None
            assert runner._counts["load_errors"] == 1
        finally:
            await runner.close()


@pytest.mark.asyncio
async def test_busy_call_falls_back_and_cancellation_discards_late_reply(plugin_distribution):
    runner = PolicyRunner(replace(plugin_distribution, options={"mode": "hang"}, timeout_ms=10000))
    await runner.start()
    process = runner._process
    task = asyncio.create_task(runner.rank(selection()))
    try:
        while not runner._lock.locked():
            await asyncio.sleep(0)
        assert await runner.rank(selection()) is None
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert process.returncode is not None
        runner.config = plugin_distribution
        await runner.start()
        assert (await runner.rank(selection()))[0].id.instance_id == 2
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await runner.close()


@pytest.mark.parametrize(
    "raw",
    [
        [],
        [{"id": {"instance_id": 99, "endpoint_id": 0}, "score": 1}],
        [{"id": {"instance_id": 1, "endpoint_id": 0}, "score": float("inf")}],
        [{"id": {"instance_id": 1, "endpoint_id": 0}, "score": True}],
        [{"id": {"instance_id": 1, "endpoint_id": 0}, "score": 1}] * 2,
    ],
)
def test_invalid_plugin_ranking_is_rejected(raw):
    with pytest.raises((TypeError, ValueError)):
        PolicyRunner._validate({"ranked": raw}, selection())


@pytest.mark.parametrize(
    "options",
    [
        {"options": []},
        {"timeout_ms": 0},
        {"timeout_ms": True},
        {"role": ["invalid"]},
        {"startup_timeout_ms": -1},
        {"cooldown_seconds": float("nan")},
    ],
)
def test_plugin_configuration_rejects_invalid_values(options):
    with pytest.raises(ValueError):
        PolicyPluginConfig(**{"role": ["prefill"], "name": "customer.test", **options}).validate()


def test_plugin_config_json_and_existing_config_defaults(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "motor_coordinator_config": {
                    "scheduler_config": {
                        "scheduler_type": "round_robin",
                        "policy_plugin": [{"name": "customer.test", "role": ["decode"], "options": {"weight": 2}}],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    config = CoordinatorConfig.from_json(str(path))
    assert config.scheduler_config.policy_plugin[0].name == "customer.test"
    assert config.scheduler_config.policy_plugin[0].options == {"weight": 2}
    assert config.scheduler_config.prefill_scheduler_type.value == "round_robin"
    assert CoordinatorConfig().scheduler_config.policy_plugin == []


@pytest.mark.parametrize(
    "plugins, message",
    [
        ([{"name": "x", "role": "prefill"}], "role must be a non-empty list"),
        ([{"name": "x"}], "role is required"),
        ([{"role": ["prefill"]}], "name is required"),
        ([{"role": ["prefill"], "name": "x", "roles": ["decode"]}], "unknown key"),
        (None, "must be a list"),
        (["x"], "must be an object"),
        ([{"role": [], "name": "x"}], "non-empty list"),
        ([{"role": ["prefill"], "name": " "}], "non-empty string"),
        ([{"role": ["prefill", "prefill"], "name": "x"}], "unique roles"),
        ([{"role": ["prefill"], "name": "x"}, {"role": ["prefill", "decode"], "name": "y"}], "duplicates role"),
    ],
)
def test_role_plugin_schema_rejects_invalid_entries(plugins, message):
    from motor.config.coordinator import normalize_policy_plugins

    with pytest.raises(ValueError, match=message):
        normalize_policy_plugins(plugins)


def test_role_plugin_schema_rejects_legacy_object_and_normalizes_dicts():
    from motor.config.coordinator import normalize_policy_plugins

    with pytest.raises(ValueError, match="old object/roles schema"):
        normalize_policy_plugins({"name": "x", "roles": ["decode"]})
    normalized = normalize_policy_plugins([{"role": ["prefill", "decode"], "name": "x"}])
    assert normalized[0].role == ["prefill", "decode"]


@pytest.mark.parametrize(
    "plugins, message",
    [
        ({"name": "x", "roles": ["decode"]}, "old object/roles schema"),
        (None, "must be a list"),
        ([{"role": ["prefill"]}, {"role": ["prefill"], "name": "x"}], r"policy_plugin\[0\].name is required"),
        ([{"role": ["prefill"], "name": "x"}, {"role": ["decode"], "name": "x"}], None),
    ],
)
def test_from_json_preserves_role_plugin_validation(tmp_path, plugins, message):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"scheduler_config": {"policy_plugin": plugins}}), encoding="utf-8")
    if message is None:
        loaded = CoordinatorConfig.from_json(str(path))
        assert [plugin.role for plugin in loaded.scheduler_config.policy_plugin] == [["prefill"], ["decode"]]
    else:
        with pytest.raises(ValueError, match=message):
            CoordinatorConfig.from_json(str(path))


def test_same_name_role_configs_get_independent_runners(plugin_distribution):
    prefill = replace(plugin_distribution, role=["prefill"], options={"mode": "error"})
    decode = replace(plugin_distribution, role=["decode"], options={"mode": "empty"})
    client = AsyncSchedulerClient(SchedulerClientConfig(policy_plugin=[prefill, decode]))
    assert client._policy_runners["prefill"] is not client._policy_runners["decode"]
    assert client._policy_runners["prefill"].config.options == {"mode": "error"}
    assert client._policy_runners["decode"].config.options == {"mode": "empty"}
    metrics = client.policy_metrics_text()
    assert metrics.count("# TYPE motor_policy_calls_total counter") == 1
    assert 'policy="customer.test",role="prefill"' in metrics
    assert 'policy="customer.test",role="decode"' in metrics
    families = metrics.split("# TYPE ")[1:]
    assert len(families) == 7
    for family in families:
        assert 'role="prefill"' in family
        assert 'role="decode"' in family


@pytest.mark.asyncio
@pytest.mark.parametrize("failing_role", ["prefill", "decode"])
@pytest.mark.parametrize("failure", ["error", "hang", "busy"])
async def test_shared_config_keeps_other_role_healthy_and_reaps_all_children(
    plugin_distribution, failing_role, failure
):
    """A shared item must isolate faults, cooldown and lock contention by actual role."""
    spec = replace(
        plugin_distribution,
        role=["prefill", "decode"],
        options={failure + "_role": failing_role},
    )
    client, _, request = await scheduler_with_pool(spec)
    instances = [
        Instance(
            id=i,
            job_name="decode-%s" % i,
            model_name="model",
            role="decode",
            engine_type="vllm",
            endpoints={
                "pod": {
                    0: Endpoint(
                        id=0, ip="127.0.0.1", business_port="8080", workload=Workload(active_tokens=float(i * 10))
                    )
                }
            },
        )
        for i in (3, 4)
    ]
    await client._cache.replace_all(PDRole.ROLE_D, instances)
    client.get_available_instances = AsyncMock(
        side_effect=lambda role: {instance.id: instance for instance in client._cache.get_instances(role)}
    )
    processes = []
    faulty = client._policy_runners[failing_role]
    healthy_role = "decode" if failing_role == "prefill" else "prefill"
    healthy = client._policy_runners[healthy_role]
    try:
        await asyncio.gather(*(runner.start() for runner in client._policy_runners.values()))
        processes = [runner._process for runner in client._policy_runners.values()]
        assert all(process is not None for process in processes)
        assert processes[0].pid != processes[1].pid
        if failure == "busy":
            await faulty._lock.acquire()
        for attempt in range(2):
            prefill, decode = await asyncio.gather(
                client.select_and_allocate(PDRole.ROLE_P, request),
                client.select_and_allocate(PDRole.ROLE_D, request),
            )
            assert prefill is not None and decode is not None
            if attempt == 0:
                assert prefill[0].id == (1 if failing_role == "prefill" else 2)
                assert decode[0].id == (3 if failing_role == "decode" else 4)
            assert (decode if healthy_role == "decode" else prefill)[0].id == (4 if healthy_role == "decode" else 2)
        assert faulty._counts["fallbacks"] == 2
        assert healthy._counts["calls"] == 2
        assert healthy._counts["fallbacks"] == 0
        assert healthy._retry_after == 0
        if failure != "busy":
            assert faulty._counts["timeouts" if failure == "hang" else "errors"] == 1
    finally:
        if faulty._lock.locked():
            faulty._lock.release()
        await client.disconnect()
    assert all(process.returncode is not None for process in processes)


@pytest.mark.asyncio
async def test_prefill_and_decode_use_their_own_plugin_options(plugin_distribution):
    prefill = replace(plugin_distribution, role=["prefill"], options={})
    decode = replace(plugin_distribution, role=["decode"], options={"mode": "light"})
    client, native, request = await scheduler_with_pool([prefill, decode])
    decode_instances = [
        Instance(
            id=i,
            job_name="decode-%s" % i,
            model_name="model",
            role="decode",
            engine_type="vllm",
            endpoints={
                "pod": {
                    0: Endpoint(
                        id=0, ip="127.0.0.1", business_port="8080", workload=Workload(active_tokens=float(i * 10))
                    )
                }
            },
        )
        for i in (3, 4)
    ]
    await client._cache.replace_all(PDRole.ROLE_D, decode_instances)
    try:
        await asyncio.gather(*(runner.start() for runner in client._policy_runners.values()))
        prefill_result = await client.select_and_allocate(PDRole.ROLE_P, request)
        decode_result = await client.select_and_allocate(PDRole.ROLE_D, request)
        assert prefill_result[0].id == 2
        assert decode_result[0].id == 3
        assert client._policy_runners["prefill"]._counts["calls"] == 1
        assert client._policy_runners["decode"]._counts["calls"] == 1
    finally:
        await client.disconnect()


async def scheduler_with_pool(spec=None, scheduler_type="load_balance"):
    plugin_configs = spec if isinstance(spec, list) else [spec] if spec else []
    client = AsyncSchedulerClient(SchedulerClientConfig(scheduler_type=scheduler_type, policy_plugin=plugin_configs))
    instances = [
        Instance(
            id=i,
            job_name="job-%s" % i,
            model_name="model",
            role="prefill",
            engine_type="vllm",
            endpoints={
                "pod": {
                    0: Endpoint(
                        id=0, ip="127.0.0.1", business_port="8080", workload=Workload(active_tokens=float(i * 10))
                    )
                }
            },
        )
        for i in (1, 2)
    ]
    await client._cache.replace_all(PDRole.ROLE_P, instances)
    client._refresh_cache_from_workload_reader = AsyncMock()
    client.get_available_instances = AsyncMock(return_value={i.id: i for i in instances})
    native = Mock()
    native.cas_add.side_effect = lambda *args, **kwargs: (STATUS_OK, args[3] + args[4])
    client._workload_reader = Mock(native=native)
    client._workload_reader.entry_meta.return_value = {"generation": 1, "slot": 0, "flags": 2}
    request = RequestInfo(
        req_id="test", req_data={"model": "model"}, req_len=10, api="v1/chat/completions", token_ids=list(range(10))
    )
    return client, native, request


@pytest.mark.asyncio
async def test_plugin_selection_commits_and_releases_through_core(plugin_distribution):
    client, native, request = await scheduler_with_pool(plugin_distribution)
    try:
        await client._policy_runners["prefill"].start()
        result = await client.select_and_allocate(PDRole.ROLE_P, request)
        assert result[0].id == 2  # Plugin deliberately chooses the heavier endpoint.
        assert native.cas_add.call_args.args[:2] == (2, 0)
        assert native.cas_add.call_args.args[3] == 20.0
        assert result[2].active_tokens > 0
        native.cas_sub_floor0.return_value = (STATUS_OK, 20.0)
        assert await client.update_workload(
            UpdateWorkloadParams(
                instance_id=2,
                endpoint_id=0,
                role=PDRole.ROLE_P,
                req_id=request.req_id,
                workload_action=WorkloadAction.RELEASE_TOKENS,
                workload_change=result[2],
            )
        )
        assert native.cas_sub_floor0.call_args.args[3] == result[2].active_tokens
    finally:
        await client.disconnect()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["error", "hang", "exit"])
async def test_plugin_faults_keep_allocating_with_configured_builtin(plugin_distribution, mode):
    spec = replace(plugin_distribution, options={"mode": mode})
    client, native, request = await scheduler_with_pool(spec)
    try:
        await client._policy_runners["prefill"].start()
        for _ in range(5):
            result = await client.select_and_allocate(PDRole.ROLE_P, request)
            assert result is not None
        assert native.cas_add.call_count == 5
        assert client._policy_runners["prefill"]._counts["calls"] == 1
    finally:
        await client.disconnect()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [STATUS_CHANGED, STATUS_BLOCKED])
async def test_cas_conflicts_reinvoke_plugin_with_fresh_snapshot(plugin_distribution, status):
    client, native, request = await scheduler_with_pool(plugin_distribution)
    calls = []

    def allocate(*args, **_kwargs):
        calls.append(args)
        if len(calls) == 1:
            endpoint = client._cache.get_instances(PDRole.ROLE_P)[0].get_all_endpoints()[0]
            endpoint.workload.active_tokens = 50
            return status, 999
        return STATUS_OK, args[3] + args[4]

    native.cas_add.side_effect = allocate
    try:
        await client._policy_runners["prefill"].start()
        result = await client.select_and_allocate(PDRole.ROLE_P, request)
        assert result[0].id == 1
        assert [args[0] for args in calls] == [2, 1]
        assert client._policy_runners["prefill"]._counts["calls"] == 2
    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_pins_and_role_scope_preserve_core_selection(plugin_distribution):
    decode_plugin = replace(plugin_distribution, role=["decode"])
    client, native, request = await scheduler_with_pool([decode_plugin])
    try:
        await client._policy_runners["decode"].start()
        result = await client.select_and_allocate(PDRole.ROLE_P, request, target_instance_id=1)
        assert result[0].id == 1
        assert client._policy_runners["decode"]._counts["calls"] == 0
        result = await client.select_and_allocate(PDRole.ROLE_P, request)
        assert result is not None
        assert client._policy_runners["decode"]._counts["calls"] == 0
    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_plugin_uses_decision_snapshot_for_cas_expected(plugin_distribution):
    from motor.coordinator.scheduler.policy.api import RankedCandidate

    client, native, request = await scheduler_with_pool(plugin_distribution)

    async def rank_and_concurrent_update(snapshot):
        endpoint = client._cache.get_instances(PDRole.ROLE_P)[1].get_all_endpoints()[0]
        endpoint.workload.active_tokens = 123
        return (RankedCandidate(CandidateId(2, 0), -20.0),)

    client._policy_runners["prefill"].rank = AsyncMock(side_effect=rank_and_concurrent_update)
    try:
        assert await client.select_and_allocate(PDRole.ROLE_P, request) is not None
        assert native.cas_add.call_args.args[3] == 20.0
    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_snapshot_failure_and_retry_exhaustion_use_builtin(plugin_distribution):
    client, native, request = await scheduler_with_pool(plugin_distribution)
    try:
        client._rank_external_policy = AsyncMock(side_effect=RuntimeError("snapshot failure"))
        assert await client.select_and_allocate(PDRole.ROLE_P, request) is not None
        assert client._policy_runners["prefill"]._counts["fallbacks"] == 1
    finally:
        await client.disconnect()

    client, native, request = await scheduler_with_pool(plugin_distribution)
    try:
        await client._policy_runners["prefill"].start()
        native.cas_add.side_effect = [
            (STATUS_CHANGED, 0),
            (STATUS_CHANGED, 0),
            (STATUS_CHANGED, 0),
            (STATUS_OK, 30),
        ]
        assert await client.select_and_allocate(PDRole.ROLE_P, request) is not None
        assert client._policy_runners["prefill"]._counts["calls"] == 3
        assert client._policy_runners["prefill"]._counts["fallbacks"] == 1
    finally:
        await client.disconnect()


@pytest.mark.asyncio
@pytest.mark.parametrize("strategy", ["round_robin", "load_balance", "kv_cache_affinity", "dynamic_bucket"])
async def test_disabled_plugin_keeps_builtin_allocations(strategy):
    client, native, request = await scheduler_with_pool(scheduler_type=strategy)
    try:
        assert client._policy_runners == {}
        result = await client.select_and_allocate(PDRole.ROLE_P, request)
        assert result is not None
        assert result[2].active_tokens == (0 if strategy == "round_robin" else 10)
    finally:
        await client.disconnect()


def test_only_inference_workers_receive_plugin_config(plugin_distribution):
    from motor.coordinator.scheduler.runtime.scheduler_connection_manager import SchedulerConnectionManager

    config = CoordinatorConfig()
    config.scheduler_config.policy_plugin = [plugin_distribution]
    assert SchedulerConnectionManager.from_config(config)._client._policy_runners == {}
    config.worker_index = 0
    assert (
        SchedulerConnectionManager.from_config(config)._client._policy_runners["prefill"].config == plugin_distribution
    )


def test_worker_metaserver_exposes_plugin_metrics(plugin_distribution):
    from fastapi.testclient import TestClient
    from motor.coordinator.api_server.inference_server import InferenceServer

    runner = PolicyRunner(plugin_distribution)
    client = AsyncSchedulerClient(SchedulerClientConfig())
    client._policy_runners["prefill"] = runner
    server = InferenceServer.__new__(InferenceServer)
    server._get_scheduler_client = lambda: client
    with TestClient(server.create_metaserver_app()) as http:
        response = http.get("/metrics")
        assert response.status_code == 200
        assert 'motor_policy_calls_total{policy="customer.test",role="prefill"} 0' in response.text


def test_loader_only_imports_selected_entry_point(monkeypatch):
    from types import SimpleNamespace
    from motor.coordinator.scheduler.policy.api import EndpointSelectionPolicy
    from motor.coordinator.scheduler.policy.plugin_worker import load_policy

    class Policy(EndpointSelectionPolicy):
        def rank(self, selection):
            return []

    chosen = SimpleNamespace(name="chosen", value="pkg:Policy", dist=None, load=Mock(return_value=Policy))
    other = SimpleNamespace(name="other", load=Mock(side_effect=RuntimeError("must not import")))
    monkeypatch.setattr(
        "motor.coordinator.scheduler.policy.plugin_worker.entry_points", lambda **kwargs: [chosen, other]
    )
    assert isinstance(load_policy("chosen", {}), Policy)
    other.load.assert_not_called()
    with pytest.raises(ValueError, match="exactly one"):
        load_policy("missing", {})
    Policy.api_version = 1
    with pytest.raises(ValueError, match="API version"):
        load_policy("chosen", {})


def test_loader_requires_concrete_synchronous_rank_and_loads_legacy_plugins(monkeypatch):
    from types import SimpleNamespace

    from motor.coordinator.scheduler.policy.api import EndpointSelectionPolicy, LoadBalancingPolicy
    from motor.coordinator.scheduler.policy.plugin_worker import load_policy

    class MissingRank(EndpointSelectionPolicy):
        pass

    class AsyncRank(EndpointSelectionPolicy):
        async def rank(self, selection):  # pylint: disable=invalid-overridden-method
            return []

    class LegacyPolicy(LoadBalancingPolicy):
        def rank(self, selection):
            return []

    entry = SimpleNamespace(name="chosen", value="pkg:Policy", dist=None, load=Mock())
    monkeypatch.setattr("motor.coordinator.scheduler.policy.plugin_worker.entry_points", lambda **kwargs: [entry])
    for invalid in (MissingRank, AsyncRank):
        entry.load.return_value = invalid
        with pytest.raises(ValueError, match=r"must override synchronous rank"):
            load_policy("chosen", {})
    entry.load.return_value = LegacyPolicy
    assert isinstance(load_policy("chosen", {}), EndpointSelectionPolicy)


@pytest.mark.asyncio
async def test_shutdown_interrupts_busy_plugin_and_cooldown_recovers(plugin_distribution):
    runner = PolicyRunner(replace(plugin_distribution, options={"mode": "hang"}, timeout_ms=60000))
    await runner.start()
    task = asyncio.create_task(runner.rank(selection()))
    try:
        while not runner._lock.locked():
            await asyncio.sleep(0)
        await asyncio.wait_for(runner.close(), timeout=2)
        assert await task is None
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await runner.close()

    runner = PolicyRunner(replace(plugin_distribution, options={"mode": "error"}))
    try:
        await runner.start()
        assert await runner.rank(selection()) is None
        runner.config = plugin_distribution
        runner._retry_after = 0
        assert await runner.rank(selection()) is None
        await runner._restart_task
        assert (await runner.rank(selection()))[0].id.instance_id == 2
    finally:
        await runner.close()


@pytest.mark.asyncio
async def test_membership_change_while_ranking_falls_back(plugin_distribution):
    from motor.coordinator.scheduler.policy.api import RankedCandidate

    client, native, request = await scheduler_with_pool(plugin_distribution)

    async def rank_and_replace_slot(snapshot):
        client._workload_reader.entry_meta.return_value = {"generation": 2, "slot": 0, "flags": 2}
        return (RankedCandidate(CandidateId(2, 0), 0.0),)

    client._policy_runners["prefill"].rank = AsyncMock(side_effect=rank_and_replace_slot)
    try:
        result = await client.select_and_allocate(PDRole.ROLE_P, request)
        assert result[0].id == 1
        assert native.cas_add.call_args.args[2] == 2
        assert client._policy_runners["prefill"]._counts["fallbacks"] == 1
    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_real_plugin_with_native_shm_allocation_and_release(plugin_distribution):
    import uuid
    from motor.common.resources.http_msg_spec import EventType
    from motor.coordinator.domain.instance_manager import InstanceManager
    from motor.coordinator.scheduler.runtime.workload_shm.native import (
        NativeWorkloadShmUnavailable,
        load_native_library,
    )
    from motor.coordinator.scheduler.runtime.workload_shm.reader import WorkloadSharedMemoryReader
    from motor.coordinator.scheduler.runtime.workload_shm.writer import WorkloadSharedMemoryOwner

    try:
        load_native_library()
    except NativeWorkloadShmUnavailable as exc:
        pytest.skip(str(exc))
    client, _, request = await scheduler_with_pool(plugin_distribution)
    manager = InstanceManager(CoordinatorConfig())
    await manager.refresh_instances(EventType.ADD, client._cache.get_instances(PDRole.ROLE_P))
    owner = WorkloadSharedMemoryOwner(manager, max_entries=8, shm_name="plugin_" + uuid.uuid4().hex[:12])
    owner.write_snapshot()
    reader = WorkloadSharedMemoryReader(owner.shm_name)
    reader.attach()
    client._workload_reader = reader
    try:
        for slot in range(owner.native.read_header()["entry_count"]):
            meta = owner.native.load_entry(slot)
            if meta["instance_id"] == 2:
                assert owner.native.cas_add(2, 0, meta["generation"], 0.0, 50.0)[0] == STATUS_OK
        reader.read_and_patch_cache(client._cache, role=PDRole.ROLE_P)
        await client._policy_runners["prefill"].start()
        result = await client.select_and_allocate(PDRole.ROLE_P, request)
        assert result[0].id == 2
        reader.read_and_patch_cache(client._cache, role=PDRole.ROLE_P)
        assert reader.entry_meta(2, 0)["active_tokens"] == 50 + result[2].active_tokens
        assert await client.update_workload(
            UpdateWorkloadParams(
                2,
                0,
                PDRole.ROLE_P,
                request.req_id,
                WorkloadAction.RELEASE_TOKENS,
                result[2],
            )
        )
        reader.read_and_patch_cache(client._cache, role=PDRole.ROLE_P)
        assert reader.entry_meta(2, 0)["active_tokens"] == 50
    finally:
        await client.disconnect()
        owner.release()
