"""
Algerian Government Open Data Collector — fetches from Algerian government
open data portals.

Sources:
  - data.gov.dz (Algerian open data portal — when available)
  - ONS (Office National des Statistiques) — statistics.dz
  - DGRI (Direction Générale de la Réglementation et de l'Information)
  - CNRC (Centre National du Registre du Commerce) — company registry
  - Douanes (Customs) — trade statistics
  - Ministry of Commerce — pricing bulletins

Government data is high-reliability (0.90+) but often slow to update.
"""
from __future__ import annotations

from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from xml.etree import ElementTree as ET
import re
from core.models import RawItem
from collectors.marketplace.base import MarketplaceCollector, CollectorMetadata


class AlgerianGovCollector(MarketplaceCollector):
    """Algerian government open data collector.

    Config:
      sources: list of {url, name, type: "rss"|"html"|"pdf_index"}
      max_items: int (default 30)
    """
    metadata = CollectorMetadata(
        name="algeria_gov",
        country="DZ",
        category="government",
        entity_types=["statistic", "regulation", "company_registration", "trade_data", "price_bulletin"],
        description="Algerian government open data — ONS statistics, CNRC company registry, customs, ministry bulletins",
        rate_limit_per_hour=20,           # be respectful to government servers
        reliability=0.90,                 # official sources
        cost_per_call=0.0,
        required_credentials=[],
        tags=["algeria", "government", "official", "statistics", "registry", "dz"],
    )

    DEFAULT_SOURCES = [
        {"url": "https://www.ons.dz/feed", "name": "ONS Algeria", "type": "rss"},
        {"url": "https://www.douanes.gov.dz/feed", "name": "Algerian Customs", "type": "rss"},
        {"url": "https://www.commerce.gov.dz/feed", "name": "Ministry of Commerce", "type": "rss"},
        {"url": "https://www.cnrc.dz/feed", "name": "CNRC Company Registry", "type": "rss"},
    ]

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self._sources: list[dict] = self._config.get("sources", self.DEFAULT_SOURCES)
        self._max_items: int = int(self._config.get("max_items", 30))

    def collect(self) -> list[RawItem]:
        items: list[RawItem] = []
        for source in self._sources:
            url = source.get("url", "")
            name = source.get("name", url)
            source_type = source.get("type", "rss")
            if not url:
                continue
            try:
                if source_type == "rss":
                    source_items = self._fetch_rss(url, name)
                else:
                    # For HTML/PDF sources, just record the URL for now
                    source_items = []
                items.extend(source_items[: self._max_items // len(self._sources) if self._sources else self._max_items])
            except Exception as e:
                self._logger.error(f"Failed to fetch government source '{name}' ({url}): {e}")

        self._logger.info(f"Algerian government: collected {len(items)} items from {len(self._sources)} sources")
        return items

    def _fetch_rss(self, url: str, source_name: str) -> list[RawItem]:
        req = Request(url, headers={
            "User-Agent": "Market-Intel/1.0 (+https://github.com/marwangpt237/market-intel)",
            "Accept-Language": "fr-FR,fr;q=0.9",
        })
        try:
            with urlopen(req, timeout=20) as resp:
                data = resp.read()
        except (URLError, HTTPError) as e:
            self._logger.warning(f"Government RSS error '{source_name}': {e}")
            return []

        try:
            root = ET.fromstring(data)
        except ET.ParseError as e:
            self._logger.warning(f"Government RSS parse error '{source_name}': {e}")
            return []

        items: list[RawItem] = []

        # RSS 2.0
        for item_elem in root.findall(".//item"):
            title = self._get_text(item_elem, "title")
            link = self._get_text(item_elem, "link")
            description = self._get_text(item_elem, "description")
            pub_date = self._get_text(item_elem, "pubDate")

            if title and link:
                items.append(RawItem.create(
                    source="algeria_gov",
                    source_name=source_name,
                    title=title,
                    url=link,
                    body=description,
                    author=None,
                    published_at=pub_date,
                    tags=["government", "algeria", "official", "statistics"],
                ))

        return items

    @staticmethod
    def _get_text(parent, tag: str) -> str | None:
        if parent is None:
            return None
        elem = parent.find(tag)
        if elem is None or elem.text is None:
            return None
        return elem.text.strip()
