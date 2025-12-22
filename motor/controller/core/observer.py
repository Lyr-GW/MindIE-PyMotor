# coding=utf-8
# Copyright (c) 2025, HUAWEI CORPORATION.  All rights reserved.

from abc import ABC, abstractmethod
from enum import Enum

from motor.common.resources import ReadOnlyInstance


class ObserverEvent(Enum):
    INSTANCE_ADDED = 0
    INSTANCE_SEPERATED = 1
    INSTANCE_REMOVED = 2


class Observer(ABC):

    def __init__(self) -> None:
        pass

    @abstractmethod
    def update(self, instance: ReadOnlyInstance, event: ObserverEvent) -> None:
        pass
