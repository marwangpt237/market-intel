"""Base processor interface."""
from __future__ import annotations
from abc import ABC, abstractmethod
from core.models import ProcessedItem
from core.logger import get_logger


class BaseProcessor(ABC):
    name: str = "base"

    def __init__(self, config: dict | None = None):
        self._config = config or {}
        self._logger = get_logger(f"processor.{self.name}")

    @abstractmethod
    def _process(self, items: list[ProcessedItem]) -> list[ProcessedItem]: ...

    def process(self, items: list[ProcessedItem]) -> list[ProcessedItem]:
        self._logger.info(f"Starting processing", extra={"processor": self.name, "input_count": len(items)})
        result = self._process(items)
        self._logger.info(f"Processing complete", extra={"processor": self.name, "output_count": len(result)})
        return result
