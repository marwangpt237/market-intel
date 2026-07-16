"""
Country Packs — pluggable per-country intelligence modules.

A Country Pack bundles:
  - Localized NLP processors (Darija, Arabic, French, etc.)
  - Geographic entity extractors (wilayas, cities, regions)
  - Local payment method detectors
  - Seasonal pattern detectors (Ramadan, Aid, back-to-school)
  - Country-specific collectors (Ouedkniss for Algeria, etc.)
  - Local product/price extractors
  - Country-specific report generators

The core engine (collectors → processors → scoring → strategy → learning)
remains generic. Country Packs add a regional intelligence layer on top.

Adding a new country pack:
  1. Create country_packs/<country_name>/ directory
  2. Subclass CountryPack and implement get_processors(), get_collectors(), get_reports()
  3. Register in country_packs/registry.py
  4. Add config.<country>_<vertical>.yaml profile

Long-term moat: proprietary regional intelligence that global products
(Google Trends, FB Insights, etc.) cannot match.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any


class CountryPack(ABC):
    """Base class for country-specific intelligence packs.

    A CountryPack contributes:
      - get_processors(): list of BaseProcessor instances to inject into pipeline
      - get_collectors(): list of BaseCollector instances (country-specific sources)
      - get_reports(): list of BaseReportGenerator instances (country-specific reports)
      - get_entity_extractors(): functions that extract country-specific entities
      - get_signal_patterns(): country-specific regex patterns for signal detection

    All return values are optional — a CountryPack may contribute only
    processors (e.g. Darija NLP) without collectors or reports.
    """
    country_code: str = "XX"
    country_name: str = "Base"
    language_codes: list[str] = ["en"]

    def __init__(self, config: dict | None = None):
        self._config = config or {}

    @abstractmethod
    def get_processors(self) -> list[Any]:
        """Return list of BaseProcessor instances to add to pipeline."""
        ...

    def get_collectors(self) -> list[Any]:
        """Return list of BaseCollector instances (country-specific sources)."""
        return []

    def get_reports(self) -> list[Any]:
        """Return list of BaseReportGenerator instances."""
        return []

    def get_metadata(self) -> dict:
        """Return metadata about this country pack."""
        return {
            "country_code": self.country_code,
            "country_name": self.country_name,
            "language_codes": self.language_codes,
            "processors_count": len(self.get_processors()),
            "collectors_count": len(self.get_collectors()),
            "reports_count": len(self.get_reports()),
        }


# Registry of available country packs
_COUNTRY_PACKS: dict[str, type[CountryPack]] = {}


def register_country_pack(name: str, pack_class: type[CountryPack]) -> None:
    """Register a country pack class."""
    _COUNTRY_PACKS[name] = pack_class


def get_country_pack(name: str, config: dict | None = None) -> CountryPack | None:
    """Instantiate a country pack by name. Returns None if not found."""
    cls = _COUNTRY_PACKS.get(name)
    if cls is None:
        return None
    return cls(config)


def list_country_packs() -> list[str]:
    """List all registered country pack names."""
    return list(_COUNTRY_PACKS.keys())
