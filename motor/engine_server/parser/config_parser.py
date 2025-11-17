#!/usr/bin/env python3
# coding=utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved.

from typing import Dict, Type, Optional
import importlib

from motor.engine_server.config.base import IConfig, ServerConfig
from motor.common.utils.logger import get_logger

logger = get_logger("engine_server")


class ConfigParser:
    def __init__(self, server_config: ServerConfig):
        self.server_config = server_config
        self._config_class_map: Dict[str, Optional[Type[IConfig]]] = self._load_config_classes()

    @staticmethod
    def _load_config_classes() -> Dict[str, Optional[Type[IConfig]]]:
        config_classes = {}
        
        try:
            vllm_module = importlib.import_module("motor.engine_server.config.vllm")
            vllm_config = getattr(vllm_module, "VLLMConfig")
            config_classes["vllm"] = vllm_config
        except (ImportError, AttributeError) as e:
            config_classes["vllm"] = None
            logger.warning(f"Failed to load VLLMConfig: {e}")
        
        return config_classes

    def parse(self) -> IConfig:
        config_class = self._config_class_map.get(self.server_config.engine_type)

        if not config_class:
            supported_types = [k for k, v in self._config_class_map.items() if v is not None]
            raise ValueError(
                f"Unsupported engine type: {self.server_config.engine_type}. "
                f"Supported types are: {supported_types}."
            )

        config_instance = config_class(server_config=self.server_config)

        config_instance.initialize()
        config_instance.convert()
        config_instance.validate()
        return config_instance