# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2025-2026. All rights reserved.
# MindIE is licensed under Mulan PSL v2.
# You can use this software according to the terms and conditions of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
#         http://license.coscl.org.cn/MulanPSL2
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the Mulan PSL v2 license for more details.

"""Tests for FunctionCallAffinityPolicy and its helpers (TDD)."""

from __future__ import annotations

import threading
import time
import unittest
from unittest.mock import Mock, patch

from motor.common.resources.instance import PDRole
from motor.coordinator.api_client.conductor_api_client import TENANT_ID
from motor.coordinator.scheduler.policy.function_call_affinity import (
    FunctionCallAffinityPolicy,
    ToolsAffinityCache,
    compute_tools_fingerprint,
    extract_tools,
    has_function_call_signal,
)


# -----------------------------------------------------------------------------
# compute_tools_fingerprint
# -----------------------------------------------------------------------------


class TestComputeToolsFingerprint(unittest.TestCase):
    """Tests for compute_tools_fingerprint (canonicalised SHA256)."""

    def test_none_returns_none(self) -> None:
        self.assertIsNone(compute_tools_fingerprint(None))

    def test_empty_list_returns_none(self) -> None:
        self.assertIsNone(compute_tools_fingerprint([]))

    def test_same_content_different_key_order_same_fingerprint(self) -> None:
        tools_a = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "weather",
                    "parameters": {"type": "object"},
                },
            }
        ]
        tools_b = [
            {
                "function": {
                    "parameters": {"type": "object"},
                    "description": "weather",
                    "name": "get_weather",
                },
                "type": "function",
            }
        ]
        self.assertEqual(
            compute_tools_fingerprint(tools_a),
            compute_tools_fingerprint(tools_b),
        )

    def test_different_tools_yield_different_fingerprints(self) -> None:
        tools_a = [{"function": {"name": "get_weather"}}]
        tools_b = [{"function": {"name": "get_time"}}]
        self.assertNotEqual(
            compute_tools_fingerprint(tools_a),
            compute_tools_fingerprint(tools_b),
        )

    def test_fingerprint_is_hex_string(self) -> None:
        fp = compute_tools_fingerprint([{"function": {"name": "x"}}])
        self.assertIsInstance(fp, str)
        # SHA256 hex digest length
        self.assertEqual(len(fp), 64)
        int(fp, 16)  # raises if not hex

    def test_non_serialisable_returns_none(self) -> None:
        # bytes are not JSON-serialisable; helper must not raise
        self.assertIsNone(
            compute_tools_fingerprint([{"function": {"name": b"\x00\x01"}}])
        )

    def test_order_of_tools_matters(self) -> None:
        """Tool position can change cache locality, so order is significant."""
        tools_a = [
            {"function": {"name": "a"}},
            {"function": {"name": "b"}},
        ]
        tools_b = [
            {"function": {"name": "b"}},
            {"function": {"name": "a"}},
        ]
        self.assertNotEqual(
            compute_tools_fingerprint(tools_a),
            compute_tools_fingerprint(tools_b),
        )


# -----------------------------------------------------------------------------
# extract_tools / has_function_call_signal
# -----------------------------------------------------------------------------


class TestExtractTools(unittest.TestCase):
    def test_returns_tools_when_present(self) -> None:
        req_data = {"tools": [{"function": {"name": "foo"}}]}
        self.assertEqual(extract_tools(req_data), req_data["tools"])

    def test_returns_none_when_absent(self) -> None:
        self.assertIsNone(extract_tools({"prompt": "hi"}))

    def test_returns_none_for_non_dict(self) -> None:
        self.assertIsNone(extract_tools(None))
        self.assertIsNone(extract_tools("not-a-dict"))


