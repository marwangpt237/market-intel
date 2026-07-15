"""Base report generator interface."""
from __future__ import annotations
from abc import ABC, abstractmethod
from core.models import ProcessedItem
from core.logger import get_logger


class BaseReportGenerator(ABC):
    name: str = "base"

    def __init__(self, config: dict):
        self._config = config
        self._logger = get_logger(f"report.{self.name}")

    @abstractmethod
    def _generate(self, items: list[ProcessedItem], run_id: str) -> str: ...

    def generate(self, items: list[ProcessedItem], run_id: str) -> str:
        self._logger.info(f"Generating report", extra={"report": self.name, "items": len(items)})
        return self._generate(items, run_id)
