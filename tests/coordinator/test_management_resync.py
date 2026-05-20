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

"""Tests for ManagementServer's kv-conductor registration resync loop.

We test the lifecycle hooks (``_start_registration_resync`` /
``_registration_resync_loop``) in isolation rather than spinning up the full
uvicorn stack; the helpers are designed to be unit-testable.
"""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import Mock, patch

import pytest

from motor.coordinator.api_server import management_server as ms


def _make_server_with_config(conductor_service: str):
    """Build a minimally-initialised ``ManagementServer`` for testing helpers."""
    server = ms.ManagementServer.__new__(ms.ManagementServer)
    server.coordinator_config = Mock()
    server.coordinator_config.prefill_kv_event_config = Mock(
        conductor_service=conductor_service
    )
    return server


class TestStartRegistrationResync(unittest.IsolatedAsyncioTestCase):
    async def test_returns_none_when_conductor_service_empty(self) -> None:
        server = _make_server_with_config("")
        task = server._start_registration_resync()
        self.assertIsNone(task)

    async def test_returns_task_when_conductor_service_configured(self) -> None:
        server = _make_server_with_config("fake-conductor")
        task = server._start_registration_resync()
        try:
            self.assertIsNotNone(task)
            self.assertFalse(task.done())
        finally:
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass


class TestRegistrationResyncLoop(unittest.IsolatedAsyncioTestCase):
    async def test_calls_resync_periodically(self) -> None:
        server = _make_server_with_config("fake-conductor")
        recovered_calls: list[int] = []

        def fake_resync():
            recovered_calls.append(1)
            return 0

        with patch.object(ms, "_REGISTRATION_RESYNC_INTERVAL", 0.01), patch.object(
            ms.ConductorApiClient,
            "resync_registrations",
            side_effect=fake_resync,
        ):
            task = asyncio.create_task(server._registration_resync_loop())
            await asyncio.sleep(0.05)  # let several ticks fire
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Should have ticked at least a couple of times in 50ms with interval 10ms.
        self.assertGreaterEqual(len(recovered_calls), 2)

    async def test_swallows_resync_exceptions(self) -> None:
        server = _make_server_with_config("fake-conductor")
        calls = {"n": 0}

        def boom():
            calls["n"] += 1
            raise RuntimeError("transient")

        with patch.object(ms, "_REGISTRATION_RESYNC_INTERVAL", 0.01), patch.object(
            ms.ConductorApiClient,
            "resync_registrations",
            side_effect=boom,
        ):
            task = asyncio.create_task(server._registration_resync_loop())
            await asyncio.sleep(0.04)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Loop kept ticking despite each call raising.
        self.assertGreater(calls["n"], 1)

    async def test_logs_when_recovery_succeeds(self) -> None:
        server = _make_server_with_config("fake-conductor")

        with patch.object(ms, "_REGISTRATION_RESYNC_INTERVAL", 0.01), patch.object(
            ms.ConductorApiClient,
            "resync_registrations",
            return_value=3,
        ), patch.object(ms, "logger") as mock_logger:
            task = asyncio.create_task(server._registration_resync_loop())
            await asyncio.sleep(0.03)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        info_msgs = [c.args[0] if c.args else "" for c in mock_logger.info.call_args_list]
        self.assertTrue(
            any("Periodic resync recovered" in m for m in info_msgs),
            f"expected recovery message, got: {info_msgs}",
        )


if __name__ == "__main__":
    unittest.main()
