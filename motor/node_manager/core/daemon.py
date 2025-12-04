#!/usr/bin/env python3
# coding=utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved.

import os
import signal
import ipaddress
import subprocess
import threading


from motor.common.resources.instance import PDRole
from motor.common.resources.endpoint import Endpoint
from motor.common.utils.singleton import ThreadSafeSingleton
from motor.common.utils.logger import get_logger
from motor.common.utils.env import Env
from motor.config.node_manager import NodeManagerConfig


logger = get_logger(__name__)
MAX_PORT = 65535
MIN_PORT = 1024


class Daemon(ThreadSafeSingleton):
    def __init__(self, config: NodeManagerConfig | None = None):
        if hasattr(self, "_initialized"):
            return

        self.engine_pids: list[int] = []
        if config is None:
            config = NodeManagerConfig.from_json()

        # related config
        self.parallel_config = config.basic_config.parallel_config
        self.device_num = config.basic_config.device_num
        
        self._initialized = True
        self._pids_lock = threading.Lock()


    @staticmethod
    def _check_params(params: Endpoint) -> bool:
        try:
            port = int(params.business_port)
            if not (MIN_PORT <= port <= MAX_PORT):
                logger.error(f"Port {port} is out of valid range")
                return False
        except ValueError:
            logger.error(f"Invalid port value: {params.business_port}")
            return False
        try:
            ipaddress.ip_address(params.ip)
        except ValueError:
            logger.error(f"Invalid IP address: {params.ip}")
            return False
        except Exception as e:
            logger.error(f"Error validating IP address {params.ip}: {e}")
            return False

        return True

    def pull_engine(self, pd_role_info: PDRole, endpoints_info: list[Endpoint], instance_id: int):
        """
        start engine processes based on the provided role and endpoint information.
        engine_server parameters:
            --dp-rank engine dpGroup rank
            --engine-id
            --role  prefill | decode | both
            --host engine service ip
            --port engine service port
            --mgmt-port endpoint management port
            --config-path engine config file path
        """
        try:
            parallel_config = self.parallel_config
            local_world_size = parallel_config.tp_size * parallel_config.pp_size
            env = os.environ.copy()
            device_size = self.device_num
            for i, endpoint in enumerate(endpoints_info):
                if not self._check_params(endpoint):
                    raise ValueError(f"Invalid endpoint parameters")
                start_device_id = i * local_world_size % device_size
                end_device_id = start_device_id + local_world_size
                if end_device_id > device_size:
                    device_ids = list(range(start_device_id, device_size)) + list(range(0, end_device_id - device_size))
                else:
                    device_ids = list(range(start_device_id, end_device_id))
                device_ids_str = ",".join(map(str, device_ids))
                logger.info(f"Device IDs: {device_ids_str}")
                env["ASCEND_RT_VISIBLE_DEVICES"] = device_ids_str
                cmd = [
                    "engine_server",
                    "--dp-rank", str(endpoint.id),
                    "--instance-id", str(instance_id),
                    "--role", str(pd_role_info.value),
                    "--host", str(endpoint.ip),
                    "--port", str(int(endpoint.business_port)),
                    "--mgmt-port", str(int(endpoint.mgmt_port)),
                    "--config-path", str(Env.motor_engine_path)
                ]
                logger.info(" ".join(cmd))
                process = subprocess.Popen(cmd,
                                           shell=False,
                                           env=env)
                if process.poll() is not None:
                    raise RuntimeError(f"Engine process exited immediately with code {process.returncode}")
                with self._pids_lock:
                    self.engine_pids.append(process.pid)
        except Exception as e:
            raise RuntimeError(f"Failed to pull engine: {e}") from e

    def stop(self):
        with self._pids_lock:
            pids = list(self.engine_pids)
            self.engine_pids.clear()
        for pid in pids:
            try:
                os.kill(pid, signal.SIGKILL)
                logger.info(f"Killed engine process with PID: {pid}")
            except ProcessLookupError:
                logger.info(f"Process {pid} already terminated")
            except PermissionError:
                logger.error(f"No permission to kill process {pid}")
            except Exception as e:
                logger.error(f"Failed to kill process {pid}: {e}")
        return

