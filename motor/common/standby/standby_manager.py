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

import struct
import threading
import time
from multiprocessing import shared_memory
from typing import Any, Callable, Protocol
from enum import Enum

from motor.common.utils.logger import get_logger
from motor.common.etcd.etcd_client import EtcdClient
from motor.config.standby import StandbyConfig
from motor.common.utils.singleton import ThreadSafeSingleton


logger = get_logger(__name__)


class StandbyConfigProvider(Protocol):
    """Protocol for configuration objects that provide standby configuration"""
    standby_config: StandbyConfig


class StandbyRole(Enum):
    STANDBY = "standby"
    MASTER = "master"


class StandbyManager(ThreadSafeSingleton):
    """Master/standby management class"""

    def __init__(self, config: StandbyConfigProvider | None = None):
        # Prevent re-initialization for singleton
        if hasattr(self, '_initialized'):
            return

        # First time initialization must have config
        if config is None:
            raise ValueError("config must be provided for first initialization of StandbyManager singleton")
        self.config = config
        self.etcd_client = EtcdClient(
            etcd_config=config.etcd_config,
            tls_config=config.etcd_tls_config
        )
        standby_config = config.standby_config
        self.current_role = StandbyRole.STANDBY
        self._role_shm_name = (standby_config.role_shm_name or "").strip()
        self._role_shm: Any = None  # SharedMemory when role_shm_name set and start() called
        self.role_lock = threading.Lock()
        self.stop_event = threading.Event()
        self.stanyby_loop_thread: threading.Thread | None = None
        self._heartbeat_thread: threading.Thread | None = None
        self.is_running = False
        self.has_set_role = False

        # Enhanced lock configuration for better reliability (loaded from config)
        self.lock_ttl = standby_config.master_lock_ttl
        self.lock_retry_interval = standby_config.master_lock_retry_interval
        self.max_lock_failures = standby_config.master_lock_max_failures

        # Callbacks
        self.on_become_master: Callable[[], None] | None = None
        self.on_become_standby: Callable[[], None] | None = None

        self.stanyby_loop_thread = threading.Thread(
            target=self._master_standby_loop,
            name="MasterStandbyManager",
            daemon=False
        )

        self._initialized = True

    def start(
        self,
        on_become_master: Callable[[], None],
        on_become_standby: Callable[[], None]
    ) -> None:
        """Start the master/standby management thread"""
        if self.is_running:
            logger.warning("Master/standby manager is already running")
            return

        # Set callbacks
        self.on_become_master = on_become_master
        self.on_become_standby = on_become_standby

        # Reset stop_event if it was previously set (for singleton reuse)
        if self.stop_event.is_set():
            self.stop_event.clear()

        # Start the pre-created thread
        self.stanyby_loop_thread.start()
        self.is_running = True
        if self._role_shm_name:
            self._init_role_shm()
            interval = self.config.standby_config.role_heartbeat_interval_sec
            stale_sec = getattr(self.config.standby_config, "role_heartbeat_stale_sec", 0.0) or 0.0
            if interval > 0 and stale_sec > 0 and stale_sec < 2 * interval:
                logger.warning(
                    "[Standby] role_heartbeat_stale_sec=%.1f < 2*role_heartbeat_interval_sec=%.1f, may cause false 503",
                    stale_sec,
                    interval,
                )
            if interval > 0 and self._role_shm is not None:
                self._heartbeat_thread = threading.Thread(
                    target=self._heartbeat_loop,
                    name="StandbyRoleHeartbeat",
                    daemon=False,
                )
                self._heartbeat_thread.start()
                logger.debug("[Standby] Role shm heartbeat thread started, interval=%.1fs", interval)
        logger.info("Master/standby manager started")

    def stop(self) -> None:
        """Stop the master/standby management thread"""
        if not self.is_running:
            return

        logger.info("Stopping master/standby manager...")
        self.stop_event.set()

        if self.stanyby_loop_thread and self.stanyby_loop_thread.is_alive():
            self.stanyby_loop_thread.join(timeout=30)
            if self.stanyby_loop_thread.is_alive():
                logger.warning("Master/standby manager thread did not finish within timeout")
            else:
                logger.info("Master/standby manager thread stopped successfully")

        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            self._heartbeat_thread.join(timeout=10)
            if self._heartbeat_thread.is_alive():
                logger.warning("Role shm heartbeat thread did not finish within timeout")
            self._heartbeat_thread = None

        self.is_running = False

        if self._role_shm:
            try:
                self._role_shm.close()
                self._role_shm.unlink()
                logger.debug("[Standby] Role shm unlinked: name=%s", self._role_shm_name)
            except Exception as e:
                logger.debug("Unlink role shm %s: %s", self._role_shm_name, e)
            self._role_shm = None

        # Close etcd client
        if hasattr(self, 'etcd_client'):
            self.etcd_client.close()

        # Reset callbacks for singleton reuse (but keep stop_event set)
        self.on_become_master = None
        self.on_become_standby = None

    def is_master(self) -> bool:
        """Check if current pod is master"""
        with self.role_lock:
            return self.current_role == StandbyRole.MASTER

    def set_role(self, role: StandbyRole) -> None:
        """Set current pod role"""
        with self.role_lock:
            if self.current_role != role:
                old_role = self.current_role
                self.current_role = role
                logger.info(
                    "[Standby] Role changed from %s to %s (role shm updated for Mgmt readiness)",
                    old_role.value,
                    role.value,
                )
            if self.is_running and self._role_shm:
                self._write_role_shm(role)

    _ROLE_SHM_MASTER = 1
    _ROLE_SHM_STANDBY = 0
    _ROLE_SHM_SIZE = 1
    _ROLE_SHM_SIZE_WITH_HEARTBEAT = 9

    def _role_shm_has_heartbeat(self) -> bool:
        """True if heartbeat is enabled (Daemon writes bytes 1-8)."""
        return (
            self.config.standby_config.role_heartbeat_interval_sec > 0
            and self._role_shm is not None
            and len(self._role_shm.buf) >= self._ROLE_SHM_SIZE_WITH_HEARTBEAT
        )

    def _init_role_shm(self) -> None:
        """Create SharedMemory and write initial role (only in Daemon process after start()).
        If name already exists (e.g. previous Daemon crashed without unlink), attach and take over
        when existing size is sufficient; otherwise unlink and create new.
        """
        if not self._role_shm_name or self._role_shm is not None:
            return
        interval = self.config.standby_config.role_heartbeat_interval_sec
        needed_size = (
            self._ROLE_SHM_SIZE_WITH_HEARTBEAT if interval > 0 else self._ROLE_SHM_SIZE
        )
        try:
            self._role_shm = shared_memory.SharedMemory(
                name=self._role_shm_name, create=True, size=needed_size
            )
            self._write_role_shm(self.current_role)
            if needed_size >= self._ROLE_SHM_SIZE_WITH_HEARTBEAT:
                logger.info(
                    "[Standby] Role shm created with heartbeat: name=%s size=%s (Mgmt can detect Daemon liveness)",
                    self._role_shm_name,
                    needed_size,
                )
            logger.debug(
                "[Standby] Role shm created: name=%s, initial_role=%s, size=%s",
                self._role_shm_name,
                self.current_role.value,
                needed_size,
            )
        except FileExistsError:
            try:
                existing = shared_memory.SharedMemory(
                    name=self._role_shm_name,
                    create=False,
                )
                size = len(existing.buf)
                if size >= needed_size:
                    self._role_shm = existing
                    self._write_role_shm(self.current_role)
                    logger.info(
                        "[Standby] Role shm attached to existing: name=%s size=%s (take over after restart)",
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
                        name=self._role_shm_name, create=True, size=needed_size
                    )
                    self._write_role_shm(self.current_role)
                    logger.info(
                        "[Standby] Role shm created: name=%s size=%s (Mgmt can detect Daemon liveness)",
                        self._role_shm_name,
                        needed_size,
                    )
            except Exception as e2:
                logger.warning("Failed to attach to or recreate role shm %s: %s", self._role_shm_name, e2)
                self._role_shm = None
        except Exception as e:
            logger.warning("Failed to create role shm %s: %s", self._role_shm_name, e)
            self._role_shm = None

    def _write_role_shm(self, role: StandbyRole) -> None:
        """Write role byte (and optional heartbeat bytes 1-8) to shared memory for Mgmt."""
        if not self._role_shm:
            return
        try:
            byte_val = (
                self._ROLE_SHM_MASTER if role == StandbyRole.MASTER else self._ROLE_SHM_STANDBY
            )
            self._role_shm.buf[0] = byte_val
            if self._role_shm_has_heartbeat():
                ns = time.monotonic_ns()
                self._role_shm.buf[1:9] = struct.pack("<Q", ns)
            logger.debug(
                "[Standby] Role shm written: name=%s role=%s byte=%s",
                self._role_shm_name,
                role.value,
                byte_val,
            )
        except Exception as e:
            logger.warning("Failed to write role shm: %s", e)

    def _write_heartbeat_only(self) -> None:
        """Write only heartbeat bytes 1-8 (used by heartbeat thread)."""
        if not self._role_shm_has_heartbeat():
            return
        try:
            ns = time.monotonic_ns()
            self._role_shm.buf[1:9] = struct.pack("<Q", ns)
        except Exception as e:
            logger.warning("Failed to write role shm heartbeat: %s", e)

    def _heartbeat_loop(self) -> None:
        """Periodically write heartbeat to role shm so Mgmt can detect Daemon liveness."""
        interval = self.config.standby_config.role_heartbeat_interval_sec
        if interval <= 0:
            return
        while not self.stop_event.is_set():
            if self.stop_event.wait(timeout=interval):
                break
            self._write_heartbeat_only()

    def _master_standby_loop(self) -> None:
        """Master/standby management loop"""

        while not self.stop_event.is_set():
            try:
                if self.is_master():
                    # As master, renew lock
                    if not self._renew_master_lock():
                        logger.warning("Failed to renew master lock, becoming standby")
                        self.set_role(StandbyRole.STANDBY)
                        if self.on_become_standby:
                            self.on_become_standby()
                        continue
                else:
                    # As standby, try to become master
                    if self._try_become_master():
                        logger.info("Became master, starting modules")
                        if self.on_become_master:
                            self.on_become_master(self.etcd_client.get_bool(key="should_report_event"))
                            self.etcd_client.set_bool(key="should_report_event", value=True)
                    self.has_set_role = True

            except Exception as e:
                logger.error("Error in master/standby manager: %s", e)

            time.sleep(self.config.standby_config.master_standby_check_interval)

        # Thread is stopping, release master lock if we hold it and update role shm
        if self.is_master():
            self._release_master_lock()
            self.set_role(StandbyRole.STANDBY)
            logger.info("Master/standby manager thread stopped and released lock")

    def _renew_master_lock(self) -> bool:
        """Renew master lock lease"""
        if not self.is_master():
            return False

        try:
            return self.etcd_client.renew_lease(self.config.standby_config.master_lock_key)
        except Exception as e:
            logger.error(f"Error renewing master lock: {e}")
            return False

    def _release_master_lock(self) -> None:
        """Release master lock"""
        try:
            self.etcd_client.release_lock(self.config.standby_config.master_lock_key)
            logger.info("Released master lock")
        except Exception as e:
            logger.error(f"Error releasing master lock: {e}")

    def _try_become_master(self) -> bool:
        """Try to become master pod using ETCD lock with enhanced reliability"""
        consecutive_failures = 0

        while consecutive_failures < self.max_lock_failures and not self.stop_event.is_set():
            try:
                # Try to acquire master lock with increased TTL
                lease_id = self.etcd_client.acquire_lock(
                    lock_key=self.config.standby_config.master_lock_key,
                    ttl=self.lock_ttl
                )
                if lease_id:
                    self.set_role(StandbyRole.MASTER)
                    logger.info("Successfully became master with TTL %ds", self.lock_ttl)
                    return True
                else:
                    # Lock is held by another pod, remain standby
                    self.set_role(StandbyRole.STANDBY)
                    return False

            except Exception as e:
                consecutive_failures += 1
                logger.warning("Failed to acquire master lock (attempt %d/%d): %s",
                             consecutive_failures, self.max_lock_failures, e)

                if consecutive_failures < self.max_lock_failures:
                    # Wait before retrying, but allow interruption by stop_event
                    if self.stop_event.wait(self.lock_retry_interval):
                        # stop_event was set, exit the loop
                        break
                else:
                    logger.error("Max consecutive failures reached, giving up master acquisition")
                    self.set_role(StandbyRole.STANDBY)
                    return False

        return False