class TestHasFunctionCallSignal(unittest.TestCase):
    def test_with_top_level_tools(self) -> None:
        self.assertTrue(
            has_function_call_signal({"tools": [{"function": {"name": "x"}}]})
        )

    def test_with_tool_calls_in_messages(self) -> None:
        req_data = {
            "messages": [
                {
                    "role": "assistant",
                    "tool_calls": [{"function": {"name": "x", "arguments": "{}"}}],
                }
            ]
        }
        self.assertTrue(has_function_call_signal(req_data))

    def test_without_signal(self) -> None:
        self.assertFalse(has_function_call_signal({"prompt": "hi"}))
        self.assertFalse(
            has_function_call_signal({"messages": [{"role": "user", "content": "hi"}]})
        )

    def test_empty_or_invalid_input(self) -> None:
        self.assertFalse(has_function_call_signal({}))
        self.assertFalse(has_function_call_signal(None))
        self.assertFalse(has_function_call_signal({"tools": []}))


# -----------------------------------------------------------------------------
# ToolsAffinityCache (LRU + TTL)
# -----------------------------------------------------------------------------


class TestToolsAffinityCache(unittest.TestCase):
    def test_get_missing_returns_none(self) -> None:
        cache = ToolsAffinityCache(max_size=4, ttl_seconds=10.0)
        self.assertIsNone(cache.get("fp"))

    def test_put_then_get_roundtrip(self) -> None:
        cache = ToolsAffinityCache(max_size=4, ttl_seconds=10.0)
        cache.put("fp1", instance_id=1, endpoint_id=2)
        record = cache.get("fp1")
        self.assertIsNotNone(record)
        self.assertEqual(record.instance_id, 1)
        self.assertEqual(record.endpoint_id, 2)

    def test_ttl_expiration(self) -> None:
        cache = ToolsAffinityCache(max_size=4, ttl_seconds=0.05)
        cache.put("fp", instance_id=1, endpoint_id=1)
        time.sleep(0.08)
        self.assertIsNone(cache.get("fp"))

    def test_lru_eviction(self) -> None:
        cache = ToolsAffinityCache(max_size=2, ttl_seconds=10.0)
        cache.put("a", 1, 1)
        cache.put("b", 2, 2)
        # Touch 'a' to make 'b' the LRU
        self.assertIsNotNone(cache.get("a"))
        cache.put("c", 3, 3)
        self.assertIsNotNone(cache.get("a"))
        self.assertIsNone(cache.get("b"))  # evicted
        self.assertIsNotNone(cache.get("c"))

    def test_put_updates_existing(self) -> None:
        cache = ToolsAffinityCache(max_size=2, ttl_seconds=10.0)
        cache.put("a", 1, 1)
        cache.put("a", 2, 9)
        record = cache.get("a")
        self.assertEqual(record.instance_id, 2)
        self.assertEqual(record.endpoint_id, 9)

    def test_thread_safety_basic(self) -> None:
        cache = ToolsAffinityCache(max_size=64, ttl_seconds=10.0)

        def worker(idx: int) -> None:
            for j in range(50):
                cache.put(f"fp-{idx}-{j}", idx, j)
                cache.get(f"fp-{idx}-{j}")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # No exception means it survived the concurrent access; size <= max_size.
        self.assertLessEqual(cache.size(), 64)

    def test_clear(self) -> None:
        cache = ToolsAffinityCache(max_size=4, ttl_seconds=10.0)
        cache.put("a", 1, 1)
        cache.clear()
        self.assertIsNone(cache.get("a"))
        self.assertEqual(cache.size(), 0)


# -----------------------------------------------------------------------------
# FunctionCallAffinityPolicy
# -----------------------------------------------------------------------------


def _make_instance(instance_id: int, endpoint_ids):
    instance = Mock()
    instance.id = instance_id
    eps = {}
    for ep_id in endpoint_ids:
        ep = Mock()
        ep.id = ep_id
        eps[ep_id] = ep
    instance.endpoints = {"pod-0": eps}
    instance.get_all_endpoints = Mock(return_value=tuple(eps.values()))
    return instance


