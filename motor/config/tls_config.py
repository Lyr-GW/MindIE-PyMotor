# coding=utf-8
# Copyright (c) 2025, HUAWEI CORPORATION.  All rights reserved.
from dataclasses import dataclass


@dataclass
class TLSConfig:
    """TLS configuration class"""

    # TLS enable/disable
    tls_enable: bool = True

    # certificate paths
    ca_file: str = 'security/mgmt/cert/ca.crt'
    cert_file: str = 'security/mgmt/cert/server.crt'
    key_file: str = 'security/mgmt/keys/server.key'
    passwd_file: str = 'security/mgmt/keys/key_pwd.txt'
    crl_file: str = ''

    @classmethod
    def from_dict(cls, config_dict):
        """Update configuration object fields from dictionary, only for existing keys"""
        return cls(**{k: v for k, v in config_dict.items() if k in cls.__dataclass_fields__})