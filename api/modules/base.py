from abc import ABC, abstractmethod
from dataclasses import dataclass
from api.services.risk_manager import Signal


class BaseModule(ABC):
    name: str = "base"
    enabled: bool = True

    @abstractmethod
    def evaluate(self) -> list[Signal]:
        """Run the module's strategy and return trade signals."""
        ...

    @abstractmethod
    def get_status(self) -> dict:
        """Return current module state for the dashboard."""
        ...
