"""Base storage interface."""
from __future__ import annotations
from abc import ABC, abstractmethod
from core.logger import get_logger


class BaseStorage(ABC):
    name: str = "base"

    def __init__(self, config: dict):
        self._config = config
        self._logger = get_logger(f"storage.{self.name}")

    @abstractmethod
    def save(self, items: list[dict], run_id: str) -> str: ...

    @abstractmethod
    def load_recent(self, days: int = 7) -> list[dict]: ...
