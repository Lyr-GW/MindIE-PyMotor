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

from dataclasses import dataclass

LOCK_SLASH = "/"


@dataclass
class StandbyConfig:
    """Standby (master/standby) configuration class"""

    # master/standby feature enable/disable
    enable_master_standby: bool = False

    # master/standby check interval in seconds
    master_standby_check_interval: int = 5

    # master lock lease TTL in seconds
    master_lock_ttl: int = 10

    # master lock retry interval in seconds
    master_lock_retry_interval: int = 5

    # max consecutive lock failures
    master_lock_max_failures: int = 3

    # master lock key path in ETCD
    # Note: controller and coordinator will automatically 
    # add "/controller/" and "/coordinator/" prefixes respectively
    master_lock_key: str = "/master_lock"

    # Shared memory name for role IPC (Daemon writes, Mgmt reads for /readiness).
    # When non-empty, coordinator Daemon creates SharedMemory with this name; Mgmt opens by name to read.
    # Default empty; coordinator config sets a name when needed. Controller does not use shm.
    role_shm_name: str = ""

    # Role shm heartbeat (Daemon liveness detection). See docs/design/standby-role-shm-heartbeat.md.
    # Daemon: write heartbeat every this many seconds; 0 = do not write heartbeat (shm stays 1 byte).
    role_heartbeat_interval_sec: float = 5.0
    # Mgmt: treat Daemon as dead if heartbeat not updated for this many seconds; 0 = do not check.
    # Should be >= 2*interval to avoid false 503.
    role_heartbeat_stale_sec: float = 10.0
