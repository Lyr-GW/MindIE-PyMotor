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
import concurrent.futures
from typing import Any
from pydantic import BaseModel, Field, model_validator

from motor.config.controller import ControllerConfig
from motor.common.utils.logger import get_logger
from motor.common.utils.singleton import ThreadSafeSingleton
from motor.common.etcd.persistent_state import PersistentState
from motor.common.resources import Instance, ReadOnlyInstance
from motor.common.etcd.etcd_client import EtcdClient
from motor.controller.core import Observer, ObserverEvent, InstanceManager
from motor.controller.fault_tolerance.strategy import generate_strategy_map
from motor.controller.fault_tolerance.k8s.cluster_fault_codes import (
    FaultInfo, NodeStatus, FaultLevel, FaultType, SpecialFaultCode
)


logger = get_logger(__name__)


class NodeMetadata(BaseModel):
    """
    Each node metadata represents a node in the cluster.
    And An instance may have multiple nodes.

    We don't determine the node's status, we just use this
    node's device configmap info to update the node's status.
    And the `device_fulat_infos` is used to record the device faults
    of the node, if there is no device fault, it will be an empty dict.
    """
    pod_ip: str = Field(..., description="Pod IP address")
    host_ip: str = Field(..., description="Host IP address")
    instance_id: int = Field(..., description="Instance ID that this node belongs to")
    node_status: NodeStatus = Field(default=NodeStatus.READY, description="Node status")
    fault_infos: dict[int, FaultInfo] = Field(default_factory=dict,
                                              description="Fault information dictionary keyed by fault_code")


class InstanceMetadata(BaseModel):
    """
    Instance metadata for fault tolerance management.
    
    When an instance's nodes are faulty, we need to trigger
    the recovery function, we record the current strategy,
    strategy level and fault code. if the instance is healthy,
    we should try to stop the strategy.
    """
    instance_id: int = Field(..., description="Instance ID")
    fault_level: FaultLevel = Field(default=FaultLevel.HEALTHY, description="Current instance fault level")
    fault_code: int = Field(default=0x0, description="Fault code that trigger the current strategy")
    
    # Non-serializable fields (excluded from serialization)
    lock: Any = Field(default=None, exclude=True)
    # StrategyBase instance, using Any to avoid requiring arbitrary_types_allowed
    strategy: Any = Field(default=None, exclude=True)
    
    @model_validator(mode='after')
    def init_lock(self):
        """Initialize lock if not provided"""
        if self.lock is None:
            self.lock = threading.Lock()
        return self
    
    def model_dump(self, **kwargs) -> dict:
        """Override model_dump to exclude non-serializable fields"""
        return super().model_dump(exclude={'lock', 'strategy'}, **kwargs)


