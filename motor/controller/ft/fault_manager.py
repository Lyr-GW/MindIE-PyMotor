# coding=utf-8
# Copyright (c) 2025, HUAWEI CORPORATION.  All rights reserved.

import time
import threading
import concurrent.futures
from enum import Enum
from dataclasses import dataclass, field

from motor.common.utils.logger import get_logger
from motor.common.utils.singleton import ThreadSafeSingleton
from motor.config.controller import ControllerConfig
from motor.common.resources.instance import Instance, ReadOnlyInstance, NodeManagerInfo
from motor.controller.core.observer import Observer, ObserverEvent
from motor.controller.core.instance_manager import InstanceManager, InsStatus
from motor.controller.ft.cluster_grpc import cluster_fault_pb2
from motor.controller.ft.cluster_grpc.cluster_grpc_client import ClusterNodeClient
from motor.controller.ft.strategy.strategy import StrategyBase, generate_strategy_map


logger = get_logger(__name__)


class Status(int, Enum):
    HEALTHY = 0
    SUB_HEALTHY = 1
    UNHEALTHY = 2


class FaultLevel(str, Enum):
    L0 = "L0"  # Healthy
    L1 = "L1"  # Level 1 fault
    L2 = "L2"  # Level 2 fault
    L3 = "L3"  # Level 3 fault
    L4 = "L4"  # Level 4 fault
    L5 = "L5"  # Level 5 fault
    L6 = "L6"  # Level 6 fault


def convert_protobuf_device_fault_info(pb_device_fault) -> "DeviceFaultInfo":
    """
    Convert protobuf DeviceFaultInfo to Python DeviceFaultInfo object.
    """
    def _extract_first_from_list_or_none(obj, attr_name: str):
        """Extract first element from a list attribute, or None if empty/invalid."""
        attr_list = getattr(obj, attr_name, [])
        return attr_list[0] if attr_list else None

    # Extract fault codes and convert to int if possible
    fault_codes = getattr(pb_device_fault, 'faultCodes', [])
    fault_code = 0x0
    if fault_codes:
        # Try to convert first fault code to int, default to 0x0 if fails
        try:
            fault_code = int(fault_codes[0], 16) if fault_codes[0].startswith('0x') else int(fault_codes[0])
        except (ValueError, IndexError):
            fault_code = 0x0

    # Convert fault level string to enum
    fault_level_str = getattr(pb_device_fault, 'faultLevel', 'L1')
    try:
        fault_level = FaultLevel(fault_level_str)
    except ValueError:
        # If unknown fault level, default to L1
        fault_level = FaultLevel.L1

    return DeviceFaultInfo(
        device_type=getattr(pb_device_fault, 'deviceType', 'UNKNOWN'),
        rank_id=-1,  # Default for non-NPU devices
        fault_code=fault_code,
        fault_level=fault_level,
        fault_type=_extract_first_from_list_or_none(pb_device_fault, 'faultType'),
        fault_reason=_extract_first_from_list_or_none(pb_device_fault, 'faultReason')
    )


@dataclass
class DeviceFaultInfo:
    device_type: str # npu, switch, node, PSU, disk......
    rank_id: int # only npu has rank_id, others use -1.
    fault_code: int = 0x0
    fault_level: FaultLevel = FaultLevel.L1
    fault_type: str | None = None
    fault_reason: str | None = None


@dataclass
class ServerMetadata:
    """
    Each server metadata represents a server in the cluster.
    And An instance may have multiple servers.
    
    We don't determine the server's status, we just use the 
    broadcast message to update the server's status.  And the
    `device_fulat_infos` is used to record the device faults 
    of the server, if there is no device fault, it will be an 
    empty list.
    """
    pod_ip: str
    host_ip: str
    status: Status = Status.HEALTHY
    device_fault_infos: list[DeviceFaultInfo] = field(default_factory=list)


