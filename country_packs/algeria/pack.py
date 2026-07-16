"""
Algeria Pack v1 — first Country Pack for the Market OS platform.

Bundles all Algeria-specific intelligence modules:
  - WilayaExtractor (58 wilayas, French + Arabic)
  - DarijaNLPProcessor (Arabic + French + Darija mixed text)
  - PaymentMethodDetector (CCP, BaridiMob, Edahabia, CIB, cash, crypto)
  - SeasonalDetector (Ramadan, Aid, Back-to-school, Summer, Winter)
  - AlgeriaProductExtractor (DZD prices + product categories + brands)

These processors run AFTER the generic pipeline (similarity_dedup, enrich,
entity_extraction, etc.) and tag each item with metadata["algeria"].

Downstream modules (E-commerce Radar, vertical reports) read this metadata
to produce Algeria-specific intelligence output.
"""
from __future__ import annotations
from typing import Any
from country_packs.base import CountryPack
from country_packs.algeria.wilaya_extractor import WilayaExtractor
from country_packs.algeria.darija_nlp import DarijaNLPProcessor
from country_packs.algeria.payment_detector import PaymentMethodDetector
from country_packs.algeria.seasonal_detector import SeasonalDetector
from country_packs.algeria.product_extractor import AlgeriaProductExtractor


class AlgeriaPack(CountryPack):
    """Algeria Country Pack v1."""
    country_code = "DZ"
    country_name = "Algeria"
    language_codes = ["ar", "fr", "dz"]  # Arabic, French, Darija

    def get_processors(self) -> list[Any]:
        """Return all Algeria-specific processors.

        Order matters:
          1. Darija NLP first (sets language context)
          2. Wilaya extractor (geographic)
          3. Payment detector (commerce)
          4. Seasonal detector (timing)
          5. Product extractor last (uses context from above)
        """
        return [
            DarijaNLPProcessor(self._config.get("darija_nlp", {})),
            WilayaExtractor(self._config.get("wilaya_extractor", {})),
            PaymentMethodDetector(self._config.get("payment_detector", {})),
            SeasonalDetector(self._config.get("seasonal_detector", {})),
            AlgeriaProductExtractor(self._config.get("product_extractor", {})),
        ]


# Auto-register on import
from country_packs.base import register_country_pack
register_country_pack("algeria", AlgeriaPack)