class FaultManager(ThreadSafeSingleton, Observer):
    """
    Fault tolerance manager for handling device and node faults in the cluster.

    This class monitors node statuses, processes fault messages from the cluster,
    and manages fault recovery strategies for instances. It implements the Observer
    pattern to respond to instance lifecycle events and coordinates with the
    InstanceManager for fault isolation and recovery.
    """

    def __init__(self, config: ControllerConfig | None = None) -> None:
        super().__init__()
        # If the fault manager is already initialized, return.
        if hasattr(self, '_initialized'):
            return

        if config is None:
            config = ControllerConfig()
        self.config = config

        # Manage all nodes's status with host_ip, when it comes a faulty node,
        # we firstly find out which instance this node belongs to,
        # and then use self.instances to find out all nodes in this instance.
        self.nodes: dict[str, NodeMetadata] = {}
        self.instances: dict[int, InstanceMetadata] = {}
        self.lock = threading.Lock()
        self.config_lock = threading.RLock()

        # Version control for data persistence
        self._data_version = 0
        self._version_lock = threading.Lock()

        # Extract required config fields
        with self.config_lock:
            self.etcd_config = config.etcd_config
            self.etcd_tls_config = config.etcd_tls_config
            self.strategy_center_check_interval = config.fault_tolerance_config.strategy_center_check_interval

        with self.config_lock:
            self.etcd_client = EtcdClient(etcd_config=self.etcd_config, tls_config=self.etcd_tls_config)

        self.stop_event = threading.Event()

        # For dual handle function trigger, we use a thread pool executor to handle it.
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=5)

        self.strategies = generate_strategy_map()

        self.ft_strategy_center_thread = None
        self._initialized = True
        logger.info("FaultManager initialized.")

    def start(self) -> None:
        """Start the fault tolerance threads"""
        # Reset stop_event if it was previously set (for singleton reuse)
        if self.stop_event.is_set():
            self.stop_event.clear()

        self.ft_strategy_center_thread = threading.Thread(
            target=self._ft_strategy_center,
            daemon=True,
            name="FaultToleranceStrategyCenter"
        )

        # Try to restore data from ETCD, if failed, it will start with empty state.
        with self.config_lock:
            enable_persistence = self.etcd_config.enable_etcd_persistence
        if enable_persistence and not self.restore_data():
            logger.warning("Failed to restore fault manager's data from ETCD, start with empty state")

        self.ft_strategy_center_thread.start()

        logger.info("FaultManager started.")

    def is_alive(self) -> bool:
        """ Check if the fault manager threads are alive """
        return (self.ft_strategy_center_thread is not None
                and self.ft_strategy_center_thread.is_alive())

    def stop(self) -> None:
        self.stop_event.set()

        # Only join threads that have been started
        if self.ft_strategy_center_thread is not None and self.ft_strategy_center_thread.is_alive():
            self.ft_strategy_center_thread.join()

        logger.info("FaultManager stopped.")

    def update_config(self, config: ControllerConfig) -> None:
        """ Update config for fault manager, only invoked by config watcher when config changed """
        with self.config_lock:
            self.config = config

            # Update config fields
            self.etcd_config = config.etcd_config
            self.etcd_tls_config = config.etcd_tls_config
            self.strategy_center_check_interval = config.fault_tolerance_config.strategy_center_check_interval

            # Update ETCD client with new configuration
            self.etcd_client = EtcdClient(etcd_config=self.etcd_config, tls_config=self.etcd_tls_config)

            logger.info("FaultManager configuration updated")

    def persist_data(self) -> bool:
        """Persist fault manager data to ETCD with version control and checksum.
        This func will trigger when:
        1. Node or Instance status changed
        2. Strategy created or updated
        3. Strategy completed
        """
        try:
            with self.lock:
                current_time = time.time()
                next_version = self._get_next_version()

                # Prepare fault manager data
                fault_data = {'nodes': {}, 'instances': {}}

                for host_ip, node_metadata in self.nodes.items():
                    fault_data['nodes'][host_ip] = node_metadata.model_dump(mode='json')
                for ins_id, ins_metadata in self.instances.items():
                    fault_data['instances'][str(ins_id)] = ins_metadata.model_dump(mode='json')
                logger.debug("Persisting fault manager data - full data: %s", fault_data)

                # Create persistent state with version control and checksum
                persistent_state = PersistentState(
                    data=fault_data,
                    version=next_version,
                    timestamp=current_time,
                    checksum=""  # Will be calculated
                )
                persistent_state.checksum = persistent_state.calculate_checksum()
                logger.debug("Persisting fault manager data - calculated checksum: %s, version: %s, timestamp: %s",
                             persistent_state.checksum, next_version, current_time)

                # Convert PersistentState to dict for etcd storage
                dict_data = {"state": persistent_state.model_dump()}
                logger.debug("Persistence data being saved to ETCD: %s", dict_data)

                success = self.etcd_client.persist_data("/controller/fault_manager", dict_data)
                if success:
                    logger.info("Successfully persisted fault manager data with version %d", next_version)
                return success

        except Exception as e:
            logger.error("Error persisting fault manager data: %s", e)
            return False

    def restore_data(self) -> bool:
        """Restore fault manager data from ETCD with version control and validation.
        This func will trigger when:
        1. FaultManager starts or restarts
        """
        try:
            persistent_states = self.etcd_client.restore_data("/controller/fault_manager", PersistentState)
            if persistent_states is None:
                logger.info("No fault manager data found in ETCD, starting with empty state")
                return True

            logger.info("Restoring fault manager data from ETCD")
            
            persistent_state = persistent_states.get("state")
            if persistent_state is None:
                logger.warning("Expected 'state' key not found in persistent states, found keys: %s",
                             list(persistent_states.keys()))
                return False

            if not isinstance(persistent_state, PersistentState):
                logger.error("Invalid persistent state format, expected PersistentState instance")
                return False

            # Validate data integrity
            if not persistent_state.is_valid():
                logger.error("Data integrity check failed for fault_manager, cannot restore")
                return False

            # Update data version
            self._data_version = max(self._data_version, persistent_state.version)
            with self.lock:
                self.nodes.clear()
                self.instances.clear()

                # Restore nodes and instances from data (already normalized from ETCD)
                nodes_data = persistent_state.data.get('nodes', {})
                for host_ip, node_dict in nodes_data.items():
                    self.nodes[host_ip] = NodeMetadata.model_validate(node_dict)

                instances_data = persistent_state.data.get('instances', {})
                for ins_id_str, ins_dict in instances_data.items():
                    ins_metadata = InstanceMetadata.model_validate(ins_dict)
                    self.instances[ins_metadata.instance_id] = ins_metadata
                    logger.debug("Restored instance %s", ins_id_str)

            logger.info("Successfully restored fault manager data: %d nodes, %d instances",
                        len(self.nodes), len(self.instances))
            return True
        except Exception as e:
            logger.error("Error restoring fault manager data: %s", e)
            return False

    def update_instances(self, instances: list[Instance]) -> None:
        """
        Update fault manager with existing instances, this func will be invoked 
        when fault manager is restarted and needs to catch up with existing instances.
        """
        logger.info("Updating fault manager with %d instances", len(instances))

        for instance in instances:
            logger.debug("Processing instance %s (id: %d)", instance.job_name, instance.id)

            # Get current node managers from instance
            current_node_managers = instance.get_node_managers()

            with self.lock:
                if instance.id in self.instances:
                    # Instance exists, check for node changes
                    current_host_ips = {node_mgr.host_ip for node_mgr in current_node_managers}
                    existing_nodes = {
                        host_ip: node
                        for host_ip, node in self.nodes.items()
                        if node.instance_id == instance.id
                    }
                    existing_host_ips = set(existing_nodes.keys())

                    # Remove nodes that are no longer in the instance
                    removed_host_ips = existing_host_ips - current_host_ips
                    for host_ip in removed_host_ips:
                        self.nodes.pop(host_ip, None)
                        logger.debug("Removed node %s from instance %d", host_ip, instance.id)

                    # Add new nodes
                    added_host_ips = current_host_ips - existing_host_ips
                    for node_mgr in current_node_managers:
                        if node_mgr.host_ip in added_host_ips:
                            self.nodes[node_mgr.host_ip] = NodeMetadata(
                                pod_ip=node_mgr.pod_ip,
                                host_ip=node_mgr.host_ip,
                                instance_id=instance.id,
                            )
                            logger.debug("Added new node %s to instance %d", node_mgr.host_ip, instance.id)
                else:
                    # Instance doesn't exist, add it
                    logger.debug("Adding new instance %d to fault manager", instance.id)
                    ins_metadata = InstanceMetadata(instance_id=instance.id)

                    node_metadatas = {}
                    for node_mgr in current_node_managers:
                        node_metadatas[node_mgr.host_ip] = NodeMetadata(
                            pod_ip=node_mgr.pod_ip,
                            host_ip=node_mgr.host_ip,
                            instance_id=instance.id,
                        )

                    self.instances[instance.id] = ins_metadata
                    self.nodes.update(node_metadatas)
                    logger.debug("Added instance %d with %d nodes", instance.id, len(node_metadatas))

    def update(self, instance: ReadOnlyInstance, event: ObserverEvent) -> None:
        logger.info("FaultManager update instance %s with event: %s.", instance.job_name, event)

        if event == ObserverEvent.INSTANCE_INITIAL:
            self._handle_instance_initial(instance)
        elif event == ObserverEvent.INSTANCE_REMOVED:
            self._handle_instance_removed(instance)

    def _handle_instance_initial(self, instance: ReadOnlyInstance) -> None:
        with self.lock:
            # Check if instance already exists, if so, skip adding
            if instance.id in self.instances:
                logger.debug("Instance %d already exists in fault manager, skipping add operation.",
                             instance.id)
                return

        current_node_managers = instance.get_node_managers()
        ins_metadata = InstanceMetadata(instance_id=instance.id)

        with self.lock:
            self.instances[instance.id] = ins_metadata

            # Process nodes: update existing ones or add new ones
            for node_mgr in current_node_managers:
                if node_mgr.host_ip in self.nodes:
                    # Node already exists, only update pod_ip and instance_id to preserve fault_infos
                    existing_node = self.nodes[node_mgr.host_ip]
                    existing_node.pod_ip = node_mgr.pod_ip
                    existing_node.instance_id = instance.id
                    logger.info("Updated existing node %s (pod_ip: %s -> %s, instance_id: %d -> %d)",
                                 node_mgr.host_ip, existing_node.pod_ip, node_mgr.pod_ip,
                                 existing_node.instance_id, instance.id)
                else:
                    # Node doesn't exist, create new one
                    self.nodes[node_mgr.host_ip] = NodeMetadata(
                        pod_ip=node_mgr.pod_ip,
                        host_ip=node_mgr.host_ip,
                        instance_id=instance.id,
                    )
                    logger.info("Added new node %s to instance %d", node_mgr.host_ip, instance.id)

    def _handle_instance_removed(self, instance: ReadOnlyInstance) -> None:
        # Find all nodes belonging to this instance
        instance_nodes = []
        with self.lock:
            if instance.id not in self.instances:
                return

            # Collect all nodes that belong to this instance
            for host_ip, node_metadata in self.nodes.items():
                if node_metadata.instance_id == instance.id:
                    instance_nodes.append((host_ip, node_metadata))

        # Stop Resource monitors for all hosts in the instance
        for host_ip, _ in instance_nodes:
            self._stop_resource_monitor_for_host(host_ip)

        with self.lock:
            # Remove all nodes belonging to this instance
            for host_ip, _ in instance_nodes:
                self.nodes.pop(host_ip, None)

            # Remove the instance
            self.instances.pop(instance.id, None)

    def _handle_fault_info_update(self, fault_infos: list[FaultInfo], host_ip: str) -> None:
        """ Process the (host_ip)node's fault information update from ResourceMonitor """
        # Get node metadata
        node_metadata = None
        with self.lock:
            node_metadata = self.nodes.get(host_ip)

        if node_metadata is None:
            logger.warning("Node with host_ip %s not found, cannot process fault info update", host_ip)
            return

        for idx, info in enumerate(fault_infos, start=1):
            npu_segment = f", NPU: {info.npu_name}" if info.npu_name else ""
            logger.info("Fault[%d/%d] detected - Type: %s%s, Code: 0x%x, Level: %s(%s)",
                        idx, len(fault_infos), info.fault_type.value, npu_segment,
                        info.fault_code, info.fault_level.name, info.origin_fault_level.value)
        # Update fault infos: preserve node_reboot faults (managed by node_change_handler)
        node_reboot_key = int(SpecialFaultCode.NODE_REBOOT)
        node_reboot_fault = node_metadata.fault_infos.get(node_reboot_key)

        # Clear all faults and add new faults from ConfigMap
        node_metadata.fault_infos.clear()
        for info in fault_infos:
            # Ensure fault_code is stored as int (not enum)
            node_metadata.fault_infos[int(info.fault_code)] = info

        # Restore node_reboot fault if it existed
        if node_reboot_fault:
            node_metadata.fault_infos[node_reboot_key] = node_reboot_fault

        logger.info("Updated node %s with %d fault infos (preserved node_reboot: %s)",
                    host_ip, len(fault_infos), node_reboot_fault is not None)

        # Refresh instance fault levels for the node that may have been updated
        self._refresh_instance_fault_level(node_metadata.instance_id)

    def _handle_node_status_update(self, status: NodeStatus, host_ip: str) -> None:
        """ Process Node status update from ResourceMonitor.  """
        logger.info("Processing Node status update: %s -> %s", host_ip, status)

        # Update node status
        with self.lock:
            if host_ip not in self.nodes:
                logger.warning("Node with host_ip %s not found, cannot process node info update", host_ip)
                return

            node_metadata = self.nodes[host_ip]
            old_status = node_metadata.node_status
            node_metadata.node_status = status
            logger.info("Updated node %s status to %s", host_ip, status)

            # Handle node_reboot fault based on status change
            if old_status != status:
                if status == NodeStatus.NOT_READY:
                    # Add node reboot fault
                    node_reboot_key = int(SpecialFaultCode.NODE_REBOOT)
                    node_reboot_fault = FaultInfo(
                        fault_type=FaultType.NODE_UNHEALTHY,
                        npu_name="",  # Empty for node faults
                        fault_code=SpecialFaultCode.NODE_REBOOT,
                        fault_level=FaultLevel.L6
                    )
                    self.nodes[host_ip].fault_infos[node_reboot_key] = node_reboot_fault

                    logger.info("Added node reboot fault for node %s", host_ip)
                elif status == NodeStatus.READY:
                    # Remove node reboot fault
                    node_reboot_key = int(SpecialFaultCode.NODE_REBOOT)
                    if node_reboot_key in self.nodes[host_ip].fault_infos:
                        del self.nodes[host_ip].fault_infos[node_reboot_key]
                        logger.info("Removed node reboot fault for node %s", host_ip)
                    else:
                        logger.debug("Node reboot fault not found for node %s", host_ip)

        self._refresh_instance_fault_level(node_metadata.instance_id)

    def _refresh_instance_fault_level(self, instance_id: int) -> None:
        """
        Refresh the fault level of the instance with the given instance_id.
        This is called after configuration updates that may have updated node fault_infos.
        """
        instance_metadata = None
        with self.lock:
            instance_metadata = self.instances.get(instance_id)
            if instance_metadata is None:
                logger.warning("Instance %d not found, skipping fault level refresh", instance_id)
                return

        # Find all nodes belonging to this instance that have fault infos
        instance_nodes = []
        with self.lock:
            for node_metadata in self.nodes.values():
                if node_metadata.instance_id == instance_id and len(node_metadata.fault_infos) > 0:
                    instance_nodes.append(node_metadata)

        # Evaluate the instance's nodes' fault level, and update the instance's fault level
        with instance_metadata.lock:
            if not instance_nodes:
                # No nodes with device faults, instance is healthy
                if instance_metadata.fault_level != FaultLevel.HEALTHY:
                    instance_metadata.fault_level = FaultLevel.HEALTHY
                    instance_metadata.fault_code = 0x0
                    logger.info("Instance %d reset to healthy state", instance_id)
                    # Recover instance from forced separation when it becomes healthy
                    InstanceManager().recover_instance(instance_id)
                return

            self._update_highest_fault_level(instance_nodes, instance_metadata)

            if instance_metadata.fault_level > FaultLevel.L2:
                InstanceManager().separate_instance(instance_id)
            else:
                # when fault level <= L2, try to revocer instance
                if InstanceManager().is_instance_separated(instance_id):
                    InstanceManager().recover_instance(instance_id)

        # Persist data after instance fault level update
        with self.config_lock:
            enable_persistence = self.etcd_config.enable_etcd_persistence
        if enable_persistence and not self.persist_data():
            logger.warning("Failed to persist fault manager data to ETCD after "
                            "instance fault level refresh for instance %d", instance_id)

    def _update_highest_fault_level(
        self,
        instance_nodes: list[NodeMetadata], 
        instance_metadata: InstanceMetadata
    ) -> None:
        """ Update the highest fault level among all nodes in an instance.
            Args:
                instance_nodes: List of node metadata belonging to the instance
                instance_metadata: Instance metadata to update
        """
        highest_fault_level = FaultLevel.HEALTHY
        highest_fault_info = None

        for node_metadata in instance_nodes:
            node_fault_info = self._eval_node_status(node_metadata.host_ip)
            if node_fault_info and node_fault_info.fault_level > highest_fault_level:
                highest_fault_level = node_fault_info.fault_level
                highest_fault_info = node_fault_info

        # Update instance fault level and code
        if instance_metadata.fault_level != highest_fault_level:
            instance_metadata.fault_level = highest_fault_level
            instance_metadata.fault_code = int(highest_fault_info.fault_code) if highest_fault_info else 0x0
            logger.info("Updated instance %d fault level to %s with code %s",
                        instance_metadata.instance_id, highest_fault_level,
                        hex(instance_metadata.fault_code) if instance_metadata.fault_code else '0x0')

    def _eval_node_status(self, host_ip: str) -> FaultInfo | None:
        with self.lock:
            node_metadata = self.nodes.get(host_ip)

        if node_metadata is None:
            logger.error("Node not found for host_ip: %s", host_ip)
            return None

        logger.debug("Found node metadata for host_ip %s: node_status=%s, fault_count=%d",
                     host_ip, node_metadata.node_status, len(node_metadata.fault_infos))

        # Check faults for all issues (including node_reboot faults)
        if len(node_metadata.fault_infos) == 0:
            logger.debug("Node %s has no fault infos", host_ip)
            return None

        # Evaluate all faults (device faults + node faults)
        highest_fault_level = FaultLevel.HEALTHY
        target_fault_info = None
        for fault_info in node_metadata.fault_infos.values():
            if fault_info.fault_level > highest_fault_level:
                highest_fault_level = fault_info.fault_level
                target_fault_info = fault_info

        logger.debug("Node %s highest fault level: %s, fault_code: %s",
                     host_ip, highest_fault_level,
                     f"0x{int(target_fault_info.fault_code):08x}" if target_fault_info else "None")
        return target_fault_info

    def _ft_strategy_center(self) -> None:
        logger.info("Fault tolerance strategy center started")
        while not self.stop_event.is_set():
            instance_ids = []
            with self.lock:
                instance_ids = list(self.instances.keys())

            logger.debug("Processing %d instances in strategy center", len(instance_ids))

            for instance_id in instance_ids:
                self._process_instance_strategy(instance_id)

            with self.config_lock:
                check_interval = self.strategy_center_check_interval
            time.sleep(check_interval)

        logger.info("Fault tolerance strategy center stopped")

    def _process_instance_strategy(self, ins_id: int) -> None:
        """
        This function will generate the instance's strategy base on the instance's fault level
        and fault code. If the current strategy is not None, it will check if the new strategy
        is the same as the current strategy. Below are the rules:

        1.SAME_LEVEL: check if the current strategy is finished, if it is finished,
                      it will reset the relative state.
        2.DIFFERENT_AND_UPGRADE: stop the current strategy and start the new strategy.
        3.DIFFERENT_AND_DOWNGRADE: do nothing.
        """
        logger.debug("Processing strategy for instance %d", ins_id)

        ins_metadata = None
        with self.lock:
            ins_metadata = self.instances.get(ins_id)
            if ins_metadata is None:
                logger.warning("Instance %d not found in instances dict", ins_id)
                return

        with ins_metadata.lock:
            # Use highest fault level and fault code to generate the new strategy for this instance
            fault_level, fault_code = ins_metadata.fault_level, ins_metadata.fault_code
            logger.debug("Instance %d current state: fault_level=%s, fault_code=0x%08x, has_strategy=%s",
                         ins_id, fault_level, fault_code, ins_metadata.strategy is not None)

            new_strategy_cls = self.strategies[fault_level](fault_code, ins_id, self.config)
            current_strategy = ins_metadata.strategy
            current_cls = current_strategy.__class__ if current_strategy is not None else None

            logger.debug("Instance %d strategy evaluation: current_cls=%s, new_cls=%s",
                         ins_id, current_cls.__name__ if current_cls else None,
                         new_strategy_cls.__name__ if new_strategy_cls else None)

            # Check if the new strategy is different from the current strategy
            if new_strategy_cls is not None:
                is_upgrade = False
                if current_strategy is None:
                    logger.info("Instance %d: No current strategy, will create new one", ins_id)
                    is_upgrade = True
                else:
                    if new_strategy_cls != current_cls:
                        logger.info("Instance %d: Strategy changed from %s to %s, stopping old strategy",
                                    ins_id, current_cls.__name__ if current_cls else "None",
                                    new_strategy_cls.__name__)
                        current_strategy.stop()
                        ins_metadata.strategy = None
                        is_upgrade = True
                    else:
                        logger.debug("Instance %d: Strategy unchanged (%s)", ins_id, current_cls.__name__)

                if is_upgrade:
                    new_strategy = new_strategy_cls()
                    logger.info("Instance %d: Starting new strategy %s with fault level %s and code 0x%08x",
                                ins_id, new_strategy_cls.__name__, fault_level, fault_code)
                    self.executor.submit(new_strategy.execute, ins_id)
                    ins_metadata.strategy = new_strategy

            # Check if the current strategy is finished, if it is finished, reset the relative state.
            if ins_metadata.strategy is not None:
                if ins_metadata.strategy.is_finished():
                    logger.info("Instance %d: Strategy %s finished, resetting instance state",
                                ins_id, ins_metadata.strategy.__class__.__name__)
                    ins_metadata.strategy = None
                    ins_metadata.fault_level = FaultLevel.HEALTHY
                    ins_metadata.fault_code = 0x0

                    # Active persistence whenever strategy completes
                    with self.config_lock:
                        enable_persistence = self.etcd_config.enable_etcd_persistence
                    if enable_persistence and not self.persist_data():
                        logger.warning("Failed to persist fault manager data to ETCD after "
                                       "strategy completion for instance %d", ins_id)
                else:
                    # New strategy and have unfinished strategy will both reach here.
                    logger.debug("Instance %d: Updating fault state to level=%s, code=0x%08x",
                                 ins_id, fault_level, fault_code)
                    ins_metadata.fault_level = fault_level
                    ins_metadata.fault_code = fault_code

    def _get_next_version(self) -> int:
        """ Get next data version for persistence """
        with self._version_lock:
            self._data_version += 1
            return self._data_version
