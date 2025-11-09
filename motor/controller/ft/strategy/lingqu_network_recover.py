# coding=utf-8
# Copyright (c) 2025, HUAWEI CORPORATION.  All rights reserved.
from motor.utils.logger import get_logger
from motor.controller.ft.strategy.strategy import StrategyBase


logger = get_logger(__name__)


class LingquNetworkRecoverStrategy(StrategyBase):
    def __init__(self) -> None:
        super().__init__()
    
    def execute(self, instance_id: int) -> None:
        while not self.event.is_set():
            pass
    
    def stop(self) -> None:
        logger.info(f"Lingqu Network Recover strategy can not be stopped.")