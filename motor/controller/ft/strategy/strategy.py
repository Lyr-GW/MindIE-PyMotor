# coding=utf-8
# Copyright (c) 2025, HUAWEI CORPORATION.  All rights reserved.

from abc import ABC, abstractmethod
import threading
from collections.abc import Callable


class StrategyBase(ABC):
    """Strategy base class"""

    def __init__(self) -> None:
        self.event = threading.Event()
        self.name = self.__class__.__name__
        self._is_finished = False
        self._lock = threading.Lock()
    
    @abstractmethod
    def execute(self, instance_id: int):
        """
        Execute the strategy with the instance id.
        """
        raise NotImplementedError

    @abstractmethod
    def stop(self) -> None:
        raise NotImplementedError
    
    def is_finished(self) -> bool:
        with self._lock:
            return self._is_finished


def general_level0_strategy(fault_code: int, instance_id: int) -> type[StrategyBase] | None:
    "level0 means healthy, so no strategy is needed."
    return None


def general_level1_strategy(fault_code: int, instance_id: int) -> type[StrategyBase] | None:
    return None


def specific_level2_strategy(fault_code: int, instance_id: int) -> type[StrategyBase] | None:
    # Only handle whitelisted fault codes for L2 strategy
    if fault_code in [0x00f1fef5, 0x08520003]:
        from motor.controller.ft.strategy.lingqu_network_recover import LingquNetworkRecoverStrategy
        return LingquNetworkRecoverStrategy
    else:
        return None


def general_level3_to_level6_strategy(fault_code: int, instance_id: int) -> type[StrategyBase]:
    from motor.controller.core.instance_manager import InstanceManager
    from motor.controller.ft.strategy.scale_p2d import ScaleP2DStrategy
    instance = InstanceManager().get_instance(instance_id)
    if instance is not None and instance.role == "decode":
        return ScaleP2DStrategy
    else:
        return None
    

def generate_strategy_map() -> dict[str, Callable[[int], type[StrategyBase] | None] | None]:
    return {
        "L0": general_level0_strategy,
        "L1": general_level1_strategy,
        "L2": specific_level2_strategy,
        "L3": general_level3_to_level6_strategy,
        "L4": general_level3_to_level6_strategy,
        "L5": general_level3_to_level6_strategy,
        "L6": general_level3_to_level6_strategy,
    }