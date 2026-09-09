# Copyright (c) Huawei Technologies Co., Ltd. 2025-2026. All rights reserved.
# MindIE is licensed under Mulan PSL v2.
# You can use this software according to the terms and conditions of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
#         http://license.coscl.org.cn/MulanPSL2
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the Mulan PSL v2 for more details.

"""Unit tests for scheduling policy plugin API, loader, executor, and builtins."""

from __future__ import annotations

import math
from collections.abc import Sequence
from unittest.mock import MagicMock, patch

import pytest

from motor.common.resources.instance import PDRole
from motor.config.coordinator import PolicyPluginConfig
from motor.coordinator.scheduler.policy.api import (
    CandidateId,
    CandidateSnapshot,
    LoadBalancingPolicy,
    RankedCandidate,
    RequestContext,
    SelectionInput,
)
from motor.coordinator.scheduler.policy.builtin import (
    BuiltinLoadBalancePolicy,
    BuiltinRoundRobinPolicy,
)
from motor.coordinator.scheduler.policy.executor import PolicyExecutor
from motor.coordinator.scheduler.policy.feature_provider import PolicyContextBuilder
from motor.coordinator.scheduler.policy.factory import create_load_balancing_policy
from motor.coordinator.scheduler.policy.kv_feature_provider import KvFeatureProvider
from motor.coordinator.scheduler.policy.loader import (
    FALLBACK_POLICY_NAMES,
    PolicyLoadError,
    PolicyLoader,
    RESERVED_POLICY_NAMES,
    validate_policy_plugin_config,
)
from motor.coordinator.scheduler.policy.metrics import PolicyMetrics


def _selection(*candidates: CandidateSnapshot, excluded=None) -> SelectionInput:
    return SelectionInput(
        request=RequestContext(
            request_id="r1",
            role=PDRole.ROLE_P,
            model_name="m",
            prompt_tokens=10,
            max_output_tokens=32,
        ),
        candidates=tuple(candidates),
        excluded=frozenset(excluded or []),
        attempt=0,
        kv_available=False,
    )


def test_builtin_load_balance_rank_order():
    policy = BuiltinLoadBalancePolicy(options={"instance_score_weight": 0.0})
    c_low = CandidateSnapshot(
        id=CandidateId(1, 1),
        active_tokens=1.0,
        instance_active_tokens=1.0,
        blocked=False,
    )
    c_high = CandidateSnapshot(
        id=CandidateId(2, 1),
        active_tokens=5.0,
        instance_active_tokens=5.0,
        blocked=False,
    )
    ranked = policy.rank(_selection(c_high, c_low))
    assert ranked[0].id == CandidateId(1, 1)
    assert ranked[1].id == CandidateId(2, 1)


def test_builtin_round_robin_rotates():
    policy = BuiltinRoundRobinPolicy(options={"start_counter": 0})
    c1 = CandidateSnapshot(CandidateId(1, 1), 0.0, 0.0, False)
    c2 = CandidateSnapshot(CandidateId(2, 1), 0.0, 0.0, False)
    first = policy.rank(_selection(c1, c2))
    second = policy.rank(_selection(c1, c2))
    assert first[0].id == CandidateId(1, 1)
    assert second[0].id == CandidateId(2, 1)


def test_executor_rejects_duplicate_ids():
    policy = BuiltinLoadBalancePolicy()
    c1 = CandidateSnapshot(CandidateId(1, 1), 1.0, 1.0, False)

    class DupPolicy(LoadBalancingPolicy):
        def rank(self, selection: SelectionInput) -> Sequence[RankedCandidate]:
            return [
                RankedCandidate(id=c1.id, score=1.0),
                RankedCandidate(id=c1.id, score=2.0),
            ]

    executor = PolicyExecutor(DupPolicy(), policy_name="dup", fallback_policy=policy)
    ranked = executor.rank(_selection(c1))
    assert ranked and ranked[0].id == CandidateId(1, 1)


def test_executor_fallback_on_exception():
    policy = BuiltinLoadBalancePolicy()
    c1 = CandidateSnapshot(CandidateId(1, 1), 1.0, 1.0, False)

    class BrokenPolicy(LoadBalancingPolicy):
        def rank(self, selection: SelectionInput) -> Sequence[RankedCandidate]:
            raise RuntimeError("boom")

    executor = PolicyExecutor(
        BrokenPolicy(),
        policy_name="broken",
        fallback_policy=policy,
        fallback_name="load_balance",
    )
    ranked = executor.rank(_selection(c1))
    assert ranked and ranked[0].id == CandidateId(1, 1)


