# coding=utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved.

from motor.common.utils.http_client import SafeHTTPSClient
from motor.common.utils.logger import get_logger
from motor.config.coordinator import CoordinatorConfig

logger = get_logger(__name__)


class EngineServerApiClient:
    tls_config = CoordinatorConfig.from_json().mgmt_tls_config

    @staticmethod
    def query_metrics(address: str):
        client_args = EngineServerApiClient._generate_client_args(address)
        try:
            client = SafeHTTPSClient(timeout=2, **client_args)
            response = client.do_get("/metrics")
            if response.status_code == 200:
                data = response.text
                return data
            else:
                logger.warning(f"[Metrics] request metrics failed: code = {response.status_code}")
        except Exception as e:
            logger.warning(f"[Metrics] request metrics failed: {e}")

        return ""

    @classmethod
    def _generate_client_args(cls, address) -> dict[str, str]:
        client_ars = {
            "address": f"{address}",
            "tls_config": cls.tls_config,
        }
        return client_ars

