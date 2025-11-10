#!/usr/bin/env python3
# coding=utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved.
# Copyright (c) 2019 eugen1j

from abc import ABC, abstractmethod
from typing import Dict, Any

from motor.engine_server.config.base import IConfig


class Collector(ABC):
    def __init__(self, config: IConfig):
        pass

    @abstractmethod
    def collect(self) -> Dict[str, Any]:
        pass


class BaseCollector(Collector):
    def __init__(self, config: IConfig):
        super().__init__(config)
        self.name = f"{config.get_server_config().engine_type}_metrics_and_health_collector"

    def collect(self) -> Dict[str, Any]:
        return self._collect()

    def _collect(self) -> Dict[str, Any]:
        pass
