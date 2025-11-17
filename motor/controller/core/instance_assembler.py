# coding=utf-8
# Copyright (c) 2025, HUAWEI CORPORATION.  All rights reserved.

import time
import threading
import queue
from enum import Enum
from dataclasses import dataclass

from motor.common.utils.logger import get_logger
from motor.common.utils.data_builder import build_ins_ranktable, build_endpoints
from motor.common.utils.http_client import SafeHTTPSClient
from motor.common.utils.singleton import ThreadSafeSingleton
from motor.common.resources.http_msg_spec import RegisterMsg, StartCmdMsg, ReregisterMsg
from motor.common.resources.instance import Instance, ReadOnlyInstance
from motor.common.resources.endpoint import Endpoint
from motor.controller.core.instance_manager import InstanceManager
from motor.controller.core.observer import Observer, ObserverEvent
from motor.config.controller import ControllerConfig

logger = get_logger(__name__)


class RegisterStatus(Enum):
    NOT_REGISTERED = 0
    ASSEMBLING = 1
    ASSEMBLED = 2


@dataclass
class InstanceGroupMetadata:
    """
    Instance assembler use instance's job_name to manager instance, 
    so we use job_name to manager instance group too.
    """
    id: int
    p_job_names: list[str] = None
    d_job_names: list[str] = None
    current_group_member: int = 0
    max_group_member: int = None

    def __post_init__(self) -> None:
        if self.p_job_names is None:
            self.p_job_names = []
        if self.d_job_names is None:
            self.d_job_names = []
        # max_group_member will be set later when creating the group


