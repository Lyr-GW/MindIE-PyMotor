# Copyright (c) Huawei Technologies Co., Ltd. 2025-2026. All rights reserved.
# MindIE is licensed under Mulan PSL v2.
# You can use this software according to the terms and conditions of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
#         http://license.coscl.org.cn/MulanPSL2
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the Mulan PSL v2 for more details.

"""In-process entry-point execution, concurrency, anomaly isolation, and allocation regression coverage."""

import ast
import asyncio
import importlib
import logging
import sys
import time
import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from motor.common.resources.endpoint import Endpoint, Workload, WorkloadAction
from motor.common.resources.instance import Instance, PDRole
from motor.config.coordinator import CoordinatorConfig, PolicyPluginConfig
from motor.coordinator.domain.scheduling import UpdateWorkloadParams
from motor.coordinator.models.request import RequestInfo
from motor.coordinator.scheduler.policy.api import (
    CandidateId,
    CandidateSnapshot,
    RankedCandidate,
    RequestContext,
    SelectionInput,
)
from motor.coordinator.scheduler.policy.plugin_runner import PolicyRunner
from motor.coordinator.scheduler.runtime.scheduler_client import AsyncSchedulerClient, SchedulerClientConfig
from motor.coordinator.scheduler.runtime.workload_shm.native import STATUS_BLOCKED, STATUS_CHANGED, STATUS_OK


