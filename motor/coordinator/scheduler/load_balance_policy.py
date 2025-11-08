# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2012-2020. All rights reserved.
from motor.resources.instance import Instance, PDRole
from motor.resources.endpoint import Endpoint, Workload, WorkloadAction
from motor.utils.singleton import ThreadSafeSingleton
from motor.coordinator.scheduler.base_scheduling_policy import BaseSchedulingPolicy
from motor.coordinator.core.instance_manager import InstanceManager
from motor.utils.logger import get_logger

logger = get_logger(__name__)


class LoadBalancePolicy(BaseSchedulingPolicy, ThreadSafeSingleton):
    """
    Load Balance Scheduler Policy implementation.
    Selects instances and endpoints based on their current workload.
    """
    def __init__(self):
        # If the load-balance policy is already initialized, return.
        if hasattr(self, '_initialized'):
            return
        self._initialized = True
        super().__init__()
        self.req_workload_dict: dict[tuple[str, PDRole], Workload] = {}
        logger.info("LoadBalancePolicy started.")

    def update_workload(self, instance: Instance, endpoint: Endpoint, req_id: str,
                        workload_action: WorkloadAction, request_length: int) -> bool:
        """
        Update workload information for load-aware scheduling.
        
        Args:
            instance: The instance being used
            endpoint: The endpoint being used
            req_id: Request identifier
            workload_action: Workload action type
            request_length: Length of the request
            
        Returns:
            True if workload was updated successfully, False otherwise
        """
        
        # Handle different workload actions
        if workload_action == WorkloadAction.ALLOCATION:
            return self._handle_allocation(instance, endpoint, req_id, request_length)
        elif workload_action == WorkloadAction.RELEASE_KV:
            return self._handle_release_kv(instance, endpoint, req_id)
        elif workload_action == WorkloadAction.RELEASE_TOKENS:
            return self._handle_release_tokens(instance, endpoint, req_id)
        else:
            logger.warning(f"Unknown workload action {workload_action}")
            return False
    
    def _select_instance(self, role: PDRole = None) -> Instance | None:
        """
        Select an instance with the least workload.
        
        Args:
            role: Optional PDRole to filter instances by role
            
        Returns:
            Selected Instance or None if no instance available
        """
        active_instances = InstanceManager().get_available_instances(role)
        if not active_instances:
            logger.warning("No active instances available for scheduling")
            return None

        # Dynamic load balancing - select instance with minimum workload
        min_workload = float('inf')
        selected_instance = None
        
        for instance in active_instances.values():
            # Calculate total workload for this instance
            workload_score = instance.gathered_workload.calculate_workload_score(role=instance.role)
            if workload_score < min_workload:
                min_workload = workload_score
                selected_instance = instance
                
        return selected_instance

    def _select_endpoint(self, instance: Instance) -> Endpoint | None:
        """
        Select an endpoint with the least workload from the given instance.
        
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

        # Dynamic load balancing - select endpoint with minimum workload
        min_workload = float('inf')
        selected_endpoint = None
        
        for endpoint in all_endpoints:
            # Consider both active requests and active KV cache for load calculation
            workload_score = endpoint.workload.calculate_workload_score(role=instance.role)
            if workload_score < min_workload:
                min_workload = workload_score
                selected_endpoint = endpoint
                
        return selected_endpoint
    
    def _handle_allocation(self, instance: Instance, endpoint: Endpoint, 
                          req_id: str, request_length: int) -> bool:
        """Handle workload allocation for a new request."""
        key = (req_id, instance.role)
        if key in self.req_workload_dict:
            logger.warning(f"Request {req_id} already allocated for role {instance.role}, allocation ignored")
            return False
            
        allocate_workload = self._calculate_demand_workload(instance.role, request_length)
        InstanceManager().update_instance_workload(instance.id, endpoint, allocate_workload)
        self.req_workload_dict[key] = allocate_workload
        
        logger.info(f"Request {req_id} allocated: kv={allocate_workload.active_kv_cache}, "
                   f"tokens={allocate_workload.active_tokens} for role {instance.role}")
        return True

    def _handle_release_kv(self, instance: Instance, endpoint: Endpoint, req_id: str) -> bool:
        """Handle KV cache release for a request."""
        key = (req_id, instance.role)
        if key not in self.req_workload_dict:
            logger.warning(f"Request {req_id} not allocated for role {instance.role}, KV release ignored")
            return False
            
        current_workload = self.req_workload_dict[key]
        release_workload = Workload(active_kv_cache=-current_workload.active_kv_cache)
        
        InstanceManager().update_instance_workload(instance.id, endpoint, release_workload)
        
        # Update local workload tracking
        current_workload.active_kv_cache = 0
        
        # Check if request can be fully removed
        if current_workload.active_tokens <= 0:
            self.req_workload_dict.pop(key)
            logger.info(f"Request {req_id} released KV {release_workload.active_kv_cache}, "
                       f"all workload released for role {instance.role}")
        else:
            logger.info(f"Request {req_id} released KV {release_workload.active_kv_cache}, "
                       f"tokens {current_workload.active_tokens} left for role {instance.role}")
        return True

    def _handle_release_tokens(self, instance: Instance, endpoint: Endpoint, req_id: str) -> bool:
        """Handle tokens release for a request."""
        key = (req_id, instance.role)
        if key not in self.req_workload_dict:
            logger.warning(f"Request {req_id} not allocated for role {instance.role}, tokens release ignored")
            return False
            
        current_workload = self.req_workload_dict[key]
        release_workload = Workload(active_tokens=-current_workload.active_tokens)
        
        InstanceManager().update_instance_workload(instance.id, endpoint, release_workload)
        
        # Update local workload tracking
        current_workload.active_tokens = 0
        
        # Check if request can be fully removed
        if current_workload.active_kv_cache <= 0:
            self.req_workload_dict.pop(key)
            logger.info(f"Request {req_id} released tokens {release_workload.active_tokens}, "
                       f"all workload released for role {instance.role}")
        else:
            logger.info(f"Request {req_id} released tokens {release_workload.active_tokens}, "
                       f"KV cache {current_workload.active_kv_cache} left for role {instance.role}")
        return True
    
    def _calculate_demand_workload(self, role: PDRole, request_length: int) -> Workload:
        """
        Calculate the workload score for the given role and request length.
        
        Args:
            role: PDRole enum indicating the role (prefill/decode/both)
            request_length: The length of the request
        """

        # Update endpoint workload
        if role == PDRole.ROLE_P:
            score = self._calculate_prefill_scores(request_length)
            return Workload(active_kv_cache=score, active_tokens=score)
        elif role == PDRole.ROLE_D:
            score = self._calculate_decode_scores(request_length)
            return Workload(active_tokens=score)
        elif role == PDRole.ROLE_U:
            score = self._calculate_both_scores(request_length)
            return Workload(active_kv_cache=score, active_tokens=score)
        else:
            logger.warning(f"Unknown role {role} for workload update")
            return Workload()
    
    def _calculate_prefill_scores(self, request_length: int) -> float:
        length_score = request_length / 4.0
        input_score = length_score * 0.0345 + 120.0745
        return input_score

    def _calculate_decode_scores(self, request_length: int) -> float:
        return request_length
    
    def _calculate_both_scores(self, request_length: int) -> float:
        prefill_score = self._calculate_prefill_scores(request_length)
        decode_score = self._calculate_decode_scores(request_length)
        input_score = (prefill_score + decode_score) * 0.5
        return input_score