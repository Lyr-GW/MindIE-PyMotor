#!/usr/bin/env python3
# coding=utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved.

from typing import Dict, Type

from motor.engine_server.config.base import IConfig
from motor.engine_server.core.base_core import IServerCore
from motor.engine_server.core.vllm.vllm_core import VLLMServerCore


class ServerCoreFactory:
    def __init__(self):
        self._core_map: Dict[str, Type[IServerCore]] = {
            "vllm": VLLMServerCore,
        }

    def create_server_core(self, config: IConfig) -> IServerCore:
        config_type = config.get_server_config().engine_type
        server_core_class = self._core_map.get(config_type)

        if not server_core_class:
            raise ValueError(f"unsupported engine type {config_type}")

        return server_core_class(config)
