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

"""Tests for the ConductorApiClient registration tracking & resync logic."""

from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from motor.coordinator.api_client.conductor_api_client import ConductorApiClient


def _make_instance(instance_id: int = 1):
    inst = Mock()
    inst.id = instance_id
    inst.model_name = "fake-model"
    return inst


def _make_endpoint(endpoint_id: int = 0, ip: str = "10.0.0.1"):
    ep = Mock()
    ep.id = endpoint_id
    ep.ip = ip
    return ep


@patch.object(
    ConductorApiClient,
    "coordinator_config",
    new=Mock(
        prefill_kv_event_config=Mock(
            conductor_service="fake-conductor",
            http_server_port=13333,
            endpoint="http://*:9000",
            replay_endpoint="",
            engine_type="vLLM",
            block_size=128,
            model_path="",
        )
    ),
)
class TestConductorApiClientRegistration(unittest.TestCase):
    def setUp(self) -> None:
        ConductorApiClient.reset_registration_state_for_testing()

    @patch("motor.coordinator.api_client.conductor_api_client.SafeHTTPSClient")
    def test_register_post_success_records_key(self, mock_client_cls) -> None:
        # Context manager mock chain
        mock_client = mock_client_cls.return_value.__enter__.return_value
        mock_client.post.return_value = {"status": "ok"}

        instance, endpoint = _make_instance(7), _make_endpoint(0)
        result = ConductorApiClient.register_post(instance, endpoint)

        self.assertTrue(result)
        self.assertEqual(ConductorApiClient.registered_count(), 1)
        self.assertEqual(ConductorApiClient.pending_registration_count(), 0)

    @patch("motor.coordinator.api_client.conductor_api_client.SafeHTTPSClient")
    def test_register_post_failure_marks_pending(self, mock_client_cls) -> None:
        mock_client = mock_client_cls.return_value.__enter__.return_value
        mock_client.post.side_effect = ConnectionError("conductor down")

        instance, endpoint = _make_instance(7), _make_endpoint(0)
        result = ConductorApiClient.register_post(instance, endpoint)

        self.assertFalse(result)
        self.assertEqual(ConductorApiClient.registered_count(), 0)
        self.assertEqual(ConductorApiClient.pending_registration_count(), 1)

    @patch("motor.coordinator.api_client.conductor_api_client.SafeHTTPSClient")
    def test_resync_retries_pending_until_success(self, mock_client_cls) -> None:
        # First call fails, second call succeeds.
        mock_client = mock_client_cls.return_value.__enter__.return_value
        mock_client.post.side_effect = [ConnectionError("down"), {"status": "ok"}]

        instance, endpoint = _make_instance(7), _make_endpoint(0)
        ConductorApiClient.register_post(instance, endpoint)
        self.assertEqual(ConductorApiClient.pending_registration_count(), 1)

        recovered = ConductorApiClient.resync_registrations()
        self.assertEqual(recovered, 1)
        self.assertEqual(ConductorApiClient.pending_registration_count(), 0)
        self.assertEqual(ConductorApiClient.registered_count(), 1)

    @patch("motor.coordinator.api_client.conductor_api_client.SafeHTTPSClient")
    def test_resync_keeps_pending_when_still_failing(self, mock_client_cls) -> None:
        mock_client = mock_client_cls.return_value.__enter__.return_value
        mock_client.post.side_effect = ConnectionError("down")

        ConductorApiClient.register_post(_make_instance(1), _make_endpoint(0))
        ConductorApiClient.register_post(_make_instance(2), _make_endpoint(0))
        self.assertEqual(ConductorApiClient.pending_registration_count(), 2)

        recovered = ConductorApiClient.resync_registrations()
        self.assertEqual(recovered, 0)
        # Still pending; we did not lose track of them.
        self.assertEqual(ConductorApiClient.pending_registration_count(), 2)

    @patch("motor.coordinator.api_client.conductor_api_client.SafeHTTPSClient")
    def test_resync_with_no_pending_is_noop(self, mock_client_cls) -> None:
        recovered = ConductorApiClient.resync_registrations()
        self.assertEqual(recovered, 0)
        mock_client_cls.assert_not_called()

    @patch("motor.coordinator.api_client.conductor_api_client.SafeHTTPSClient")
    def test_unregister_clears_tracked_state(self, mock_client_cls) -> None:
        mock_client = mock_client_cls.return_value.__enter__.return_value
        mock_client.post.return_value = {"status": "ok"}

        instance, endpoint = _make_instance(7), _make_endpoint(0)
        ConductorApiClient.register_post(instance, endpoint)
        self.assertEqual(ConductorApiClient.registered_count(), 1)

        ConductorApiClient.unregister_post(instance, endpoint)
        self.assertEqual(ConductorApiClient.registered_count(), 0)
        self.assertEqual(ConductorApiClient.pending_registration_count(), 0)


@patch.object(
    ConductorApiClient,
    "coordinator_config",
    new=Mock(
        prefill_kv_event_config=Mock(
            conductor_service="fake-conductor",
            http_server_port=13333,
            endpoint="http://*:9000",
            replay_endpoint="",
            engine_type="vLLM",
            block_size=128,
            model_path="",
        )
    ),
)
class TestQueryConductorLogging(unittest.TestCase):
    def setUp(self) -> None:
        ConductorApiClient.reset_registration_state_for_testing()

    @patch("motor.coordinator.api_client.conductor_api_client.logger")
    @patch("motor.coordinator.api_client.conductor_api_client.SafeHTTPSClient")
    def test_empty_response_logged_as_warning_once(
        self, mock_client_cls, mock_logger
    ) -> None:
        mock_client = mock_client_cls.return_value.__enter__.return_value
        mock_client.post.return_value = {}

        instance = _make_instance(1)
        for _ in range(5):
            ConductorApiClient.query_conductor([instance], [1, 2, 3])

        # State throttling: only the first empty response logs a WARN.
        self.assertEqual(mock_logger.warning.call_count, 1)

    @patch("motor.coordinator.api_client.conductor_api_client.logger")
    @patch("motor.coordinator.api_client.conductor_api_client.SafeHTTPSClient")
    def test_state_transition_relogs(self, mock_client_cls, mock_logger) -> None:
        mock_client = mock_client_cls.return_value.__enter__.return_value
        # Empty -> empty -> populated -> empty
        mock_client.post.side_effect = [
            {},
            {},
            {"default": {"vllm-prefill-1": {}}},
            {},
        ]
        instance = _make_instance(1)
        for _ in range(4):
            ConductorApiClient.query_conductor([instance], [1, 2, 3])

        # Initial empty -> 1 WARN
        # Repeat empty -> suppressed
        # Empty -> populated transition -> 1 INFO
        # Populated -> empty transition -> 1 WARN
        self.assertEqual(mock_logger.warning.call_count, 2)
        self.assertEqual(mock_logger.info.call_count, 1)

    @patch("motor.coordinator.api_client.conductor_api_client.logger")
    @patch("motor.coordinator.api_client.conductor_api_client.SafeHTTPSClient")
    def test_exception_logged_at_most_once_per_window(
        self, mock_client_cls, mock_logger
    ) -> None:
        mock_client = mock_client_cls.return_value.__enter__.return_value
        mock_client.post.side_effect = ConnectionError("down")

        instance = _make_instance(1)
        for _ in range(5):
            ConductorApiClient.query_conductor([instance], [1, 2, 3])

        self.assertEqual(mock_logger.error.call_count, 1)


if __name__ == "__main__":
    unittest.main()
