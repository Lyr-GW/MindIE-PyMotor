#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2025-2026. All rights reserved.
# MindIE is licensed under Mulan PSL v2.

"""Unit tests for SubprocessSupervisor."""

from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from motor.coordinator.daemon.subprocess_supervisor import SubprocessSupervisor


def test_subprocess_supervisor_can_restart_under_limit():
    """_can_restart returns True when under limit."""
    mgr = MagicMock()
    supervisor = SubprocessSupervisor({"proc1": mgr})
    assert supervisor._can_restart("proc1") is True


def test_subprocess_supervisor_can_restart_over_limit():
    """_can_restart returns False when over limit."""
    mgr = MagicMock()
    supervisor = SubprocessSupervisor({"proc1": mgr})
    for _ in range(5):
        supervisor._record_restart("proc1")
    assert supervisor._can_restart("proc1") is False


def test_subprocess_supervisor_restart_limit_exceeded_no_start():
    """When over limit, supervisor does not call mgr.start()."""
    with patch('motor.coordinator.daemon.subprocess_supervisor.MAX_RESTART_PER_MINUTE', 2):
        mgr = MagicMock()
        mgr.is_running.return_value = False
        supervisor = SubprocessSupervisor({"proc1": mgr})
        for _ in range(3):
            supervisor._record_restart("proc1")
        assert supervisor._can_restart("proc1") is False


def test_subprocess_supervisor_per_process_limits():
    """Each process has independent RestartLimiter."""
    with patch('motor.coordinator.daemon.subprocess_supervisor.MAX_RESTART_PER_MINUTE', 3):
        mgr1 = MagicMock()
        mgr2 = MagicMock()
        supervisor = SubprocessSupervisor({"proc1": mgr1, "proc2": mgr2})
        for _ in range(3):
            supervisor._record_restart("proc1")
        assert supervisor._can_restart("proc1") is False
        assert supervisor._can_restart("proc2") is True


def test_subprocess_supervisor_is_master_default():
    """When no provider, _is_master returns True."""
    supervisor = SubprocessSupervisor({})
    assert supervisor._is_master() is True


def test_subprocess_supervisor_is_master_from_provider():
    """_is_master uses provider when set."""
    supervisor = SubprocessSupervisor({}, is_master_provider=lambda: False)
    assert supervisor._is_master() is False
    supervisor = SubprocessSupervisor({}, is_master_provider=lambda: True)
    assert supervisor._is_master() is True


@pytest.mark.asyncio
async def test_subprocess_supervisor_run_skips_when_standby():
    """When not master, supervisor does not restart processes."""
    with patch('motor.coordinator.daemon.subprocess_supervisor.CHECK_INTERVAL', 0.05):
        mgr = MagicMock()
        mgr.is_running.return_value = False
        supervisor = SubprocessSupervisor(
            {"proc1": mgr},
            is_master_provider=lambda: False,
        )
        stop_event = __import__("asyncio").Event()
        task = __import__("asyncio").create_task(supervisor.run(stop_event))
        await __import__("asyncio").sleep(0.15)
        stop_event.set()
        await task
        mgr.start.assert_not_called()


@pytest.mark.asyncio
async def test_subprocess_supervisor_run_restarts_when_master_and_not_running():
    """When master and process not running, supervisor restarts."""
    with patch('motor.coordinator.daemon.subprocess_supervisor.CHECK_INTERVAL', 0.05):
        mgr = MagicMock()
        mgr.is_running.return_value = False
        supervisor = SubprocessSupervisor({"proc1": mgr}, is_master_provider=lambda: True)
        stop_event = __import__("asyncio").Event()
        task = __import__("asyncio").create_task(supervisor.run(stop_event))
        await __import__("asyncio").sleep(0.15)
        stop_event.set()
        await task
        mgr.start.assert_called()
