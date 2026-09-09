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
    KvMatch,
    LoadBalancingPolicy,
    RankedCandidate,
    RequestContext,
    SelectionInput,
)
from motor.coordinator.scheduler.policy.builtin import (
    BuiltinKvCacheAffinityPolicy,
    BuiltinLoadBalancePolicy,
    BuiltinRoundRobinPolicy,
)
from motor.coordinator.scheduler.policy.executor import PolicyExecutor
from motor.coordinator.scheduler.policy.feature_provider import PolicyContextBuilder
from motor.coordinator.scheduler.policy.factory import create_load_balancing_policy
from motor.coordinator.scheduler.policy.kv_feature_provider import KvFeatureProvider
from motor.coordinator.scheduler.policy.loader import (
    PolicyLoadError,
    PolicyLoader,
    validate_policy_plugin_config,
)
from motor.coordinator.scheduler.policy.metrics import PolicyMetrics, append_policy_metrics, get_policy_metrics


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


@pytest.fixture(autouse=True)
def _reset_policy_loader_cache():
    PolicyLoader.reset_cache()
    get_policy_metrics().reset()
    yield
    PolicyLoader.reset_cache()
    get_policy_metrics().reset()


class _GoodPolicy(LoadBalancingPolicy):
    def rank(self, selection: SelectionInput) -> Sequence[RankedCandidate]:
        return [RankedCandidate(id=candidate.id, score=candidate.active_tokens) for candidate in selection.candidates]


class _AsyncRankPolicy(LoadBalancingPolicy):
    # pylint: disable=invalid-overridden-method
    async def rank(self, selection: SelectionInput) -> Sequence[RankedCandidate]:
        return []


class _NoRankPolicy(LoadBalancingPolicy):
    pass


class _BoomPolicy(LoadBalancingPolicy):
    def __init__(self, options=None) -> None:  # pylint: disable=super-init-not-called
        raise RuntimeError("nope")

    def rank(self, selection: SelectionInput) -> Sequence[RankedCandidate]:
        return []


class _BadVersionPolicy(LoadBalancingPolicy):
    api_version = 99

    def rank(self, selection: SelectionInput) -> Sequence[RankedCandidate]:
        return []


def _mock_entry(name: str, policy_cls: type, *, value: str = "pkg.mod:Cls") -> MagicMock:
    entry = MagicMock()
    entry.name = name
    entry.value = value
    entry.load.return_value = policy_cls
    entry.dist = MagicMock()
    entry.dist.metadata = {"Name": "pkg"}
    entry.dist.version = "1.0"
    return entry


def _policy_from_rank(rank_impl):
    class _Policy(LoadBalancingPolicy):
        def rank(self, selection: SelectionInput) -> Sequence[RankedCandidate]:
            return rank_impl(selection)

    return _Policy()


def _rank_duplicate(selection: SelectionInput) -> Sequence[RankedCandidate]:
    cid = selection.candidates[0].id
    return [RankedCandidate(id=cid, score=1.0), RankedCandidate(id=cid, score=2.0)]


def _rank_boom(_selection: SelectionInput) -> Sequence[RankedCandidate]:
    raise RuntimeError("boom")


def _rank_empty(_selection: SelectionInput) -> Sequence[RankedCandidate]:
    return []


def _rank_unknown(_selection: SelectionInput) -> Sequence[RankedCandidate]:
    return [RankedCandidate(id=CandidateId(99, 1), score=0.0)]


def _rank_nan(selection: SelectionInput) -> Sequence[RankedCandidate]:
    return [RankedCandidate(id=selection.candidates[0].id, score=float("nan"))]


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


@pytest.mark.parametrize(
    "rank_impl",
    [_rank_duplicate, _rank_boom, _rank_empty, _rank_unknown, _rank_nan],
    ids=["duplicate", "exception", "empty", "unknown-id", "nan"],
)
def test_executor_invalid_rank_falls_back(rank_impl):
    c1 = CandidateSnapshot(CandidateId(1, 1), 1.0, 1.0, False)
    executor = PolicyExecutor(
        _policy_from_rank(rank_impl),
        policy_name="bad",
        fallback_policy=BuiltinLoadBalancePolicy(),
    )
    ranked = executor.rank(_selection(c1))
    assert ranked and ranked[0].id == CandidateId(1, 1)
    assert executor.last_used_fallback is True


