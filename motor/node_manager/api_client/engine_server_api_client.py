#!/usr/bin/env python3
# coding=utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved.

from motor.common.utils.http_client import SafeHTTPSClient
from motor.common.utils.logger import get_logger
from motor.config.node_manager import NodeManagerConfig

logger = get_logger(__name__)


class EngineServerApiClient:
    tls_config = NodeManagerConfig.from_json().mgmt_tls_config

    @staticmethod
    def query_status(address: str):
        client_args = EngineServerApiClient._generate_client_args(address)
        client = SafeHTTPSClient(**client_args, timeout=2)
        response = client.get("/status")
        logger.debug(f"Query engine server status success, "
                    f"response: {response}, "
                    f"address: {client_args['address']}")
        return response

    @classmethod
    def _generate_client_args(cls, address: str) -> dict[str, str]:
        client_ars = {
            "address": f"{address}",
            "tls_config": cls.tls_config
        }
        return client_ars

