"""Vertical Packs — pluggable use-case-specific intelligence modules.

A Vertical Pack bundles:
  - Vertical-specific aggregators (e.g. E-commerce Radar aggregates product signals)
  - Vertical-specific reports (e.g. ProductIntelligenceReport)
  - Vertical-specific scoring (e.g. opportunity score for products)

The core engine + country packs provide the data layer. Vertical packs
provide the analysis layer that turns raw signals into actionable insights
for a specific use case.

Example verticals:
  - E-commerce Radar — "Which products are trending in Algeria?"
  - Seller Radar — "Which sellers are growing fastest?"
  - Lead Radar — "Which businesses need a website?"
  - Business Radar — "Which local businesses are expanding?"
  - Ad Radar — "Which ad campaigns are working?"
  - Opportunity Radar — "Which opportunities exist before competitors notice?"
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any


class VerticalPack(ABC):
    """Base class for vertical-specific intelligence packs."""
    vertical_name: str = "base"
    description: str = ""

    def __init__(self, config: dict | None = None):
        self._config = config or {}

    @abstractmethod
    def get_processors(self) -> list[Any]:
        """Return list of BaseProcessor instances (vertical aggregators)."""
        ...

    def get_reports(self) -> list[Any]:
        """Return list of BaseReportGenerator instances."""
        return []

    def get_metadata(self) -> dict:
        return {
            "vertical_name": self.vertical_name,
            "description": self.description,
            "processors_count": len(self.get_processors()),
            "reports_count": len(self.get_reports()),
        }


_VERTICAL_PACKS: dict[str, type[VerticalPack]] = {}


def register_vertical_pack(name: str, pack_class: type[VerticalPack]) -> None:
    _VERTICAL_PACKS[name] = pack_class


def get_vertical_pack(name: str, config: dict | None = None) -> VerticalPack | None:
    cls = _VERTICAL_PACKS.get(name)
    if cls is None:
        return None
    return cls(config)


def list_vertical_packs() -> list[str]:
    return list(_VERTICAL_PACKS.keys())
