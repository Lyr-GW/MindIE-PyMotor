#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2025-2026. All rights reserved.
# MindIE is licensed under Mulan PSL v2.
# You can use this software according to the terms and conditions of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
#         http://license.coscl.org.cn/MulanPSL2
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the Mulan PSL v2 for more details.

"""
Daemon heartbeat writer for non-master/standby mode.

When enable_master_standby is False but role_heartbeat_interval_sec > 0, the Daemon
still creates the role shm and periodically writes a heartbeat so that Mgmt can
detect Daemon liveness (e.g. Daemon as PID 1 in container). See
docs/design/standby-role-shm-heartbeat.md.
"""

import struct
import threading
import time
from multiprocessing import shared_memory
from typing import Any

from motor.config.standby import StandbyConfig
from motor.common.utils.logger import get_logger

logger = get_logger(__name__)

_ROLE_SHM_SIZE = 1
_ROLE_SHM_SIZE_WITH_HEARTBEAT = 9
_ROLE_SHM_MASTER = 1


class DaemonHeartbeatWriter:
    """
    Creates role shm and writes heartbeat only (no master/standby logic).
    Used by Coordinator Daemon when enable_master_standby is False but
    role_heartbeat_interval_sec > 0.
    """

    def __init__(self, standby_config: StandbyConfig) -> None:
        self._config = standby_config
        self._role_shm_name = (standby_config.role_shm_name or "").strip()
        if not self._role_shm_name:
            self._role_shm_name = "coordinator_standby_role"
        self._role_shm: Any = None
        self._stop_event = threading.Event()
        self._heartbeat_thread: threading.Thread | None = None

    def start(self) -> None:
        """Create role shm (size 9), write role=master and initial heartbeat, start heartbeat thread.
        If name already exists (e.g. previous Daemon crashed without unlink), attach and take over
        when size >= 9; otherwise unlink and create new, so restarted Mgmt reads current Daemon's heartbeat.
        """
        if self._role_shm is not None:
            return
        try:
            self._role_shm = shared_memory.SharedMemory(
                name=self._role_shm_name,
                create=True,
                size=_ROLE_SHM_SIZE_WITH_HEARTBEAT,
            )
            self._write_role_and_heartbeat()
            logger.info(
                "[Standby] Daemon heartbeat-only shm created: name=%s (Mgmt can detect Daemon liveness)",
                self._role_shm_name,
            )
        except FileExistsError:
            # Previous Daemon may have crashed without unlink; attach and take over so new Mgmt sees current heartbeat.
            try:
                existing = shared_memory.SharedMemory(
                    name=self._role_shm_name,
                    create=False,
                )
                size = len(existing.buf)
                if size >= _ROLE_SHM_SIZE_WITH_HEARTBEAT:
                    self._role_shm = existing
                    self._write_role_and_heartbeat()
                    logger.info(
                        "[Standby] Daemon heartbeat-only attached to existing shm: name=%s size=%s "
                        "(take over after restart)",
                        self._role_shm_name,
                        size,
                    )
                else:
                    existing.close()
                    existing.unlink()
                    logger.debug(
                        "[Standby] Removed stale role shm name=%s size=%s, will create new",
                        self._role_shm_name,
                        size,
                    )
                    self._role_shm = shared_memory.SharedMemory(
                        name=self._role_shm_name,
                        create=True,
                        size=_ROLE_SHM_SIZE_WITH_HEARTBEAT,
                    )
                    self._write_role_and_heartbeat()
                    logger.info(
                        "[Standby] Daemon heartbeat-only shm created: name=%s (Mgmt can detect Daemon liveness)",
                        self._role_shm_name,
                    )
            except Exception as e2:
                logger.warning(
                    "Failed to attach to or recreate role shm for heartbeat %s: %s",
                    self._role_shm_name,
                    e2,
                )
                self._role_shm = None
                return
        except Exception as e:
            logger.warning("Failed to create role shm for heartbeat %s: %s", self._role_shm_name, e)
            self._role_shm = None
            return

        interval = float(self._config.role_heartbeat_interval_sec or 0)
        if interval <= 0:
            return
        stale_sec = float(getattr(self._config, "role_heartbeat_stale_sec", 0.0) or 0.0)
        if stale_sec > 0 and stale_sec < 2 * interval:
            logger.warning(
                "[Standby] role_heartbeat_stale_sec=%.1f < 2*role_heartbeat_interval_sec=%.1f, may cause false 503",
                stale_sec,
                interval,
            )
        self._stop_event.clear()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name="DaemonHeartbeatWriter",
            daemon=False,
        )
        self._heartbeat_thread.start()
        logger.debug("[Standby] Daemon heartbeat-only thread started, interval=%.1fs", interval)

    def stop(self) -> None:
        """Stop heartbeat thread and close/unlink shm."""
        self._stop_event.set()
        if self._heartbeat_thread is not None:
            self._heartbeat_thread.join(timeout=5.0)
            self._heartbeat_thread = None
        if self._role_shm is not None:
            try:
                self._role_shm.close()
                self._role_shm.unlink()
                logger.debug("[Standby] Daemon heartbeat-only shm unlinked: name=%s", self._role_shm_name)
            except Exception as e:
                logger.debug("Unlink role shm %s: %s", self._role_shm_name, e)
            self._role_shm = None

    def _write_role_and_heartbeat(self) -> None:
        if self._role_shm is None:
            return
        try:
            self._role_shm.buf[0] = _ROLE_SHM_MASTER
            ns = time.monotonic_ns()
            self._role_shm.buf[1:9] = struct.pack("<Q", ns)
        except Exception as e:
            logger.warning("Failed to write role shm heartbeat: %s", e)

    def _heartbeat_loop(self) -> None:
        interval = float(self._config.role_heartbeat_interval_sec or 0)
        if interval <= 0:
            return
        while not self._stop_event.is_set():
            if self._stop_event.wait(timeout=interval):
                break
            if self._role_shm is not None:
                try:
                    ns = time.monotonic_ns()
                    self._role_shm.buf[1:9] = struct.pack("<Q", ns)
                except Exception as e:
                    logger.warning("Failed to write heartbeat: %s", e)
