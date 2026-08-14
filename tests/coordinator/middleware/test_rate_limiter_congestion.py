# Copyright (c) Huawei Technologies Co., Ltd. 2025-2026. All rights reserved.
# MindIE is licensed under Mulan PSL v2.
# You can use this software according to the terms and conditions of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
#         http://license.coscl.org.cn/MulanPSL2
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the Mulan PSL v2 for more details.

"""Tests for SimpleRateLimiter congestion alarm based on used token capacity."""

from unittest.mock import patch

from motor.coordinator.middleware.rate_limiter import SimpleRateLimiter


class TestSimpleRateLimiterCongestion:
    @patch("motor.coordinator.api_client.controller_api_client.ControllerApiClient.report_alarms")
    def test_congestion_alarm_on_high_used_capacity(self, mock_report):
        limiter = SimpleRateLimiter(max_requests=100, window_size=60)
        # Force remaining tokens low so used = 100 - 10 = 90 >= 85.
        limiter._bucket.tokens = 10

        allowed, info = limiter.is_allowed()

        assert allowed is True
        assert info["available"] <= 10
        assert limiter._congestion_alarm_sent is True
        assert mock_report.call_count == 1
        payload = mock_report.call_args[0][0]
        assert "greater than or equal to" in payload["additional_information"]

    @patch("motor.coordinator.api_client.controller_api_client.ControllerApiClient.report_alarms")
    def test_congestion_recover_on_low_used_capacity(self, mock_report):
        limiter = SimpleRateLimiter(max_requests=100, window_size=60)
        limiter._congestion_alarm_sent = True
        # used = 100 - 40 = 60 < 75 → recover.
        limiter._bucket.tokens = 40

        allowed, _ = limiter.is_allowed()

        assert allowed is True
        assert limiter._congestion_alarm_sent is False
        assert mock_report.call_count == 1
        payload = mock_report.call_args[0][0]
        assert "less than" in payload["additional_information"]

    @patch("motor.coordinator.api_client.controller_api_client.ControllerApiClient.report_alarms")
    def test_idle_bucket_does_not_trigger_congestion(self, mock_report):
        limiter = SimpleRateLimiter(max_requests=100, window_size=60)

        limiter.is_allowed()

        assert limiter._congestion_alarm_sent is False
        mock_report.assert_not_called()
