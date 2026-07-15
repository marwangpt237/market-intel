"""Base class for domain-specific modules."""
from __future__ import annotations
from abc import ABC, abstractmethod
from core.models import ProcessedItem
from core.logger import get_logger


class BaseDomainModule(ABC):
    """Base class for domain-specific signal extractors.

    Each domain module scans items for domain-specific signals and tags
    them in item.metadata["domain_signals"][<domain_name>].

    Example: SaaS module might tag an item with:
        {"saas": {"signals": ["pricing_complaint", "churn_mention"], "severity": "high"}}

    The Strategy Engine can then prefer decisions that align with the
    user's active domain (configured in config.yaml).
    """
    domain_name: str = "base"

    def __init__(self, config: dict | None = None):
        self._config = config or {}
        self._logger = get_logger(f"domain.{self.domain_name}")

    @abstractmethod
    def extract(self, item: ProcessedItem) -> dict:
        """Extract domain-specific signals from a single item.

        Returns a dict with at least:
          - "signals": list[str]   (signal type identifiers)
          - "severity": str        ("high" | "medium" | "low" | "none")
          - "entities": dict       (domain-specific entities found)
        """
        ...

    def process(self, items: list[ProcessedItem]) -> list[ProcessedItem]:
        """Process all items — tag each with domain signals."""
        tagged = 0
        for item in items:
            signals = self.extract(item)
            if signals.get("signals"):
                if "domain_signals" not in item.metadata:
                    item.metadata["domain_signals"] = {}
                item.metadata["domain_signals"][self.domain_name] = signals
                tagged += 1

        self._logger.info(
            f"{self.domain_name}: {tagged}/{len(items)} items tagged with domain signals",
            extra={"tagged": tagged, "total": len(items)},
        )
        return items
