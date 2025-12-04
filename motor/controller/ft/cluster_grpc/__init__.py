# Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved.

"""
Fault tolerance cluster gRPC module - contains gRPC client for cluster communication.
"""

__all__ = [
    "ClusterNodeClient",
    "cluster_fault_pb2",
    "cluster_fault_pb2_grpc",
]

from .cluster_grpc_client import ClusterNodeClient
from . import cluster_fault_pb2
from . import cluster_fault_pb2_grpc
