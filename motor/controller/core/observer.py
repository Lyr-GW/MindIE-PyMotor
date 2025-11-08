from abc import ABC, abstractmethod
from enum import Enum

from motor.resources.instance import Instance


class ObserverEvent(Enum):
    INSTANCE_ADDED = 0
    INSTANCE_SEPERATED = 1
    INSTANCE_REMOVED = 2


class Observer(ABC):

    def __init__(self) -> None:
        pass

    @abstractmethod
    def update(self, instance: Instance, event: ObserverEvent) -> None:
        pass