class TestFunctionCallAffinityPolicy(unittest.TestCase):
    def setUp(self) -> None:
        self.mock_provider = Mock()
        self.policy = FunctionCallAffinityPolicy(self.mock_provider)

    def test_init(self) -> None:
        self.assertIs(self.policy._instance_provider, self.mock_provider)
        self.assertIsInstance(self.policy.affinity_cache, ToolsAffinityCache)

    def test_select_instance_returns_none(self) -> None:
        self.assertIsNone(self.policy._select_instance())

    def test_select_endpoint_returns_none(self) -> None:
        self.assertIsNone(self.policy._select_endpoint(Mock()))

    @patch(
        "motor.coordinator.scheduler.policy.function_call_affinity"
        ".KvCacheAffinityPolicy.select_endpoint_from_list"
    )
    def test_sticky_routing_on_fingerprint_hit(self, mock_kv) -> None:
        """Same fingerprint twice -> second time uses sticky route, not KV path."""
        instance_a = _make_instance(1, [10, 11])
        instance_b = _make_instance(2, [20, 21])
        instances = [instance_a, instance_b]

        req_info = Mock()
        req_info.req_data = {
            "tools": [{"function": {"name": "get_weather"}}],
            "messages": [{"role": "user", "content": "hi"}],
        }

        # First call: cache miss -> falls back to KV path which picks instance_b/ep20
        mock_kv.return_value = (instance_b, instance_b.endpoints["pod-0"][20])
        first = self.policy.select_endpoint_from_list_with_cache(instances, req_info)
        self.assertEqual(first[0].id, 2)
        self.assertEqual(first[1].id, 20)
        self.assertEqual(mock_kv.call_count, 1)

        # Second call: cache hit -> sticky returns the same (instance_b, ep20),
        # KV path NOT invoked again.
        mock_kv.reset_mock()
        second = self.policy.select_endpoint_from_list_with_cache(instances, req_info)
        self.assertEqual(second[0].id, 2)
        self.assertEqual(second[1].id, 20)
        self.assertEqual(mock_kv.call_count, 0)

    @patch(
        "motor.coordinator.scheduler.policy.function_call_affinity"
        ".KvCacheAffinityPolicy.select_endpoint_from_list"
    )
    def test_sticky_invalidated_when_instance_gone(self, mock_kv) -> None:
        """If the cached instance disappears, fallback to KV path and update cache."""
        instance_a = _make_instance(1, [10])
        instance_b = _make_instance(2, [20])

        req_info = Mock()
        req_info.req_data = {"tools": [{"function": {"name": "f"}}]}

        # Seed cache with (instance_a, ep10)
        mock_kv.return_value = (instance_a, instance_a.endpoints["pod-0"][10])
        self.policy.select_endpoint_from_list_with_cache([instance_a, instance_b], req_info)
        self.assertEqual(mock_kv.call_count, 1)

        # Now instance_a is gone; only instance_b is available.
        mock_kv.reset_mock()
        mock_kv.return_value = (instance_b, instance_b.endpoints["pod-0"][20])
        result = self.policy.select_endpoint_from_list_with_cache([instance_b], req_info)
        self.assertEqual(result[0].id, 2)
        self.assertEqual(result[1].id, 20)
        self.assertEqual(mock_kv.call_count, 1)  # KV path used

    @patch(
        "motor.coordinator.scheduler.policy.function_call_affinity"
        ".KvCacheAffinityPolicy.select_endpoint_from_list"
    )
    def test_sticky_invalidated_when_endpoint_gone(self, mock_kv) -> None:
        """Cached endpoint missing on the instance -> fallback to KV path."""
        instance_a = _make_instance(1, [10, 11])
        req_info = Mock()
        req_info.req_data = {"tools": [{"function": {"name": "f"}}]}
        mock_kv.return_value = (instance_a, instance_a.endpoints["pod-0"][10])
        self.policy.select_endpoint_from_list_with_cache([instance_a], req_info)

        # Endpoint 10 disappears
        instance_a.endpoints["pod-0"].pop(10)
        instance_a.get_all_endpoints = Mock(return_value=(instance_a.endpoints["pod-0"][11],))

        mock_kv.reset_mock()
        mock_kv.return_value = (instance_a, instance_a.endpoints["pod-0"][11])
        result = self.policy.select_endpoint_from_list_with_cache([instance_a], req_info)
        self.assertEqual(result[1].id, 11)
        self.assertEqual(mock_kv.call_count, 1)

    @patch(
        "motor.coordinator.scheduler.policy.function_call_affinity.LoadBalancePolicy"
    )
    @patch(
        "motor.coordinator.scheduler.policy.function_call_affinity"
        ".KvCacheAffinityPolicy.select_endpoint_from_list"
    )
    def test_falls_back_to_load_balance_when_kv_fails(
        self, mock_kv, mock_lb_class
    ) -> None:
        instance_a = _make_instance(1, [10])
        req_info = Mock()
        req_info.req_data = {"tools": [{"function": {"name": "f"}}]}

        mock_kv.return_value = None
        ep = instance_a.endpoints["pod-0"][10]
        mock_lb_class.select_instance_from_list.return_value = instance_a
        mock_lb_class.select_endpoint_from_instance.return_value = ep

        result = self.policy.select_endpoint_from_list_with_cache(
            [instance_a], req_info
        )
        self.assertEqual(result[0].id, 1)
        self.assertEqual(result[1].id, 10)
        mock_kv.assert_called_once()
        mock_lb_class.select_instance_from_list.assert_called_once()
        mock_lb_class.select_endpoint_from_instance.assert_called_once_with(
            instance_a
        )

    @patch(
        "motor.coordinator.scheduler.policy.function_call_affinity"
        ".KvCacheAffinityPolicy.select_endpoint_from_list"
    )
    def test_no_signal_uses_kv_only(self, mock_kv) -> None:
        """No tools/tool_calls -> fall through to KV path; cache not seeded."""
        instance_a = _make_instance(1, [10])
        req_info = Mock()
        req_info.req_data = {"prompt": "hi"}
        mock_kv.return_value = (instance_a, instance_a.endpoints["pod-0"][10])

        result = self.policy.select_endpoint_from_list_with_cache(
            [instance_a], req_info
        )
        self.assertEqual(result[0].id, 1)
        # Without tools fingerprint, cache stays empty.
        self.assertEqual(self.policy.affinity_cache.size(), 0)

    def test_empty_instances_returns_none(self) -> None:
        req_info = Mock()
        req_info.req_data = {"tools": [{"function": {"name": "x"}}]}
        self.assertIsNone(
            self.policy.select_endpoint_from_list_with_cache([], req_info)
        )

    @patch(
        "motor.coordinator.scheduler.policy.function_call_affinity"
        ".KvCacheAffinityPolicy.select_endpoint_from_list"
    )
    def test_static_helper_uses_global_cache(self, mock_kv) -> None:
        """Module-level static helper retains state across calls (singleton cache)."""
        FunctionCallAffinityPolicy.reset_global_cache_for_testing()
        instance_a = _make_instance(1, [10])
        req_info = Mock()
        req_info.req_data = {"tools": [{"function": {"name": "g"}}]}

        mock_kv.return_value = (instance_a, instance_a.endpoints["pod-0"][10])
        FunctionCallAffinityPolicy.select_endpoint_from_list(
            [instance_a], req_info
        )
        self.assertEqual(mock_kv.call_count, 1)

        mock_kv.reset_mock()
        result = FunctionCallAffinityPolicy.select_endpoint_from_list(
            [instance_a], req_info
        )
        self.assertEqual(result[0].id, 1)
        self.assertEqual(mock_kv.call_count, 0)  # sticky hit


