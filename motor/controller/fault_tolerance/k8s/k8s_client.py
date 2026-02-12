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
from kubernetes import client, config

from motor.common.utils.logger import get_logger

logger = get_logger(__name__)


class K8sClient:
    """ Kubernetes client wrapper for common operations """
    def __init__(self):
        self.v1 = None
        try:
            # Try to load in-cluster config (for Pod environment)
            config.load_incluster_config()
            self.v1 = client.CoreV1Api()
            logger.info("Loaded in-cluster Kubernetes config")
        except Exception as e:
            try:
                config.load_kube_config()
                self.v1 = client.CoreV1Api()
                logger.info("Loaded kubeconfig")
            except Exception as e2:
                logger.warning("Failed to load Kubernetes config: %s, %s", e, e2)

    def get_node_hostname_by_ip(self, host_ip: str) -> str | None:
        """ Get Kubernetes node hostname by host IP """
        if self.v1 is None:
            logger.warning("Kubernetes client not available, cannot get node hostname")
            return None

        try:
            # List all nodes
            nodes = self.v1.list_node()
            for node in nodes.items:
                # Check node internal IP addresses
                addresses = node.status.addresses or []
                for address in addresses:
                    if address.type == "InternalIP" and address.address == host_ip:
                        # Return node name (hostname)
                        return node.metadata.name
            logger.warning("Node with IP %s not found in Kubernetes cluster", host_ip)
            return None
        except Exception as e:
            logger.error("Error getting node hostname for IP %s: %s", host_ip, e)
            return None

    def is_available(self) -> bool:
        """ Check if Kubernetes client is available and initialized """
        return self.v1 is not None