@pytest.mark.parametrize(
    "spec",
    [
        PolicyPluginConfig(name="load_balance"),
        PolicyPluginConfig(name="acme.test", fallback="kv_cache_affinity"),
    ],
)
def test_loader_rejects_invalid_plugin_config(spec: PolicyPluginConfig):
    with pytest.raises(PolicyLoadError):
        validate_policy_plugin_config(spec)


def test_loader_not_installed():
    with pytest.raises(PolicyLoadError):
        PolicyLoader().load(PolicyPluginConfig(name="acme.missing.policy"))


def test_loader_duplicate_entry_points():
    entry = _mock_entry("acme.dup", _GoodPolicy, value="pkg.mod:Cls")
    entry.dist.metadata = {"Name": "pkg-a"}
    entry2 = _mock_entry("acme.dup", _GoodPolicy, value="pkg2.mod:Cls")
    entry2.dist.metadata = {"Name": "pkg-b"}
    entry2.dist.version = "2.0"
    with patch("motor.coordinator.scheduler.policy.loader.entry_points", return_value=[entry, entry2]):
        with pytest.raises(PolicyLoadError, match="multiple entry points"):
            PolicyLoader().load(PolicyPluginConfig(name="acme.dup"))


def test_factory_builtin_names():
    assert isinstance(create_load_balancing_policy("load_balance"), BuiltinLoadBalancePolicy)
    assert isinstance(create_load_balancing_policy("round_robin"), BuiltinRoundRobinPolicy)


def test_kv_feature_provider_unavailable():
    provider = KvFeatureProvider()
    instance = MagicMock()
    instance.id = 1
    instance.role = PDRole.ROLE_P
    with (
        patch(
            "motor.coordinator.scheduler.policy.kv_feature_provider.ConductorApiClient.query_conductor",
            side_effect=RuntimeError("down"),
        ) as mock_query,
        patch(
            "motor.coordinator.scheduler.policy.kv_feature_provider.KvCacheAffinityPolicy._conductor_block_size",
            return_value=0,
        ),
    ):
        matches, available = provider.build([1, 2, 3], [instance], [CandidateId(1, 1)])
    assert matches == {}
    assert available is False
    mock_query.assert_called_once()


def test_context_builder_reads_shm_active_tokens():
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


def test_builtin_kv_cache_affinity_unified_ranks_by_prefill_and_load():
    policy = BuiltinKvCacheAffinityPolicy(options={"mode": "unified", "prefill_load_scale": 1.0, "load_weight": 1.0})
    c1 = CandidateSnapshot(
        id=CandidateId(1, 1),
        active_tokens=5.0,
        instance_active_tokens=5.0,
        blocked=False,
        kv_match=KvMatch(matched_tokens=8, prefill_cost=2.0, hit_ratio=0.8),
    )
    c2 = CandidateSnapshot(
        id=CandidateId(2, 1),
        active_tokens=1.0,
        instance_active_tokens=1.0,
        blocked=False,
        kv_match=KvMatch(matched_tokens=5, prefill_cost=4.0, hit_ratio=0.5),
    )
    ranked = policy.rank(_selection(c1, c2))
    assert [item.id for item in ranked] == [CandidateId(2, 1), CandidateId(1, 1)]


def test_builtin_kv_cache_affinity_load_gated_limits_to_topn_then_prefers_match():
    policy = BuiltinKvCacheAffinityPolicy(options={"mode": "load_gated", "load_gate_topn": 2})
    c1 = CandidateSnapshot(
        id=CandidateId(1, 1),
        active_tokens=1.0,
        instance_active_tokens=1.0,
        blocked=False,
        kv_match=KvMatch(matched_tokens=2, prefill_cost=8.0, hit_ratio=0.2),
    )
    c2 = CandidateSnapshot(
        id=CandidateId(2, 1),
        active_tokens=2.0,
        instance_active_tokens=2.0,
        blocked=False,
        kv_match=KvMatch(matched_tokens=9, prefill_cost=1.0, hit_ratio=0.9),
    )
    c3 = CandidateSnapshot(
        id=CandidateId(3, 1),
        active_tokens=100.0,
        instance_active_tokens=100.0,
        blocked=False,
        kv_match=KvMatch(matched_tokens=100, prefill_cost=0.0, hit_ratio=1.0),
    )
    selection = SelectionInput(
        request=RequestContext(
            request_id="r1",
            role=PDRole.ROLE_P,
            model_name="m",
            prompt_tokens=10,
            max_output_tokens=32,
        ),
        candidates=(c1, c2, c3),
        excluded=frozenset(),
        attempt=0,
        kv_available=True,
    )
    ranked = policy.rank(selection)
    assert [item.id for item in ranked] == [CandidateId(2, 1), CandidateId(1, 1)]


