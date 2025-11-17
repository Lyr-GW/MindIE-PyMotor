# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2012-2020. All rights reserved.
from enum import Enum
from motor.common.resources.instance import Instance, PDRole
from motor.common.resources.endpoint import Endpoint, WorkloadAction
from motor.coordinator.scheduler.base_scheduling_policy import BaseSchedulingPolicy
from motor.coordinator.scheduler.round_robin_policy import RoundRobinPolicy
from motor.coordinator.scheduler.load_balance_policy import LoadBalancePolicy
from motor.common.utils.logger import get_logger

logger = get_logger(__name__)


class SchedulingPolicyType(Enum):
    ROUND_ROBIN = "round_robin"
    LOAD_BALANCE = "load_balance"


class SchedulingPolicyFactory:
    """
    Factory class for creating scheduling policy instances.
    """

    @staticmethod
    def create_scheduling_policy(policy_type: SchedulingPolicyType | str) -> BaseSchedulingPolicy:
        """
        Create a scheduling policy instance based on the specified policy type.
        
        Args:
            policy: The scheduling policy to use
            
        Returns:
            A scheduler instance
        """
        policy_type_str = policy_type.value if isinstance(policy_type, SchedulingPolicyType) else policy_type

        if policy_type_str == SchedulingPolicyType.ROUND_ROBIN.value:
            return RoundRobinPolicy()
        elif policy_type_str == SchedulingPolicyType.LOAD_BALANCE.value:
            return LoadBalancePolicy()
        else:
            logger.error(f"Unsupported scheduling policy: {policy_type_str}")
            raise ValueError(f"Unsupported scheduling policy: {policy_type_str}")


class Scheduler:
    """
    Main scheduler class that acts as a facade for different scheduling algorithms.
    """

    def __init__(self, policy_type: SchedulingPolicyType | str = SchedulingPolicyType.ROUND_ROBIN):
        self._scheduling_policy: BaseSchedulingPolicy = SchedulingPolicyFactory.create_scheduling_policy(policy_type)
        self._policy_type = policy_type

    def set_scheduling_policy(self, policy_type: SchedulingPolicyType | str) -> None:
        """
        Set the current scheduler instance.
        
        Args:
            policy: The scheduler type to use
        """
        self._scheduling_policy = SchedulingPolicyFactory.create_scheduling_policy(policy_type)
        self._policy_type = policy_type
        logger.info(f"Scheduling policy type changed to {policy_type}")
    
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