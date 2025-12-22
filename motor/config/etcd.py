# coding=utf-8
# Copyright (c) 2025, HUAWEI CORPORATION.  All rights reserved.
from dataclasses import dataclass


@dataclass
class EtcdConfig:
    """ETCD configuration class"""

    # ETCD connection configuration
    etcd_host: str = 'etcd.default.svc.cluster.local'
    etcd_port: int = 2379
    etcd_timeout: int = 5

    # ETCD certificate configuration
    etcd_ca_cert: str | None = None
    etcd_cert_key: str | None = None
    etcd_cert_cert: str | None = None

    # ETCD persistence configuration
    enable_etcd_persistence: bool = False  # Enable/disable ETCD persistence and restoration
