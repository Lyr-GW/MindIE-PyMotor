#!/usr/bin/env python3
# coding=utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved.

import os
import signal
import ipaddress
import subprocess


from motor.common.resources.instance import PDRole
from motor.common.resources.endpoint import Endpoint
from motor.common.utils.singleton import ThreadSafeSingleton
from motor.common.utils.logger import get_logger
from motor.common.utils.env import Env


logger = get_logger(__name__)
MAX_PORT = 65535
MIN_PORT = 1024


class Daemon(ThreadSafeSingleton):
    def __init__(self):
        if hasattr(self, "_initialized"):
            return

        self.engine_pids: list[int] = []
        self.base_port = 10000

        self._initialized = True

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

    # allocate ports for engine service plane and ctrl plane
    def gen_engine_ports(self, port_num) -> dict[str, list[int]]:
        service_ports = [str(self.base_port + i * 2) for i in range(port_num)]
        mgmt_ports = [str(self.base_port + i * 2 + 1) for i in range(port_num)]
        return {"service_ports": service_ports, "mgmt_ports": mgmt_ports}

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
            for i, endpoint in enumerate(endpoints_info):
                if not self._check_params(endpoint):
                    raise ValueError(f"Invalid endpoint parameters")
                cmd = [
                    "engine_server",
                    "--dp-rank", str(i),
                    "--engine_id", str(instance_id),
                    "--role", str(pd_role_info.value),
                    "--host", str(endpoint.ip),
                    "--port", str(int(endpoint.business_port)),
                    "--mgmt-port", str(int(endpoint.mgmt_port)),
                    "--config-path", str(Env.motor_engine_path)
                ]
                logger.info(" ".join(cmd))
                process = subprocess.Popen(cmd, shell=False)
                self.engine_pids.append(process.pid)
        except Exception as e:
            raise RuntimeError(f"Failed to pull engine: {e}") from e

    def exit_daemon(self):
        for pid in self.engine_pids:
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

