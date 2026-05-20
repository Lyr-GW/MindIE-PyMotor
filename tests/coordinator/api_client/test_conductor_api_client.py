# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Tests for ConductorApiClient query response normalization."""

import unittest

from motor.coordinator.api_client.conductor_api_client import (
    TENANT_ID,
    ConductorApiClient,
)


class TestNormalizeQueryResponse(unittest.TestCase):
    """Test _normalize_query_response handles multiple conductor API shapes."""

    def test_empty(self):
        self.assertEqual(ConductorApiClient._normalize_query_response({}), {})

    def test_legacy_tenant_map(self):
        raw = {
            TENANT_ID: {
                "vllm-prefill-1": {"longest_matched": 4, "DP": {"0": 1}},
            }
        }
        self.assertEqual(ConductorApiClient._normalize_query_response(raw), raw)

    def test_flat_instance_map(self):
        raw = {
            "vllm-prefill-1": {"longest_matched": 6, "GPU": 4, "DP": {"0": 4}},
        }
        expected = {TENANT_ID: raw}
        self.assertEqual(ConductorApiClient._normalize_query_response(raw), expected)

    def test_data_wrapped_tenant_map(self):
        inner = {TENANT_ID: {"vllm-prefill-2": {"longest_matched": 1, "DP": {}}}}
        raw = {"data": inner}
        self.assertEqual(ConductorApiClient._normalize_query_response(raw), inner)

    def test_data_wrapped_flat_instance_map(self):
        instances = {"vllm-prefill-3": {"longest_matched": 2, "DP": {"1": 2}}}
        raw = {"data": instances}
        expected = {TENANT_ID: instances}
        self.assertEqual(ConductorApiClient._normalize_query_response(raw), expected)

    def test_data_empty(self):
        self.assertEqual(ConductorApiClient._normalize_query_response({"data": {}}), {})


if __name__ == "__main__":
    unittest.main()
