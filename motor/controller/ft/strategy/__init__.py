# Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved.

"""
Fault tolerance strategy module - contains fault recovery strategies.
"""

__all__ = [
    "StrategyBase",
    "generate_strategy_map",
    "ScaleP2DStrategy",
    "LingquNetworkRecoverStrategy",
]

from .strategy import StrategyBase, generate_strategy_map
from .scale_p2d import ScaleP2DStrategy
from .lingqu_network_recover import LingquNetworkRecoverStrategy
