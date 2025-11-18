#!/usr/bin/env python3
# coding=utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved.

import os
import json
from typing import Any, Optional
from enum import Enum

from motor.common.resources.http_msg_spec import Ranktable
from motor.common.resources.instance import ParallelConfig, PDRole
from motor.common.resources.endpoint import DeviceInfo
from motor.common.utils.singleton import ThreadSafeSingleton
from motor.common.utils.env import Env
from motor.common.utils.patch_check import safe_open
from motor.common.utils.logger import get_logger

PP = "pp_size"
TP = "tp_size"

logger = get_logger(__name__)


class HardwareType(str, Enum):
    TYPE_800I_A2 = "800I-A2"
    TYPE_800I_A3 = "800I-A3"
    
    def __repr__(self) -> str:
        return str.__repr__(self.value)


class NodeManagerConfig(ThreadSafeSingleton):
    """
    Global configuration singleton for node manager.
    Loads basic config and HCCL config file.
    """

    pod_ip: Optional[str] = None
    host_ip: Optional[str] = None
    parallel_config: Optional[ParallelConfig] = None
    endpoint_num: int = 0

    node_manager_port: int = 8080
    mgmt_ports: list[str] = []
    service_ports: list[str] = []

    job_name: str = Env.job_name
    role: Optional[PDRole] = None
    model_name: str = None
    device_info: list[DeviceInfo] = []
    heartbeat_interval_seconds: int = 1
    tls_config: {} = None

    controller_api_dns: Optional[str] = None
    controller_api_port: Optional[int] = None

    ranktable: Ranktable = None
    base_port: int = 10000
    hardware_type: HardwareType = None

    def __init__(self) -> None:
        if hasattr(self, "_initialized"):
            return  # Ensure singleton only initializes once

        config_path = os.path.join(Env.config_path, "config", "node_manager_config.json")
        hccl_path = os.path.join(Env.home_hccl_path, "hccl.json")

        NodeManagerConfig.parse_config_json(config_path)
        NodeManagerConfig.parse_hccl_json(hccl_path)
        NodeManagerConfig.generate_endpoint_ports()

        self._initialized = True

    @staticmethod
    def _check_json(json_data: dict[str, Any]) -> bool:
        """Validate required config json fields"""
        required_fields = [
            "parallel_config",
            "role",
            "controller_api_dns",
            "controller_api_port",
            "node_manager_port",
            "model_name",
        ]

        # Ensure required top-level fields exist
        for field in required_fields:
            if field not in json_data:
                logger.error(f"Missing required config field: {field}")
                return False

        # Validate parallel config structure
        pc = json_data.get("parallel_config")
        if not isinstance(pc, dict):
            logger.error("parallel_config must be a dict")
            return False

        if TP not in pc or PP not in pc:
            logger.error("parallel_config must contain tp and pp fields")
            return False

        if not isinstance(pc[TP], int) or not isinstance(pc[PP], int):
            logger.error("tp and pp must be integers")
            return False

        if pc[TP] <= 0 or pc[PP] <= 0:
            logger.error("tp and pp must be > 0")
            return False

        return True

    @classmethod
    def parse_config_json(cls, file_path: str):
        """Load basic node config JSON and validate required settings."""
        with safe_open(file_path, "r") as f:
            cfg = json.load(f)

        if not cls._check_json(cfg):
            raise ValueError("Invalid config json")

        cls.model_name = str(cfg.get("model_name"))

        cls.parallel_config = ParallelConfig(**cfg["parallel_config"])

        try:
            cls.role = PDRole(Env.role)
        except ValueError as e:
            raise ValueError(f"Invalid role value") from e

        cls.controller_api_dns = cfg.get("controller_api_dns") or cfg.get("controller_api_dns")
        cls.controller_api_port = cfg.get("controller_api_port")

        cls.node_manager_port = cfg.get("node_manager_port", 8080)

        cls.heartbeat_interval_seconds = cfg.get("heartbeat_interval_seconds", 1)

        cls.tls_config = cfg.get("nodemanager_tls_config", {})
        cls.base_port = cfg.get("base_port", 10000)

        logger.info(
            f"[NodeManagerConfig] Loaded: role={cls.role}, "
            f"controller={cls.controller_api_dns}:{cls.controller_api_port}, "
            f"NM_port={cls.node_manager_port}"
        )

    @classmethod
    def parse_hccl_json(cls, file_path: str):
        """Load HCCL topology info JSON. It includes devices & IP mapping."""
        with safe_open(file_path, "r") as f:
            data = json.load(f)

        try:
            cls.ranktable = Ranktable(**data)
        except ValueError as e:
            raise ValueError("Invalid HCCL json") from e

        server = (data.get("server_list") or [None])[0]

        cls.pod_ip = server.get("container_ip") if server else None
        cls.host_ip = server.get("host_ip") or server.get("server_id") if server else None

        devices = server.get("device") if server else []
        for d in devices or []:
            dev_info = DeviceInfo(
                device_ip=d.get("device_ip"),
                device_id=d.get("device_id"),
                rank_id=d.get("rank_id"),
            )
            if d.get("super_device_id"):
                dev_info.super_device_id = d["super_device_id"]
            cls.device_info.append(dev_info)
        if len(cls.device_info) == 8:
            cls.hardware_type = HardwareType.TYPE_800I_A2
        elif len(cls.device_info) == 16:
            cls.hardware_type = HardwareType.TYPE_800I_A3
        else:
            raise ValueError(f"Invalid device count: {len(cls.device_info)}")

    @classmethod
    def generate_endpoint_ports(cls):
        """
        Calculate endpoint number based on tensor parallel & pipeline parallel config.
        Example: tp=2, pp=4 => 8 devices per pod
        """
        dp = cls.parallel_config.dp_size
        devices_per_dp = cls.parallel_config.tp_size * cls.parallel_config.pp_size

        if len(cls.device_info) < devices_per_dp or dp < 1:
            raise ValueError(
                f"Device count ({len(cls.device_info)}) must bigger than"
                f"or equal to devices per dp ({devices_per_dp})"
                f"and dp must be bigger than 0"
            )

        cls.endpoint_num = min(dp, len(cls.device_info) // devices_per_dp)
        cls.service_ports = [str(cls.base_port + i * 2) for i in range(cls.endpoint_num)]
        cls.mgmt_ports = [str(cls.base_port + i * 2 + 1) for i in range(cls.endpoint_num)]

        logger.info(
            f"Generate endpoint ports successfully: endpoint_num: {cls.endpoint_num},"
            f"mgmt_ports: {cls.mgmt_ports}, service_ports: {cls.service_ports}."
        )