def test_builtin_kv_cache_affinity_falls_back_when_kv_unavailable():
    policy = BuiltinKvCacheAffinityPolicy(options={"mode": "unified"})
    c1 = CandidateSnapshot(CandidateId(1, 1), 1.0, 1.0, False, kv_match=None)
    c2 = CandidateSnapshot(CandidateId(2, 1), 2.0, 2.0, False, kv_match=None)
    selection = SelectionInput(
        request=RequestContext(
            request_id="r1",
            role=PDRole.ROLE_P,
            model_name="m",
            prompt_tokens=10,
            max_output_tokens=32,
        ),
        candidates=(c2, c1),
        excluded=frozenset(),
        attempt=0,
        kv_available=False,
    )
    ranked = policy.rank(selection)
    assert [item.id for item in ranked] == [CandidateId(1, 1), CandidateId(2, 1)]


@pytest.mark.parametrize(
    ("policy_cls", "name", "match"),
    [
        (_AsyncRankPolicy, "acme.async", "synchronous"),
        (_NoRankPolicy, "acme.norank", "does not override rank"),
        (_BoomPolicy, "acme.boom", "Failed to construct"),
        (_BadVersionPolicy, "acme.bad", "api_version"),
    ],
)
def test_loader_rejects_invalid_policy_class(policy_cls, name, match):
    entry = _mock_entry(name, policy_cls)
    with patch("motor.coordinator.scheduler.policy.loader.entry_points", return_value=[entry]):
        with pytest.raises(PolicyLoadError, match=match):
            PolicyLoader().load(PolicyPluginConfig(name=name))
    assert name not in PolicyLoader._cache


def test_load_at_startup_skips_entry_points_when_unconfigured():
    with patch("motor.coordinator.scheduler.policy.loader.entry_points") as mock_eps:
        assert PolicyLoader.load_at_startup(None) is None
        assert PolicyLoader.load_at_startup(PolicyPluginConfig(name="")) is None
        assert PolicyLoader.load_at_startup(PolicyPluginConfig(name="   ")) is None
        mock_eps.assert_not_called()


def test_loader_only_loads_and_caches_configured_entry_point():
    other = _mock_entry("other.policy", _GoodPolicy, value="other.mod:Cls")
    configured = _mock_entry("acme.ok", _GoodPolicy, value="pkg.mod:Ok")
    with patch("motor.coordinator.scheduler.policy.loader.entry_points", return_value=[other, configured]):
        first = PolicyLoader.load_at_startup(PolicyPluginConfig(name="acme.ok"))
        second = PolicyLoader().load(PolicyPluginConfig(name="acme.ok"))
    assert isinstance(first, _GoodPolicy)
    assert first is second
    configured.load.assert_called_once()
    other.load.assert_not_called()


def test_append_policy_metrics():
    with patch("motor.coordinator.scheduler.policy.metrics.get_policy_metrics", return_value=PolicyMetrics()):
        assert append_policy_metrics("up 1\n") == "up 1\n"
    filled = PolicyMetrics()
    filled.observe_selection("acme.append", 0.02)
    filled.inc_errors("acme.append")
    filled.inc_fallback("acme.append")
    filled.inc_cas_retries("acme.append")
    with patch("motor.coordinator.scheduler.policy.metrics.get_policy_metrics", return_value=filled):
        text = append_policy_metrics("up 1\n")
    assert text.startswith("up 1\n")
    assert "motor_policy_selection_seconds" in text
    assert "motor_policy_errors_total" in text
    assert "motor_policy_fallback_total" in text
    assert "motor_policy_cas_retries_total" in text
    assert 'policy="acme.append"' in text
