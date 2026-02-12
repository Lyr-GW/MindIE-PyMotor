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
import time
import threading
from typing import Any
from collections.abc import Callable
from kubernetes import client, config, watch

from motor.common.utils.logger import get_logger
from motor.controller.fault_tolerance.k8s.k8s_client import K8sClient
from motor.controller.fault_tolerance.k8s.cluster_fault_codes import NodeStatus, FaultInfo
from motor.controller.fault_tolerance.k8s.configmap_parser import (
    process_device_info,
    process_switch_info,
    process_manually_separate_npu,
    is_configmap_valid
)


logger = get_logger(__name__)


class ResourceMonitor:
    """
    Unified resource monitor for Node status and ConfigMap changes monitoring.

    This monitor combines Node and ConfigMap changes monitoring into a single interface,
    providing processed fault information and server status updates to fault manager.
    """

    def __init__(
        self,
        host_ip: str,
        namespace: str,
        configmap_name_prefix: str,
        node_change_handler: Callable[[NodeStatus, str], None] | None = None,
        configmap_change_handler: Callable[[list[FaultInfo], str], None] | None = None,
        retry_interval: int = 30
    ):
        """ Initialize Resource monitor for a specific host

        Args:
            host_ip: Host IP address to monitor
            namespace: Namespace for ConfigMap monitoring
            configmap_name_prefix: Prefix for ConfigMap name, will be combined with hostname
            node_change_handler: Handler for node status changes, NodeStatus, host_ip
            configmap_change_handler: Handler for processed fault info updates, list[FaultInfo]
            retry_interval: Retry interval in seconds for failed monitoring
        """
        self.host_ip = host_ip
        self.namespace = namespace
        self.configmap_name_prefix = configmap_name_prefix
        self.node_change_handler = node_change_handler
        self.configmap_change_handler = configmap_change_handler
        self.retry_interval = retry_interval

        self.stop_event = threading.Event()
        self.monitor_threads: list[threading.Thread] = []

        # Cache for last processed fault information for each ConfigMap
        self.last_fault_infos_cache: dict[str, list[FaultInfo]] = {}

        # Cache for last processed node status for each hostname
        self.last_node_status_cache: dict[str, NodeStatus] = {}

        # Initialize Kubernetes client for hostname lookup
        self.k8s_client = K8sClient()

        # Load Kubernetes configuration
        try:
            # Try to load in-cluster config (for Pod environment)
            config.load_incluster_config()
            logger.info("Loaded in-cluster Kubernetes config for Resource monitoring")
        except Exception as e:
            try:
                config.load_kube_config()
                logger.info("Loaded kubeconfig for Resource monitoring")
            except Exception as e2:
                logger.error("Failed to load Kubernetes config: %s, %s", e, e2)
                return

        self.v1 = client.CoreV1Api()

    @staticmethod
    def _get_node_ready_status(node) -> NodeStatus:
        """ Extract the ready status from a Node object """
        ready_condition = None
        if node.status.conditions:
            ready_condition = next(
                (condition for condition in node.status.conditions if condition.type == "Ready"), None
            )

        # Determine status based on Ready condition
        if ready_condition and ready_condition.status == "True":
            return NodeStatus.READY
        else:
            return NodeStatus.NOT_READY

    def start_monitoring(self) -> None:
        """ Start monitoring both Node and ConfigMap for this host """
        if not hasattr(self, 'v1') or self.v1 is None:
            logger.error("Resource monitoring not available for host %s", self.host_ip)
            return

        hostname = self.k8s_client.get_node_hostname_by_ip(self.host_ip)
        if hostname is None:
            logger.error("Cannot start Resource monitor for host %s: hostname not found", self.host_ip)
            return

        logger.info("Starting Resource monitor for host %s (%s)", self.host_ip, hostname)

        # Start Node monitoring thread
        node_thread = threading.Thread(
            target=self._monitor_node,
            daemon=True,
            name=f"ResourceMonitor-Node-{hostname}"
        )
        node_thread.start()
        self.monitor_threads.append(node_thread)
        logger.info("Started Node monitoring for %s", hostname)

        # Start ConfigMap monitoring thread
        configmap_name = f"{self.configmap_name_prefix}{hostname}"
        cm_thread = threading.Thread(
            target=self._monitor_configmap,
            args=(configmap_name,),
            daemon=True,
            name=f"ResourceMonitor-CM-{self.namespace}-{configmap_name}"
        )
        cm_thread.start()
        self.monitor_threads.append(cm_thread)
        logger.info("Started ConfigMap monitoring for %s/%s", self.namespace, configmap_name)

        logger.info("Resource monitor started for host %s", self.host_ip)

    def stop_monitoring(self) -> None:
        """ Stop monitoring for this host """
        logger.info("Stopping Resource monitor for host %s", self.host_ip)
        self.stop_event.set()

        # Wait for all monitoring threads to finish
        for thread in self.monitor_threads:
            if thread.is_alive():
                thread.join(timeout=5.0)
                if thread.is_alive():
                    logger.warning("Thread %s did not stop within timeout", thread.name)

        self.monitor_threads.clear()
        logger.info("Resource monitor stopped for host %s", self.host_ip)

    def is_alive(self) -> bool:
        """ Check if the Resource monitor is alive and functioning """
        # Check if Kubernetes client is available
        if not hasattr(self, 'v1') or self.v1 is None:
            return False

        # Check if stop event is set (monitor is stopping/stopped)
        if self.stop_event.is_set():
            return False

        # Check if we have monitoring threads and they are alive
        if not self.monitor_threads:
            return False

        # Check if at least one monitoring thread is alive
        return any(thread.is_alive() for thread in self.monitor_threads)

    def _monitor_node(self) -> None:
        """ Monitor Node status changes for this host """
        hostname = self.k8s_client.get_node_hostname_by_ip(self.host_ip)
        if hostname is None:
            logger.error("Cannot monitor Node for host %s: hostname not found", self.host_ip)
            return

        while not self.stop_event.is_set():
            try:
                w = watch.Watch()

                # Monitor Node changes
                for event in w.stream(self.v1.list_node,
                                      field_selector=f"metadata.name={hostname}"):
                    if self.stop_event.is_set():
                        w.stop()
                        break

                    event_type = event['type']
                    node = event['object']

                    self._handle_node_change(event_type, node)

            except Exception as e:
                logger.error("Error monitoring Node %s: %s", hostname, e)
                if not self.stop_event.is_set():
                    logger.info("Retrying Node monitoring in %s seconds...", self.retry_interval)
                    time.sleep(self.retry_interval)

    def _monitor_configmap(self, configmap_name: str) -> None:
        """ Monitor ConfigMap changes for this host """
        while not self.stop_event.is_set():
            try:
                w = watch.Watch()

                # Monitor ConfigMap changes
                for event in w.stream(self.v1.list_namespaced_config_map,
                                      namespace=self.namespace,
                                      field_selector=f"metadata.name={configmap_name}"):
                    if self.stop_event.is_set():
                        w.stop()
                        break

                    event_type = event['type']
                    configmap = event['object']

                    self._handle_configmap_change(event_type, configmap, configmap_name)

            except Exception as e:
                logger.error("Error monitoring ConfigMap %s/%s: %s",
                             self.namespace, configmap_name, e)
                if not self.stop_event.is_set():
                    logger.info("Retrying ConfigMap monitoring in %s seconds...", self.retry_interval)
                    time.sleep(self.retry_interval)

    def _handle_node_change(self, event_type: str, node) -> None:
        """ Handle Node change events and call the node change handler
        Args:
            event_type: Event type ('ADDED', 'MODIFIED', 'DELETED')
            node: Node object
        """
        logger.debug("Node %s: %s", event_type, node.metadata.name)

        # Determine node ready status
        node_status = self._get_node_ready_status(node)

        # Call the node change handler
        hostname = self.k8s_client.get_node_hostname_by_ip(self.host_ip)
        if self.node_change_handler:
            try:
                if event_type in ['ADDED', 'MODIFIED']:
                    # Check if node status has actually changed (ignore duplicate status updates)
                    node_key = node.metadata.name  # Use node name as cache key
                    if self._has_node_status_changed(node_key, node_status):
                        logger.info("Node %s status changed to: %s", hostname or self.host_ip, node_status)
                        self.last_node_status_cache[node_key] = node_status  # Update cache
                        self.node_change_handler(node_status, self.host_ip)
                    else:
                        logger.debug("Node status unchanged, skipping duplicate processing")
                elif event_type == 'DELETED':
                    logger.warning("Node %s was deleted", node.metadata.name)
                    # Node deletion is always processed (reset cache)
                    self.last_node_status_cache.pop(node.metadata.name, None)
                    # Node deleted means not ready
                    self.node_change_handler(NodeStatus.NOT_READY, self.host_ip)

            except Exception as e:
                logger.error("Error in node status change handler for %s: %s", hostname or self.host_ip, e)
        else:
            logger.warning("No node change handler configured for host %s", self.host_ip)

    def _handle_configmap_change(self, event_type: str, configmap, configmap_name: str) -> None:
        """
        Handle ConfigMap change events, process the data, and call the configmap change handler

        Args:
            event_type: Event type ('ADDED', 'MODIFIED', 'DELETED')
            configmap: ConfigMap object
        """
        cm_metadata = configmap.metadata
        logger.debug("ConfigMap %s: %s in %s", event_type, cm_metadata.name, cm_metadata.namespace)

        # Call the configmap change handler with processed data
        if self.configmap_change_handler:
            try:
                if event_type in ['ADDED', 'MODIFIED']:
                    data = configmap.data or {}
                    logger.debug("ConfigMap %s changed! changed data keys: %s",
                                 cm_metadata.name, list(data.keys()))

                    # Process ConfigMap data to check for changes and handle
                    fault_infos = self._process_configmap_data(data)

                    # Check if fault information has actually changed (ignore time-only updates)
                    if self._has_fault_info_changed(configmap_name, fault_infos):
                        logger.info("Fault information changed, processing ConfigMap update")
                      
                        self.last_fault_infos_cache[configmap_name] = fault_infos.copy()  # Update cache
                        self.configmap_change_handler(fault_infos, self.host_ip)
                    else:
                        logger.debug("Fault information unchanged, skipping duplicate processing")
                elif event_type == 'DELETED':
                    logger.warning("ConfigMap %s was deleted", cm_metadata.name)
                    # ConfigMap deleted means no fault information available
                    self.last_fault_infos_cache.pop(configmap_name, None)  # Reset cache on deletion
                    self.configmap_change_handler([], self.host_ip)

            except Exception as e:
                logger.error("Error in configmap change handler for %s: %s", cm_metadata.name, e)
        else:
            logger.warning("No configmap change handler configured for host %s", self.host_ip)

    def _has_fault_info_changed(self, configmap_name: str, new_fault_infos: list[FaultInfo]) -> bool:
        """
        Check if the fault information has actually changed compared to the last processed data for this ConfigMap.
        Will return True if fault information has changed or this is the first time processing this ConfigMap.
        """
        last_fault_infos = self.last_fault_infos_cache.get(configmap_name)
        if last_fault_infos is None:
            return True  # First time processing this ConfigMap

        # Compare fault info lists (FaultInfo is a dataclass, so we can compare directly)
        if len(new_fault_infos) != len(last_fault_infos):
            return True  # Different number of faults

        # Sort both lists by fault attributes for consistent comparison
        def sort_key(fault: FaultInfo) -> tuple:
            return (fault.fault_type, fault.npu_name, fault.fault_code, fault.fault_level)

        sorted_new = sorted(new_fault_infos, key=sort_key)
        sorted_last = sorted(last_fault_infos, key=sort_key)

        return sorted_new != sorted_last

    def _has_node_status_changed(self, hostname: str, new_node_status: NodeStatus) -> bool:
        """
        Check if the node status has actually changed compared to the last processed status for this hostname.
        Will return True if node status has changed or this is the first time processing this hostname.
        """
        last_node_status = self.last_node_status_cache.get(hostname)
        if last_node_status is None:
            return True  # First time processing this hostname

        return new_node_status != last_node_status

    def _process_configmap_data(self, config_data: dict[str, Any]) -> list[FaultInfo]:
        """ Process ConfigMap configuration data and extract fault information """
        fault_infos = []

        try:
            # Handle configuration format with DeviceInfoCfg, SwitchInfoCfg, ManuallySeparateNPU
            if is_configmap_valid(config_data):
                # Process DeviceInfoCfg
                device_info_cfg = config_data.get('DeviceInfoCfg', '')
                if device_info_cfg:
                    device_fault_infos = process_device_info(device_info_cfg)
                    fault_infos.extend(device_fault_infos)
                    logger.debug("Processed %d device fault infos from DeviceInfoCfg",
                                 len(device_fault_infos))

                # Process SwitchInfoCfg
                switch_info_cfg = config_data.get('SwitchInfoCfg', '')
                if switch_info_cfg:
                    switch_fault_infos = process_switch_info(switch_info_cfg)
                    fault_infos.extend(switch_fault_infos)
                    logger.debug("Processed %d switch fault infos from SwitchInfoCfg",
                                 len(switch_fault_infos))

                # Process ManuallySeparateNPU (for future use, not added to fault_infos)
                manually_separate_npu = config_data.get('ManuallySeparateNPU', '')
                if manually_separate_npu:
                    separated_ranks = process_manually_separate_npu(manually_separate_npu)
                    logger.info("Processed manually separated NPU ranks: %s", separated_ranks)
                    # Note: Manually separated NPUs are not treated as faults here
                    # They may be handled separately by the fault manager
            else:
                logger.debug("ConfigMap data is not in expected configuration format")

        except Exception as e:
            logger.error("Error processing ConfigMap data for host %s: %s", self.host_ip, e)

        logger.debug("Total processed %d fault infos for host %s", len(fault_infos), self.host_ip)
        return fault_infos
