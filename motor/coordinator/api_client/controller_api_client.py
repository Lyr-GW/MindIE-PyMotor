#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2025-2026. All rights reserved.
# MindIE is licensed under Mulan PSL v2.
# You can use this software according to the terms and conditions of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
#         http://license.coscl.org.cn/MulanPSL2
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the Mulan PSL v2 for more details.

from typing import Dict

from motor.common.utils.http_client import SafeHTTPSClient
from motor.common.utils.logger import get_logger
from motor.config.controller import ControllerConfig
from motor.config.coordinator import CoordinatorConfig

logger = get_logger(__name__)


class ControllerApiClient:
    controller_config = ControllerConfig.from_json()
    coordinator_config = CoordinatorConfig.from_json()

    @staticmethod
    def terminate_instance(params: Dict[str, str]):
        # Read config values under lock protection
        client_args = {}
        try:
            client_args = ControllerApiClient._generate_client_args()
            with SafeHTTPSClient(timeout=5, **client_args) as client:
                response = client.do_post("/controller/terminate-instance", params)
                logger.info("Terminate instance success!")
                return response.status_code == 200
        except Exception as e:
            logger.error(
                "Exception occurred while terminating instance at %s: %s",
                client_args.get('address', 'unknown'), e
            )
            return False

    @staticmethod
    def report_alarms(params: Dict[str, str]):
        client_args = {}
        try:
            client_args = ControllerApiClient._generate_client_args()
            with SafeHTTPSClient(timeout=5, **client_args) as client:
                response = client.do_post("/v1/alarm/coordinator", params)
                logger.info("Report alarms success!")
                return response.status_code == 200
        except Exception as e:
            logger.error(
                "Exception occurred while reporting alarms at %s: %s",
                client_args.get('address', 'unknown'), e
            )
            return False

    @classmethod
    def _generate_client_args(cls) -> dict[str, str]:
        api_config = cls.controller_config.api_config
        tls_config = cls.coordinator_config.mgmt_tls_config
        address = f"{api_config.controller_api_dns}:{api_config.controller_api_port}"
        client_ars = {
            "address": f"{address}",
            "tls_config": tls_config
        }
        return client_ars