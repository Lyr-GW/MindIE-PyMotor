#!/usr/bin/env python3
# coding=utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved.

from motor.common.resources.instance import Instance, NodeManagerInfo
from motor.common.utils.http_client import SafeHTTPSClient
from motor.common.utils.logger import get_logger


logger = get_logger(__name__)


class NodeManagerApiClient:

    @staticmethod
    def start(self):
        pass


    @staticmethod
    def stop(node_mgr: NodeManagerInfo):
        is_succeed = True

        base_url = f"http://{node_mgr.pod_ip}:{node_mgr.port}"
        try:
            client = SafeHTTPSClient(base_url)
            response = client.post("/node-manager/stop", data={})
            logger.info(f"Stop command sent to node manager {node_mgr.pod_ip}:{node_mgr.port}")
        except Exception as e:
            is_succeed = False
            logger.error(f"Error sending stop command to node manager {node_mgr.pod_ip}:{node_mgr.port}, \
                        details: {e}")
        finally:
            client.close()

        return is_succeed