def test_loader_rejects_reserved_name():
    with pytest.raises(PolicyLoadError):
        validate_policy_plugin_config(PolicyPluginConfig(name="load_balance"))


def test_loader_not_installed():
    with pytest.raises(PolicyLoadError):
        PolicyLoader().load(PolicyPluginConfig(name="acme.missing.policy"))


def test_loader_duplicate_entry_points():
    entry = MagicMock()
    entry.name = "acme.dup"
    entry.value = "pkg.mod:Cls"
    entry.dist = MagicMock()
    entry.dist.metadata = {"Name": "pkg-a"}
    entry.dist.version = "1.0"
    entry2 = MagicMock()
    entry2.name = "acme.dup"
    entry2.value = "pkg2.mod:Cls"
    entry2.dist = MagicMock()
    entry2.dist.metadata = {"Name": "pkg-b"}
    entry2.dist.version = "2.0"

    class GoodPolicy(LoadBalancingPolicy):
        def rank(self, selection: SelectionInput) -> Sequence[RankedCandidate]:
            return []

    with patch(
        "motor.coordinator.scheduler.policy.loader.entry_points",
        return_value=[entry, entry2],
    ):
        with pytest.raises(PolicyLoadError, match="multiple entry points"):
            PolicyLoader().load(PolicyPluginConfig(name="acme.dup"))


def test_loader_validates_api_version():
    class BadVersionPolicy(LoadBalancingPolicy):
        api_version = 99

        def rank(self, selection: SelectionInput) -> Sequence[RankedCandidate]:
            return []

    entry = MagicMock()
    entry.name = "acme.bad"
    entry.value = "pkg.mod:Bad"
    entry.load.return_value = BadVersionPolicy
    entry.dist = MagicMock()
    entry.dist.metadata = {"Name": "pkg"}
    entry.dist.version = "1.0"

    with patch("motor.coordinator.scheduler.policy.loader.entry_points", return_value=[entry]):
        with pytest.raises(PolicyLoadError, match="api_version"):
            PolicyLoader().load(PolicyPluginConfig(name="acme.bad"))


def test_factory_builtin_names():
    assert isinstance(create_load_balancing_policy("load_balance"), BuiltinLoadBalancePolicy)
    assert isinstance(create_load_balancing_policy("round_robin"), BuiltinRoundRobinPolicy)


def test_kv_feature_provider_unavailable():
    provider = KvFeatureProvider()
    with patch(
        "motor.coordinator.scheduler.policy.kv_feature_provider.ConductorApiClient.query_conductor",
        side_effect=RuntimeError("down"),
    ):
        matches, available = provider.build([], [], [])
    assert matches == {}
    assert available is False


def test_policy_metrics_render():
    metrics = PolicyMetrics()
    metrics.observe_selection("acme.test", 0.01)
    metrics.inc_errors("acme.test")
    metrics.inc_fallback("acme.test")
    metrics.inc_cas_retries("acme.test")
    text = metrics.render_prometheus()
    assert "motor_policy_selection_seconds" in text
    assert 'policy="acme.test"' in text
    assert "motor_policy_errors_total" in text
    assert "motor_policy_fallback_total" in text
    assert "motor_policy_cas_retries_total" in text


def test_context_builder_blocked_flag():
    builder = PolicyContextBuilder(is_instance_blocked=lambda _i: False)
    reader = MagicMock()
    reader.entry_meta.return_value = {"active_tokens": 3.0, "flags": 0}
    instance = MagicMock()
    instance.id = 1
    instance.engine_type = "vllm"
    instance.dispatch_capabilities = []
    endpoint = MagicMock()
    endpoint.id = 1
    endpoint.workload.active_tokens = 1.0
    instance.get_all_endpoints.return_value = [endpoint]
    req = MagicMock()
    req.req_id = "r"
    req.req_data = {}
    req.token_ids = []
    selection = builder.build(
        req,
        PDRole.ROLE_P,
        [instance],
        excluded=frozenset(),
        attempt=0,
        required_engine_type=None,
        required_dispatch_capability=None,
        workload_reader=reader,
        policy_requires_kv=False,
    )
    assert len(selection.candidates) == 1
    assert math.isclose(selection.candidates[0].active_tokens, 3.0)


def test_fallback_policy_names_constant():
    assert FALLBACK_POLICY_NAMES == frozenset({"load_balance", "round_robin"})
    assert "kv_cache_affinity" in RESERVED_POLICY_NAMES
