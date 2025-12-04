# coding=utf-8
# Copyright (c) 2025, HUAWEI CORPORATION.  All rights reserved.

import time
import threading
import hashlib
from enum import Enum
from dataclasses import dataclass
from typing import Any

from motor.common.utils.logger import get_logger
from motor.common.utils.data_builder import build_ins_ranktable, build_endpoints
from motor.common.utils.singleton import ThreadSafeSingleton
from motor.common.resources.http_msg_spec import RegisterMsg, StartCmdMsg, ReregisterMsg
from motor.common.resources.instance import Instance
from motor.common.resources.endpoint import Endpoint
from motor.controller.api_client.node_manager_api_client import NodeManagerApiClient
from motor.controller.core import InstanceManager
from motor.config.controller import ControllerConfig
from motor.common.utils.etcd_client import EtcdClient

logger = get_logger(__name__)


class RegisterStatus(Enum):
    NOT_REGISTERED = 0
    ASSEMBLING = 1
    ASSEMBLED = 2


@dataclass
class AssembleInstanceMetadata:
    instance: Instance
    register_status: RegisterStatus = RegisterStatus.NOT_REGISTERED
    start_command_send_times: int = 0
    register_timestamp: float = 0.0
    is_reregister: bool = False
    lock: threading.Lock = None

    def __post_init__(self):
        if self.lock is None:
            self.lock = threading.Lock()


@dataclass
class PersistentAssembleInstanceMetadataState:
    """Enhanced persistent state for assemble instance metadata with version control and data integrity"""
    metadata_data: dict[str, Any]
    version: int
    timestamp: float
    checksum: str

    def is_valid(self) -> bool:
        """Validate data integrity using checksum"""
        current_checksum = self._calculate_checksum()
        return self.checksum == current_checksum

    def _calculate_checksum(self) -> str:
        """Calculate checksum for data integrity verification"""
        data_str = f"{self.metadata_data}{self.version}{self.timestamp}"
        return hashlib.sha256(data_str.encode()).hexdigest()


