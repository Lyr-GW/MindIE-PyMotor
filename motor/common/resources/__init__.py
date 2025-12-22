# Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved.

"""
Common resources module - contains shared data models and specifications.
"""

__all__ = [
    # From http_msg_spec
    "RegisterMsg",
    "StartCmdMsg",
    "ReregisterMsg",
    "HeartbeatMsg",
    "TerminateInstanceMsg",
    "InsEventMsg",
    "EventType",
    # From instance
    "Instance",
    "PDRole",
    "ReadOnlyInstance",
    "InsStatus",
    "InsConditionEvent",
    "NodeManagerInfo",
    "ParallelConfig",
    # From endpoint
    "Endpoint",
    "Workload",
    "DeviceInfo",
    "EndpointStatus",
]

# Import from http_msg_spec
from .http_msg_spec import (
    RegisterMsg,
    StartCmdMsg,
    ReregisterMsg,
    HeartbeatMsg,
    TerminateInstanceMsg,
    InsEventMsg,
    EventType,
)

# Import from instance
from .instance import (
    Instance,
    PDRole,
    ReadOnlyInstance,
    InsStatus,
    InsConditionEvent,
    NodeManagerInfo,
    ParallelConfig,
)

# Import from endpoint
from .endpoint import (
    Endpoint,
    Workload,
    DeviceInfo,
    EndpointStatus,
)