# -----------------------------------------------------------------------------
# SchedulerType / Factory wiring
# -----------------------------------------------------------------------------


class TestSchedulerTypeAndFactory(unittest.TestCase):
    def test_scheduler_type_has_function_call_affinity(self) -> None:
        from motor.config.coordinator import SchedulerType

        self.assertTrue(hasattr(SchedulerType, "FUNCTION_CALL_AFFINITY"))
        self.assertEqual(
            SchedulerType.FUNCTION_CALL_AFFINITY.value, "function_call_affinity"
        )

    def test_factory_creates_function_call_affinity_policy(self) -> None:
        from motor.config.coordinator import SchedulerType
        from motor.coordinator.scheduler.policy.factory import (
            SchedulingPolicyFactory,
        )

        provider = Mock()
        policy = SchedulingPolicyFactory.create(
            SchedulerType.FUNCTION_CALL_AFFINITY, provider
        )
        self.assertIsInstance(policy, FunctionCallAffinityPolicy)

    def test_scheduler_type_from_string(self) -> None:
        from motor.config.coordinator import SchedulerType

        self.assertEqual(
            SchedulerType.from_string("function_call_affinity"),
            SchedulerType.FUNCTION_CALL_AFFINITY,
        )


# -----------------------------------------------------------------------------
# AsyncSchedulerClient runtime path integration
# -----------------------------------------------------------------------------