class InstanceAssembler(ThreadSafeSingleton):
    def __init__(self, config: ControllerConfig | None = None) -> None:
        super().__init__()
        # If the instance assembler is already initialized, return.
        if hasattr(self, '_initialized'):
            return

        # Use default config if not provided (for backward compatibility)
        if config is None:
            config = ControllerConfig()

        # Extract required config fields
        self.etcd_config = config.etcd_config
        self.instance_assemble_timeout = config.instance_config.instance_assemble_timeout
        self.instance_assembler_check_internal = config.instance_config.instance_assembler_check_internal
        self.instance_assembler_cmd_send_internal = config.instance_config.instance_assembler_cmd_send_internal
        self.send_cmd_retry_times = config.instance_config.send_cmd_retry_times

        self.ins_id_cnt = 1
        self.instances: dict[str, AssembleInstanceMetadata] = {}

        self.stop_event = threading.Event()
        self.lock = threading.Lock()

        # Version control for data persistence
        self._data_version = 0
        self._version_lock = threading.Lock()

        self.etcd_client = EtcdClient(
            host=self.etcd_config.etcd_host,
            port=self.etcd_config.etcd_port,
            ca_cert=self.etcd_config.etcd_ca_cert,
            cert_key=self.etcd_config.etcd_cert_key,
            cert_cert=self.etcd_config.etcd_cert_cert,
            timeout=self.etcd_config.etcd_timeout
        )
        self.assemble_instance_thread = threading.Thread(
            target=self._instances_assembler_loop,
            daemon=True,
            name="InstanceAssemblerLoop"
        )
        self.start_command_thread = threading.Thread(
            target=self._start_commmand_sender,
            daemon=True,
            name="StartCommandSender"
        )
        self._initialized = True
        logger.info("InstanceAssembler initialized.")

    def start(self) -> None:
        """Start the instance assembler threads"""
        # Try to restore data from ETCD, if failed,
        # it will start with empty state.
        if self.etcd_config.enable_etcd_persistence:
            self.restore_data()

        self.assemble_instance_thread.start()
        self.start_command_thread.start()
        logger.info("InstanceAssembler started.")

    def stop(self) -> None:
        self.stop_event.set()
        # Only join threads that have been started
        if self.assemble_instance_thread.is_alive():
            self.assemble_instance_thread.join()
        if self.start_command_thread.is_alive():
            self.start_command_thread.join()

        # Close ETCD client
        if hasattr(self, 'etcd_client'):
            self.etcd_client.close()

        logger.info("InstanceAssembler stopped.")

    def update_config(self, config: ControllerConfig) -> None:
        """Update configuration for the instance assembler"""
        # Update config fields
        self.etcd_config = config.etcd_config
        self.instance_assemble_timeout = config.instance_config.instance_assemble_timeout
        self.instance_assembler_check_internal = config.instance_config.instance_assembler_check_internal
        self.instance_assembler_cmd_send_internal = config.instance_config.instance_assembler_cmd_send_internal
        self.send_cmd_retry_times = config.instance_config.send_cmd_retry_times

        # Update ETCD client with new configuration
        self.etcd_client = EtcdClient(
            host=self.etcd_config.etcd_host,
            port=self.etcd_config.etcd_port,
            ca_cert=self.etcd_config.etcd_ca_cert,
            cert_key=self.etcd_config.etcd_cert_key,
            cert_cert=self.etcd_config.etcd_cert_cert,
            timeout=self.etcd_config.etcd_timeout
        )
        logger.info("InstanceAssembler configuration updated")

    def register(self, msg: RegisterMsg) -> int:
        """
        Each node manager(nm) will register to instance assembler when it starts,
        and instance assembler will create or update the instance, then check
        wether the instance is ready to be start. If ready, notify the relative
        node manager to start inference engine and handle this instance to the
        instance manager to manager instance's status.

        Args:
            msg (RegisterMsg):
        """
        if msg is None or not isinstance(msg, RegisterMsg):
            raise Exception(f"Invalid msg provided to register. "
                            f"expect RegisterMsg, got {type(msg)}")

        with self.lock:
            status = self._eval_register_status(msg.job_name)
            if status == RegisterStatus.ASSEMBLED:
                logger.info("Instance %s already registered, no need to register again.",
                            msg.job_name)
                return -1
            elif status == RegisterStatus.NOT_REGISTERED:
                instance = Instance(
                    job_name=msg.job_name,
                    model_name=msg.model_name,
                    id=self.ins_id_cnt,
                    role=msg.role,
                    parallel_config=msg.parallel_config
                )
                metadata = AssembleInstanceMetadata(
                    instance=instance,
                    register_timestamp=time.time()
                )
                self.instances[msg.job_name] = metadata
                self.ins_id_cnt += 1
                logger.info("New instance %s(id:%d) created and added.", msg.job_name, instance.id)
            elif status == RegisterStatus.ASSEMBLING:
                metadata = self.instances[msg.job_name]
                with metadata.lock:
                    metadata.register_timestamp = time.time()

        pod_endpoints = build_endpoints(msg, metadata.instance.get_endpoints_num())
        metadata.instance.add_endpoints(msg.pod_ip, pod_endpoints)
        metadata.instance.add_node_mgr(msg.pod_ip, msg.host_ip, msg.nm_port)
        logger.info("Endpoints added for instance %s from pod %s.", msg.job_name, msg.host_ip)

        # Persist data on state change
        if self.etcd_config.enable_etcd_persistence:
            self.persist_data()

        return 0

    def reregister(self, msg: ReregisterMsg) -> int:
        """
        When controller restarts, all node manager will re-register to controller,
        instance assembler will recover its instance info and max instance's id and
        max device's cluster id according to the reregister msg.
        """
        if msg is None or not isinstance(msg, ReregisterMsg):
            raise Exception(f"Invalid msg provided to reregister. "
                            f"expect ReregisterMsg, got {type(msg)}")

        with self.lock:
            status = self._eval_register_status(msg.job_name)
            if status == RegisterStatus.ASSEMBLED:
                logger.info("Instance %s already registered, no need to reregister again.",
                            msg.job_name)
                return -1
            elif status == RegisterStatus.NOT_REGISTERED:
                instance = Instance(
                    job_name=msg.job_name,
                    model_name=msg.model_name,
                    id=msg.instance_id,
                    role=msg.role,
                    parallel_config=msg.parallel_config
                )
                metadata = AssembleInstanceMetadata(
                    instance=instance,
                    register_timestamp=time.time(),
                    is_reregister=True
                )
                self.instances[msg.job_name] = metadata
                logger.info("New instance %s(id:%d) created and added by re-registration.",
                            msg.job_name, instance.id)
            elif status == RegisterStatus.ASSEMBLING:
                metadata = self.instances[msg.job_name]
                with metadata.lock:
                    metadata.register_timestamp = time.time()
                    metadata.is_reregister = True

            # recover ins_id_cnt
            self.ins_id_cnt = max(self.ins_id_cnt, msg.instance_id + 1)

        metadata.instance.add_endpoints(msg.pod_ip, {endpoint.id: endpoint for endpoint in msg.endpoints})
        metadata.instance.add_node_mgr(msg.pod_ip, msg.host_ip, msg.nm_port)
        logger.info("Recovery instance assembler's info, current ins_id_idx is %d.", self.ins_id_cnt)

        # Persist data on state change
        if self.etcd_config.enable_etcd_persistence:
            self.persist_data()

        return 0

    def persist_data(self) -> bool:
        """Persist instance assembler data to ETCD with version control and checksum"""
        try:
            with self.lock:
                current_time = time.time()
                next_version = self._get_next_version()

                persistent_states = {}
                # Persist ins_id_cnt
                ins_id_cnt_data = {"ins_id_cnt": self.ins_id_cnt}
                ins_id_cnt_checksum = self._calculate_ins_id_cnt_checksum()

                persistent_states["ins_id_cnt"] = PersistentAssembleInstanceMetadataState(
                    metadata_data=ins_id_cnt_data,
                    version=next_version,
                    timestamp=current_time,
                    checksum=ins_id_cnt_checksum
                )

                # Persist instances metadata
                for job_name, metadata in self.instances.items():
                    # Create persistent state for metadata
                    role_value = (metadata.instance.role.value
                                if hasattr(metadata.instance.role, 'value')
                                else str(metadata.instance.role))
                    parallel_config_data = (metadata.instance.parallel_config.model_dump()
                                          if hasattr(metadata.instance.parallel_config, 'model_dump')
                                          else metadata.instance.parallel_config)
                    endpoints_data = {pod_ip: {eid: endpoint.model_dump()
                                             for eid, endpoint in endpoints.items()}
                                    for pod_ip, endpoints in metadata.instance.endpoints.items()}

                    metadata_data = {
                        "job_name": metadata.instance.job_name,
                        "model_name": metadata.instance.model_name,
                        "instance_id": metadata.instance.id,
                        "role": role_value,
                        "parallel_config": parallel_config_data,
                        "endpoints": endpoints_data,
                        "node_managers": [(nm.pod_ip, nm.host_ip, nm.port)
                                        for nm in metadata.instance.node_managers],
                        "register_status": metadata.register_status.value,
                        "start_command_send_times": metadata.start_command_send_times,
                        "register_timestamp": metadata.register_timestamp,
                        "is_reregister": metadata.is_reregister
                    }
                    checksum = self._calculate_metadata_checksum(metadata)

                    persistent_states[job_name] = PersistentAssembleInstanceMetadataState(
                        metadata_data=metadata_data,
                        version=next_version,
                        timestamp=current_time,
                        checksum=checksum
                    )

                success = self.etcd_client.persist_data("/controller/instance_assembler", persistent_states)
                if success:
                    logger.info("Successfully persisted %d instance assembler states with version %d",
                              len(persistent_states), next_version)
                return success

        except Exception as e:
            logger.error("Error persisting instance assembler data: %s", e)
            return False

    def restore_data(self) -> bool:
        """Restore instance assembler data from ETCD with version control and validation"""
        try:
            persistent_states = self.etcd_client.restore_data(
                "/controller/instance_assembler",
                PersistentAssembleInstanceMetadataState
            )
            if persistent_states is None:
                logger.info("No instance assembler data found in ETCD, starting with empty state")
                return True

            # Process enhanced persistent format
            with self.lock:
                self.instances.clear()
                current_time = time.time()
                valid_states = 0
                invalid_states = 0

                for key, persistent_state in persistent_states.items():
                    if isinstance(persistent_state, PersistentAssembleInstanceMetadataState):
                        # Validate data integrity
                        if not persistent_state.is_valid():
                            logger.warning("Data integrity check failed for instance assembler state %s, skipping",
                                           key)
                            invalid_states += 1
                            continue

                        # Reconstruct data from persistent state
                        try:
                            if key == "ins_id_cnt":
                                # Restore ins_id_cnt
                                self.ins_id_cnt = persistent_state.metadata_data.get("ins_id_cnt", 0)
                                logger.info("Restored ins_id_cnt: %d (v%d)",
                                            self.ins_id_cnt, persistent_state.version)
                            else:
                                # Restore instance metadata
                                metadata_data = persistent_state.metadata_data
                                instance = Instance(
                                    job_name=metadata_data["job_name"],
                                    model_name=metadata_data["model_name"],
                                    id=metadata_data["instance_id"],
                                    role=metadata_data["role"],
                                    parallel_config=metadata_data["parallel_config"]
                                )

                                # Restore endpoints
                                for pod_ip, endpoints_data in metadata_data["endpoints"].items():
                                    endpoints = {}
                                    for eid, endpoint_data in endpoints_data.items():
                                        # Reconstruct Endpoint from dict data
                                        endpoint = Endpoint(**endpoint_data)
                                        endpoints[int(eid)] = endpoint
                                    instance.endpoints[pod_ip] = endpoints

                                # Restore node managers
                                for nm_data in metadata_data["node_managers"]:
                                    pod_ip, host_ip, port = nm_data
                                    instance.add_node_mgr(pod_ip, host_ip, port)

                                # Create metadata
                                metadata = AssembleInstanceMetadata(
                                    instance=instance,
                                    register_status=RegisterStatus(metadata_data["register_status"]),
                                    start_command_send_times=metadata_data["start_command_send_times"],
                                    register_timestamp=metadata_data["register_timestamp"],
                                    is_reregister=metadata_data["is_reregister"]
                                )

                                self.instances[key] = metadata
                                logger.info("Restored instance assembler state for %s (v%d)",
                                          key, persistent_state.version)

                            # Update data version
                            with self._version_lock:
                                self._data_version = max(self._data_version, persistent_state.version)

                            valid_states += 1

                        except Exception as e:
                            logger.error("Error reconstructing instance assembler state %s: %s", key, e)
                            invalid_states += 1
                            continue

                logger.info("Successfully restored %d valid instance assembler states, %d invalid states skipped",
                            valid_states, invalid_states)
                return True

        except Exception as e:
            logger.error("Error restoring instance assembler data: %s", e)
            return False

    def _eval_register_status(self, job_name: str) -> RegisterStatus:
        # First check if instance is already managed by InstanceManager (fully registered)
        if InstanceManager().has_active_instance_by_job_name(job_name):
            return RegisterStatus.ASSEMBLED

        # Then check if instance is still being assembled locally
        if job_name in self.instances.keys():
            return RegisterStatus.ASSEMBLING

        # Instance not found anywhere
        return RegisterStatus.NOT_REGISTERED

    def _start_commmand_sender(self) -> None:
        while not self.stop_event.is_set():
            with self.lock:
                job_names = list(self.instances.keys())

            for job_name in job_names:
                with self.lock:
                    if job_name not in self.instances:
                        continue
                    metadata = self.instances[job_name]
                    with metadata.lock:
                        if metadata.register_status != RegisterStatus.ASSEMBLED:
                            continue

                if self._send_start_command(metadata):
                    logger.info("Start command sent for instance %s successfully.", job_name)
                    with self.lock:
                        self.instances.pop(job_name, None)
                    # Persist data on state change (instance removed after successful start command)
                    if self.etcd_config.enable_etcd_persistence:
                        self.persist_data()
                else:
                    retry_times = metadata.start_command_send_times + 1
                    if retry_times < self.send_cmd_retry_times:
                        logger.warning("Failed to send start command to instance %s with (%d/%d) times.",
                                        job_name, retry_times, self.send_cmd_retry_times)
                        metadata.start_command_send_times = retry_times
                        # Persist data on state change (retry count updated)
                        if self.etcd_config.enable_etcd_persistence:
                            self.persist_data()
                    else:
                        logger.error("Failed to send start command to instance %s with (%d/%d) times, "
                                     "abort it.", job_name, retry_times, self.send_cmd_retry_times)
                        with self.lock:
                            self.instances.pop(job_name, None)
                        # Persist data on state change (instance removed after max retries)
                        if self.etcd_config.enable_etcd_persistence:
                            self.persist_data()

            time.sleep(self.instance_assembler_cmd_send_internal)

    def _send_start_command(self, metadata: AssembleInstanceMetadata) -> bool:
        ins_ranktable = build_ins_ranktable(metadata.instance)

        is_succeed = True
        for node_mgr in metadata.instance.get_node_managers():
            endpoints = metadata.instance.get_endpoints(node_mgr.pod_ip)
            if not endpoints:
                continue

            start_cmd_msg = StartCmdMsg(
                job_name=metadata.instance.job_name,
                role=metadata.instance.role,
                instance_id=metadata.instance.id,
                endpoints=[endpoint for endpoint in endpoints.values()],
                ranktable=ins_ranktable
            )

            is_succeed = NodeManagerApiClient.send_start_command(node_mgr, start_cmd_msg) and is_succeed
        return is_succeed

    def _instances_assembler_loop(self) -> None:
        # Check all instances in assembling, if one instance is ready,
        # notify relative node manager to start inference engine and 
        # handle this instance to instance manager.
        while not self.stop_event.is_set():
            with self.lock:
                keys = list(self.instances.keys())

            logger.debug("Assembling instance... remain %d instances.", len(keys))
            for job_name in keys:
                with self.lock:
                    if job_name not in self.instances:
                        continue
                    metadata = self.instances[job_name]
                    with metadata.lock:
                        if metadata.register_status == RegisterStatus.ASSEMBLED:
                            continue

                self._assemble_instance(metadata)

            time.sleep(self.instance_assembler_check_internal)

    def _assemble_instance(self, metadata: AssembleInstanceMetadata) -> None:
        job_name = metadata.instance.job_name
        logger.debug("Assembling instance %s(id:%d)...", job_name, metadata.instance.id)
        need_persist = False

        if metadata.instance.is_endpoints_enough():
            # Assemble successfully
            with metadata.lock:
                metadata.register_status = RegisterStatus.ASSEMBLED
                if metadata.is_reregister:
                    # Reregister instance, just handle it to instance manager.
                    InstanceManager().add_instance(metadata.instance)
                    with self.lock:
                        self.instances.pop(job_name, None)
                    need_persist = True
                else:
                    # Only new registered instance need to send start command
                    # Keep it in instances with ASSEMBLED status for _start_commmand_sender to handle
                    InstanceManager().add_instance(metadata.instance)
                    # No need to persist for new registration until start command is sent
        else:
            # Assembling... check if this instance registration is timeout
            with metadata.lock:
                if time.time() - metadata.register_timestamp > self.instance_assemble_timeout:
                    with self.lock:
                        self.instances.pop(job_name, None)
                    need_persist = True
                    logger.warning("Instance %s registration timed out and removed.", job_name)

        # Persist data on state change
        if need_persist and self.etcd_config.enable_etcd_persistence:
            self.persist_data()

    def _get_next_version(self) -> int:
        """Get next data version for persistence"""
        with self._version_lock:
            self._data_version += 1
            return self._data_version

    def _calculate_metadata_checksum(self, metadata: AssembleInstanceMetadata) -> str:
        """Calculate checksum for metadata data integrity"""
        try:
            # Calculate checksum using key fields
            data_str = (f"{metadata.instance.job_name}{metadata.instance.id}"
                        f"{metadata.register_status.value}{metadata.start_command_send_times}"
                        f"{metadata.register_timestamp}{metadata.is_reregister}")
            # Include endpoint information
            for pod_ip, endpoints in metadata.instance.endpoints.items():
                data_str += f"{pod_ip}:{len(endpoints)}"
            return hashlib.sha256(data_str.encode()).hexdigest()
        except Exception as e:
            logger.error("Error calculating checksum for metadata %s: %s", metadata.instance.job_name, e)
            return ""

    def _calculate_ins_id_cnt_checksum(self) -> str:
        """Calculate checksum for ins_id_cnt data integrity"""
        try:
            data_str = f"ins_id_cnt:{self.ins_id_cnt}"
            return hashlib.sha256(data_str.encode()).hexdigest()
        except Exception as e:
            logger.error("Error calculating checksum for ins_id_cnt: %s", e)
            return ""