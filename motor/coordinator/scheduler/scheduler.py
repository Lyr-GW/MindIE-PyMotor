# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2012-2020. All rights reserved.
from motor.common.resources.instance import Instance, PDRole
from motor.common.resources.endpoint import Endpoint, WorkloadAction
from motor.common.utils.singleton import ThreadSafeSingleton
from motor.common.utils.logger import get_logger
from motor.coordinator.scheduler.base_scheduling_policy import BaseSchedulingPolicy
from motor.coordinator.scheduler.round_robin_policy import RoundRobinPolicy
from motor.coordinator.scheduler.load_balance_policy import LoadBalancePolicy
from motor.config.coordinator import CoordinatorConfig, SchedulerType


logger = get_logger(__name__)


class Scheduler(ThreadSafeSingleton):
    """
    Main scheduler class that acts as a facade for different scheduling algorithms.
    """

    def __init__(self, config: CoordinatorConfig | SchedulerType | None = None):
        """
        Initialize the scheduler.
        
        Args:
            config: Can be:
                   - CoordinatorConfig object
                   - SchedulerType enum value
                   - None (uses default config)
        """
        # If the scheduler is already initialized, return.
        if hasattr(self, '_initialized'):
            return
        
        if config is None:
            config = CoordinatorConfig()
        
        if isinstance(config, SchedulerType):
            self._policy_type = config
        else:
            self._policy_type = config.scheduler_config.scheduler_type
        
        if self._policy_type == SchedulerType.ROUND_ROBIN:
            self._scheduling_policy = RoundRobinPolicy()
        elif self._policy_type == SchedulerType.LOAD_BALANCE:
            self._scheduling_policy = LoadBalancePolicy()
        else:
            logger.error(f"Unsupported scheduling policy: {self._policy_type}")
            raise ValueError(f"Unsupported scheduling policy: {self._policy_type}")

        self._initialized = True
        logger.info("Scheduler started.")
    
    def get_scheduling_policy(self) -> BaseSchedulingPolicy:
        """
        Get the current scheduling policy.
        
        Returns:
            Current scheduling policy
        """
        return self._scheduling_policy

    def select_instance_and_endpoint(self, role: PDRole = None) -> Instance | None:
        """
        Select an instance and endpoint based on the current scheduling algorithm.
        
        Args:
            role: Optional PDRole to filter instances by role (prefill/decode)
            
        Returns:
            Selected Instance or None if no instance available
        """
        return self._scheduling_policy.select_instance_and_endpoint(role)

    def update_workload(self, instance: Instance, endpoint: Endpoint, req_id: str,
                         workload_action: WorkloadAction, request_length: int) -> bool:
        """
        Update workload information for load-aware scheduling strategies.
        This method is only effective when using load-balancing strategies.
        
        Args:
            instance: The instance being used
            endpoint: The endpoint being used
            req_id: Request identifier
            workload_action: Workload action type
            request_length: Length of the request
            
        Returns:
            True if workload was updated successfully, False otherwise
        """
        if hasattr(self._scheduling_policy, 'update_workload'):
            return self._scheduling_policy.update_workload(instance, endpoint, req_id, workload_action, request_length)
        return True  # Ignore for strategies that don't support workload tracking