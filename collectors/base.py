"""
Base collector interface.

Every collector inherits from BaseCollector and implements collect().
The base class handles logging, retry configuration, and item limits.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any
from core.models import RawItem
from core.logger import get_logger
from core.retry import retry, RetryConfig


class BaseCollector(ABC):
    """Abstract base class for all collectors.

    Subclasses must implement the _fetch() method.
    The base class wraps it with retry logic, logging, and item limiting.
    """

    name: str = "base"

    def __init__(self, config: dict, retry_config: dict | None = None):
        self._config = config or {}
        self._logger = get_logger(f"collector.{self.name}")
        self._retry_config = RetryConfig(retry_config)
        self._max_items: int = config.get("max_items", 50)

    @abstractmethod
    def _fetch(self) -> list[RawItem]:
        """Subclasses implement this to fetch raw data from their source."""
        ...

    def collect(self) -> list[RawItem]:
        """Public entry point. Wraps _fetch with retry + logging + item cap."""
        self._logger.info(f"Starting collection", extra={"collector": self.name})

        try:
            decorator = self._retry_config.get_decorator()
            items = decorator(self._fetch)()
        except Exception as e:
            self._logger.error(
                f"Collection failed after retries",
                extra={"collector": self.name, "error": str(e)}
            )
            return []

        # Cap items
        if len(items) > self._max_items:
            self._logger.info(
                f"Capping items from {len(items)} to {self._max_items}",
                extra={"collector": self.name, "original_count": len(items), "capped_to": self._max_items}
            )
            items = items[:self._max_items]

        self._logger.info(
            f"Collection complete",
            extra={"collector": self.name, "items_collected": len(items)}
        )
        return items
