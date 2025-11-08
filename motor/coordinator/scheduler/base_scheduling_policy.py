# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2012-2020. All rights reserved.
from abc import ABC, abstractmethod
from motor.resources.instance import Instance, PDRole
from motor.resources.endpoint import Endpoint
from motor.utils.logger import get_logger

logger = get_logger(__name__)


class BaseSchedulingPolicy(ABC):
    """
    Abstract base class for all scheduler policies.
    Defines the interface that all scheduler policies must implement.
    """
    @abstractmethod
    def _select_instance(self, role: PDRole = None) -> Instance | None:
        """
        Select the best instance based on the scheduling algorithm.
        
        Args:
            role: Optional PDRole to filter instances by role (prefill/decode)
            
        Returns:
            Selected Instance or None if no instance available
        """
        raise NotImplementedError("Subclasses must implement select_instance method")

    @abstractmethod
    def _select_endpoint(self, instance: Instance) -> Endpoint | None:
        """
        Select the best endpoint from the given instance based on the scheduling algorithm.
        
        Args:
            instance: The instance to select an endpoint from
            
        Returns:
            Selected Endpoint or None if no endpoint available
        """
        raise NotImplementedError("Subclasses must implement select_endpoint method")

    def select_instance_and_endpoint(self, role: PDRole = None) -> Instance | None:
        """
        Select an instance and endpoint based on the current scheduling algorithm.
        
        Args:
            role: Optional PDRole to filter instances by role (prefill/decode)
            
        Returns:
            Selected Instance or None if no instance available
        """
        instance = self._select_instance(role)
        endpoint = self._select_endpoint(instance)
        return instance, endpoint