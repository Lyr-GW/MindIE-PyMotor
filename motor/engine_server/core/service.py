#!/usr/bin/env python3
# coding=utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved.

from abc import ABC, abstractmethod
from typing import Dict, Any


class Service(ABC):
    @abstractmethod
    def get_data(self) -> Dict[str, Any]:
        pass


class BaseService(Service):
    def __init__(self, name: str):
        self.name = name

    def get_data(self) -> Dict[str, Any]:
        pass


class MetricsService(BaseService):
    def __init__(self, data_controller):
        super().__init__(name="metrics_service")
        self.data_controller = data_controller

    def get_data(self) -> Dict[str, Any]:
        return self.data_controller.get_metrics_data()


class HealthService(BaseService):
    def __init__(self, data_controller):
        super().__init__(name="health_service")
        self.data_controller = data_controller

    def get_data(self) -> Dict[str, Any]:
        return self.data_controller.get_health_data()