@pytest.fixture
def plugin_distribution(tmp_path, monkeypatch):
    """A real installed-distribution layout discovered in-process via importlib.metadata."""
    (tmp_path / "customer_policy.py").write_text(
        '''
import time
from motor.coordinator.scheduler.policy.api import EndpointSelectionPolicy, RankedCandidate

class Policy(EndpointSelectionPolicy):
    def __init__(self, options=None):
        super().__init__(options)
        if self.options.get("startup_hang"):
            time.sleep(0.25)

    def rank(self, selection):
        mode = self.options.get("mode")
        if mode == "error" or self.options.get("error_role") == selection.request.role:
            raise RuntimeError("customer failure")
        if mode == "hang" or self.options.get("hang_role") == selection.request.role:
            time.sleep(0.05)
            return [RankedCandidate(selection.candidates[0].id, 0)]
        if mode == "exit" or self.options.get("exit_role") == selection.request.role:
            raise SystemExit(3)
        if mode == "recursion":
            raise RecursionError("excessive recursion")
        if mode == "empty":
            return []
        if selection.request.request_id == "decline":
            return None
        if selection.request.request_id == "slow":
            time.sleep(0.05)
            return [RankedCandidate(selection.candidates[0].id, 0)]
        if mode == "invalid":
            return [RankedCandidate(selection.candidates[0].id, float("nan"))]
        if mode == "least_load":
            w = float(self.options.get("instance_weight", 0.05))
            candidates = sorted(
                selection.candidates,
                key=lambda c: (c.active_tokens + w * c.instance_active_tokens, c.id.instance_id, c.id.endpoint_id),
            )
            return [RankedCandidate(c.id, c.active_tokens + w * c.instance_active_tokens) for c in candidates]
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
    monkeypatch.syspath_prepend(str(tmp_path))
    sys.modules.pop("customer_policy", None)
    importlib.invalidate_caches()
    try:
        yield PolicyPluginConfig(role=["prefill"], name="customer.test", timeout_ms=20, startup_timeout_ms=100)
    finally:
        sys.modules.pop("customer_policy", None)
        importlib.invalidate_caches()


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


async def scheduler_with_pool(spec=None, scheduler_type="load_balance", role=PDRole.ROLE_P):
    plugin_configs = spec if isinstance(spec, list) else [spec] if spec else []
    client = AsyncSchedulerClient(SchedulerClientConfig(scheduler_type=scheduler_type, policy_plugin=plugin_configs))
    instances = [
        Instance(
            id=i,
            job_name="job-%s" % i,
            model_name="model",
            role=role.value,
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
    await client._cache.replace_all(role, instances)
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
async def test_real_entry_point_ranks_in_process_and_close_clears_policy(plugin_distribution):
    runner = PolicyRunner(plugin_distribution)
    try:
        await runner.start()
        assert runner._policy is not None
        ranked = runner.rank_sync(selection())
        assert [item.id.instance_id for item in ranked] == [2, 1]
        assert 'motor_policy_loads_total{policy="customer.test",role="prefill"} 1' in runner.metrics_text()
    finally:
        await runner.close()
    assert runner._policy is None
    assert runner._closed is True


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["error", "hang", "exit", "recursion", "empty", "invalid"])
async def test_repeated_plugin_failure_is_bounded_and_cools_down(plugin_distribution, mode, caplog):
    runner = PolicyRunner(replace(plugin_distribution, options={"mode": mode}))
    try:
        await runner.start()
        started = time.monotonic()
        with caplog.at_level(logging.WARNING):
            assert runner.rank_sync(selection()) is None
            for _ in range(20):
                assert runner.rank_sync(selection()) is None
        assert time.monotonic() - started < 1
        assert runner._policy is None
        assert runner._counts["calls"] == 1
        assert runner._counts["fallbacks"] == 21
        assert runner._counts["timeouts"] == (1 if mode == "hang" else 0)
        assert runner._counts["errors"] == (0 if mode == "hang" else 1)
        assert runner._fallback_reasons["cooldown"] == 20
        assert "name=customer.test" in caplog.text
        assert "role=prefill" in caplog.text
        assert "req_id=req" in caplog.text
        if mode in ("exit", "recursion"):
            assert any(record.levelno == logging.ERROR for record in caplog.records)
    finally:
        await runner.close()


@pytest.mark.asyncio
async def test_missing_and_hung_loader_fall_back(plugin_distribution, caplog):
    for spec in (
        replace(plugin_distribution, name="missing"),
        replace(plugin_distribution, options={"startup_hang": True}, startup_timeout_ms=30),
    ):
        runner = PolicyRunner(spec)
        try:
            with caplog.at_level(logging.WARNING):
                await runner.start()
            assert runner._policy is None
            assert runner.rank_sync(selection()) is None
            assert runner._counts["load_errors"] == 1
        finally:
            await runner.close()
    assert "Scheduling plugin load failed" in caplog.text
    assert "Scheduling plugin startup timed out" in caplog.text


@pytest.mark.asyncio
async def test_decline_falls_back_without_cooldown(plugin_distribution):
    runner = PolicyRunner(plugin_distribution)
    try:
        await runner.start()
        policy = runner._policy
        request = selection().request
        assert runner.rank_sync(replace(selection(), request=replace(request, request_id="decline"))) is None
        assert runner._policy is policy
        assert runner._retry_after == 0.0
        assert runner.rank_sync(selection())[0].id.instance_id == 2
        assert 'reason="declined"} 1' in runner.metrics_text()
    finally:
        await runner.close()


@pytest.mark.parametrize(
    "raw",
    [
        "not-a-sequence",
        {"ranked": []},
        [],
        [42],
        [RankedCandidate(CandidateId(True, 0), 1.0)],
        [RankedCandidate(CandidateId(99, 0), 1.0)],
        [RankedCandidate(CandidateId(1, 0), float("inf"))],
        [RankedCandidate(CandidateId(1, 0), True)],
        [RankedCandidate(CandidateId(1, 0), 1.0), RankedCandidate(CandidateId(1, 0), 2.0)],
    ],
)
def test_invalid_plugin_ranking_is_rejected(raw):
    with pytest.raises(ValueError):
        PolicyRunner._validate(raw, selection())


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
    assert len(families) == 8
    for family in families:
        assert 'role="prefill"' in family
        assert 'role="decode"' in family


@pytest.mark.asyncio
@pytest.mark.parametrize("failing_role", ["prefill", "decode"])
@pytest.mark.parametrize("failure", ["error", "hang", "exit"])
async def test_shared_config_isolates_faults_and_cooldown_by_role(plugin_distribution, failing_role, failure):
    """A shared item must isolate faults, cooldown, and instances by actual role."""
    spec = replace(
        plugin_distribution,
        role=["prefill", "decode"],
        options={failure + "_role": failing_role},
    )
    client, _, request = await scheduler_with_pool(spec)
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
    client.get_available_instances = AsyncMock(
        side_effect=lambda role: {instance.id: instance for instance in client._cache.get_instances(role)}
    )
    faulty = client._policy_runners[failing_role]
    healthy_role = "decode" if failing_role == "prefill" else "prefill"
    healthy = client._policy_runners[healthy_role]
    try:
        await asyncio.gather(*(runner.start() for runner in client._policy_runners.values()))
        assert faulty._policy is not None and healthy._policy is not None
        assert faulty._policy is not healthy._policy
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
        assert faulty._counts["timeouts" if failure == "hang" else "errors"] == 1
    finally:
        await client.disconnect()
    assert faulty._policy is None and healthy._policy is None


@pytest.mark.asyncio
async def test_prefill_and_decode_use_their_own_plugin_options(plugin_distribution):
    prefill = replace(plugin_distribution, role=["prefill"], options={})
    decode = replace(plugin_distribution, role=["decode"], options={"mode": "light"})
    client, _, request = await scheduler_with_pool([prefill, decode])
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
async def test_high_concurrency_zero_busy_bypass(plugin_distribution):
    """All 64 concurrent requests must execute the external plugin with zero busy bypass."""
    spec = replace(plugin_distribution, options={"mode": "least_load"}, timeout_ms=200)
    client, native, request = await scheduler_with_pool(spec)
    try:
        await client._policy_runners["prefill"].start()
        results = await asyncio.gather(*(client.select_and_allocate(PDRole.ROLE_P, request) for _ in range(64)))
        assert all(result is not None for result in results)
        runner = client._policy_runners["prefill"]
        assert runner._counts["calls"] == 64
        assert runner._counts["fallbacks"] == 0
        assert runner._fallback_reasons["busy"] == 0
        assert native.cas_add.call_count == 64
    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_real_cas_contention_across_concurrent_requests(plugin_distribution):
    """Concurrent requests share the unified SHM CAS loop and spread load evenly without busy bypass."""
    spec = replace(plugin_distribution, options={"mode": "least_load"}, timeout_ms=200)
    client = AsyncSchedulerClient(SchedulerClientConfig(scheduler_type="load_balance", policy_plugin=[spec]))
    instances = [
        Instance(
            id=i,
            job_name="job-%s" % i,
            model_name="model",
            role="prefill",
            engine_type="vllm",
            endpoints={
                "pod": {
                    ep_id: Endpoint(
                        id=ep_id,
                        ip="10.0.0.%s" % i,
                        business_port=str(8000 + ep_id),
                        workload=Workload(active_tokens=0.0),
                    )
                    for ep_id in range(4)
                }
            },
        )
        for i in (1, 2, 3, 4)
    ]
    await client._cache.replace_all(PDRole.ROLE_P, instances)
    shm = {(i, ep_id): 0.0 for i in (1, 2, 3, 4) for ep_id in range(4)}

    async def sync_shm(role=None):
        for (iid, eid), value in shm.items():
            client._cache.patch_workload_from_shm(iid, eid, PDRole.ROLE_P, value)

    native = Mock()

    def cas_add(iid, eid, gen, expected, delta, slot=None):
        current = shm[(iid, eid)]
        if current != expected:
            return STATUS_CHANGED, current
        shm[(iid, eid)] = current + delta
        return STATUS_OK, current + delta

    native.cas_add.side_effect = cas_add
    client._refresh_cache_from_workload_reader = sync_shm
    client.get_available_instances = AsyncMock(return_value={i.id: i for i in instances})
    client._workload_reader = Mock(native=native)
    client._workload_reader.entry_meta.return_value = {"generation": 1, "slot": 0, "flags": 2}
    request = RequestInfo(
        req_id="burst", req_data={"model": "model"}, req_len=10, api="v1/chat/completions", token_ids=list(range(10))
    )
    try:
        await client._policy_runners["prefill"].start()
        results = await asyncio.gather(*(client.select_and_allocate(PDRole.ROLE_P, request) for _ in range(32)))
        assert all(result is not None for result in results)
        runner = client._policy_runners["prefill"]
        assert runner._counts["calls"] == 32
        assert runner._counts["fallbacks"] == 0
        assert runner._fallback_reasons["busy"] == 0
        # 32 requests of 10 tokens across 16 endpoints balance evenly to 20.0 per endpoint.
        assert all(load == 20.0 for load in shm.values())
    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_builtin_and_external_share_unified_selection_and_admission_filters(plugin_distribution):
    client, _, request = await scheduler_with_pool(plugin_distribution)
    eligible, wrong_engine = client._cache.get_instances(PDRole.ROLE_P)
    eligible.dispatch_capabilities = ["decode_colocation"]
    wrong_engine.engine_type = "sglang"
    wrong_engine.dispatch_capabilities = ["decode_colocation"]
    wrong_dispatch = eligible.model_copy(update={"id": 3, "dispatch_capabilities": []})
    await client._cache.replace_all(PDRole.ROLE_P, [eligible, wrong_engine, wrong_dispatch])
    try:
        runner = client._policy_runners["prefill"]
        runner._policy = Mock(rank=Mock(return_value=[RankedCandidate(CandidateId(eligible.id, 0), 0.0)]))
        candidates, policy = await client._select_endpoint_candidates_with_policy(
            request, PDRole.ROLE_P, required_engine_type="vllm", required_dispatch_capability="decode_colocation"
        )
        assert policy == "plugin:customer.test"
        snapshot = runner._policy.rank.call_args.args[0]
        assert [candidate.id.instance_id for candidate in snapshot.candidates] == [eligible.id]
        assert [instance.id for instance, *_ in candidates] == [eligible.id]
    finally:
        await client.disconnect()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["error", "hang", "exit", "recursion"])
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
    client, _, request = await scheduler_with_pool([decode_plugin])
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
    client, native, request = await scheduler_with_pool(plugin_distribution)
    shm_tokens = {(1, 0): 10.0, (2, 0): 20.0}

    def cas_add(iid, eid, gen, expected, delta, slot=None):
        current = shm_tokens[(iid, eid)]
        if current != expected:
            return STATUS_CHANGED, current
        shm_tokens[(iid, eid)] = current + delta
        return STATUS_OK, current + delta

    async def refresh_after_first(role=None):
        for (iid, eid), value in shm_tokens.items():
            client._cache.patch_workload_from_shm(iid, eid, PDRole.ROLE_P, value)

    # Simulate another worker advancing SHM slot (2, 0) concurrently before this worker's CAS.
    shm_tokens[(2, 0)] = 123.0
    native.cas_add.side_effect = cas_add
    client._refresh_cache_from_workload_reader = refresh_after_first
    try:
        await client._policy_runners["prefill"].start()
        # First attempt sees cached 20.0 -> cas_add receives expected=20.0 -> STATUS_CHANGED -> refreshes & retries.
        # Reset cache to stale 20.0 after initial refresh inside select_and_allocate by mocking refresh on call 1.
        call_no = 0

        async def staged_refresh(role=None):
            nonlocal call_no
            call_no += 1
            if call_no > 1:
                await refresh_after_first(role)

        client._refresh_cache_from_workload_reader = staged_refresh
        assert await client.select_and_allocate(PDRole.ROLE_P, request) is not None
        assert native.cas_add.call_args_list[0].args[3] == 20.0
        assert native.cas_add.call_args_list[1].args[3] == 123.0
    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_snapshot_failure_and_retry_exhaustion_use_builtin(plugin_distribution, caplog):
    client, native, request = await scheduler_with_pool(plugin_distribution)
    try:
        await client._policy_runners["prefill"].start()
        entry_calls = 0

        def fail_first_meta(*_args, **_kwargs):
            nonlocal entry_calls
            entry_calls += 1
            if entry_calls == 1:
                raise RuntimeError("snapshot failure")
            return {"generation": 1, "slot": 0, "flags": 2}

        client._workload_reader.entry_meta.side_effect = fail_first_meta
        with caplog.at_level(logging.WARNING):
            assert await client.select_and_allocate(PDRole.ROLE_P, request) is not None
        assert client._policy_runners["prefill"]._counts["fallbacks"] == 1
        assert client._policy_runners["prefill"]._fallback_reasons["snapshot_error"] == 1
        assert "role=prefill" in caplog.text
        assert "PDRole" not in caplog.text
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
        assert client._policy_runners["prefill"]._fallback_reasons["cas_retry_limit"] == 1
    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_mid_cas_retry_fallback_preserves_builtin_demand(plugin_distribution):
    """If plugin declines or fails during a CAS retry, the unified loop switches to built-in demand."""
    client, native, request = await scheduler_with_pool(plugin_distribution, scheduler_type="round_robin")
    runner = client._policy_runners["prefill"]
    try:
        await runner.start()
        calls = 0

        def rank_then_decline(sel):
            nonlocal calls
            calls += 1
            if calls == 1:
                return (RankedCandidate(CandidateId(2, 0), 0.0),)
            runner.record_fallback("declined")
            return None

        runner.rank_sync = Mock(side_effect=rank_then_decline)
        native.cas_add.side_effect = [(STATUS_CHANGED, 0), (STATUS_OK, 0)]
        result = await client.select_and_allocate(PDRole.ROLE_P, request)
        assert result is not None
        assert result[2].active_tokens == 0.0
        assert native.cas_add.call_args_list[0].args[4] == 10.0
        assert native.cas_add.call_args_list[1].args[4] == 0.0
    finally:
        await client.disconnect()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("strategy", "role", "expected_demand"),
    [
        ("round_robin", PDRole.ROLE_P, 0),
        ("load_balance", PDRole.ROLE_P, 10),
        ("kv_cache_affinity", PDRole.ROLE_P, 10),
        ("dynamic_bucket", PDRole.ROLE_D, 10),
    ],
)
async def test_disabled_plugin_keeps_builtin_allocations(strategy, role, expected_demand):
    client, native, request = await scheduler_with_pool(scheduler_type=strategy, role=role)
    try:
        if role == PDRole.ROLE_D:
            request.req_len = 99
            _, selected_policy = await client._select_endpoint_candidates_with_policy(request, role)
            assert selected_policy == "dynamic_bucket"
        assert client._policy_runners == {}
        result = await client.select_and_allocate(role, request)
        assert result is not None
        assert result[2].active_tokens == expected_demand
        assert native.cas_add.call_args.args[4] == expected_demand
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
async def test_shutdown_cancels_recovery_without_errors_and_cooldown_recovers(plugin_distribution):
    runner = PolicyRunner(replace(plugin_distribution, options={"startup_hang": True}, startup_timeout_ms=5000))
    runner._restart_task = asyncio.create_task(runner.start())
    await asyncio.sleep(0)
    await asyncio.wait_for(runner.close(), timeout=2)
    assert runner.rank_sync(selection()) is None
    assert runner._counts["errors"] == 0
    assert runner._counts["load_errors"] == 0
    assert runner._counts["timeouts"] == 0
    assert runner._fallback_reasons["plugin_error"] == 0
    assert runner._fallback_reasons["unavailable"] == 1

    runner = PolicyRunner(replace(plugin_distribution, options={"mode": "error"}))
    try:
        await runner.start()
        assert runner.rank_sync(selection()) is None
        runner.config = plugin_distribution
        runner._retry_after = 0
        assert runner.rank_sync(selection()) is None
        await runner._restart_task
        assert runner.rank_sync(selection())[0].id.instance_id == 2
    finally:
        await runner.close()


@pytest.mark.asyncio
async def test_membership_change_while_ranking_falls_back(plugin_distribution):
    client, native, request = await scheduler_with_pool(plugin_distribution)

    def rank_and_replace_slot(snapshot):
        client._workload_reader.entry_meta.return_value = {"generation": 2, "slot": 0, "flags": 2}
        return (RankedCandidate(CandidateId(2, 0), 0.0),)

    try:
        await client._policy_runners["prefill"].start()
        client._policy_runners["prefill"].rank_sync = Mock(side_effect=rank_and_replace_slot)
        result = await client.select_and_allocate(PDRole.ROLE_P, request)
        assert result[0].id == 1
        assert native.cas_add.call_args.args[2] == 2
        assert client._policy_runners["prefill"]._counts["fallbacks"] == 1
        assert client._policy_runners["prefill"]._fallback_reasons["membership_changed"] == 1
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


def test_fallback_reasons_stay_in_sync_and_unknown_reason_is_exported(plugin_distribution, caplog):
    from motor.coordinator.scheduler.policy.plugin_runner import _FALLBACK_REASONS

    scheduler_root = Path(__file__).resolve().parents[3] / "motor" / "coordinator" / "scheduler"
    for py_file in scheduler_root.rglob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not (isinstance(node.func, ast.Attribute) and node.func.attr == "record_fallback"):
                continue
            if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                assert node.args[0].value in _FALLBACK_REASONS, f"{py_file}:{node.lineno} -> {node.args[0].value}"

    runner = PolicyRunner(plugin_distribution)
    with caplog.at_level(logging.WARNING):
        runner.record_fallback("future_reason")
    assert "Unknown scheduling plugin fallback reason" in caplog.text
    assert 'reason="future_reason"} 1' in runner.metrics_text()
