#!/usr/bin/env python3
# coding=utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved.

from abc import ABC, abstractmethod

from motor.engine_server.config.base import IConfig
from motor.engine_server.core.data_controller import DataController
from motor.engine_server.core.endpoint import Endpoint
from motor.engine_server.core.service import MetricsService, HealthService


class IServerCore(ABC):
    @abstractmethod
    def __init__(self, config: IConfig):
        pass

    @abstractmethod
    def initialize(self) -> None:
        pass

    @abstractmethod
    def run(self) -> None:
        pass

    @abstractmethod
    def join(self) -> None:
        pass

    @abstractmethod
    def shutdown(self) -> None:
        pass

    @abstractmethod
    def status(self) -> str:
        pass


class BaseServerCore(IServerCore):
    def __init__(self, config: IConfig):
        super().__init__(config)
        self.config = config
        self.data_controller = DataController(self.config)
        self.metrics_service = MetricsService(self.data_controller)
        self.health_service = HealthService(self.data_controller)
        self.endpoint = Endpoint(self.config.get_server_config(), [self.metrics_service, self.health_service])

    def initialize(self) -> None:
        pass

    def run(self) -> None:
        self.data_controller.run()
        self.endpoint.run()

    def join(self) -> None:
        pass

    def shutdown(self) -> None:
        self.endpoint.shutdown()
        self.data_controller.shutdown()

    def status(self) -> str:
        pass