class TestSchedulerClientFunctionCallAffinityRouting(unittest.TestCase):
    """Light integration test for scheduler_client._select_instance_and_endpoint_from_list."""

    def _make_client(self, scheduler_type: str):
        from motor.coordinator.scheduler.runtime.scheduler_client import (
            AsyncSchedulerClient,
            SchedulerClientConfig,
        )

        cfg = SchedulerClientConfig(
            scheduler_address="ipc:///tmp/_unit_test_func_call_affinity",
            scheduler_type=scheduler_type,
        )
        return AsyncSchedulerClient(cfg)

    @patch(
        "motor.coordinator.scheduler.runtime.scheduler_client"
        ".FunctionCallAffinityPolicy.select_endpoint_from_list"
    )
    def test_p_role_uses_function_call_affinity(self, mock_fc) -> None:
        client = self._make_client("function_call_affinity")
        instance = _make_instance(1, [10])
        ep = instance.endpoints["pod-0"][10]
        mock_fc.return_value = (instance, ep)

        req_info = Mock()
        req_info.req_data = {"tools": [{"function": {"name": "f"}}]}

        result = client._select_instance_and_endpoint_from_list(
            [instance], PDRole.ROLE_P, req_info
        )
        self.assertEqual(result, (instance, ep))
        mock_fc.assert_called_once()

    @patch(
        "motor.coordinator.scheduler.runtime.scheduler_client"
        ".FunctionCallAffinityPolicy.select_endpoint_from_list"
    )
    def test_p_role_falls_back_to_load_balance_then_round_robin(self, mock_fc) -> None:
        client = self._make_client("function_call_affinity")
        instance = _make_instance(1, [10])
        mock_fc.return_value = None  # FC affinity fails

        req_info = Mock()
        req_info.req_data = {"prompt": "hi"}

        # Stub the LB path used inside the client to also fail, forcing RR
        with patch.object(
            client, "_select_instance_and_endpoint_by_load_balance", return_value=None
        ):
            result = client._select_instance_and_endpoint_from_list(
                [instance], PDRole.ROLE_P, req_info
            )
        # Round-robin path picks the only instance with first endpoint
        self.assertIsNotNone(result)
        self.assertEqual(result[0].id, 1)

    def test_d_role_uses_load_balance(self) -> None:
        client = self._make_client("function_call_affinity")
        instance = _make_instance(2, [20])
        ep = instance.endpoints["pod-0"][20]
        with patch.object(
            client,
            "_select_instance_and_endpoint_by_load_balance",
            return_value=instance,
        ) as mock_lb, patch.object(
            client,
            "_select_endpoint_for_instance",
            return_value=(instance, ep),
        ) as mock_pick:
            req_info = Mock()
            req_info.req_data = {"tools": [{"function": {"name": "x"}}]}
            result = client._select_instance_and_endpoint_from_list(
                [instance], PDRole.ROLE_D, req_info
            )
            self.assertEqual(result, (instance, ep))
            mock_lb.assert_called_once()
            mock_pick.assert_called_once_with(instance)


if __name__ == "__main__":
    unittest.main()
