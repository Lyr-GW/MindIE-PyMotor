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
from threading import Lock
from motor.common.resources.instance import Instance, PDRole
from motor.common.resources.endpoint import Endpoint
from motor.common.utils.singleton import ThreadSafeSingleton
from motor.coordinator.scheduler.base_scheduling_policy import BaseSchedulingPolicy
from motor.coordinator.core.instance_manager import InstanceManager
from motor.common.utils.logger import get_logger

logger = get_logger(__name__)


class RoundRobinPolicy(BaseSchedulingPolicy, ThreadSafeSingleton):
    """
    Round Robin Scheduler Policy implementation.
    Selects instances and endpoints in a round-robin fashion.
    """

    def __init__(self):
        # If the round-robin policy is already initialized, return.
        if hasattr(self, '_initialized'):
            return
        self._initialized = True
        super().__init__()
        self._instance_rr_counters: dict[PDRole, int] = {}
        self._endpoint_rr_counters: dict[int, int] = {}
        self._instance_lock = Lock()  # Lock for instance counters
        self._endpoint_lock = Lock()  # Lock for endpoint counters
        logger.info("RoundRobinPolicy started.")

    def _select_instance(self, role: PDRole = None) -> Instance | None:
        """
        Select an instance using round-robin algorithm.
        
        Args:
            role: Optional PDRole to filter instances by role
            
        Returns:
            Selected Instance or None if no instance available
        """
        active_instances = list(InstanceManager().get_available_instances(role).values())
        if not active_instances:
            logger.warning("No active instances available for scheduling")
            return None

        # Initialize counter for this role if not exists
        if role not in self._instance_rr_counters:
            self._instance_rr_counters[role] = 0

        # Thread-safe counter operations for read-modify-write
        with self._instance_lock:
            # Round-robin selection for this specific role
            counter = self._instance_rr_counters[role]
            selected_instance = active_instances[counter % len(active_instances)]
            self._instance_rr_counters[role] = (counter + 1) % len(active_instances)
        return selected_instance

    def _select_endpoint(self, instance: Instance) -> Endpoint | None:
        """
        Select an endpoint from the given instance using round-robin algorithm.
        
        Args:
            instance: The instance to select an endpoint from
            
        Returns:
            Selected Endpoint or None if no endpoint available
        """
        if not instance:
            logger.warning("No instance provided for endpoint selection")
            return None

        all_endpoints = instance.get_all_endpoints()
        if not all_endpoints:
            logger.warning(f"No endpoints available in instance {instance.id}")
            return None

        # Counter for each instance
        if instance.id not in self._endpoint_rr_counters:
            self._endpoint_rr_counters[instance.id] = 0
        
        # Thread-safe counter operations for read-modify-write
        with self._endpoint_lock:
            # Round-robin selection among endpoints
            endpoint_counter = self._endpoint_rr_counters[instance.id]
            selected_endpoint = all_endpoints[endpoint_counter % len(all_endpoints)]
            self._endpoint_rr_counters[instance.id] = (endpoint_counter + 1) % len(all_endpoints)
        return selected_endpoint