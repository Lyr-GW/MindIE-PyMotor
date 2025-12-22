#!/usr/bin/env python3
# coding=utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved.

from motor.common.resources import NodeManagerInfo, StartCmdMsg
from motor.common.utils.http_client import SafeHTTPSClient
from motor.common.utils.logger import get_logger


logger = get_logger(__name__)


class NodeManagerApiClient:

    @staticmethod
    def send_start_command(node_mgr: NodeManagerInfo, start_cmd_msg: StartCmdMsg) -> bool:
        is_succeed = True

        base_url = f"http://{node_mgr.pod_ip}:{node_mgr.port}"
        try:
            # For `superpod_id` we need to use `exclude_none` to avoid error,
            # when we use atlas A2 server which doesn't have superpod_id.
            client = SafeHTTPSClient(base_url)
            response = client.post(
                "/node-manager/start",
                data=start_cmd_msg.model_dump(exclude_none=True),
            )
            logger.info("Start command sent to node manager %s:%s for instance %s successfully.",
                        node_mgr.pod_ip, node_mgr.port, start_cmd_msg.job_name)
        except Exception as e:
            is_succeed = False
            logger.error("Error sending start command to node manager %s:%s for instance %s: %s",
                         node_mgr.pod_ip, node_mgr.port, start_cmd_msg.job_name, e)
        finally:
            client.close()

        return is_succeed

    @staticmethod
    def stop(node_mgr: NodeManagerInfo) -> bool:
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