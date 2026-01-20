# coding=utf-8
# Copyright (c) 2025, HUAWEI CORPORATION.  All rights reserved.
from dataclasses import dataclass, field


@dataclass
class EtcdConfig:
    """ETCD configuration class"""

    # ETCD connection configuration
    etcd_host: str = 'etcd.default.svc.cluster.local'
    etcd_port: int = 2379
    etcd_timeout: int = 5

    # ETCD persistence configuration
    enable_etcd_persistence: bool = False  # Enable/disable ETCD persistence and restoration