@dataclass
class InstanceMetadata:
    instance_id: int
    status: Status = Status.HEALTHY
    node_managers: list[NodeManagerInfo] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    # When an instance's servers are faulty, we need to trigger
    # the recovery function, we record the current strategy,
    # strategy level and fault code. if the instance is healthy,
    # we should try to stop the strategy.
    fault_level: FaultLevel = FaultLevel.L0 # current instance fault level, L0 means healthy, L1+ means faulty.
    fault_code: int = 0x0 # fault code that trigger the current strategy
    strategy: StrategyBase | None = None # current handling strategy

    
@dataclass
class InstanceGroupMetadata:
    """
    Instance group metadata for scale prefill to decode recovery.
    it is defferent from instance group metadata in instance assembler.
    because it interact with instance manager, which manage instances 
    by instance id, so it use instance id instead of job name.
    """
    id: int
    p_ids: list[int] = field(default_factory=list)
    d_ids: list[int] = field(default_factory=list)


class FaultManager(ThreadSafeSingleton, Observer):
    """
    Fault tolerance manager for handling device and server faults in the cluster.

    This class monitors server statuses, processes fault messages from the cluster,
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

        # Manage all servers's status with pod_ip, when it comes a faulty server,
        # we firstly find out which instance this server belongs to,
        # and then use self.instances to find out all nodes in this instance.
        self.servers: dict[str, ServerMetadata] = {}
        self.instances: dict[int, InstanceMetadata] = {}
        # For scale prefill to decode recovery
        self.groups: dict[int, InstanceGroupMetadata] = {}
        self.lock = threading.Lock()

        self.client = ClusterNodeClient('localhost', 5005)

        self.stop_event = threading.Event()

        # For dual handle function trigger, we use a thread pool executor to handle it.
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=5)

        self.strategies = generate_strategy_map()

        self.server_status_subscriber_thread = threading.Thread(
            target=self._server_status_subscriber,
            daemon=True,
            name="ServerStatusSubscriber"
        )
        self.ft_strategy_center_thread = threading.Thread(
            target=self._ft_strategy_center,
            daemon=True,
            name="FaultToleranceStrategyCenter"
        )
        self._initialized = True
        logger.info("FaultManager initialized.")

    def start(self) -> None:
        """Start the fault tolerance threads"""
        self.server_status_subscriber_thread.start()
        self.ft_strategy_center_thread.start()
        logger.info("FaultManager started.")

    def stop(self) -> None:
        self.stop_event.set()
        # Only join threads that have been started
        if self.ft_strategy_center_thread.is_alive():
            self.ft_strategy_center_thread.join()
        logger.info("FaultManager stopped.")

    def update(self, instance: ReadOnlyInstance, event: ObserverEvent) -> None:
        logger.info("FaultManager update instance %s with event: %s.",
                    instance.job_name, event)

        # Duck typing for instance
        if event == ObserverEvent.INSTANCE_ADDED:
            self._handle_instance_added(instance)
        elif event == ObserverEvent.INSTANCE_SEPERATED:
            self._handle_instance_separated(instance)
        elif event == ObserverEvent.INSTANCE_REMOVED:
            self._handle_instance_removed(instance)
        else:
            raise ValueError(f"Invalid event: {event}.")

    def _handle_instance_added(self, instance: Instance) -> None:
        ins_metadata = InstanceMetadata(
            instance_id=instance.id,
            node_managers=instance.get_node_managers()
        )
        
        server_metadatas = {}
        for node_mgr in ins_metadata.node_managers:
            server_metadatas[node_mgr.pod_ip] = ServerMetadata(
                pod_ip=node_mgr.pod_ip,
                host_ip=node_mgr.host_ip,
            )

        with self.lock:
            self.instances[instance.id] = ins_metadata
            self.servers.update(server_metadatas)

            if instance.group_id not in self.groups:
                group = InstanceGroupMetadata(id=instance.group_id)
                self.groups[instance.group_id] = group
            else:
                group = self.groups[instance.group_id]
            
            if instance.role == "prefill":
                group.p_ids.append(instance.id)
            else:
                group.d_ids.append(instance.id)

    def _handle_instance_separated(self, instance: Instance) -> None:
        with self.lock:
            if instance.id in self.instances:
                ins_metadata = self.instances[instance.id]
        
        if ins_metadata is not None:
            with ins_metadata.lock:
                ins_metadata.status = Status.UNHEALTHY

    def _handle_instance_removed(self, instance: Instance) -> None:
        node_managers = []
        with self.lock:
            if instance.id in self.instances:
                ins_metadata = self.instances[instance.id]
                node_managers = ins_metadata.node_managers.copy()
            else:
                return

        with self.lock:
            for node_mgr in node_managers:
                self.servers.pop(node_mgr.pod_ip, None)

            if instance.group_id in self.groups:
                group = self.groups[instance.group_id]
                if instance.role == "prefill" and instance.id in group.p_ids:
                    group.p_ids.remove(instance.id)
                elif instance.role == "decode" and instance.id in group.d_ids:
                    group.d_ids.remove(instance.id)
                if len(group.p_ids) == 0 and len(group.d_ids) == 0:
                    self.groups.pop(instance.group_id)

            self.instances.pop(instance.id, None)

    def _server_status_subscriber(self) -> None:
        reconnect_attempts, max_reconnect_attempts = 0, 10
        base_wait_time, max_wait_time = 5, 300

        while not self.stop_event.is_set():
            try:
                # First, ensure we are registered
                if not self.client.is_registered():
                    if not self.client.register():
                        reconnect_attempts += 1
                        if reconnect_attempts <= max_reconnect_attempts:
                            wait_time = min(base_wait_time * (2 ** (reconnect_attempts - 1)), max_wait_time)
                            logger.warning("client register failed, attempt %d/%d, retrying in %ds...",
                                            reconnect_attempts, max_reconnect_attempts, wait_time)
                            time.sleep(wait_time)
                            continue
                        else:
                            logger.error("client register failed after %d attempts, giving up for now! "
                                         "will retry later!", max_reconnect_attempts)
                            time.sleep(max_wait_time)
                            reconnect_attempts = 0  # reset counter, avoid infinite waiting
                            continue
                    else:
                        reconnect_attempts = 0
                        logger.info("client register successful")

                # Once registered, start subscription (this will block until connection is lost)
                logger.info("starting fault message subscription...")
                self.client.subscribe_fault_messages(self._process_cluster_fault_message)

                # If we reach here, the subscription ended (likely due to connection loss)
                logger.warning("fault message subscription ended, will retry...")

            except Exception as e:
                reconnect_attempts += 1
                logger.error("hardware info subscriber error: %s", e)
                self.client.close()

                if reconnect_attempts <= max_reconnect_attempts:
                    wait_time = min(base_wait_time * (2 ** (reconnect_attempts - 1)), max_wait_time)
                    logger.warning("subscriber error, attempt %d/%d, retrying in %ds...",
                                   reconnect_attempts, max_reconnect_attempts, wait_time)
                    time.sleep(wait_time)
                else:
                    logger.error("subscriber failed after %d attempts, "
                                 "giving up for now. Will retry later.", max_reconnect_attempts)
                    time.sleep(max_wait_time)
                    reconnect_attempts = 0  # reset counter, avoid infinite waiting

    def _process_device_faults(self, node_info, node_ip: str, server_metadata) -> None:
        """
        Process device fault information for a node.
        Sets server_metadata.device_fault_infos and handles any conversion errors.
        """
        try:
            if hasattr(node_info, 'faultDevice') and node_info.faultDevice is not None:
                device_faults = list(node_info.faultDevice)
                if len(device_faults) > 1000:
                    logger.warning("Too many device faults (%d), truncating to 1000!",
                                   len(device_faults))
                    device_faults = device_faults[:1000]
                # Convert protobuf DeviceFaultInfo to Python DeviceFaultInfo objects
                server_metadata.device_fault_infos = [
                    convert_protobuf_device_fault_info(pb_fault)
                    for pb_fault in device_faults
                ]
            else:
                server_metadata.device_fault_infos = []
        except Exception as e:
            logger.error("Error processing device fault info for %s: %s", node_ip, e)
            server_metadata.device_fault_infos = []

    def _process_cluster_fault_message(self, fault_msg: cluster_fault_pb2.FaultMsgSignal):
        # Handle MindCluster's Server fault message. Only care about the servers
        # that we deploy inference service and managed by this motor.

        # check if the fault message is valid
        if fault_msg is None:
            logger.error("Received None fault message")
            return
        if not hasattr(fault_msg, 'signalType'):
            logger.error("Fault message missing signalType attribute")
            return
        if fault_msg.signalType == "normal":
            logger.info("read fault message signalType is : %s.", fault_msg.signalType)
            return
        if not hasattr(fault_msg, 'nodeFaultInfo') or fault_msg.nodeFaultInfo is None:
            logger.warning("No nodeFaultInfo in fault message")
            return

        with self.lock:
            for node_info in fault_msg.nodeFaultInfo:
                try:
                    if not hasattr(node_info, 'nodeIP') or not hasattr(node_info, 'faultLevel'):
                        logger.warning("Invalid node_info structure, missing required fields")
                        continue

                    node_ip = getattr(node_info, 'nodeIP', None)
                    fault_level = getattr(node_info, 'faultLevel', None)
                    if node_ip is None or fault_level is None:
                        logger.warning("Missing required node_info fields (nodeIP or faultLevel)")
                        continue

                    logger.info("Get node fault level: %s, ip: %s.", fault_level, node_ip)

                    server_metadata = self.servers.get(node_ip)
                    if server_metadata is None:
                        logger.warning("Unknown server %s, skipping fault message processing.", node_ip)
                        continue

                    # Process device fault information
                    self._process_device_faults(node_info, node_ip, server_metadata)

                    # Determine server status based on fault_level and device faults
                    has_device_faults = (
                        hasattr(node_info, 'faultDevice') and
                        node_info.faultDevice is not None and
                        len(node_info.faultDevice) > 0
                    )

                    if fault_level == "unhealthy" and has_device_faults:
                        # Server is unhealthy only when fault_level is unhealthy AND has device faults
                        server_metadata.status = Status.UNHEALTHY
                        logger.info("Server %s marked as unhealthy due to fault level: %s with device faults",
                                    node_ip, fault_level)
                    else:
                        # fault_level is healthy, set server status to healthy.
                        server_metadata.status = Status.HEALTHY

                except Exception as e:
                    logger.error("Error processing node_info: %s", e)
                    continue

        # update instances status by server status and device fault info
        self._update_instances_status()

    def _update_instances_status(self) -> None:
        with self.lock:
            instance_ids = list(self.instances.keys())

        for instance_id in instance_ids:
            try:
                with self.lock:
                    ins_metadata = self.instances[instance_id]

                with ins_metadata.lock:
                    # Use the server's highest level device fault to represent
                    # the instance's fault level, if the instance is healthy,
                    # the fault level will be L0, and the fault code will be 0x0.

                    # Record the previous fault level for comparison
                    previous_fault_level = ins_metadata.fault_level

                    # Calculate the new fault level based on current server statuses
                    final_level, fault_code = FaultLevel.L0, 0x0
                    for node_mgr in ins_metadata.node_managers:
                        try:
                            device_fault_info = self._eval_server_status(node_mgr.pod_ip)
                            if device_fault_info is not None:
                                final_level = max(final_level, device_fault_info.fault_level)
                                fault_code = max(fault_code, device_fault_info.fault_code)
                        except Exception as e:
                            logger.error("Error evaluating server status for %s in instance %d: %s",
                                        node_mgr.pod_ip, instance_id, e)
                            continue

                    ins_metadata.fault_level = final_level
                    ins_metadata.fault_code = fault_code

                    # Handle instance isolation/recovery based on fault level transition
                    # Check if instance became unhealthy (from healthy to faulty)
                    if previous_fault_level == FaultLevel.L0 and final_level != FaultLevel.L0:
                        InstanceManager().separate_instance(instance_id)
                        logger.info("Instance %d became unhealthy (fault level: %s -> %s), isolating",
                                    instance_id, previous_fault_level, final_level)
                    # Check if instance became healthy (from faulty to healthy)
                    elif previous_fault_level != FaultLevel.L0 and final_level == FaultLevel.L0:
                        InstanceManager().recover_instance(instance_id)
                        logger.info("Instance %d became healthy (fault level: %s -> %s), recovering",
                                    instance_id, previous_fault_level, final_level)

            except Exception as e:
                logger.error("Critical error updating status for instance %d: %s", instance_id, e)
                continue

    def _eval_server_status(self, pod_ip: str) -> DeviceFaultInfo | None:
        server_metadata = None
        with self.lock:
            server_metadata = self.servers.get(pod_ip)
        
        if server_metadata is None:
            raise ValueError(f"Server {pod_ip} not found.")

        # use the devices' highest level error to represent the server's fault level
        # Only consider device faults if server is unhealthy
        if server_metadata.status == Status.HEALTHY:
            return None

        if len(server_metadata.device_fault_infos) == 0:
            return None

        highest_fault_level = FaultLevel.L1
        target_fault_info = None
        for fault_info in server_metadata.device_fault_infos:
            if fault_info.fault_level > highest_fault_level:
                highest_fault_level = fault_info.fault_level
                target_fault_info = fault_info

        return target_fault_info

    def _ft_strategy_center(self) -> None:
        while not self.stop_event.is_set():
            instance_ids = []
            with self.lock:
                instance_ids = list(self.instances.keys())
            
            for instance_id in instance_ids:
                self._process_instance_strategy(instance_id)

            time.sleep(self.config.strategy_center_check_internal)

    def _process_instance_strategy(self, ins_id: int) -> None:
        """
        This function will generate the instance's strategy base on the instance's
        fault level and fault code. If the current strategy is not None, it will 
        check if the new strategy is the same as the current strategy. Below are 
        the rules:

        1.SAME_LEVEL: check if the current strategy is finished, if it is finished,
                      it will reset the relative state. 
        2.DIFFERENT_AND_UPGRADE: stop the current strategy and start the new strategy.
        3.DIFFERENT_AND_DOWNGRADE: do nothing.
        """
        ins_metadata = None
        with self.lock:
            ins_metadata = self.instances.get(ins_id)
            if ins_metadata is None:
                return
        
        with ins_metadata.lock:
            fault_level, fault_code = ins_metadata.fault_level, ins_metadata.fault_code
            new_strategy_cls = self.strategies[fault_level](fault_code, ins_id)
            current_strategy = ins_metadata.strategy
            current_cls = current_strategy.__class__ if current_strategy is not None else None

            if new_strategy_cls is not None:
                is_upgrade = False
                if current_strategy is None:
                    is_upgrade = True
                else:
                    if new_strategy_cls != current_cls:
                        current_strategy.stop()
                        ins_metadata.strategy = None
                        is_upgrade = True

                if is_upgrade:
                    new_strategy = new_strategy_cls()
                    self.executor.submit(new_strategy.execute, ins_id)
                    ins_metadata.strategy = new_strategy
                    logger.info("Set new strategy for instance %d to %s with fault code %d.",
                                ins_id, fault_level, fault_code)

            if ins_metadata.strategy is not None:
                if ins_metadata.strategy.is_finished():
                    ins_metadata.strategy = None
                    ins_metadata.fault_level = FaultLevel.L0
                    ins_metadata.fault_code = 0x0
                    logger.info("Strategy for instance %d finished, reset state.", ins_id)
                else:
                    # New strategy and have unfinished strategy will both reach here.
                    ins_metadata.fault_level = fault_level
                    ins_metadata.fault_code = fault_code