class InstanceAssembler(ThreadSafeSingleton, Observer):
    def __init__(self, config: ControllerConfig | None = None) -> None:
        super().__init__()
        # If the instance assembler is already initialized, return.
        if hasattr(self, '_initialized'):
            return

        # Use default config if not provided (for backward compatibility)
        if config is None:
            config = ControllerConfig()
        self.config = config

        self.ins_id_cnt = 0
        self.instances: dict[str, Instance] = {}
        self.registered_job_names = set()
        self.instances_group: dict[int, InstanceGroupMetadata] = {}

        self.starting_instances = set()
        self.reregister_instances = set()
        self.assembled_instances = queue.Queue() # element is tuple(Instance: int)

        self.ins_register_timestamp: dict[str, float] = {}

        self.stop_event = threading.Event()
        self.lock = threading.Lock()
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
        self.assemble_instance_thread.start()
        self.start_command_thread.start()
        logger.info("InstanceAssembler started.")

    def stop(self) -> None:
        self.stop_event.set()
        if self.assembled_instances.qsize() == 0:
            # Put a element into queue to make thread exit.
            self.assembled_instances.put(None)
        # Only join threads that have been started
        if self.assemble_instance_thread.is_alive():
            self.assemble_instance_thread.join()
        if self.start_command_thread.is_alive():
            self.start_command_thread.join()
        logger.info("InstanceAssembler stopped.")

    def update(self, instance: ReadOnlyInstance, event: ObserverEvent) -> None:
        # We only update instance group's metadata when instance is removed.
        if event == ObserverEvent.INSTANCE_REMOVED:
            with self.lock:
                group_info = self.instances_group.get(instance.get_group_id(), None)
                if group_info is None:
                    return

                if instance.job_name in group_info.p_job_names:
                    group_info.p_job_names.remove(instance.job_name)
                elif instance.job_name in group_info.d_job_names:
                    group_info.d_job_names.remove(instance.job_name)
                else:
                    logger.warning("Instance %s is not in instance group %d!",
                                   instance.job_name, instance.group_id)
                    return
                group_info.current_group_member -= instance.parallel_config.world_size
            logger.info("Instance removed: %s, group %d's current group member is %d",
                        instance.job_name, instance.group_id, group_info.current_group_member)

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
                self.instances[msg.job_name] = instance
                self.ins_id_cnt += 1
                logger.info("New instance %s(id:%d) created and added.", msg.job_name, instance.id)
            elif status == RegisterStatus.ASSEMBLING:
                instance = self.instances[msg.job_name]

            self.ins_register_timestamp[msg.job_name] = time.time()
            self.registered_job_names.add(msg.job_name)

        pod_endpoints = build_endpoints(msg, instance.get_endpoints_num())
        instance.add_endpoints(msg.pod_ip, pod_endpoints)
        instance.add_node_mgr(msg.pod_ip, msg.host_ip, msg.nm_port)
        logger.info("Endpoints added for instance %s from pod %s.", msg.job_name, msg.host_ip)
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
                self.instances[msg.job_name] = instance
                logger.info("New instance %s(id:%d) created and added by re-registration.",
                            msg.job_name, instance.id)
            elif status == RegisterStatus.ASSEMBLING:
                instance = self.instances[msg.job_name]
        
        # Don't need to build endpoints again, just use the endpoints in reregister msg
        with self.lock:
            self.ins_register_timestamp[msg.job_name] = time.time()
            self.reregister_instances.add(msg.job_name)

            # recover ins_id_cnt
            self.ins_id_cnt = max(self.ins_id_cnt, msg.instance_id + 1)

        instance.add_endpoints(msg.pod_ip, {endpoint.id: endpoint for endpoint in msg.endpoints})
        instance.add_node_mgr(msg.pod_ip, msg.host_ip, msg.nm_port)
        logger.info("Recovery instance assembler's info, current ins_id_idx is %d.", self.ins_id_cnt)
        return 0

    def _start_commmand_sender(self) -> None:
        while not self.stop_event.is_set():
            item = self.assembled_instances.get() # item is tuple(Instance, int)
            if item is not None:
                instance, send_times = item
                job_name = instance.job_name
                if self._send_start_command(instance):
                    logger.info("Start command sent for instance %s successfully.", job_name)
                    with self.lock:
                        self.starting_instances.remove(job_name)
                else:
                    send_times += 1
                    if send_times < self.config.send_cmd_retry_times:
                        self.assembled_instances.put((instance, send_times))
                        logger.warning("Failed to send start command to instance %s with (%d/%d) times.",
                                       job_name, send_times, self.config.send_cmd_retry_times)
                    else:
                        logger.error("Failed to send start command to instance %s with (%d/%d) times, "
                                     "abort it.", job_name, send_times, self.config.send_cmd_retry_times)

            time.sleep(self.config.instance_assembler_cmd_send_internal)

    def _send_start_command(self, instance: Instance) -> bool:
        ins_ranktable = build_ins_ranktable(instance)

        is_succeed = True
        for node_mgr in instance.get_node_managers():
            base_url = f"http://{node_mgr.pod_ip}:{node_mgr.port}"
            endpoints = instance.get_endpoints(node_mgr.pod_ip)
            if not endpoints:
                continue
            
            start_cmd_msg = StartCmdMsg(
                job_name=instance.job_name,
                role=instance.role,
                instance_id=instance.id,
                endpoints=[endpoint for endpoint in endpoints.values()],
                ranktable=ins_ranktable
            )
            try:
                # For `superpod_id` we need to use `exclude_none` to avoid error,
                # when we use atlas A2 server which doesn't have superpod_id.
                client = SafeHTTPSClient(base_url)
                response = client.post(
                    "/node-manager/start", 
                    data=start_cmd_msg.model_dump(exclude_none=True),
                )
                logger.info("Start command sent to node manager %s:%s for instance %s successfully.",
                            node_mgr.pod_ip, node_mgr.port, instance.job_name)
            except Exception as e:
                is_succeed = False
                logger.error("Error sending start command to node manager %s:%s for instance %s: %s",
                             node_mgr.pod_ip, node_mgr.port, instance.job_name, e)
            finally:
                client.close()
            
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
                    if ( 
                        job_name not in self.instances
                        or job_name in self.starting_instances
                    ):
                        continue
                    ins = self.instances[job_name]
                
                self._assemble_instance(ins)

            time.sleep(self.config.instance_assembler_check_internal)

    def _assemble_instance(self, ins: Instance) -> None:
        if not isinstance(ins, Instance):
            raise Exception(f"Invalid instance provided to assemble. "
                            f"expect Instance, got {type(ins)}")

        job_name = ins.job_name
        logger.debug("Assembling instance %s(id:%d)...", job_name, ins.id)
        if ins.is_endpoints_enough():
            # Assemble successfully
            self._assign_ins_group(ins)

            if job_name in self.reregister_instances:
                # Reregister instnace, just handle it to instance manager.
                with self.lock:
                    self.reregister_instances.remove(job_name)
            else:
                # Only new registered instance need to send start command
                with self.lock:
                    # record starting instance to avoid register multiple times
                    # when instance is in starting state, ignore its register msg
                    self.starting_instances.add(job_name)
                self.assembled_instances.put((ins, 0))

            InstanceManager().add_instance(ins)
            with self.lock:
                self.instances.pop(job_name, None)
        else:
            # Assembling... check if this instance registration is timeout
            with self.lock:
                register_time = self.ins_register_timestamp.get(job_name, 0)
            if time.time() - register_time > self.config.instance_assemble_timeout:
                with self.lock:
                    self.instances.pop(job_name, None)
                    self.ins_register_timestamp.pop(job_name, None)
                logger.warning("Instance %s registration timed out and removed.", job_name)       
    
    def _assign_ins_group(self, ins: Instance) -> None:
        class ActionMode(Enum):
            ALLOC = 0
            EXIST = 1
            CREATE = 2
            FAILED = 3
            
        def _select_group(ins: Instance) -> tuple[int, ActionMode]:
            member_size = ins.parallel_config.world_size
            if member_size > self.config.max_link_number:
                return -1, ActionMode.FAILED

            for group in self.instances_group.values():
                if ins.job_name in group.p_job_names + group.d_job_names:
                    return group.id, ActionMode.EXIST
                
                if member_size + group.current_group_member <= group.max_group_member:
                    return group.id, ActionMode.ALLOC
            
            # Reach here means no suitable group found, create a new one.
            return len(self.instances_group), ActionMode.CREATE
        
        group_id, action = _select_group(ins)

        if action is ActionMode.EXIST:
            logger.info("Instance %s(id:%d) already in group %d, no need to assign again.",
                        ins.job_name, ins.id, group_id)
            return
        elif action is ActionMode.ALLOC:
            group = self.instances_group[group_id]
        elif action is ActionMode.CREATE:
            self.instances_group.update(
                {group_id: InstanceGroupMetadata(
                    id=group_id,
                    max_group_member=self.config.max_link_number,
                    current_group_member=0
                )})
            group = self.instances_group[group_id]
        elif action is ActionMode.FAILED:
            raise Exception("Instance %s(id:%d) allocate ins group failed, "
                            "max link number is %d, but need %d."
                            % (ins.job_name, ins.id, self.config.max_link_number,
                            ins.parallel_config.world_size))

        # assign instance to this group
        group.current_group_member += ins.parallel_config.world_size
        group.p_job_names.append(ins.job_name) if ins.role == "prefill" \
            else group.d_job_names.append(ins.job_name)
        ins.set_group_id(group.id)
        logger.info("Instance %s assigned to group %d, current group member is %d, "
                    "max group member is %d.",
                    ins.job_name,
                    group.id,
                    group.current_group_member,
                    group.max_group_member)

    def _eval_register_status(self, job_name: str) -> RegisterStatus:
        status = RegisterStatus.NOT_REGISTERED
        for group in self.instances_group.values():
            if job_name in group.p_job_names + group.d_job_names:
                status = RegisterStatus.ASSEMBLED
                break
        if job_name in self.instances.keys():
            status = RegisterStatus.ASSEMBLING
        return status
