# Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved.

"""
Fault tolerance module - contains fault detection and recovery mechanisms.
"""

__all__ = [
    # Fault management
    "FaultManager",
    "Status",
    "DeviceFaultInfo",
    "ServerMetadata",
    "InstanceMetadata",

    # Submodules
    "strategy",
    "cluster_grpc",
]

from .fault_manager import (
    FaultManager,
    Status,
    DeviceFaultInfo,
    ServerMetadata,
    InstanceMetadata,
)
from . import strategy
from . import cluster_grpc
