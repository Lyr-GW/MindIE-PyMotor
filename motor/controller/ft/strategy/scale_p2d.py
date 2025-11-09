# coding=utf-8
# Copyright (c) 2025, HUAWEI CORPORATION.  All rights reserved.
import time

from motor.utils.logger import get_logger
from motor.controller.ft.strategy.strategy import StrategyBase
from motor.controller.ft.fault_manager import FaultManager

logger = get_logger(__name__)


class ScaleP2DStrategy(StrategyBase):
    def __init__(self) -> None:
        super().__init__()
    
    def execute(self, instance_id: int) -> None:
        while not self.event.is_set():
            time.sleep(5)
    
    def stop(self) -> None:
        self.event.set()
        with self._lock:
            self._is_finished = True
        logger.info(f"Stop Scale P2D strategy.")

    def scale_p2d(self, instance_id: int) -> None:
        logger.info(f"Scale P2D strategy timeout, scale p2d.")