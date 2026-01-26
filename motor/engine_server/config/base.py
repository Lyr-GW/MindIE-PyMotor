#!/usr/bin/env python3
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

import argparse
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from motor.engine_server.config import config_loader
from motor.engine_server.config.config_loader import DeployConfig
from motor.engine_server.utils.ip import ip_valid_check, port_valid_check
from motor.engine_server.utils.validators import FileValidator

supported_engine = ["vllm"]
supported_role = ["prefill", "decode", "union"]


@dataclass
class ServerConfig:
    engine_type: str = "vllm"
    server_host: str = "127.0.0.1"
    role: str = "union"
    server_port: int = 9001
    engine_port: int = 8000
    instance_id: int = 0
    dp_rank: int = 0
    config_path: Optional[str] = None
    deploy_config: DeployConfig = None

    @classmethod
    def parse_cli_args(cls) -> argparse.Namespace:
        parser = argparse.ArgumentParser(description="EngineServer - Universal Inference Engine Service")
        parser.add_argument("--host",
                            help="EngineServer endpoint host")
        parser.add_argument("--role",
                            help="PD separate role, prefill/decode/union")
        parser.add_argument("--port", type=int,
                            help="EngineServer business interface port")
        parser.add_argument("--mgmt-port", type=int, dest="server_port",
                            help="EngineServer management interface port")
        parser.add_argument("--instance-id", type=int, default=0,
                            help="Engine instance id")
        parser.add_argument("--dp-rank", type=int, default=0,
                            help="DP parallel rank")
        parser.add_argument("--config-path",
                            help="Path to engine-specific configuration file (JSON format)")
        return parser.parse_args()

    @classmethod
    def init_engine_server_config(cls) -> 'ServerConfig':
        cli_args = cls.parse_cli_args()
        server_config = cls(
            server_host=cli_args.host,
            role=cli_args.role,
            server_port=cli_args.server_port,
            engine_port=cli_args.port,
            instance_id=cli_args.instance_id,
            config_path=cli_args.config_path,
            dp_rank=cli_args.dp_rank,
        )
        server_config.validate()
        server_config.load_deploy_config()
        return server_config

    def validate(self):
        if self.role not in supported_role:
            raise ValueError(f"role {self.role} is not supported.")
        if self.instance_id < 0:
            raise ValueError(f"instance_id {self.instance_id} illegal.")
        ip_valid_check(self.server_host)
        port_valid_check(int(self.server_port))
        port_valid_check(int(self.engine_port))
        if self.dp_rank < 0 or self.dp_rank > 65535:
            raise ValueError(f"{self.dp_rank} is not supported.")
        if not os.path.exists(self.config_path):
            raise ValueError(f"config file {self.config_path} does not exist")
        if not FileValidator(self.config_path) \
                .check_not_soft_link().check_file_size().check().is_valid():
            raise ValueError(f"{self.config_path} is not a valid file path.")

    def load_deploy_config(self):
        self.deploy_config = config_loader.DeployConfig.load(self.config_path)
        self.engine_type = str(self.deploy_config.engine_type)
        if self.engine_type not in supported_engine:
            raise ValueError(f"engine type {self.engine_type} is not supported.")


class IConfig(ABC):
    @abstractmethod
    def __init__(self, server_config: ServerConfig):
        pass

    @abstractmethod
    def initialize(self):
        pass

    @abstractmethod
    def validate(self):
        pass

    @abstractmethod
    def convert(self):
        pass

    @abstractmethod
    def get_args(self) -> Optional[argparse.Namespace]:
        pass

    @abstractmethod
    def get_server_config(self) -> Optional[ServerConfig]:
        pass


@dataclass
class BaseConfig(IConfig):
    server_config: ServerConfig

    def initialize(self):
        pass

    def validate(self):
        pass

    def convert(self):
        pass

    def get_args(self) -> Optional[argparse.Namespace]:
        return None

    def get_server_config(self) -> Optional[ServerConfig]:
        return self.server_config
